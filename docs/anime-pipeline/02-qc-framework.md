# Master QC Framework

A thirteenth agent that reviews the other twelve. It does not produce episode
content; it decides whether an episode ships.

Implementation: `anime_pipeline/app/schemas/master_qc_report.py`.
Prompt: `anime_pipeline/app/agents/prompts/master_anime_qc.txt`.

---

## What was inconsistent in the original design

The QC model arrived with three rules that could not all be true at once. All
three are resolved here, and the resolution is enforced in code rather than
documented and hoped for.

**1. Category maximums contradicted the example reports.** The weight table gave
each category a different maximum — Emotional Impact 12, Audio Mix 5 — but the
example reports scored every category on a 0–10 scale, producing `audio_mix: 9`
against a stated maximum of 5, and `character_consistency: 9` against 8.

*Resolved:* every category is scored **0–10**. The weights are how much each
category *matters*, applied at roll-up. A score above 10 is now a validation
error rather than a number nobody notices.

**2. `overall_score` matched neither the sum nor the weighted sum.** The example
report's sections summed to 92; it declared 84.

*Resolved:* `overall_score` and `anime_style_score` are **computed from the
sections**. Any value supplied by the caller is discarded. An agent cannot claim
a passing total alongside failing sections.

**3. Three different publish thresholds.** 80 in one formula, 85 in the publish
rule, 90 in the readiness tier.

*Resolved:* one constant, `PUBLISH_SCORE_THRESHOLD = 85`, used by the schema,
the orchestrator's publish gate and the `/pipeline/qc-model` endpoint.

---

## Category weights

| Category | Weight | What it checks |
|---|---:|---|
| story_logic | 10 | Plot clarity, progression, no contradictions |
| screenplay | 10 | Dialogue efficiency, scene purpose, structure |
| emotion | 12 | Feeling readability, tension, payoff |
| character_consistency | 8 | Voice, reactions, motivation |
| scene_pacing | 10 | Dead space, drag, rushed beats |
| shot_design | 8 | Framing, emphasis, cinematic flow |
| animation_feel | 8 | Motion liveliness; not static, not chaotic |
| editing_rhythm | 10 | Cut timing, hold timing, impact timing |
| sound_design | 7 | SFX clarity, layering, environment |
| music | 7 | Cue selection, emotional sync, restraint |
| vfx | 5 | Glitch, speed lines, impact FX, overuse |
| audio_mix | 5 | Dialogue clarity, music and SFX balance |
| **Total** | **100** | |

`overall_score = Σ (category_score / 10 × weight)`, rounded.

**`anime_style_score`** re-rolls the same scores over the seven edit-feel
categories only — scene_pacing, shot_design, animation_feel, editing_rhythm,
sound_design, music, vfx — normalised to 100. A story-strong, edit-weak episode
scores well overall and badly here, which is precisely the failure mode a
faceless anime channel needs to see.

## Readiness tiers

| Overall score | Tier | What to do |
|---|---|---|
| 90–100 | Premium Ready | Repeat this episode's pattern while it is working |
| 85–89 | Publishable | Ship it; make one improvement next episode |
| 70–84 | Revision Recommended | Read the category scores to find which half failed |
| 0–69 | Do Not Publish | Topic, hook or consistency problem, not a polish problem |

## The publish gate

An episode publishes only when **all four** hold:

1. `overall_score >= 85`
2. no critical issues
3. no outstanding mandatory fixes
4. the report's stage is `final_cut`

`publish_ready` is derived from those four, never accepted from input. Condition
4 matters: a rough-cut report scoring 95 does not clear an episode for release.

**Section-level `required_fixes` count as mandatory.** They are folded into
`required_fixes_before_publish` automatically, so a fix recorded inside a single
category still blocks the gate. This is why the QC prompt tells the agent to
reserve `required_fixes` for genuine defects and put everything else in
`optional_polish` — anything in the former stops the episode.

## QC gates in the pipeline

| Gate | Runs after | Checks |
|---|---|---|
| script | script_draft | Hook quality, scene purpose, emotional movement, dialogue, producibility |
| scene_plan | scene_plan | Framing variety, readability, motion opportunities, emphasis |
| rough_cut | rough_cut | Pacing, shot rhythm, dead air, sound placement, temp music |
| final_cut | final_cut | Final emotional sync, mix, VFX restraint, cliffhanger landing |

Intermediate gates pass on decision, not on `publish_ready` — see
[01-orchestration.md](01-orchestration.md#gating-rules).

## Reading a failing report

Look at the category scores before the total. The most common misread is an
episode that scores 78 because two of twelve categories collapsed while the
other ten were fine — that is a targeted fix, not a rewrite. `weakest_categories`
on the report, and on the `/publish-gate` response, names them worst-first.

## Diagnosing where the problem actually is

| CTR | Retention | Diagnosis |
|---|---|---|
| strong | strong | Package and topic match; repeat it |
| strong | weak | Promise mismatch — the packaging oversells the episode |
| weak | strong | Packaging problem; the episode works, nobody is clicking |
| weak | weak | Topic problem. Repackaging will not save it |

The bottom-right is the one most often misdiagnosed as a thumbnail problem.
