# Track B — Virality scoring for @karenvsai: report

**Verdict first: there is no trustworthy virality scorer in this data — and the
numbers below show exactly why. What looks like a near-perfect scorer
(Spearman 0.983) is mostly a tautology, and what would actually be useful
(pre-launch prediction, or forecasting later growth) has no detectable signal
at this sample size. Do not productionize any of this as a "will go viral"
predictor. The one legitimate use is day-2 triage: ranking videos that have
already launched, which is bookkeeping, not prediction.**

- Channel: @karenvsai (Mark Bobl | Karen vs AI), ~490 Shorts, 9–11 s English AI comedy.
- Sources used (no YouTube API pulls by this track): the shared dataset
  (`shared_dataset.json`, pulled 2026-10-27, 21 videos), `/home/hatch/data/sequel_candidates.json`,
  `/home/hatch/data/perpetua/retention_telemetry.jsonl` (669 rows, 72 videos),
  `/home/hatch/data/perpetua/dynamic_constraints.json` (72 videos).
- Method note: this environment has no sklearn (pip blocked by PEP 668), so all
  statistics are numpy/scipy only — Spearman/Pearson, Mann–Whitney AUC, a
  hand-rolled regularised logistic regression, and leave-one-out validation.
  Reproducibility script: `track_b_analysis.py` (same directory); machine-readable
  output: `track_b_results.json`.
- Kronos: **not used.** Kronos is a forecaster, not a classifier, and no Track A
  forecast output exists in the shared tracks directory to use as a feature, so
  no Kronos-as-feature test was possible. This is a non-Kronos scoring model,
  which is a valid Track B result.

## 1. What "viral" means here, honestly

Recent top videos run ~1,000–1,400 views; most videos sit far lower. Two lines
are reported, one primary:

| Line | Rule (eventual views) | Count | Justification |
|---|---|---|---|
| **Viral (primary)** | ≥ 1,000 | **2 / 9 (22%)** — `5gcdjQ0SdrU` (1,359), `plspTkhTHT8` (1,213) | Top of the channel's recent range; an absolute bar, not a median split chosen to flatter balance. |
| Strong (secondary) | ≥ 500 | 5 / 9 (56%) | Sensitivity check; a median-ish split. All ranking results are the same under either line. |

**Eventual views** = in-window daily-views sum from the shared dataset (pulled
2026-10-27). Cross-check: it agrees with the 2026-10-25 sequel snapshot within
~7% for 8 of 9 recent videos (e.g. `5gcdjQ0SdrU`: 1,359 in-window vs 1,358
sequel). The exception is `7oUJu0SBexk` (in-window 272 vs sequel 142 — the
sequel snapshot was evidently taken around day 0). In-window total is used
consistently for all 9 so the target is measured the same way for every video.

Cohort A eventual views (descending): 1359, 1213, 971, 709, 599, 272, 151, 138,
123. Median 599, mean 615, Q1 151 / Q3 971. With 2 positives, every binary
metric below moves by 11 percentage points per video — treat them as fragile.

## 2. Cohorts — what was included, what was excluded, and why

| Cohort | N | Definition |
|---|---|---|
| **A — early-signal model (primary)** | **9** | Shared-dataset videos published ≥ 2026-10-10 whose full launch curve falls inside the 90-day Analytics window (2026-10-10 to 2026-10-22 publishes). |
| Excluded from A | 12 | Published Jan–Jun 2025 (11 videos) plus `2ySJM2uTqZU` (2025-07-06). Their views predate the window, so in-window daily sums are 0–9 (one 177 trickle) while lifetime telemetry views are 1,287–2,835. They have **no observable launch curve**; treating them as flat videos would be false, so they are excluded from the early-signal model, not modelled as zeros. |
| **C — title/retention associations only** | 72 | Latest telemetry snapshot per video from `retention_telemetry.jsonl`. Mixed publish ages (Jan–Oct 2025) and lifetime views — usable for association checks, **not** for launch prediction. |

**Daily-granularity caveat (applies to everything below).** The Analytics pull has
no hourly dimension, so "early" means observed days, not 1 h / 6 h / 24 h.
`d0` = first observed day's views in file order — a launch-day *bucket*, not a
clean 24 h count: publish-time and Analytics-day-boundary effects shift it
(e.g. `dHdnBH9q-mg`'s first daily row predates its publish timestamp by a day;
`pnN5V1NKJ2E` has calendar gaps between rows). `d1`, `d2` are the 2nd/3rd
observed days on the same basis. `7oUJu0SBexk` (published 2026-10-22) has only
3 daily rows in the pull, so its tail is censored (recorded as 0 by
construction, not a measured zero).

## 3. Features

Per video in cohort A: early-curve `d0, d1, d2`, 3-day total, tail after day 2
(`total − 3-day`), day-0 share, velocity `d1/(d0+1)` and `d2/(d1+1)`,
days-to-peak (index of max in first 7 observed days); retention `avg_view_pct`,
`avg_dur_s` (only 6/9 have them — `plspTkhTHT8`, `GxSeiQuOPvc`, `7oUJu0SBexk`
have `telemetry_latest = null`); title/topic `title_len`, `starts_with_emoji`,
`has_karen`, `hashtag_n`, AI device, formula key; plus `duration_s`, `likes`,
`comments` (the last two are flagged as leakage-prone below, not used as
predictors).

## 4. The model: the simplest rule wins, and that is the warning

**Chosen score: 3-day total, `score = d0 + d1 + d2`, available ~72 h after
publish. Day-0 fallback: `d0` alone.** No weights, no fitted coefficients —
with N = 9, anything fancier overfits, and the tests below prove it.

| Candidate score | Spearman vs eventual | Viral AUC (≥1000) | Strong AUC (≥500) |
|---|---|---|---|
| **3-day total (chosen)** | **0.983 (p < 0.001)** | **1.000** | **1.000** |
| d0 alone | 0.983 (p < 0.001) | 1.000 | 1.000 |
| ln(1+d0) + 0.5·ln(1+d1) — tested and **rejected** | 0.833 (p = 0.005) | 0.786 | 1.000 |
| Log-early minus decay penalty — tested and rejected | 0.300 (p = 0.43) | 0.357 | 0.700 |

The log-blend loses because day-1 adds noise, not signal: the top video
`5gcdjQ0SdrU` has `d1 = 1` after a `d0 = 1,337` launch. Adding day-1 data
*demotes* the biggest winner. Shipping the prettier formula would mean
shipping a worse scorer.

## 5. Validation — honest numbers, including the failures

### 5a. Leave-one-out (LOOCV), cohort A

| Check | Result |
|---|---|
| LOOCV Spearman, d0 vs eventual (mean over 9 folds) | **0.981 (range 0.976–1.000)** |
| LOOCV Spearman, 3-day total vs eventual | **0.981 (range 0.976–1.000)** |
| LOOCV decision stump on d0, viral ≥ 1000 | Accuracy **0.889 (8/9)** — misses `plspTkhTHT8` only (held-out threshold 1,154 > its d0 of 953) |
| LOOCV decision stump on 3-day total, viral ≥ 1000 | Accuracy **1.000 (9/9)** |
| In-sample stump accuracy (either feature) | 1.000 — shown only to demonstrate that in-sample fit overstates by up to 11 points here |
| LOOCV regularised logistic regression on ln(d0), ln(d1) | Accuracy **0.778 (7/9) = the majority-class base rate; AUC 0.143** — predicts *every* video non-viral (all probabilities 0.05–0.34). With 2 positives the fitted model collapses to the majority class and its ranking is worse than chance. **This is the expected failure mode of a fitted classifier at N = 9, and it is reported rather than hidden.** |

### 5b. The test that matters: does early predict *later* growth?

Eventual views *contain* d0/d1/d2, so §5a partly measures a video against
itself. The clean test is the **tail**: views after day 2. Shorts here die
fast — tails are 0–27 views (median 9) against totals of 123–1,359 — and
**nothing predicts the tail**:

| Feature vs tail-after-day-2 | Spearman | p |
|---|---|---|
| d0 | −0.20 | 0.61 |
| d1 | −0.05 | 0.90 |
| 3-day total | −0.20 | 0.61 |
| velocity d1/d0 | 0.28 | 0.46 |
| day-0 share | −0.27 | 0.49 |
| avg_view_pct (n = 6) | 0.71 | 0.11 (not significant) |
| title_len | −0.58 | 0.10 (not significant) |

**Interpretation: early volume ranks eventual views because eventual views
*are* early volume (median day-0 share 64%; `5gcdjQ0SdrU` 98%). The scorer
does not forecast future growth; it restates the launch. Any report claiming
"day-1 views predict virality" on this data without the tail test is
overclaiming.**

## 6. Top predictive features, with numbers

Cohort A, Spearman vs eventual views (n = 9 unless noted):

| Feature | ρ | p | Reading |
|---|---|---|---|
| **d0 (launch-day views)** | **0.983** | < 0.001 | Dominant, but tautological (see §5b). |
| **3-day total** | **0.983** | < 0.001 | Same story; the usable triage rule. |
| day-0 share | 0.867 | 0.003 | Front-loaded launches finish higher — again, arithmetic more than mechanism. |
| velocity d1/d0 | −0.80 | 0.010 | **Artifact, not signal.** High ratios come from tiny denominators: `pnN5V1NKJ2E` 2→101 and `dHdnBH9q-mg` 0→58 are the *smallest* videos, not rising stars. Do not use velocity ratios on small counts. |
| days-to-peak | −0.725 | 0.027 | Same artifact from the other side: delayed-peak videos (`pnN5V1NKJ2E`, `dHdnBH9q-mg`, peak on observed day 1) are the small ones. |
| d1 alone | 0.167 | 0.67 | No signal. |
| d2 alone | 0.300 | 0.43 | No signal. |
| title_len | −0.479 | 0.19 | Direction matches `dynamic_constraints.json` (winners shorter) but not significant at n = 9. |
| starts_with_emoji | −0.137 | 0.73 | Near-constant (8/9 start with emoji); cannot discriminate. |
| has_karen | — (constant) | — | **9/9 true.** No variance, no predictive value in recent data. |
| hashtag_n | — (constant) | — | **0 in all 9 sequel titles.** No variance. |
| avg_view_pct (n = 6) | 0.200 | 0.70 | No signal in cohort A. Highest retention (216%, `xtcUVlQKmIM`) is only the 3rd-biggest video; the top video is 125%. |
| avg_dur_s (n = 6) | 0.261 | 0.62 | No signal. |
| duration_s (n = 6) | −0.778 | 0.069 | Not significant; do not chase it. |
| likes (n = 6) | 0.812 | 0.050 | **Leakage, not a feature.** Likes are measured at the latest snapshot, *after* views accrued. Excluded from the scorer. Same applies to comments (ρ = 0.207, ns). |

**Pre-launch (title/topic-only) conclusion: unscoreable on recent data.** The
formula has converged — every recent video is Karen + emoji-start, 8/9
tech-demo/instant-karma — so the title features that could once have varied
now have no variance left to learn from. A title-only model fitted on cohort A
would be fitting noise.

Cohort C (72 videos, associations only, lifetime views — read with care):

| Feature vs lifetime views | ρ | p | Caveat |
|---|---|---|---|
| avg_view_pct (n = 21 with non-null pct) | 0.544 | 0.011 | Only 1 of those 21 videos has ≥ 1,000 views (mean pct 125.5 vs 101.9 below 1,000); age-mixed. Suggestive that retention *associates* with views broadly, but it does not replicate in cohort A (ρ = 0.20, ns). |
| title_len | 0.410 | < 0.001 | **Unreliable: telemetry titles are truncated at 80 chars** (max length exactly 80; 34/72 at ≥ 79 chars, many cut mid-word). Sign also contradicts cohort A (−0.479) and `dynamic_constraints.json` (winners' titles shorter: 60.5 vs 70.8 chars). Do not use. |
| hashtag_n | 0.407 | < 0.001 | Same truncation problem (hashtags live at title ends, exactly where truncation bites); also contradicts `dynamic_constraints.json` (winners 0.15 vs losers 1.44 hashtags). Do not use. |
| duration_s | −0.493 | < 0.001 | Age/format-mixed cohort; not a launch feature. |
| starts_with_emoji | 0.148 | 0.22 | No signal. |
| has_karen | −0.040 | 0.74 | No signal. |
| review_score (n = 7 with a pipeline score) | −0.299 | 0.51 | **`dynamic_constraints.json`'s headline feature (winners 24.9 vs losers 1.69) does not replicate** in the telemetry file's pipeline scores — only 7 videos carry one, and the correlation is negative and non-significant. Its "winners" were defined by avg-view-pct, not by views, which explains the disagreement: retention-winners ≠ view-winners. |

## 7. Limitations

1. **N = 9 for the real question, 2 positives.** One video swings any binary
   metric by 11 points; confidence intervals on all cohort-A correlations are
   wide (only the d0/3-day tautology survives them).
2. **No hourly data.** The brief's "early signals" cannot be 1 h / 6 h / 24 h
   here; day buckets mix publish-time effects with performance.
3. **No variance in pre-launch features** among recent videos (Karen/emoji
   saturated), and cohort-C title features are corrupted by 80-char truncation.
4. **Retention missing for 3/9** recent videos; retention measured at differing
   snapshot ages, not at a fixed video age.
5. **Censoring:** `7oUJu0SBexk` has only 3 observed days; its tail is 0 by
   construction. Two other recent videos have only 4 rows.
6. **Survivorship in cohort C:** lifetime views mix videos of very different
   ages and eras of the channel (Feb 2025 vs Oct 2026 content).
7. **No Kronos input** was available to test (see header); if Track A later
   produces per-video forecasts on this same shared data, re-running §5b with
   the forecast as one feature (against the tail, not the total) is the correct
   test of whether it adds anything over d0.

## 8. What productionizing would actually need

1. **N ≥ 50–100 recent launches** with complete, day-aligned curves before any
   fitted model is trusted; pre-register the viral threshold (≥ 1,000) before
   looking at the new data.
2. **Fixed-age snapshots**: retention, likes, and comments measured at the same
   video age (e.g. 48 h) for every video, so they can be features rather than
   leakage.
3. **A pre-launch feature set with real variance**: device/topic, hook type,
   title structure measured on *untruncated* titles — or accept that the
   current formula has no pre-launch signal left and say so.
4. **The tail as the target**: predict views *after* the early window, not the
   total that contains the early window. Any vendor/model that reports only
   total-views accuracy is selling the tautology in §5b.
5. **Hourly data** if true early warning (first hours) is ever wanted — it does
   not exist in the current Analytics pull and would need a new pull design.
6. **What can ship now**: a day-2 triage rule, honestly labelled — rank
   just-launched videos by 3-day total; ≥ ~1,100 (≈ the in-sample stump
   threshold 1,077, between non-viral max 3-day 946 and viral min 1,207) flags the current top tier. That is ranking, not
   prediction, and it must not be presented as a virality forecast.

## 9. Per-video table (cohort A, ranked by chosen score)

| Video | d0 | d1 | d2 | 3-day | Tail | Eventual | Viral ≥1000 |
|---|---|---|---|---|---|---|---|
| 5gcdjQ0SdrU | 1337 | 1 | 8 | 1346 | 13 | 1359 | 1 |
| plspTkhTHT8 | 953 | 178 | 76 | 1207 | 6 | 1213 | 1 |
| xtcUVlQKmIM | 618 | 262 | 66 | 946 | 25 | 971 | 0 |
| fMR45Pks2PU | 488 | 154 | 58 | 700 | 9 | 709 | 0 |
| GxSeiQuOPvc | 533 | 44 | 20 | 597 | 2 | 599 | 0 |
| 7oUJu0SBexk | 141 | 80 | 51 | 272 | 0* | 272 | 0 |
| pnN5V1NKJ2E | 2 | 101 | 27 | 130 | 8 | 138 | 0 |
| 9rSkwMt6_6g | 90 | 32 | 6 | 128 | 23 | 151 | 0 |
| dHdnBH9q-mg | 0 | 58 | 38 | 96 | 27 | 123 | 0 |

\* Censored: only 3 observed days in the pull. Full features, titles, retention,
and cross-check views per video are in `track_b_results.json`.
