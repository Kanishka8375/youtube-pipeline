# Weekly Scoring Framework

Auto-rates each week out of 25 across five areas, so "was that a good week?" has an
answer that doesn't depend on your mood on Sunday evening.

All formulas go on the **Weekly Reviews** database and use the exact property names from
[04-database-schemas.md](04-database-schemas.md#g-weekly-reviews).

---

## The five categories

| Category | Max | Reads from |
|---|---:|---|
| Long-form CTR | 5 | Avg Long-Form CTR |
| Long-form retention | 5 | Avg Long-Form Retention 30s |
| Shorts performance | 5 | Shorts Health Raw |
| Monetization | 5 | Total Affiliate Clicks |
| Publishing consistency | 5 | Published vs targets |
| **Total** | **25** | |

## Ratings

| Weekly Score | Rating |
|---|---|
| 22–25 | Breakout Week |
| 18–21 | Strong Week |
| 14–17 | Solid Week |
| 10–13 | Weak Week |
| 0–9 | Poor Week |

---

## Read this before you trust the numbers

The default thresholds below are **starting assumptions, not benchmarks**. A 7% CTR bar
for full marks is aggressive; on a new channel with little browse traffic you may sit at
3–4% for months while doing everything right. The score is only useful once the bands sit
around *your* channel's actual middle — see [Calibration](#calibration) below.

Two more things the score cannot see, which is why the written review still matters:

- **Averages hide split weeks.** Two videos at 8% and 2% average to a comfortable 5%. The
  weekly score will look fine while one of your two videos failed completely.
- **Small samples move violently.** At Tier 1 the CTR score is computed from a single
  video. Read the four-week trend in the archive view, not the individual week.

---

## Category A — Long-form CTR

| Avg CTR | Score |
|---|---:|
| 7.0%+ | 5 |
| 6.0–6.99% | 4 |
| 5.0–5.99% | 3 |
| 4.0–4.99% | 2 |
| 3.0–3.99% | 1 |
| under 3.0% | 0 |

```
if(prop("Avg Long-Form CTR") >= 7, 5,
if(prop("Avg Long-Form CTR") >= 6, 4,
if(prop("Avg Long-Form CTR") >= 5, 3,
if(prop("Avg Long-Form CTR") >= 4, 2,
if(prop("Avg Long-Form CTR") >= 3, 1, 0)))))
```

## Category B — Long-form retention

| Retention at 30s | Score |
|---|---:|
| 75%+ | 5 |
| 70–74% | 4 |
| 65–69% | 3 |
| 60–64% | 2 |
| 55–59% | 1 |
| under 55% | 0 |

```
if(prop("Avg Long-Form Retention 30s") >= 75, 5,
if(prop("Avg Long-Form Retention 30s") >= 70, 4,
if(prop("Avg Long-Form Retention 30s") >= 65, 3,
if(prop("Avg Long-Form Retention 30s") >= 60, 2,
if(prop("Avg Long-Form Retention 30s") >= 55, 1, 0)))))
```

## Category C — Shorts performance

Blend both Shorts metrics rather than picking one: viewed-vs-swiped measures the hook,
completion rate measures the payoff, and a Short can win one while losing the other.

**Shorts Health Raw**

```
(prop("Avg Shorts Viewed vs Swiped") + prop("Avg Shorts Completion Rate")) / 2
```

| Shorts Health Raw | Score |
|---|---:|
| 80+ | 5 |
| 75–79.99 | 4 |
| 70–74.99 | 3 |
| 65–69.99 | 2 |
| 60–64.99 | 1 |
| under 60 | 0 |

**Shorts Score**

```
if(prop("Shorts Health Raw") >= 80, 5,
if(prop("Shorts Health Raw") >= 75, 4,
if(prop("Shorts Health Raw") >= 70, 3,
if(prop("Shorts Health Raw") >= 65, 2,
if(prop("Shorts Health Raw") >= 60, 1, 0)))))
```

If you would rather keep it to one metric, swap `prop("Shorts Health Raw")` for
`prop("Avg Shorts Completion Rate")` and shift each band up by 5 (85/80/75/70/65).

## Category D — Monetization

| Affiliate clicks | Score |
|---|---:|
| 60+ | 5 |
| 45–59 | 4 |
| 30–44 | 3 |
| 15–29 | 2 |
| 5–14 | 1 |
| under 5 | 0 |

```
if(prop("Total Affiliate Clicks") >= 60, 5,
if(prop("Total Affiliate Clicks") >= 45, 4,
if(prop("Total Affiliate Clicks") >= 30, 3,
if(prop("Total Affiliate Clicks") >= 15, 2,
if(prop("Total Affiliate Clicks") >= 5, 1, 0)))))
```

These are absolute counts, so they scale with channel size rather than with performance.
Early on you will score 0–1 here almost every week regardless of what you do; that is
expected and it is the category to recalibrate first once clicks start arriving.

## Category E — Publishing consistency

Scored against your tier's targets, not against fixed output numbers, so the same formula
is correct at Tier 1 and Tier 2. Long-form is weighted 60% because it is the harder and
more valuable half of the week.

```
round(
  (
    (if(prop("Long-Form Target") > 0,
        min(prop("Long-Form Published") / prop("Long-Form Target"), 1), 1) * 0.6)
    +
    (if(prop("Shorts Target") > 0,
        min(prop("Shorts Published") / prop("Shorts Target"), 1), 1) * 0.4)
  ) * 5
)
```

Behaviour at Tier 1 (targets 1 and 3):

| Published | Score |
|---|---:|
| 1 long + 3 Shorts | 5 |
| 1 long + 2 Shorts | 4 |
| 1 long + 1 Short | 4 |
| 1 long + 0 Shorts | 3 |
| 0 long + 3 Shorts | 2 |
| 0 long + 0 Shorts | 0 |

Overdelivering is capped at the target by `min(…, 1)`. Publishing four videos in a week
does not earn extra points — it usually costs you next week.

---

## Totals

**Weekly Score**

```
prop("CTR Score") + prop("Retention Score") + prop("Shorts Score")
  + prop("Monetization Score") + prop("Consistency Score")
```

**Weekly Rating**

```
if(prop("Weekly Score") >= 22, "Breakout Week",
if(prop("Weekly Score") >= 18, "Strong Week",
if(prop("Weekly Score") >= 14, "Solid Week",
if(prop("Weekly Score") >= 10, "Weak Week", "Poor Week"))))
```

**Total Views**

```
prop("Total Long-Form Views") + prop("Total Shorts Views")
```

All formulas use nested `if()` and `prop()`, which work in both Notion Formulas 1.0 and
2.0. In 2.0 you can shorten them with `ifs()` if you prefer.

---

## Calibration

After **eight published long-form videos**, replace the default CTR and retention bands
with bands built from your own data.

1. List the day-7 CTR of your last 8 videos.
2. Take the **median** (the average of the 4th and 5th values, sorted).
3. Build the bands from it:

| Score | Threshold |
|---|---|
| 5 | median × 1.30 |
| 4 | median × 1.15 |
| 3 | median (unchanged) |
| 2 | median × 0.85 |
| 1 | median × 0.70 |
| 0 | anything lower |

Worked example — median day-7 CTR of 5.0%:

| Score | Threshold |
|---|---:|
| 5 | 6.5% |
| 4 | 5.75% |
| 3 | 5.0% |
| 2 | 4.25% |
| 1 | 3.5% |
| 0 | below 3.5% |

Use the median, not the mean: one breakout video drags a mean up far enough that every
subsequent normal week scores as a failure.

Recalibrate every quarter, and note the date you did it in the Weekly Reviews entry —
scores before and after a recalibration are not comparable, and you will otherwise
misread the discontinuity as a real change in performance.

Retention and Shorts bands recalibrate the same way. Monetization is better set from a
target than a median: pick the clicks-per-week you want in three months, make that a 4,
and space the rest evenly.

---

## Optional weighted version

If you want a /100 score with strategic weighting rather than flat categories:

| Category | Weight |
|---|---:|
| Long-form CTR | 30% |
| Long-form retention | 25% |
| Shorts performance | 20% |
| Monetization | 15% |
| Consistency | 10% |

```
round(
  (prop("CTR Score") * 6) + (prop("Retention Score") * 5)
  + (prop("Shorts Score") * 4) + (prop("Monetization Score") * 3)
  + (prop("Consistency Score") * 2)
)
```

Each category score is 0–5, so the multipliers give a 0–100 total with the weights above.
The flat 25-point version is easier to read at a glance and is the recommended default.

---

## What each rating means to do

| Rating | Action |
|---|---|
| **Breakout Week** | Repeat the topic and packaging pattern immediately, while it is still working |
| **Strong Week** | Keep the format stable; make exactly one packaging improvement |
| **Solid Week** | One part worked, one part didn't — read the category scores to find which |
| **Weak Week** | Usually packaging or topic mismatch. Check the CTR/retention quadrant in `05-packaging-tracker.md` |
| **Poor Week** | Review topic selection, hook strength and upload consistency before touching anything else |

The single most common misread: a Poor Week caused entirely by a 0 in consistency, where
the content that did ship performed fine. Look at the five category scores before you
conclude anything from the total.
