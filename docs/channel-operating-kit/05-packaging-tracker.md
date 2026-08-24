# Thumbnail + Title Testing

Schema is in [04-database-schemas.md](04-database-schemas.md#c-packaging-tracker).
This file is the method: what to test, how to read the result, and when to repackage.

---

## What you are actually testing

Not "good thumbnail" vs "bad thumbnail". Three specific things:

### Thumbnail variables
- text vs no text
- logo-heavy vs icon/UI-heavy
- dark vs bright contrast
- one tool vs several
- result-focused wording vs curiosity wording
- clean layout vs dense layout

### Title variables
- `Best AI Tools for [Audience]`
- `I Tested [#] AI Tools`
- `[Tool A] vs [Tool B]`
- `How to Use AI for [Result]`
- `[#] AI Tools That Save [Time]`

### The pairing
A strong title with a weak thumbnail loses the click. A strong thumbnail with a vague
title wins the click from the wrong person, and retention collapses. The pairing is the
unit of analysis, which is why one row covers both.

---

## Where to build it

Notion if you want it beside everything else; Google Sheets if you want to sort, filter
and chart it. Sheets is genuinely better for this one database because packaging analysis
is comparison across many rows, which is what spreadsheets are for. Header-only CSVs for
both are in [csv/](csv/).

---

## Reading the results

The two-by-two that answers almost every packaging question:

| | Retention strong | Retention weak |
|---|---|---|
| **CTR strong** | Package and topic match — repeat this exact combination | Promise mismatch: the packaging oversells the content |
| **CTR weak** | Packaging problem: the content works, nobody is clicking | Topic problem — repackaging will not save it |

The bottom-right is the one people misdiagnose most. If both numbers are weak, the topic
had no demand; a new thumbnail buys you nothing.

---

## Repackaging triggers

Repackage when:
- CTR is clearly below your channel's trailing median, with enough impressions to judge
- impressions are climbing but views are not
- the title is vague
- the thumbnail is unreadable at mobile size
- the topic is strong but the packaging is weak (the bottom-left quadrant above)

Do **not** repackage when:
- impressions are still too low to mean anything — under ~1,000 impressions, CTR is noise
- search traffic is only just starting to build
- the topic itself had weak demand

Starting thresholds, to replace with your own baseline after eight weeks:

| Situation | Consider repackaging below |
|---|---|
| Browse-heavy video | CTR 4% |
| Strong comparison topic | CTR 5% |

Log the change: tick `Repackaged?`, set `Repackage Date`, and record `Post-Change CTR`
after a week. Without those three fields, a repackage is untracked and you learn nothing
from it. Note that YouTube's reported CTR blends before and after the swap, so compare
`Post-Change CTR` against the same window length, not against the lifetime figure.

---

## Test one variable at a time

Running all three of these at once tells you nothing about which one moved the number.

**Test 1 — Title formula:** `Best AI Tools for [Audience]` vs `[Tool A] vs [Tool B]` vs `I Tested [#] AI Tools`

**Test 2 — Thumbnail text density:** 2–3 words vs 4–6 words vs no text

**Test 3 — Thumbnail focus:** logos vs split comparison vs result phrase vs UI screenshot

Rules that keep the comparison clean:
- change one main variable at a time
- log the change immediately, not at the end of the week
- compare within a topic category, not across the whole channel
- compare search-driven videos separately from browse-driven ones — the traffic sources
  respond to completely different signals
- keep old thumbnail files; you will want to go back

---

## Example rows

| Video ID | Topic | Final Title | Title Formula | Thumbnail Style | Thumbnail Text | CTR 24h | CTR 7d | AVD | Rating | Notes |
|---|---|---|---|---|---|---:|---:|---:|---|---|
| TSAI-001 | creator tools | 7 Best AI Tools for YouTube Creators | Best AI Tools for [Audience] | Tool logos | BEST AI TOOLS | 5.4 | 6.1 | 4.3 | Strong | broad utility, clear audience |
| TSAI-002 | comparison | ChatGPT vs Claude for Scriptwriting | [Tool A] vs [Tool B] | Split comparison | GPT vs CLAUDE | 7.2 | 7.8 | 5.1 | Breakout | simple decision framing |
| TSAI-003 | workflow | This AI Workflow Saves Me 10 Hours a Week | This Workflow Saves [Time] | Outcome-focused | SAVE 10 HRS | 4.1 | 4.7 | 4.9 | Average | title strong, thumbnail vague |

---

## Weekly packaging review

- [ ] Which title formula had the highest CTR?
- [ ] Which thumbnail style won?
- [ ] Which title angle performed best?
- [ ] Did comparisons beat roundups?
- [ ] Which thumbnail text length worked best?
- [ ] Which video has weak CTR but strong retention? (repackage candidate)
- [ ] What packaging should be repeated next week?

## Monthly pattern review

Every four weeks, look across all rows rather than at the last few:

- Which title formula performs best overall, and which per content type?
- Which thumbnail style gives the most *reliable* CTR — not the highest single result?
- Which topic categories underperform regardless of packaging? (stop making them)
- Are short, clear titles beating clever ones?
- Are logo-heavy thumbnails helping or hurting?
- Which audience word wins: creators, freelancers, or solopreneurs?

Four weeks at Tier 1 is only four data points. Treat month-one conclusions as hypotheses
and re-test them; treat month-three conclusions as decisions.

---

## Packaging score

Score each video 1–5 on five dimensions for a quick comparable number:

- CTR strength
- retention alignment
- thumbnail clarity
- title clarity
- topic-packaging fit

Example: 4 + 5 + 4 + 5 + 5 = **23/25**.
