# TRACK C — Publish-slot optimization: does the data support a slot change?

**Channel:** @karenvsai (Mark Bobl | Karen vs AI), ~490 Shorts, 9–11 s English AI comedy.
**Current slots (Beijing time):** weekdays 23:30 and 05:30+1; weekends 22:30 and 04:00+1.
**Question:** does the data actually support any slot change, and is the Friday/Monday lore real?
**Answer in one line: NO CHANGE SUPPORTED — and the Friday/Monday lore is NOT SUPPORTED.**
No dataset shows a consistent, significant slot effect, and the one eye-catching pattern
(Saturday) collapses to a single date. Full machine-readable results:
`track_c_results.json` (same directory); analysis script `track_c_analysis.py`.

## 0. Method and definitions (read before the numbers)

- **Time conversion (stated, as required): every published_at in UTC was converted by +8 h
  to Beijing time (Asia/Shanghai, no DST); weekday and hour are Beijing weekday/hour.**
  This matters: 3 of the 9 recent videos change weekday under conversion —
  `fMR45Pks2PU` Fri 23:07 UTC → **Sat 07:07 BJ**, `GxSeiQuOPvc` Wed 21:39 UTC →
  **Thu 05:39 BJ**, `7oUJu0SBexk` Thu 21:35 UTC → **Fri 05:35 BJ**.
  Any lore formed in UTC time is therefore not the same claim as a Beijing-slot claim.
- **Outcome = lifetime/snapshot views, never in-window daily views.** Per the coordinator's
  verified caveat, old videos show near-zero in-window views because their views predate the
  90-day window (e.g. `z36zVLfKCsU` 1,287 snapshot views vs 0 in-window;
  `EFwLCNm31sw` 1,526 vs 0). Where a sequel-file view exists it is used; otherwise the
  telemetry latest view is used. Recent-video curves check out (e.g. `5gcdjQ0SdrU`
  1,359 in-window vs 1,358 sequel snapshot).
- **"Near current slot" = within ±90 min of the slot for that Beijing day-type**
  (weekday 23:30 / 05:30; weekend 22:30 / 04:00, circular across midnight).
  Hour buckets (fixed before inspecting outcomes): late-night 22:00–23:59,
  early-morning 03:00–06:59, daytime 07:00–21:59, deep-night 00:00–02:59.
- **Retention = telemetry `avg_view_pct` / `avg_dur_s` only.** Sequel `avg_watch_secs` is
  NOT used as retention: it contains impossible values on 9–11 s videos
  (`9rSkwMt6_6g` 89 s, `dHdnBH9q-mg` 117 s). Retention is therefore available for only
  6 of the 9 recent videos and 21 of 72 telemetry videos.
- **Tests:** Mann–Whitney U, two-sided, on raw views (rank-based, robust to skew);
  Kruskal–Wallis across weekdays where ≥3 groups have n≥2. All p-values are exploratory —
  many comparisons were run, no multiple-testing correction is claimed, and a small p in
  one slice that disappears in the next slice is treated as noise, not a finding.
- **No YouTube API pull, no YouTube writes, no credentials touched, no external agents.**
  Data gaps are recorded in §7 instead of pulled.

## 1. Datasets actually used (and their selection biases)

| Set | N | What it is | Bias / caveat |
|---|---|---|---|
| **S21-recent (primary, cleanest)** | 9 videos, 7 distinct BJ dates | Shared-dataset videos published Oct 2026 (10 Oct–23 Oct), all current Karen×device era | Sequel-candidate list = top performers by construction; "other times" arm is only n=3 and non-random (off-schedule publishes) |
| S21-all | 21 videos, 16 dates | S21-recent + 12 older videos (Jul 2025–Jun 2026) | Mixed eras + exposure times (up to ~250 days vs ~10 days); lifetime views not comparable across eras |
| **T72-recent** | 25 videos, 9 distinct BJ dates | All telemetry videos published Oct 2026 (latest snapshot each) | Latest-snapshot ages differ (median 2.6 days weekday vs 6.1 days weekend — see §5); includes the long tail of flops |
| T72-all | 72 videos, 35 dates | All telemetry videos, latest snapshot each | Same era/age mixing as S21-all, plus 65/72 publish times are *derived* (first-snapshot ts − first age_hours), not exact |
| Checked, not usable | — | `dynamic_constraints.json` (no slot/publish-time signal); `watch_hours_briefing_history.jsonl` (channel-level daily aggregates only, not per-video) | — |

Effective N for any weekday claim is the number of **distinct dates**, not videos:
recent sets have only 7–9 dates, and Saturday appears on just **2 dates** (10 Oct, 17 Oct).

## 2. Publish-slot table (primary set: 9 recent videos, Beijing time)

| video_id | Published (BJ) | Weekday (BJ) | Hour (BJ) | Bucket | Near current? | Views (snapshot) | avg_view_pct | Formula / device |
|---|---|---|---|---|---|---|---|---|
| pnN5V1NKJ2E | 2026-10-10 16:14 | Sat | 16 | daytime | No | 138 | 82.8 | tech_demo / none_detected |
| 9rSkwMt6_6g | 2026-10-12 18:47 | Mon | 18 | daytime | No | 159 | 121.6 | instant_karma / drive-thru |
| dHdnBH9q-mg | 2026-10-13 23:20 | Tue | 23 | late-night | Yes (10 min to 23:30) | 128 | 138.2 | tech_demo / doorbell cam |
| fMR45Pks2PU | 2026-10-17 07:07 | Sat | 7 | daytime | No | 709 | 131.9 | instant_karma / none_detected |
| 5gcdjQ0SdrU | 2026-10-17 22:38 | Sat | 22 | late-night | Yes (8 min to 22:30) | 1,358 | 125.5 | tech_demo / self-checkout kiosk |
| xtcUVlQKmIM | 2026-10-17 23:21 | Sat | 23 | late-night | Yes (51 min to 22:30) | 972 | 216.3 | tech_demo / smart fridge |
| plspTkhTHT8 | 2026-10-21 23:52 | Wed | 23 | late-night | Yes (22 min to 23:30) | 1,132 | — | tech_demo / self-checkout kiosk |
| GxSeiQuOPvc | 2026-10-22 05:39 | Thu | 5 | early-morning | Yes (9 min to 05:30) | 578 | — | tech_demo / self-checkout kiosk |
| 7oUJu0SBexk | 2026-10-23 05:35 | Fri | 5 | early-morning | Yes (5 min to 05:30) | 142 | — | tech_demo / parking meter |

Two facts jump out before any test: (a) **6 of 9 recent videos were already published
near a current slot** — the pipeline is already largely on-slot, so the "other times"
control is tiny and self-selected; (b) **within the near-slot group itself, views span
128–1,358 (10.6×)** — slot proximity plainly does not determine outcome; topic/quality
variation inside one slot dwarfs any between-slot gap.

Full 21-video table (including the 12 older videos, 11 with derived publish times) and
the full 72-video telemetry table are in `track_c_results.json`
(`per_video_primary_s21`, `per_video_extended_t72`). Older-video weekday medians are
not interpreted on their own because of the era/exposure confounding in §4.

## 3. Weekday analysis — including the Friday/Monday lore verdict

### 3.1 Recent (comparable-era) sets: lore fails

S21-recent weekday medians (views): Mon n=1: **159**; Tue n=1: 128; Wed n=1: 1,132;
Thu n=1: 578; **Fri n=1: 142**; Sat n=4: 840.5; Sun n=0. No weekday has n≥2 except
Saturday, so **no Friday or Monday test is even computable** in the cleanest set —
Fri+Mon combined (n=2, median 150.5) vs rest (n=7, median 709): MWU p = 0.50.
The only Friday video (parking-meter, 142) and the only Monday video (drive-thru, 159)
are both in the bottom tier of the recent set. That is not evidence *against* Friday/
Monday either — n=1 each cannot support any claim — but it is the opposite of support.

### 3.2 All-era sets: the Friday mirage, and why it evaporates

| Set | Fri median (n) | Rest median (n) | MWU p | Mon median (n) | Rest median | MWU p |
|---|---|---|---|---|---|---|
| S21-all | 1,287 (5) | 840.5 (16) | 0.68 | 83.5 (2) | 1,132 (19) | 0.11 |
| T72-all | 823 (9) | 29 (63) | 0.13 | 76 (4) | 29.5 (68) | 0.80 |
| T72-all, **views/day alive** | 3.3 (9) | 2.0 (63) | **0.90** | 2.0 (4) | 2.2 (68) | 0.78 |

The T72 Friday median of 823 with a 28× median ratio looks dramatic until age is
accounted for: **5 of the 9 T72 Friday videos are Jan/Feb 2026 videos with ~250 days
of exposure** (1,287–2,835 views), while most non-Friday videos are recent flops.
Age-normalised (views per day alive), the Friday "effect" collapses to p = 0.90.
Monday is no better: in S21-all its median (83.5) is *below* rest, driven by an
8-view June video; in T72-all it is p = 0.80. Kruskal–Wallis across weekdays:
S21-all p = 0.65; T72-all p = 0.38 — no weekday pattern overall.

**Friday/Monday lore verdict: NOT SUPPORTED.** No dataset shows Friday *and* Monday
jointly outperforming (Fri+Mon vs rest: S21-all p = 0.55, median ratio 0.15 — i.e.
below rest; T72-all p = 0.26). The only pro-Friday numbers are fully explained by
old videos' longer exposure. If the lore came from channel-level memory rather than
per-video data, these files cannot confirm it — and nothing here should be used to
defend keeping Friday/Monday as privileged days.

### 3.3 The Saturday hint — and why it must not move a slot

In T72-recent, Saturday median 421 (n=6) vs rest 5 (n=19): MWU p = 0.0056 (views),
p = 0.017 (views/day); weekend vs weekday p = 0.0027. This is the only nominally
"significant" pattern in the whole analysis — and it is a trap:
**2026-10-17 alone contributes 3,003 of the 3,239 recent-weekend views (93%).**
The other Saturday, 10 Oct, has videos of 135 / 28 / 29 (median 29) vs 17 Oct's
707 / 1,347 / 949 (median 949). With only **2 distinct Saturdays**, "Saturday" and
"17 October" are indistinguishable — a single good day (channel-wide push, three
strong topics, algorithm variance) masquerading as a weekday effect.
**Status: hypothesis for a prospective test only, never a basis to move slots.**

## 4. Hour-bucket analysis

S21-recent medians: **late-night 22:00–23:59: 1,052 (n=4)**; early-morning 03:00–06:59:
360 (n=2); daytime 07:00–21:59: 159 (n=3). Late-night vs rest: p = 0.29, median
ratio 6.6×; early-morning vs rest: p = 0.67, ratio 0.51×. The ordering is suggestive
but not significant, and the buckets are confounded with date: all four late-night
videos include the two biggest recent videos, while early-morning contains both a
578 (kiosk) and a 142 (parking meter) — a 4× spread *inside* one bucket.
In T72-all the same buckets are flat (late-night median 63.5 vs rest 29, p = 0.92;
early-morning 21 vs 32, p = 0.48), and in T72-recent late-night (119, n=5) vs rest
(6.5, n=20) is p = 0.13 — again the Oct-17 cluster, not an hour effect replicated
across dates. No hour bucket earns a change on this evidence.

## 5. Evaluation of the CURRENT slots directly

| Comparison (views) | Near-current | Other times | Median ratio | MWU p | Verdict |
|---|---|---|---|---|---|
| **S21-recent (primary)** | median 775, n=6 | median 159, n=3 | 4.87× | 0.55 | Direction favourable, **not significant** |
| S21-all | median 775, n=6 | median 1,287, n=15 | 0.60× | 0.46 | Direction **reverses** |
| T72-all | median 31, n=19 | median 29, n=53 | 1.07× | 0.82 | Essentially identical |
| T72-all, views/day | median 1.7, n=19 | median 2.2, n=53 | 0.77× | 0.71 | No effect age-normalised |
| T72-recent | median 44, n=7 | median 5.5, n=18 | 8.0× | 0.064 | Not significant; Oct-17 + snapshot-age imbalance (weekend median age 6.1 d vs weekday 2.6 d) |
| Log10-views sensitivity, S21-recent | — | — | — | 0.55 (same conclusion) | Robust to skew |

Retention does not rescue or condemn the slots either: near vs other `avg_view_pct`
medians are 138.2 vs 121.6 (S21-recent, n=3/3, p = 0.20), 100.5 vs 106.9 (T72-all,
n=7/14, p = 0.54), 113.0 vs 108.7 (T72-recent, n=6/10, p = 0.43). If slot mattered,
it would plausibly act through initial exposure rather than retention — and retention
is flat, consistent with retention being topic/quality-driven, not clock-driven.

**Reading of the table:** the only favourable headline (S21-recent, 4.87×) is based on
6 vs 3 videos, is not significant, and points the other way in the two larger sets.
**Do not quote 4.87× (or 8.0×) as an expected gain from staying on-slot or moving —
neither number survives cross-dataset checking.**

## 6. Topic control — what could be checked, and what it showed

A full topic control is **not possible** in these data: no topic family has videos
spread across both near and other times in usable numbers.

- **Within the kiosk family (the only repeated device in S21-recent):** all three
  kiosk videos are near-current (Sat 22:38 → 1,358; Wed 23:52 → 1,132; Thu 05:39 → 578).
  Same device family, same slot proximity, 2.3× view spread — slot cannot explain it,
  and there is no off-slot kiosk video to compare against.
- **Within `tech_demo` (S21-recent, n=7):** near n=6 vs other n=1 (138) — no comparison.
- **Within `instant_karma` (S21-recent, n=2):** 159 (Mon daytime, other) vs 709 (Sat
  daytime, other) — both off-slot, 4.5× apart on topic/date alone.
- **Across formulas (S21-recent):** tech_demo median 578 (n=7) vs instant_karma
  median 434 (n=2) — formula does not separate the field either at this N.
- **T72 formula slices** are even thinner (tech_demo n=4, instant_karma n=3 with
  exact formula labels; most telemetry videos carry no formula label).

Conclusion on control: **topic confounding cannot be removed here; it can only be
named.** The within-slot spreads above (10.6× near-slot, 2.3× within kiosk) are
themselves the evidence that topic/quality/day effects are at least as large as any
plausible slot effect — which is why §7's prospective design holds topic constant.

## 7. Recommendation

### Verdict: NO CHANGE SUPPORTED — keep the current slots.

- **Keep** weekdays 23:30 / 05:30+1 and weekends 22:30 / 04:00+1. There is no
  demonstrated gain from moving, and the recent pipeline is already largely on-slot,
  so a "change" would mostly be relabelling the status quo.
- **Do not privilege Friday/Monday** on the basis of lore. If Friday/Monday are kept
  in the schedule, keep them for operational reasons (cadence, staffing), not because
  the data says they perform better — it does not.
- **Do not move anything to Saturday** on the basis of the Oct-17 cluster. That is
  one date, not a weekday.
- **Estimated effect size of any slot change: not estimable from these data; the
  only honest interval includes zero and both directions.** The planning numbers
  below are about what a real test would need, not a promised lift.

### What productionizing a real answer would need

1. **Prospective, pre-registered test, not retrospective slicing.** Randomise (or
   rotate on a fixed alternating schedule) the publish slot for the *same* topic
   family — e.g. kiosk videos alternately at 23:30 vs 05:30 — and log the slot
   actually used. Retrospective data will always confound slot with date, topic,
   and which videos were deemed "slot-worthy."
2. **Sample size:** recent log10-views SD ≈ 0.44 implies roughly **~98 videos per arm
   to detect a 1.5× median shift, ~33 per arm for a 2× shift** (80% power, α = 0.05,
   lognormal approximation). At ~2 publishes/day that is ~7 weeks per arm for a 2×
   test — and a 1.5× test is likely infeasible without pooling across topics with
   topic fixed effects. Current arms (6/3) can only detect ~10×-scale shifts.
3. **Fix the measurement gaps first, or the test will be uninterpretable:**
   - Record the **actual public-flip time**, distinct from private-upload time
     (current `published_at` does not distinguish them, and daily-bucket alignment
     already wobbles by ±1 day for 2 of 9 recent videos).
   - Record **views at a common age** (e.g. 24 h and 72 h after flip) for every video,
     instead of latest-snapshot views at differing ages.
   - Record **audience geography/timezone** — these files contain none, yet the
     channel is English-language: Beijing 23:30 is 11:30 US Eastern / 08:30 Pacific
     the same day, and 05:30 BJ is 17:30 Eastern the previous day, so a "Beijing slot"
     and an "audience-local slot" are different claims. Without geography, a BJ-hour
     analysis may be testing the wrong clock entirely.
   - Capture **intraday curves** (hourly views) — daily granularity cannot test
     whether a slot wins via the first hours, which is the only mechanism by which a
     slot should matter for Shorts.
4. **Analysis discipline for the test:** pre-specify the primary comparison
   (one slot pair, one outcome, one age), hold topic constant or stratify by it,
   and treat distinct publish *dates* as the effective N for any weekday claim.
   A single big day must never again be reportable as a weekday effect.

## 8. Limitations (explicit)

- **Small N everywhere that matters:** Fri n=1 and Mon n=1 in the cleanest set;
  near/other 6/3; retention 6 videos. Absence of significance here is not proof of
  absence of a slot effect — it is proof the data cannot show one.
- **Selection bias in both directions:** S21 is top-performer-selected; T72 is a
  72-of-~490 telemetry-covered subset, itself dominated by flops (26 of 72 at ≤10 views).
  Neither is a random sample of the channel.
- **Era, age, and date confounding:** lifetime views mix exposure time (days to
  ~250 days), algorithm eras (Jan–Oct 2026), and single-date clusters (17 Oct).
  Age-normalisation removes the Friday mirage but cannot remove era effects.
- **Derived publish times:** 65 of 72 T72 times (and 11 of 21 S21 times) are derived
  as first-snapshot ts − age_hours; batch snapshots share timestamps, so minute
  precision is overstated even though hour buckets should be broadly right.
  Flagged per-video as `publish_time_source` in `track_c_results.json`.
- **No causal identification:** slot assignment was not randomised; off-slot videos
  are likely systematically different (exceptions, tests, older pipeline behaviour).
- **Daily granularity only; no geography; no flip-vs-upload distinction** (see §7.3).
- **Multiple comparisons:** ~8 tests per dataset were run; the single p < 0.01
  (Saturday in T72-recent) is exactly what multiple slicing plus one clustered date
  produces, and it fails the distinct-dates check.

## 9. Reproducibility

- Inputs (local only): `~/workspace/goals/karenvsai/hidden_files/kronos-tracks/shared_dataset.json`,
  `/home/hatch/data/sequel_candidates.json`,
  `/home/hatch/data/perpetua/retention_telemetry.jsonl`,
  `/home/hatch/data/perpetua/dynamic_constraints.json`,
  `~/workspace/goals/youtube-ypp/hidden_files/watch_hours_briefing_history.jsonl` (checked, not usable).
- Script: `track_c_analysis.py` (same directory; intermediate output
  `track_c_intermediate.json` retained for audit). Machine-readable deliverable:
  `track_c_results.json` — per-video rows for all 21 + 72 videos, group stats, test
  results, recommendation, and effective-N table.
- No YouTube API calls, no writes, no credential changes, no external agents.
