"""Canonical forms for names and fact values.

These are the comparisons the whole continuity system rests on: get either
wrong and the gate either fires on every formatting difference or never fires
at all.
"""

from __future__ import annotations

import pytest

from app.services.normalisation import (
    normalise_alias,
    normalise_fact_value,
    unwrap_scalar,
    values_agree,
)


@pytest.mark.parametrize(
    "written",
    [
        "Rene O'Hara",
        "René OHara",
        "rene o hara",
        "  RENE   O'HARA  ",
        "Rene-O'Hara",
        "René O’Hara",
    ],
)
def test_every_spelling_of_one_name_reduces_to_one_key(written):
    assert normalise_alias(written) == "reneohara"


def test_distinct_names_stay_distinct():
    assert normalise_alias("Mira") != normalise_alias("Mara")
    assert normalise_alias("Kade") != normalise_alias("Kane")


@pytest.mark.parametrize("empty", ["", "   ", "!!!", "—", None])
def test_a_name_that_reduces_to_nothing_is_not_a_key(empty):
    # Returning "" rather than raising: callers decide, and every caller here
    # treats it as "unusable name" rather than indexing an empty string that
    # every other unusable name would then collide with.
    assert normalise_alias(empty) == ""


@pytest.mark.parametrize(
    "left,right",
    [
        ("Safehouse", "  safehouse  "),
        ({"value": "safehouse"}, "safehouse"),
        ({"v": {"value": "alley"}}, "alley"),
        (3, 3.0),
        (["loyal", "stoic"], ["stoic", "loyal"]),
        (True, True),
    ],
)
def test_values_that_mean_the_same_thing_agree(left, right):
    assert values_agree(left, right)


@pytest.mark.parametrize(
    "left,right",
    [
        ("safehouse", "alley"),
        ({"value": "safehouse"}, {"value": "alley"}),
        (["loyal"], ["loyal", "stoic"]),
        (3, 4),
        (True, False),
        (None, "null"),
    ],
)
def test_values_that_differ_do_not_agree(left, right):
    assert not values_agree(left, right)


def test_a_multi_key_dict_is_not_unwrapped():
    # Picking one of several keys as "the value" would be inventing meaning.
    payload = {"value": "alley", "note": "at dusk"}
    assert unwrap_scalar(payload) == payload


def test_none_and_the_string_null_are_different_values():
    # An absent value and a fact whose value is the text "null" are not the
    # same claim, and the sentinel is what keeps them apart.
    assert normalise_fact_value(None) != normalise_fact_value("null")
    assert not values_agree(None, "null")


def test_prose_too_long_to_index_has_no_canonical_form():
    long_text = "x" * 5000
    assert normalise_fact_value({"summary": long_text}) is None
    # No canonical form means fall back to raw equality, which is stricter.
    assert values_agree({"summary": long_text}, {"summary": long_text})
    assert not values_agree({"summary": long_text}, {"summary": "short"})
