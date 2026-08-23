# Tracker import CSVs

Header rows plus example data for the Notion / Airtable trackers described in
[../04-tracker-schemas.md](../04-tracker-schemas.md).

| File | Table |
|---|---|
| `episodes.csv` | Episodes |
| `qc-reports.csv` | QC Reports |
| `qc-notes.csv` | QC Notes |

**Notion:** every column imports as Text; convert types afterwards and add
relations by hand — see the caveats section of the schema doc.

**Airtable:** import, then set the formula fields (Readiness Tier, Blocker
Status, Frame Delta, Delta ms) and the linked-record columns.

Delete the example rows once the tables are wired up. The `Overall Score` and
`Publish Ready` values in `qc-reports.csv` are the real computed outputs for
those category scores — the example EP01 row scores 76, which is
"Revision Recommended", not publishable, and that is the point of the example.
