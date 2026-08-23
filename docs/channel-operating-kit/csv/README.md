# Import CSVs

Header-only CSVs for each database, plus one clearly-marked example row so you can see
what belongs in each column.

## Notion

**Import → CSV** creates a new database with these columns. Notion imports every column
as **Text**, so after importing you must change each property to its intended type
(Select, Number, Date, Relation, Checkbox) using the type table in
[../04-database-schemas.md](../04-database-schemas.md). Relation properties cannot be
imported at all — add those by hand after both databases exist.

Delete the `EXAMPLE` row after importing.

## Google Sheets

**File → Import → Upload**, then set data validation on the Select-equivalent columns
using the option lists in `../04-database-schemas.md`. Sheets is the better home for
`packaging-tracker.csv` specifically — see `../05-packaging-tracker.md`.

## Files

| File | Database |
|---|---|
| `video-pipeline.csv` | Video Pipeline |
| `shorts-queue.csv` | Shorts Queue |
| `packaging-tracker.csv` | Packaging Tracker |
| `ideas-bank.csv` | Ideas Bank |
| `affiliate-tracker.csv` | Affiliate Tracker |
| `weekly-reviews.csv` | Weekly Reviews |

The Analytics Log has no CSV — it is optional and most operators should skip it. See
`../03-notion-dashboard-layout.md#what-to-skip`.
