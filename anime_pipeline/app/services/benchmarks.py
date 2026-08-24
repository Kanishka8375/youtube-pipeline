"""The standing adversarial suite for the continuity system.

Each case is a way the system has been wrong, or could plausibly go wrong
after a refactor. Half assert that a check fires; half assert that it stays
quiet. See app/services/evaluation.py for why the balance matters.

Cases build their own fixtures through `EvalContext` so the suite is runnable
against any database the rest of the system runs against -- SQLite in CI,
Postgres in staging -- without a separate set of fixtures that could drift
from the real schema.
"""

from __future__ import annotations

from typing import Any, Dict

from app.db.models import MemoryDocument, MemoryFact
from app.services.canon_registry import (
    AliasConflictError,
    CausalGraphService,
    EntityRegistry,
    TimelineService,
)
from app.services.contradiction import ContradictionMatcher
from app.services.evaluation import EvalCase, EvalContext
from app.services.normalisation import normalise_fact_value
from app.services.retcon import RetconService

SUITE_CODE = "continuity_adversarial_v1"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def _document(ctx: EvalContext, series) -> MemoryDocument:
    doc = MemoryDocument(
        memory_code=f"mem_{series.series_code}_canon",
        memory_type="series_canon",
        scope_type="series",
        scope_id=series.id,
        title=f"{series.series_code} canon",
    )
    ctx.session.add(doc)
    ctx.session.flush()
    return doc


def _fact(
    ctx: EvalContext,
    doc: MemoryDocument,
    *,
    entity_key: str,
    fact_key: str,
    value: Any,
    mutability: str = "immutable",
    episode=None,
    order: int | None = None,
    importance: str = "normal",
) -> MemoryFact:
    row = MemoryFact(
        memory_document_id=doc.id,
        fact_type="canon",
        entity_type="character",
        entity_key=entity_key,
        fact_key=fact_key,
        fact_value=value,
        normalised_value=normalise_fact_value(value),
        mutability=mutability,
        importance=importance,
        valid_from_episode_id=episode.id if episode else None,
        timeline_start_order=order,
        status="active",
    )
    ctx.session.add(row)
    ctx.session.flush()
    return row


def _timeline(ctx: EvalContext, series, episode, *, order: int, code: str):
    return TimelineService(ctx.session).create_event(
        {
            "event_code": code,
            "event_type": "episode_span",
            "series_id": series.id,
            "episode_id": episode.id,
            "order_index": order,
            "title": code,
            "summary": code,
        }
    )


def _check(ctx: EvalContext, series, facts, episode=None) -> Dict[str, Any]:
    result = ContradictionMatcher(ctx.session).check(
        series_id=series.id, proposed_facts=facts, episode=episode, persist=False
    )
    return {
        "passed": result.passed,
        "blocking": sum(1 for c in result.contradictions if c.blocking),
        "kinds": sorted({c.kind for c in result.contradictions}),
        "progressions": len(result.progressions),
        "unregistered": result.unregistered_entities,
        "suggested": sorted(result.entity_suggestions),
        "permitted_retcons": len(result.permitted_retcons),
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
def _case_alias_spelling(ctx: EvalContext) -> Dict[str, Any]:
    """A fact filed under an alias must meet the fact filed under the code."""
    series = ctx.make_series("BM_ALIAS")
    registry = EntityRegistry(ctx.session)
    registry.create(
        series.id,
        {
            "entity_code": "MIRA",
            "entity_type": "character",
            "display_name": "Mira Kisaragi",
            "aliases": ["Kisaragi"],
        },
    )
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="MIRA", fact_key="birth_name", value="Mira Kisaragi")
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "kisaragi",
                "fact_key": "birth_name",
                "fact_value": "Mira Tsukino",
                "mutability": "immutable",
            }
        ],
    )


def _case_unicode_and_punctuation(ctx: EvalContext) -> Dict[str, Any]:
    """Accents and punctuation are spelling, not identity."""
    series = ctx.make_series("BM_UNICODE")
    registry = EntityRegistry(ctx.session)
    registry.create(
        series.id,
        {
            "entity_code": "RENE",
            "entity_type": "character",
            "display_name": "Rene O'Hara",
            "aliases": [],
        },
    )
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="RENE", fact_key="species", value="human")
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "René OHara",
                "fact_key": "species",
                "fact_value": "oni",
                "mutability": "immutable",
            }
        ],
    )


def _case_unregistered_typo_suggests(ctx: EvalContext) -> Dict[str, Any]:
    """A near-miss name is surfaced as a suggestion, never merged."""
    series = ctx.make_series("BM_TYPO")
    EntityRegistry(ctx.session).create(
        series.id,
        {
            "entity_code": "KISARAGI",
            "entity_type": "character",
            "display_name": "Kisaragi",
            "aliases": [],
        },
    )
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="KISARAGI", fact_key="species", value="human")
    # "Kisargi" is a typo; it must NOT silently resolve to KISARAGI and so must
    # not contradict, but it must be flagged for a human.
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "Kisargi",
                "fact_key": "species",
                "fact_value": "oni",
                "mutability": "immutable",
            }
        ],
    )


def _case_alias_conflict_refused(ctx: EvalContext) -> Dict[str, Any]:
    """Two entities cannot both answer to one name."""
    series = ctx.make_series("BM_CONFLICT")
    registry = EntityRegistry(ctx.session)
    registry.create(
        series.id,
        {
            "entity_code": "MIRA",
            "entity_type": "character",
            "display_name": "Mira",
            "aliases": ["Kisaragi"],
        },
    )
    try:
        registry.create(
            series.id,
            {
                "entity_code": "KADE",
                "entity_type": "character",
                "display_name": "Kade",
                "aliases": ["kisaragi"],
            },
        )
    except AliasConflictError:
        return {"refused": True}
    return {"refused": False}


def _case_value_formatting(ctx: EvalContext) -> Dict[str, Any]:
    """Case and whitespace differences are not contradictions."""
    series = ctx.make_series("BM_FORMAT")
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="MIRA", fact_key="home", value="Safehouse")
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "home",
                "fact_value": "  safehouse  ",
                "mutability": "immutable",
            }
        ],
    )


def _case_wrapped_value(ctx: EvalContext) -> Dict[str, Any]:
    """A scalar and the same scalar in a wrapper are one value."""
    series = ctx.make_series("BM_WRAP")
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="MIRA", fact_key="home", value={"value": "safehouse"})
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "home",
                "fact_value": "safehouse",
                "mutability": "immutable",
            }
        ],
    )


def _case_reordered_list(ctx: EvalContext) -> Dict[str, Any]:
    """A reordered trait list is the same trait list."""
    series = ctx.make_series("BM_LIST")
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="MIRA", fact_key="traits", value=["stoic", "loyal"])
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "traits",
                "fact_value": ["loyal", "stoic"],
                "mutability": "immutable",
            }
        ],
    )


def _case_immutable_change_blocks(ctx: EvalContext) -> Dict[str, Any]:
    """Changing settled, unchangeable canon blocks."""
    series = ctx.make_series("BM_IMMUTABLE")
    doc = _document(ctx, series)
    _fact(
        ctx,
        doc,
        entity_key="MIRA",
        fact_key="species",
        value="human",
        importance="critical",
    )
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "species",
                "fact_value": "oni",
                "mutability": "immutable",
            }
        ],
    )


def _case_stateful_progression_passes(ctx: EvalContext) -> Dict[str, Any]:
    """The plot moving forward is not an error.

    This is the case that decides whether the gate survives contact with
    writers. If it fails, every character development reads as a contradiction.
    """
    series = ctx.make_series("BM_PROGRESS")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    _timeline(ctx, series, ep1, order=1, code="EV01")
    _timeline(ctx, series, ep2, order=2, code="EV02")
    doc = _document(ctx, series)
    _fact(
        ctx,
        doc,
        entity_key="MIRA",
        fact_key="trust_in_kade",
        value="intact",
        mutability="stateful",
        episode=ep1,
        order=1,
    )
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "trust_in_kade",
                "fact_value": "damaged",
                "mutability": "stateful",
            }
        ],
        episode=ep2,
    )


def _case_mixed_mutability_blocks(ctx: EvalContext) -> Dict[str, Any]:
    """A draft cannot downgrade an immutable fact by declaring itself stateful.

    Otherwise the check is opt-out: any agent that wants to overwrite settled
    canon just labels its own fact `stateful`.
    """
    series = ctx.make_series("BM_MIXED")
    doc = _document(ctx, series)
    _fact(ctx, doc, entity_key="MIRA", fact_key="species", value="human")
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "species",
                "fact_value": "oni",
                "mutability": "stateful",
            }
        ],
    )


def _case_retcon_blocks(ctx: EvalContext) -> Dict[str, Any]:
    """Rewriting a later-established fact from an earlier episode blocks."""
    series = ctx.make_series("BM_RETCON")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    _timeline(ctx, series, ep1, order=1, code="EV01")
    _timeline(ctx, series, ep2, order=2, code="EV02")
    doc = _document(ctx, series)
    _fact(
        ctx,
        doc,
        entity_key="MIRA",
        fact_key="location",
        value="safehouse",
        mutability="stateful",
        episode=ep2,
        order=2,
    )
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "location",
                "fact_value": "alley",
                "mutability": "stateful",
            }
        ],
        episode=ep1,
    )


def _case_approved_retcon_passes(ctx: EvalContext) -> Dict[str, Any]:
    """An approved retcon is recorded but does not block."""
    series = ctx.make_series("BM_APPROVED")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    _timeline(ctx, series, ep1, order=1, code="EV01")
    _timeline(ctx, series, ep2, order=2, code="EV02")
    doc = _document(ctx, series)
    _fact(
        ctx,
        doc,
        entity_key="MIRA",
        fact_key="location",
        value="safehouse",
        mutability="stateful",
        episode=ep2,
        order=2,
    )
    retcons = RetconService(ctx.session)
    proposal = retcons.propose(
        series=series,
        entity_key="MIRA",
        fact_key="location",
        proposed_value="alley",
        rationale="EP01 flashback relocates the scene.",
        episode=ep1,
    )
    outcome = retcons.approve(proposal, decided_by="showrunner")
    checked = _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "location",
                "fact_value": "alley",
                "mutability": "stateful",
            }
        ],
        episode=ep1,
    )
    # The old fact is closed, not deleted -- "what was true before the rewrite"
    # has to stay answerable or a retcon is indistinguishable from a lie.
    superseded = ctx.session.get(MemoryFact, outcome.superseded_fact_id)
    written = ctx.session.get(MemoryFact, outcome.new_fact_id)
    return {
        **checked,
        "superseded_status": superseded.status if superseded else None,
        "new_value": written.fact_value if written else None,
        "new_is_retcon": written.is_retcon if written else None,
        "attributed_to": outcome.proposal.decided_by,
    }


def _case_approval_does_not_unblock_other_facts(ctx: EvalContext) -> Dict[str, Any]:
    """An approval covers one change, not the episode that requested it.

    The tempting shortcut is to let an approved retcon mark its episode as
    "cleared". That would let one signed-off change carry every other rewrite in
    the same draft through the gate with it.
    """
    series = ctx.make_series("BM_SPECIFIC")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    _timeline(ctx, series, ep1, order=1, code="EV01")
    _timeline(ctx, series, ep2, order=2, code="EV02")
    doc = _document(ctx, series)
    _fact(
        ctx, doc, entity_key="MIRA", fact_key="location", value="safehouse",
        mutability="stateful", episode=ep2, order=2,
    )
    _fact(
        ctx, doc, entity_key="MIRA", fact_key="allegiance", value="rebels",
        mutability="stateful", episode=ep2, order=2,
    )
    retcons = RetconService(ctx.session)
    proposal = retcons.propose(
        series=series,
        entity_key="MIRA",
        fact_key="location",
        proposed_value="alley",
        rationale="EP01 flashback relocates the scene.",
        episode=ep1,
    )
    retcons.approve(proposal, decided_by="showrunner")

    # `allegiance` was never proposed, let alone approved. Rewriting it from
    # EP01 is still a retcon.
    checked = _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "allegiance",
                "fact_value": "crown",
                "mutability": "stateful",
            }
        ],
        episode=ep1,
    )
    # And the approval itself is value-specific, not fact-specific.
    covers_other_value = retcons.approved_change(
        series.id, "MIRA", "location", "rooftop"
    )
    return {**checked, "approval_covers_other_value": covers_other_value is not None}


def _case_rebalance_preserves_order(ctx: EvalContext) -> Dict[str, Any]:
    """Respacing the timeline must not reorder it, or resettle fact positions wrongly."""
    series = ctx.make_series("BM_REBALANCE")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    _timeline(ctx, series, ep1, order=1, code="EV01")
    _timeline(ctx, series, ep2, order=2, code="EV02")
    doc = _document(ctx, series)
    fact = _fact(
        ctx,
        doc,
        entity_key="MIRA",
        fact_key="location",
        value="safehouse",
        mutability="stateful",
        episode=ep2,
        order=2,
    )
    timeline = TimelineService(ctx.session)
    timeline.rebalance(series.id, gap=10)
    ctx.session.refresh(fact)
    codes = [event.event_code for event in timeline.for_series(series.id)]
    return {
        "order": codes,
        "fact_start_order": fact.timeline_start_order,
        "episode_position": timeline.earliest_order_index(ep2.id),
    }


def _case_retcon_still_detected_after_rebalance(ctx: EvalContext) -> Dict[str, Any]:
    """Renumbering the timeline must not blind the retcon check.

    The fact's stored position is denormalised; if a rebalance forgets to
    resync it, the matcher compares a new position against a stale one and the
    retcon slips through.
    """
    series = ctx.make_series("BM_REBAL_RETCON")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    _timeline(ctx, series, ep1, order=1, code="EV01")
    _timeline(ctx, series, ep2, order=2, code="EV02")
    doc = _document(ctx, series)
    _fact(
        ctx,
        doc,
        entity_key="MIRA",
        fact_key="location",
        value="safehouse",
        mutability="stateful",
        episode=ep2,
        order=2,
    )
    TimelineService(ctx.session).rebalance(series.id, gap=100)
    return _check(
        ctx,
        series,
        [
            {
                "entity_type": "character",
                "entity_key": "MIRA",
                "fact_key": "location",
                "fact_value": "alley",
                "mutability": "stateful",
            }
        ],
        episode=ep1,
    )


def _case_effect_before_cause(ctx: EvalContext) -> Dict[str, Any]:
    """An effect ordered before its stated cause is impossible."""
    series = ctx.make_series("BM_CAUSE")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    early = _timeline(ctx, series, ep1, order=1, code="GATE_SEALED")
    late = _timeline(ctx, series, ep2, order=2, code="SEALING_RITUAL")
    CausalGraphService(ctx.session).link(
        series_id=series.id, cause=late, effect=early, link_type="causes"
    )
    violations = CausalGraphService(ctx.session).check(series.id)
    return {"kinds": sorted({v.kind for v in violations}), "count": len(violations)}


def _case_causal_cycle(ctx: EvalContext) -> Dict[str, Any]:
    """A loop of causes has no valid ordering at all."""
    series = ctx.make_series("BM_CYCLE")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    ep3 = ctx.make_episode(series, "EP03")
    a = _timeline(ctx, series, ep1, order=1, code="A")
    b = _timeline(ctx, series, ep2, order=2, code="B")
    c = _timeline(ctx, series, ep3, order=3, code="C")
    graph = CausalGraphService(ctx.session)
    graph.link(series_id=series.id, cause=a, effect=b)
    graph.link(series_id=series.id, cause=b, effect=c)
    graph.link(series_id=series.id, cause=c, effect=a)
    violations = graph.check(series.id)
    return {
        "has_cycle": any(v.kind == "causal_cycle" for v in violations),
        "cycles": sum(1 for v in violations if v.kind == "causal_cycle"),
    }


def _case_consistent_causality_quiet(ctx: EvalContext) -> Dict[str, Any]:
    """A correctly ordered cause/effect chain reports nothing."""
    series = ctx.make_series("BM_CAUSE_OK")
    ep1 = ctx.make_episode(series, "EP01")
    ep2 = ctx.make_episode(series, "EP02")
    cause = _timeline(ctx, series, ep1, order=1, code="RITUAL")
    effect = _timeline(ctx, series, ep2, order=2, code="GATE_SEALED")
    graph = CausalGraphService(ctx.session)
    graph.link(series_id=series.id, cause=cause, effect=effect)
    return {"violations": len(graph.check(series.id))}


#: The suite. Ordered by category so a failure report reads top to bottom.
ADVERSARIAL_CASES = [
    EvalCase(
        case_code="alias_spelling_still_contradicts",
        category="entity_resolution",
        description="A fact filed under an alias meets the fact filed under the code.",
        expects_block=True,
        run=_case_alias_spelling,
        expectation={"passed": False, "blocking": 1, "kinds": ["immutable_fact_changed"]},
    ),
    EvalCase(
        case_code="accents_and_punctuation_are_spelling",
        category="entity_resolution",
        description="'René OHara' resolves to \"Rene O'Hara\".",
        expects_block=True,
        run=_case_unicode_and_punctuation,
        expectation={"passed": False, "blocking": 1},
    ),
    EvalCase(
        case_code="typo_suggests_never_merges",
        category="entity_resolution",
        description="A near-miss name is flagged for review, not silently resolved.",
        expects_block=False,
        run=_case_unregistered_typo_suggests,
        expectation={"passed": True, "blocking": 0, "suggested": ["Kisargi"]},
    ),
    EvalCase(
        case_code="alias_conflict_refused_at_write",
        category="entity_resolution",
        description="Two entities cannot claim one spelling.",
        expects_block=True,
        run=_case_alias_conflict_refused,
        expectation={"refused": True},
    ),
    EvalCase(
        case_code="case_and_whitespace_are_not_contradictions",
        category="value_normalisation",
        description="'Safehouse' and '  safehouse  ' are one value.",
        expects_block=False,
        run=_case_value_formatting,
        expectation={"passed": True, "blocking": 0},
    ),
    EvalCase(
        case_code="wrapped_scalar_matches_bare_scalar",
        category="value_normalisation",
        description="{'value': 'safehouse'} equals 'safehouse'.",
        expects_block=False,
        run=_case_wrapped_value,
        expectation={"passed": True, "blocking": 0},
    ),
    EvalCase(
        case_code="reordered_list_is_the_same_list",
        category="value_normalisation",
        description="['loyal','stoic'] equals ['stoic','loyal'].",
        expects_block=False,
        run=_case_reordered_list,
        expectation={"passed": True, "blocking": 0},
    ),
    EvalCase(
        case_code="immutable_change_blocks",
        category="mutability",
        description="Changing settled unchangeable canon blocks.",
        expects_block=True,
        run=_case_immutable_change_blocks,
        expectation={"passed": False, "blocking": 1, "kinds": ["immutable_fact_changed"]},
    ),
    EvalCase(
        case_code="stateful_progression_passes",
        category="mutability",
        description="Trust going from intact to damaged is the plot, not an error.",
        expects_block=False,
        run=_case_stateful_progression_passes,
        expectation={"passed": True, "blocking": 0, "progressions": 1},
    ),
    EvalCase(
        case_code="self_declared_stateful_cannot_override_immutable",
        category="mutability",
        description="A draft cannot opt out by labelling its own fact stateful.",
        expects_block=True,
        run=_case_mixed_mutability_blocks,
        expectation={"passed": False, "blocking": 1},
    ),
    EvalCase(
        case_code="retcon_blocks",
        category="timeline",
        description="An earlier episode rewriting a later-established fact blocks.",
        expects_block=True,
        run=_case_retcon_blocks,
        expectation={"passed": False, "blocking": 1, "kinds": ["retcon"]},
    ),
    EvalCase(
        case_code="rebalance_preserves_order",
        category="timeline",
        description="Respacing renumbers without reordering, and resyncs fact positions.",
        expects_block=False,
        run=_case_rebalance_preserves_order,
        expectation={"order": ["EV01", "EV02"], "fact_start_order": 20, "episode_position": 20},
    ),
    EvalCase(
        case_code="retcon_survives_rebalance",
        category="timeline",
        description="Renumbering the timeline does not blind the retcon check.",
        expects_block=True,
        run=_case_retcon_still_detected_after_rebalance,
        expectation={"passed": False, "blocking": 1, "kinds": ["retcon"]},
    ),
    EvalCase(
        case_code="approved_retcon_rewrites_canon_and_passes",
        category="retcon",
        description=(
            "After approval the draft passes, canon holds the new value, and the "
            "old fact is closed rather than deleted."
        ),
        expects_block=False,
        run=_case_approved_retcon_passes,
        expectation={
            "passed": True,
            "blocking": 0,
            "superseded_status": "superseded",
            "new_value": "alley",
            "new_is_retcon": True,
            "attributed_to": "showrunner",
        },
    ),
    EvalCase(
        case_code="approval_does_not_unblock_other_facts",
        category="retcon",
        description="One signed-off change does not carry the rest of the draft through.",
        expects_block=True,
        run=_case_approval_does_not_unblock_other_facts,
        expectation={
            "passed": False,
            "blocking": 1,
            "kinds": ["retcon"],
            "approval_covers_other_value": False,
        },
    ),
    EvalCase(
        case_code="effect_before_cause_detected",
        category="causality",
        description="An effect ordered before its stated cause is reported.",
        expects_block=True,
        run=_case_effect_before_cause,
        expectation={"kinds": ["effect_before_cause"], "count": 1},
    ),
    EvalCase(
        case_code="causal_cycle_detected",
        category="causality",
        description="A loop of causes is reported once.",
        expects_block=True,
        run=_case_causal_cycle,
        expectation={"has_cycle": True, "cycles": 1},
    ),
    EvalCase(
        case_code="consistent_causality_is_quiet",
        category="causality",
        description="A correctly ordered chain reports nothing.",
        expects_block=False,
        run=_case_consistent_causality_quiet,
        expectation={"violations": 0},
    ),
]
