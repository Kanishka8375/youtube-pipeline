# AI Channel Operating Kit

A reusable operating system for a faceless **AI tools / automation** YouTube channel,
run by a solo operator. It covers the weekly production loop, the Notion workspace that
tracks it, and a scoring model that rates each week automatically.

Everything here is a spec you build once and then run. Nothing depends on the code in
this repo — but the databases line up with what `pipeline.py` produces, so a video the
pipeline generates can be dropped straight into the Video Pipeline database.

## Contents

| File | What it gives you |
|---|---|
| [01-weekly-checklist.md](01-weekly-checklist.md) | Day-by-day production checklist, one week per copy |
| [02-weekly-time-system.md](02-weekly-time-system.md) | Exact time blocks for both cadence tiers |
| [03-notion-dashboard-layout.md](03-notion-dashboard-layout.md) | Page tree and block layout for the main dashboard |
| [04-database-schemas.md](04-database-schemas.md) | Full property tables for all seven databases |
| [05-packaging-tracker.md](05-packaging-tracker.md) | Thumbnail + title testing methodology |
| [06-weekly-review-dashboard.md](06-weekly-review-dashboard.md) | Review dashboard sections, views and filters |
| [07-scoring-framework.md](07-scoring-framework.md) | 25-point weekly score with Notion formulas |
| [08-copy-paste-templates.md](08-copy-paste-templates.md) | Page templates to paste into Notion |
| [csv/](csv/) | Header-only CSVs — import into Notion or Sheets to create each database |

## Pick a cadence tier first

Every other number in this kit keys off your weekly output target. There are two
supported tiers, and the honest time cost of each:

| Tier | Output per week | Realistic time | Who it fits |
|---|---|---|---|
| **Tier 1 — Sustainable** | 1 long-form + 2–3 Shorts | **~9h 45m** | Solo operator with a day job |
| **Tier 2 — Aggressive** | 2 long-form + 7 Shorts | **~18h** | Full-time, or solo + an editor |

Tier 2 is roughly double Tier 1, not a small step up. Start at Tier 1, stay there until
the weekly score is consistently in "Strong Week" territory, then move up. Set your
choice in the `Long-Form Target` and `Shorts Target` properties on the Weekly Reviews
database — the consistency score reads from those, so scoring stays correct at either tier.

## Build order

Build in this order so nothing references a database that doesn't exist yet.

1. **Video Pipeline** — the spine; everything else relates to it
2. **Shorts Queue** — add the `Related Long-Form` relation back to Video Pipeline
3. **Packaging Tracker** — add the `Related Video` relation
4. **Ideas Bank** — standalone, no relations needed
5. **Affiliate Tracker** — add the `Promoted In Videos` relation
6. **Analytics Log** — add the `Related Video` relation (or skip it and keep metrics on
   the Video Pipeline row; see the note in `04-database-schemas.md`)
7. **Weekly Reviews** — add the number properties first, formulas last
8. **ToolStack AI Dashboard** page — linked views of everything above
9. **Weekly Review Dashboard** page — the Sunday surface
10. **Page templates** — from `08-copy-paste-templates.md`

Steps 1–3 are enough to start publishing. Steps 7–9 only pay off once you have three or
four weeks of data to compare.

## The one rule that keeps this working

Log metrics on a fixed day, at the same point in each video's life. Every threshold in
the scoring framework assumes **7-day** numbers. Mixing 24-hour and 30-day figures into
the same column makes the whole comparison meaningless, which is the usual way trackers
like this quietly stop being useful.
