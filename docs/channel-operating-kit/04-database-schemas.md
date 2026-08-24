# Database Schemas

Seven databases. Property names here are used verbatim by the formulas in
`07-scoring-framework.md`, so rename at your own cost.

Build order and the case for skipping the Analytics Log are in the
[kit README](README.md#build-order).

---

# A. Video Pipeline

Every long-form video, from idea to post-publish review. This is the spine of the system.

## Production properties

| Property | Type | Purpose | Example |
|---|---|---|---|
| Title | Title | Working title | ChatGPT vs Claude for Research |
| Status | Select | Production stage | Editing |
| Publish Date | Date | Scheduled or published date | Sep 4, 2026 |
| Content Type | Select | Video format | Comparison |
| Audience | Select | Target viewer | Creators |
| Primary Goal | Select | Traffic / trust / monetization | Monetization |
| Priority | Select | Importance | High |
| Topic Category | Select | AI topic segment | Research AI |
| Target Keyword | Text | Search target | chatgpt vs claude research |
| Affiliate Fit | Select | Revenue potential | High |
| Evergreen/Trend | Select | Topic lifespan | Evergreen |
| Script Status | Select | Script progress | Complete |
| Recording Status | Select | Voice and demo status | Done |
| Edit Status | Select | Editing stage | Rough Cut |
| Packaging Status | Select | Thumbnail and title stage | Draft |
| Shorts Extracted | Checkbox | Whether Shorts were made | Yes |
| Related Shorts | Relation → Shorts Queue | Derived Shorts | 3 linked |
| Script Link | URL or Text | Script page | Notion subpage |
| Assets Folder | URL or Text | File location | Drive link |

## Post-publish properties

| Property | Type | Purpose | Example |
|---|---|---|---|
| Final Title | Text | Published title | ChatGPT vs Claude: Which Is Better for Research? |
| Thumbnail Version | Select | Packaging variation used | A |
| Thumbnail Style | Select | Main thumbnail type | Split comparison |
| CTR | Number (%) | Click-through rate at day 7 | 6.8 |
| Impressions | Number | Reach context at day 7 | 18,000 |
| Views 24h | Number | Early result | 620 |
| Views 7d | Number | First-week result | 2,400 |
| Retention 30s | Number (%) | Hook strength | 72 |
| Avg View Duration | Number (min) | Watch quality | 5.2 |
| Watch Time Hours | Number | Growth signal | 146 |
| Affiliate Clicks | Number | Monetization signal | 31 |
| Comments | Number | Engagement | 14 |
| Overall Rating | Select | Performance summary | Strong |
| Next Action | Select | What to do about it | Repeat Angle |
| Notes | Text | Insight | Comparison framing worked well |

> **Always log day-7 numbers in `CTR`, `Impressions`, `Retention 30s` and
> `Avg View Duration`.** A row mixing day-2 and day-30 figures poisons every average
> the Weekly Reviews database computes.

## Select options

**Status:** Idea · Approved · Outline · Scripted · Recorded · Editing · Packaging · Scheduled · Published · Archived

**Content Type:** Roundup · Comparison · Tutorial · Workflow · News · Test

**Audience:** Creators · Freelancers · Solopreneurs · Agencies · Beginners

**Primary Goal:** Traffic · Trust · Monetization

**Priority:** Low · Medium · High

**Topic Category:** Writing AI · Research AI · Video AI · Automation · Productivity · Image AI · Prompting · AI News

**Affiliate Fit:** Low · Medium · High

**Evergreen/Trend:** Evergreen · Trend · Hybrid

**Script Status:** Not Started · Drafting · Review · Complete

**Recording Status:** Not Started · In Progress · Done

**Edit Status:** Not Started · Rough Cut · Fine Cut · Final Export

**Packaging Status:** Not Started · Draft · Final · Scheduled

**Thumbnail Version:** A · B · C

**Thumbnail Style:** Split comparison · Tool logos · Minimal text · Bold outcome text · UI screenshot · Collage · Warning style · One-tool spotlight

**Overall Rating:** Poor · Average · Good · Strong · Breakout

**Next Action:** Repeat Angle · Repackage · Expand to Short · Make Sequel · Drop Topic · Update Description

---

# B. Shorts Queue

Every Short, from clip selection to published analysis.

| Property | Type | Purpose | Example |
|---|---|---|---|
| Hook / Title | Title | Short label | Claude Beats GPT for Research |
| Status | Select | Production stage | Scheduled |
| Publish Date | Date | Scheduled or published date | Sep 5, 2026 |
| Related Long-Form | Relation → Video Pipeline | Source video | ChatGPT vs Claude |
| Short Format | Select | Type of Short | Comparison |
| Topic Category | Select | Topic segment | Research AI |
| Clip Source Timestamp | Text | Where it came from | 02:10–02:42 |
| Hook Type | Select | Hook style | Contrarian |
| CTA Type | Select | End CTA used | Watch Full Video |
| Views | Number | Reach | 5,200 |
| Viewed vs Swiped | Number (%) | Hook performance | 66 |
| Completion Rate | Number (%) | Retention quality | 82 |
| Likes | Number | Engagement | 190 |
| Comments | Number | Engagement depth | 12 |
| Shares | Number | Viral potential | 22 |
| Saves | Number | Utility signal | 17 |
| Subscribers Gained | Number | Conversion | 8 |
| Performance Rating | Select | Summary | Strong |
| Follow-Up Opportunity | Checkbox | Expand into a long-form? | Yes |
| Next Action | Select | Next step | Expand Topic |
| Notes | Text | Insight | Strongest when framed as direct comparison |

**Status:** Idea · Clipped · Edited · Scheduled · Published · Archived

**Short Format:** Tip · Comparison · Tool Spotlight · Mistake · Prompt · Workflow Clip · News Reaction

**Hook Type:** Curiosity · Contrarian · Benefit · Speed · Mistake · Comparison · Proof

**CTA Type:** Watch Full Video · Comment Prompt · Follow for More · Link in Description · None

**Performance Rating:** Weak · Average · Strong · Breakout

**Next Action:** Expand Topic · Recut Hook · Repeat Format · Ignore · Add to Compilation

---

# C. Packaging Tracker

Thumbnail and title performance, one row per long-form video. Methodology is in
[05-packaging-tracker.md](05-packaging-tracker.md).

| Property | Type | Purpose | Example |
|---|---|---|---|
| Video Title | Title | Internal reference | ChatGPT vs Claude for Research |
| Related Video | Relation → Video Pipeline | Source video | Linked |
| Video ID | Text | Internal tracking ID | TSAI-014 |
| Publish Date | Date | Publish date | Sep 4, 2026 |
| Final Title | Text | Published title | ChatGPT vs Claude: Best AI for Research? |
| Title Formula | Select | Title structure | [Tool A] vs [Tool B] |
| Title Angle | Select | Framing | Comparison |
| Title Length | Number | Character count | 43 |
| Thumbnail Version | Select | A/B/C | A |
| Thumbnail Style | Select | Visual category | Split comparison |
| Thumbnail Text | Text | Text on the image | GPT vs CLAUDE |
| Thumbnail Text Count | Number | Word count | 2 |
| Thumbnail Focus | Select | Main visual emphasis | Comparison layout |
| Thumbnail Contrast Type | Select | Bright / dark / mixed | Mixed |
| CTR 24h | Number (%) | Early CTR | 7.1 |
| CTR 7d | Number (%) | Stable CTR | 7.6 |
| CTR 30d | Number (%) | Long-tail CTR | 6.8 |
| Impressions 24h | Number | Early reach | 6,800 |
| Impressions 7d | Number | Reach context | 21,000 |
| Views 24h | Number | Early result | 750 |
| Views 7d | Number | Weekly result | 2,600 |
| Avg View Duration | Number (min) | Content alignment | 5.3 |
| Retention 30s | Number (%) | Packaging-content fit | 73 |
| Repackaged? | Checkbox | Packaging changed | No |
| Repackage Date | Date | When changed | — |
| New Title | Text | Updated title | — |
| New Thumbnail Style | Select | Updated thumbnail | — |
| Post-Change CTR | Number (%) | CTR after the change | — |
| Winner Rating | Select | Packaging result | Breakout |
| Notes | Text | Why it worked or failed | Clear decision framing |

**Title Formula:** Best AI Tools for [Audience] · I Tested [#] AI Tools · [Tool A] vs [Tool B] · How to Use AI for [Result] · [#] AI Tools That Save [Time] · Worth It or Not? · Best Free AI Tools · This Workflow Saves [Time]

**Title Angle:** Clarity · Curiosity · Benefit · Comparison · Proof · Contrarian · Speed

**Thumbnail Style:** Split comparison · Tool logos · Minimal text · Bold outcome text · UI screenshot · Collage · Warning style · One-tool spotlight

**Thumbnail Focus:** Tool logo · Result phrase · UI screenshot · Comparison layout · Warning message · Before/after · Workflow visual

**Thumbnail Contrast Type:** Dark · Bright · Mixed

**Winner Rating:** Weak · Average · Strong · Breakout

---

# D. Ideas Bank

Fast capture. The only database where speed matters more than completeness — fill in the
title and hit save; the rest can wait until Monday.

| Property | Type | Purpose | Example |
|---|---|---|---|
| Idea Title | Title | Topic idea | Best AI Tools for Agency Owners |
| Content Type | Select | Planned format | Roundup |
| Audience | Select | Target viewer | Freelancers |
| Goal | Select | Traffic / trust / monetization | Traffic |
| Why It Could Work | Text | One-line rationale | Strong buyer intent |
| Related Tool | Text | Main tool or topic | Notion AI |
| Trend or Evergreen | Select | Lifespan | Evergreen |
| Source | Select | Where it came from | Competitor |
| Priority | Select | Importance | Medium |
| Status | Select | Idea stage | Backlog |
| Notes | Text | Extra angles | Could compare free vs paid |

**Source:** Comment · Competitor · Trend · Search · Affiliate Opportunity · Personal Idea

**Status:** Backlog · Reviewing · Approved · Moved to Pipeline · Rejected

---

# E. Affiliate Tracker

| Property | Type | Purpose | Example |
|---|---|---|---|
| Tool Name | Title | Product | Perplexity |
| Category | Select | Tool category | Research AI |
| Affiliate Program | Text | Network or brand | Direct |
| Affiliate Link | URL | Link to use | https://… |
| Commission Type | Select | Flat / recurring / percent | Recurring |
| Commission Details | Text | Payout terms | 20% recurring |
| Promoted In Videos | Relation → Video Pipeline | Where it appears | Best AI Tools for Researchers |
| Clicks | Number | Affiliate clicks | 42 |
| Conversions | Number | Sales or trials | 5 |
| Revenue | Number | Income generated | 78 |
| Best Placement | Select | Where it converts | Description |
| Status | Select | Active / paused / testing | Active |
| Notes | Text | Placement insight | Works best in comparison videos |

**Category:** Writing AI · Research AI · Video AI · Design AI · Automation · Productivity · Transcription · Note-taking

**Best Placement:** Description · Pinned Comment · Verbal Mention · Resource Page

**Status:** Testing · Active · Paused · Dropped

> Clicks come from your link shortener or the affiliate dashboard, not from YouTube.
> Set up one shortener with a per-video slug before the first affiliate video ships —
> retrofitting attribution is not possible.

---

# F. Analytics Log *(optional)*

Only build this if you want multiple measurements over time for the same video. If you
just want one set of numbers per video, keep them on the Video Pipeline row and skip
this database entirely.

| Property | Type | Purpose |
|---|---|---|
| Video Title | Title | Published video |
| Related Video | Relation → Video Pipeline | Link back |
| Measured On | Date | When these numbers were read |
| Days Since Publish | Number | 7 / 30 / 90 |
| Views | Number | Views at measurement |
| CTR | Number (%) | CTR at measurement |
| Avg View Duration | Number (min) | Watch quality |
| Retention 30s | Number (%) | Hook quality |
| Watch Time Hours | Number | Total watch time |
| Affiliate Clicks | Number | Revenue signal |
| Comments | Number | Engagement |
| Overall Rating | Select | Performance rating |
| What Worked | Text | Winning element |
| What Failed | Text | Weak point |
| Next Action | Text | Follow-up move |

**Overall Rating:** Poor · Average · Good · Strong · Breakout

---

# G. Weekly Reviews

One row per week. The scoring formulas in
[07-scoring-framework.md](07-scoring-framework.md) live here.

## Identity and targets

| Property | Type | Purpose | Example |
|---|---|---|---|
| Week | Title | Week label | Week of Sep 2, 2026 |
| Start Date | Date | Week start | Sep 2, 2026 |
| End Date | Date | Week end | Sep 8, 2026 |
| Status | Select | Review progress | Complete |
| Long-Form Target | Number | Your tier's long-form target | 1 |
| Shorts Target | Number | Your tier's Shorts target | 3 |

`Long-Form Target` and `Shorts Target` are what make the consistency score work at either
cadence tier. Set them once on the template button; change them only when you change tier.

## Output and performance

| Property | Type | Purpose | Example |
|---|---|---|---|
| Long-Form Published | Number | Videos published | 1 |
| Shorts Published | Number | Shorts published | 3 |
| Total Long-Form Views | Number | Combined views | 4,200 |
| Total Shorts Views | Number | Combined views | 18,500 |
| Total Views | Formula | Sum of the two above | 22,700 |
| Total Watch Time Hours | Number | Weekly watch time | 186 |
| Avg Long-Form CTR | Number (%) | Average day-7 CTR | 5.8 |
| Avg Long-Form Retention 30s | Number (%) | Average hook retention | 68 |
| Avg Long-Form View Duration | Number (min) | Average watch duration | 4.7 |
| Avg Shorts Viewed vs Swiped | Number (%) | Average Shorts hook rate | 64 |
| Avg Shorts Completion Rate | Number (%) | Average Shorts retention | 79 |
| Total Affiliate Clicks | Number | Weekly clicks | 53 |
| Total Conversions | Number | Conversions | 6 |
| Revenue | Number | Weekly revenue | 124 |
| Subscribers Gained | Number | Weekly growth | 73 |

## Conclusions

| Property | Type | Purpose | Example |
|---|---|---|---|
| Best Long-Form Video | Relation → Video Pipeline | Top performer | Linked |
| Best Short | Relation → Shorts Queue | Top Short | Linked |
| Worst Long-Form Video | Relation → Video Pipeline | Weakest performer | Linked |
| Best Title Formula | Select | Winning title pattern | [Tool A] vs [Tool B] |
| Best Thumbnail Style | Select | Winning visual style | Split comparison |
| Best Short Format | Select | Winning Short type | Comparison |
| Repackaging Needed | Checkbox | Any video needs new packaging | Yes |
| Biggest Win | Text | Main success | Comparison packaging won |
| Biggest Problem | Text | Main issue | Weak CTR on the roundup |
| Next Week Focus | Text | Priority | Stronger thumbnails |
| Notes | Text | Observations | Day-3 search pickup on the tutorial |

## Scoring formulas

| Property | Type | Purpose |
|---|---|---|
| CTR Score | Formula | 0–5 from Avg Long-Form CTR |
| Retention Score | Formula | 0–5 from Avg Long-Form Retention 30s |
| Shorts Health Raw | Formula | Blend of viewed-vs-swiped and completion |
| Shorts Score | Formula | 0–5 from Shorts Health Raw |
| Monetization Score | Formula | 0–5 from Total Affiliate Clicks |
| Consistency Score | Formula | 0–5 from output vs targets |
| Weekly Score | Formula | Total out of 25 |
| Weekly Rating | Formula | Breakout / Strong / Solid / Weak / Poor |

Formula bodies: [07-scoring-framework.md](07-scoring-framework.md).
