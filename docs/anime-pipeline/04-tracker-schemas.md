# Notion / Airtable Tracker Schemas

The database is the system of record. These trackers are the human surface over
it — read-mostly dashboards, not a second source of truth.

Import CSVs: [csv/](csv/).

---

## Which tool

**Airtable** for the QC dashboard: linked records, rollups and formula fields do
the aggregation the QC review needs, and Notion's rollups are weaker at it.

**Notion** if the trackers live beside the rest of your production docs and you
would rather have one tool than the right one. That is a legitimate trade.

Either way, **do not hand-maintain the scores.** They are computed by
`master_qc_report.py` and served by `/qc-reports/episode/{code}/publish-gate`.
Sync them in; typing them twice guarantees they diverge, and the version that
gates publication is the one in the database.

---

## Table: Episodes

| Field | Type | Notes |
|---|---|---|
| Episode ID | Single line text | `EP01` — matches `episodes.episode_code` |
| Season | Single line text | `S01` |
| Episode Number | Number | |
| Working Title | Single line text | |
| Final Title | Single line text | |
| Status | Single select | Idea / In Production / Review / Published |
| Current Stage | Single select | Script / Scene Plan / Rough Cut / Final Cut / Published |
| Runtime Target Min | Number | |
| Publish Target Date | Date | |
| Main Hook | Long text | |
| Core Conflict | Long text | |
| Emotional Arc | Long text | |
| Ending Beat | Long text | |
| Priority | Single select | Low / Normal / High / Urgent |
| QC Reports | Link → QC Reports | |
| QC Notes | Link → QC Notes | |
| Latest QC Score | Rollup (MAX of Overall Score) | |
| Latest Publish Ready | Rollup / Lookup | |
| Open Mandatory Fixes | Rollup (count of unresolved mandatory QC Notes) | |
| Publish Blocked | Formula | below |

```
IF(
  OR(
    {Latest QC Score} < 85,
    {Open Mandatory Fixes} > 0,
    {Latest Publish Ready} = 0
  ),
  "Blocked",
  "Clear"
)
```

> The earlier draft of this formula tested `{Status} = "Review"`, which marks an
> episode blocked purely for being under review — the normal state of every
> episode that has not shipped. Test the QC conditions, not the workflow status.

---

## Table: QC Reports

| Field | Type | Notes |
|---|---|---|
| QC Report ID | Single line text | `MQC_EP01_v1` |
| Episode | Link → Episodes | |
| Reviewer Agent | Link → Agents | Master Anime QC |
| QC Stage | Single select | Script / Scene Plan / Rough Cut / Final Cut |
| QC Type | Single select | Story QC / Scene QC / Rough Cut QC / Audio QC / Master QC |
| Status | Single select | Pending / In Review / Needs Revision / Approved / Rejected |
| Final Decision | Single select | Pass / Pass with Revisions / Reject |
| Publish Ready | Checkbox | **Synced, never typed** |
| Overall Score | Number | **Synced** — computed from the categories |
| Anime Style Score | Number | **Synced** |
| Story Logic … Audio Mix Score | Number ×12 | 0–10 each |
| Critical Issues Count | Number | |
| Mandatory Fixes Count | Number | |
| Optional Fixes Count | Number | |
| Story / Screenplay / Emotion / Editing / Audio Issues | Long text | |
| Mandatory Fixes | Long text | |
| Optional Polish | Long text | |
| Final Publish Notes | Long text | |
| Rough Cut Link, Final Cut Link | URL | |
| Report JSON | Long text | Raw payload |
| QC Notes | Link → QC Notes | |
| Review Date | Date | |
| Readiness Tier | Formula | below |
| Blocker Status | Formula | below |

```
Readiness Tier:
IF({Overall Score} >= 90, "Premium Ready",
IF({Overall Score} >= 85, "Publishable",
IF({Overall Score} >= 70, "Revision Recommended", "Do Not Publish")))
```

```
Blocker Status:
IF(
  OR({Publish Ready} = 0, {Mandatory Fixes Count} > 0, {Critical Issues Count} > 0),
  "Blocked",
  "Clear"
)
```

**Do not add a "mean of the twelve category scores" field.** A plain average
contradicts the weighted total — emotion carries weight 12 and vfx weight 5, so
the two numbers disagree on every non-uniform report, and whichever one someone
happens to read first becomes the decision.

### Category score fields

`story_logic_score`, `screenplay_score`, `emotion_score`,
`character_consistency_score`, `scene_pacing_score`, `shot_design_score`,
`animation_feel_score`, `editing_rhythm_score`, `sound_design_score`,
`music_score`, `vfx_score`, `audio_mix_score` — every one on the same 0–10
scale. Weighting happens at roll-up, not per field.

---

## Table: QC Notes

Frame-accurate editor notes. See
[03-anime-edit-checklist.md](03-anime-edit-checklist.md).

| Field | Type | Notes |
|---|---|---|
| QC Note ID | Single line text | `QCN_EP01_SC03_001` |
| QC Report | Link → QC Reports | |
| Episode | Link → Episodes | |
| Scene ID | Single line text | |
| Shot ID | Single line text | |
| Timecode | Single line text | `00:02:21:14` |
| **Frame Rate** | Number | **Required.** Without it every frame count is ambiguous |
| Issue Type | Single select | Reaction Timing / Music Timing / SFX Alignment / Pacing / VFX / Dialogue Mix |
| Severity | Single select | Low / Medium / High / Critical |
| Issue Summary | Long text | |
| Why It Hurts | Long text | |
| Current Duration Frames | Number | |
| Recommended Duration Frames | Number | |
| Frame Delta | Formula | `{Recommended} - {Current}` |
| Delta ms | Formula | `ROUND({Frame Delta} / {Frame Rate} * 1000, 1)` |
| Fix Note | Long text | |
| Mandatory Fix | Checkbox | Blocks publication |
| Resolved | Checkbox | |
| Assigned To | Single line text | |
| Category | Single select | Story / Emotion / Editing / Audio / VFX |
| Resolution Status | Formula | below |

```
IF({Resolved} = 1, "Resolved",
IF({Mandatory Fix} = 1, "Open Mandatory", "Open Optional"))
```

---

## Views worth building

**Episodes**
- Publish Blocked — `Publish Blocked = "Blocked"`
- Ready to Publish — `Publish Blocked = "Clear"`

**QC Reports**
- Final Cut QC — `QC Stage = Final Cut`
- Needs Revision — `Status = Needs Revision`
- Critical Issues — `Critical Issues Count > 0`
- By Episode — grouped

**QC Notes**
- Open Mandatory — `Mandatory Fix` checked, `Resolved` unchecked. The single
  most useful view: it is exactly the list standing between the episode and
  release.
- High Severity — `Severity` is High or Critical
- By Scene — grouped

---

## Notion import caveats

Notion imports every CSV column as **Text**. After importing, convert:

- `Publish Ready`, `Mandatory Fix`, `Resolved` → Checkbox
- all score and count columns, `Frame Rate` → Number
- `Review Date` → Date
- link columns → URL
- `Status`, `QC Stage`, `QC Type`, `Final Decision`, `Severity` → Select

Relations cannot be imported at all — create them after both tables exist.
