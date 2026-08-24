# Notion Dashboard Layout

The main workspace page. One page, everything reachable from it.

---

## Page tree

```
ToolStack AI Dashboard
├── Weekly Focus                 (current week, pinned to the top)
├── Quick Add
│   ├── + New Long-Form Video
│   ├── + New Short
│   ├── + New Idea
│   ├── + New Affiliate Tool
│   └── + New Weekly Review
├── Video Pipeline
│   ├── Board View               (grouped by Status)
│   ├── Calendar View            (by Publish Date)
│   ├── Published View
│   └── Money Videos View        (Affiliate Fit = High)
├── Shorts Queue
│   ├── Production View
│   ├── Scheduled View
│   └── Top Performers View
├── Packaging Tracker
│   ├── This Week Packaging
│   ├── Best CTR Formulas
│   └── Weak Packaging to Fix
├── Ideas Bank
│   ├── All Ideas
│   ├── Approved Ideas
│   └── Evergreen Ideas
├── Affiliate Tracker
│   ├── Active Programs
│   ├── Top Converters
│   └── Untested Tools
├── Analytics Log
│   ├── Latest Uploads
│   ├── Best Performers
│   └── Lessons
├── Weekly Review Dashboard      (see 06-weekly-review-dashboard.md)
├── Templates
│   ├── Weekly Checklist Template
│   ├── Script Template
│   ├── Description Template
│   ├── Pinned Comment Template
│   ├── Title Formula Bank
│   └── Thumbnail Notes
└── SOPs
    ├── Weekly Workflow SOP
    ├── Upload SOP
    ├── Editing SOP
    └── Analytics Review SOP
```

---

## Block layout on the dashboard page

### Row 1 — Weekly Focus (3 columns)

| Column | Content |
|---|---|
| Left | Current week label and dates |
| Middle | This week's main video (linked view, filtered to the current pipeline card) |
| Right | This week's KPI focus |

### Row 2 — Quick Add

A single row of Notion template buttons. Each one creates a pre-filled row in its
database so a captured idea never needs manual property setup.

### Row 3 — Production (2 columns)

| Column | Content |
|---|---|
| Left | Video Pipeline, board view grouped by Status |
| Right | Calendar view of the next 30 days |

### Row 4 — Queue and capture (2 columns)

| Column | Content |
|---|---|
| Left | Shorts Queue, filtered to Status is not Published |
| Right | Ideas Bank, filtered to Status = Backlog, sorted by Priority |

### Row 5 — Money and measurement (2 columns)

| Column | Content |
|---|---|
| Left | Affiliate Tracker, sorted by Clicks descending |
| Right | Analytics Log, latest 10 uploads |

### Row 6 — Reference (2 columns)

| Column | Content |
|---|---|
| Left | Templates library |
| Right | SOP library |

---

## Template buttons worth building

Build these five before anything else — they are what keeps data entry from becoming
the reason you stop using the system.

| Button | Creates | Pre-fills |
|---|---|---|
| **+ New Long-Form Video** | Video Pipeline row | Status = Idea, Priority = Medium, publish date = next Friday, full card body from `08-copy-paste-templates.md` |
| **+ New Short** | Shorts Queue row | Status = Idea, CTA Type = Watch Full Video |
| **+ New Idea** | Ideas Bank row | Status = Backlog, Source = Personal Idea |
| **+ New Affiliate Tool** | Affiliate Tracker row | Status = Testing, Best Placement = Description |
| **+ New Weekly Review** | Weekly Reviews row | Status = Draft, targets pre-set to your tier, full review body |

---

## What to skip

Do not build the Analytics Log as a separate database on day one. Its columns duplicate
the post-publish properties already on the Video Pipeline row, and keeping two copies in
sync by hand is where this kind of system usually dies. Add it later, and only if you
want to record several measurements over time for the same video (day 7, day 30, day 90)
— that's the one thing a separate log does that a single pipeline row cannot.
