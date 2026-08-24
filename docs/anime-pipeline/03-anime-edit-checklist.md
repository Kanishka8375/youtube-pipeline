# Frame-Accurate Anime Edit Checklist

For editors working in Premiere, Resolve, After Effects, CapCut — any
timeline-based tool. This is the reference the Master QC agent scores against.

---

## Declare the frame rate first

**Every timing below is stated at 24 fps, with the millisecond equivalent.**

The original checklist quoted every fix in frames — "extend by 8 frames",
"delay by 12 frames" — without ever stating a frame rate. That makes each one
ambiguous: 8 frames is 333 ms at 24 fps and 267 ms at 30 fps, a 25% difference
on exactly the kind of reaction beat where 25% is the whole note.

Milliseconds are the portable unit. Frames are what the editor actually types.
So: pick the project rate, put it in the project config
(`ANIME_FRAME_RATE`, default 24), and record it on every QC note —
`SceneEditorQCNote.frame_rate` is a required field, and
`delta_milliseconds` converts any note to wall-clock time.

### Conversion

| Frames @24 | Milliseconds | Frames @30 | Frames @60 |
|---:|---:|---:|---:|
| 4 | 167 | 5 | 10 |
| 6 | 250 | 8 | 15 |
| 8 | 333 | 10 | 20 |
| 12 | 500 | 15 | 30 |
| 18 | 750 | 23 | 45 |
| 24 | 1000 | 30 | 60 |
| 36 | 1500 | 45 | 90 |
| 48 | 2000 | 60 | 120 |
| 72 | 3000 | 90 | 180 |

---

## A. Hook and opening

- [ ] First strong image by **frame 48–96** (2–4 s)
- [ ] First tension beat by **frame 120–240** (5–10 s)
- [ ] No empty shot lingering more than **24–36 frames** (1–1.5 s) past its purpose
- [ ] Hook lands inside the first 20 seconds

**Failure:** *"Opening terminal close-up holds 18 frames (750 ms) too long before
the audio glitch."*

## B. Dialogue reaction timing

| Beat | Hold @24 | Milliseconds |
|---|---:|---:|
| Micro reaction | 6–10 | 250–417 |
| Surprise / shock | 10–18 | 417–750 |
| Pain / realization | 12–24 | 500–1000 |
| Dramatic silence before a reply | 12–30 | 500–1250 |

- [ ] Reaction shots held long enough after a key line
- [ ] Pauses before replies are intentional, not accidental
- [ ] Reply rhythm varies across the scene

**Failure:** a reveal cut away after 4 frames (167 ms); a pause past 32 frames
(1.3 s) with no tension supporting it; every reply landing on the same rhythm,
which reads as mechanical.

## C. Impact line cuts

| Intent | Placement |
|---|---|
| Pre-impact cut | 4–8 frames (167–333 ms) before the key word |
| On-word cut | Exactly on the emphasis |
| Post-line hold | 8–20 frames (333–833 ms) by emotional weight |

Use on: accusations, reveals, betrayals, cliffhanger name-drops.

## D. Hold frames

| Shot | Hold @24 | Milliseconds |
|---|---:|---:|
| Standard dialogue | 24–60 | 1000–2500 |
| Emotional close-up | 36–84 | 1500–3500 |
| Reveal image | 18–48 | 750–2000 |

- [ ] Important images are on screen long enough to register
- [ ] Static holds are broken by eye-light, parallax, camera drift, FX or an expression shift

**Failure:** every shot the same length; a key reveal on screen for 8 frames
(333 ms); a static face for 90+ frames (3.75 s) with no motion logic.

## E. Push-ins

| Intent | Duration @24 | Milliseconds |
|---|---:|---:|
| Subtle push-in | 18–48 | 750–2000 |
| Suspense creep | 36–72 | 1500–3000 |
| Realization push | 12–30 | 500–1250 |

- [ ] Push-ins used only where emotion or tension actually rises
- [ ] No more than two similar push-ins in one dialogue exchange

**Failure:** every line gets a zoom; constant push speed across the episode;
the push finishing early and leaving the payoff flat.

## F. Cut rhythm

- [ ] No four identical shot lengths in a row
- [ ] Pattern breaks on reveal beats
- [ ] Timing shortens during panic, lengthens slightly during grief
- [ ] At least one insert cut per scene (prop, signal, screen detail)

**Failure:** every dialogue shot between 48–52 frames; no acceleration before
the cliffhanger.

## G. Silence

| Use | Duration @24 | Milliseconds |
|---|---:|---:|
| Pre-reveal hush | 8–20 | 333–833 |
| Stunned pause | 12–36 | 500–1500 |
| Grief pause | 18–48 | 750–2000 |
| Cliffhanger drop before the end hit | 6–18 | 250–750 |

**Failure:** wall-to-wall music; silence too short to register; silence with no
visual carrying it.

## H. SFX placement

| SFX | Alignment |
|---|---|
| Hard impact | On frame, ±2 frames (±83 ms) |
| Glitch stinger | May pre-hit by 1–3 frames (42–125 ms) |
| Whoosh transition | Starts 3–8 frames (125–333 ms) before the cut |
| UI beep | Synced to the light or movement cue |

**Failure:** late impacts; identical whooshes throughout; transitions louder
than the drama they join.

## I. Music cues

- [ ] Emotional swell enters **8–24 frames (333–1000 ms)** before the realization peak
- [ ] Suspense bed fades in under discovery, not on top of it
- [ ] Reveal sting lands on the cut, or 2–4 frames (83–167 ms) after
- [ ] Music ducks under dialogue

**Failure:** the cue announces the emotion before the scene earns it; music
under every scene, so no scene has contrast.

## J. Cliffhanger

| Ending | Hold @24 | Milliseconds |
|---|---:|---:|
| Line lands, then cut | 8–18 | 333–750 |
| Shocking image | 12–24 | 500–1000 |
| Horror-style stare | 18–36 | 750–1500 |

**Failure:** an explanatory line after the strongest beat; a cut before the
viewer can process the image; a final swell that outstays the moment.

---

## Episode signoff

| Check | Pass |
|---|---|
| Hook lands in the first 20 s | |
| No dead air in the first 30 s | |
| Every scene has visual movement logic | |
| Key reactions readable | |
| Reveal shots held long enough | |
| Dialogue always audible | |
| Music supports without overpowering | |
| SFX aligned to action and cuts | |
| No repetitive zoom abuse | |
| Ending lands cleanly | |
| Short-worthy timestamps marked | |

## Logging a note

```json
{
  "qc_note_id": "QCN_EP01_SC03_001",
  "episode_id": "EP01",
  "scene_id": "EP01_SC03",
  "timecode": "00:02:21:14",
  "frame_rate": 24,
  "issue_type": "reaction_timing",
  "severity": "medium",
  "issue": "Reaction cut away too early after the reveal line.",
  "why_it_hurts": "The audience has no beat to register the reveal before the next shot.",
  "current_duration_frames": 5,
  "recommended_duration_frames": 14,
  "fix_note": "Extend the close-up by 9 frames (375 ms) before cutting to the monitor insert.",
  "mandatory_fix": true
}
```

`frame_rate` is required. `frame_delta` and `delta_milliseconds` are derived, so
the same note reads correctly whatever rate a future project uses.
