# Track A — Can Kronos predict a video's view curve? (zero-shot, CPU)

**Channel:** @karenvsai (Mark Bobl | Karen vs AI), ~490 Shorts, 9–11 s English AI comedy.
**Question:** can the open-source Kronos K-line LLM predict a video's future daily-view
trajectory from its early curve?
**Short answer: no — not zero-shot, not on this data. Kronos ran fine on CPU, but it
lost to a two-parameter exponential-decay fit on both splits, by a wide margin.**
That is a valid result, not a failure of the experiment.

## 1. Model identity (verified, not guessed)

- Repo cloned to `~/workspace/kronos/` (MIT, https://github.com/shiyu-coder/Kronos).
- README model table (lines 79–82) names the mini model explicitly:
  **model `NeoQuasar/Kronos-mini`, 4.1M params, tokenizer
  `NeoQuasar/Kronos-Tokenizer-2k` (vocab 2048), context length 2048.**
  This run used exactly those two ids (confirmed public/ungated on the Hub, MIT licence).
- Predict path used: `KronosPredictor.predict()` from `model/kronos.py`
  (`df` with `open/high/low/close` + `volume`, `x_timestamp`, `y_timestamp`,
  `pred_len`), zero-shot, no fine-tuning.
- Predict params: `T=1.0, top_p=0.9, sample_count=5` (averaged paths),
  `device="cpu"`, `max_context=2048`, seed fixed per video (1234).
  The run script is `track_a_run.py` in this same directory.
- Environment: fresh venv at `~/workspace/kronos/.venv`, CPU-only torch 2.14.1+cpu
  (`cuda? False`), plus numpy/pandas/einops/huggingface_hub/safetensors/tqdm.
  No GPU, no payments, no YouTube API calls, no YouTube writes, no credential changes.

## 2. Data and bar construction

### Source (shared dataset only)

`shared_dataset.json` (pulled once by the coordinator, 2026-10-27, 90-day window
2026-07-29 → 2026-10-27). No additional YouTube API pulls were made.

### Caveats that shaped the test (all honoured)

1. **Daily granularity only.** The Analytics API used has no hour dimension and the
   day+video combo was rejected, so there are **no hourly bars** — each video has one
   day-query. This kills any intraday-curve version of the test.
2. **Old videos are unusable for curve tests.** Their views predate the 90-day window
   (in-window sums 0–9 for Jan–Jun 2026 videos). They were excluded.
   `2ySJM2uTqZU` (~177 in-window) was specifically **excluded**: published 2025-07,
   its 62 in-window days are a sparse long tail (0–4/day), not a publish curve.
3. **Series cleaning (documented, deterministic):** pre-publish daily rows dropped
   (only `dHdnBH9q-mg` had one: a 0-view row on 2026-10-12, day before publish);
   missing calendar days inside a video's span filled with 0 (the day-query returns
   only days with views, so a gap day is a 0-view day). This affects `pnN5V1NKJ2E`
   (gaps 10-13/10-14/10-19) and `9rSkwMt6_6g` (gap 10-18).

### Bar construction — choice and weakness (stated plainly)

**Chosen: degenerate daily bars.**
`open = high = low = close = daily views`, `volume = daily views`,
`amount` left for `KronosPredictor` to auto-fill (volume × mean price cols).

**Rejected alternative: weekly OHLC bars** (open=first day, high=max, low=min,
close=last day, volume=week total). Test videos have only 4–11 days total, so an
early window of 2–3 days would yield **zero complete weeks** — the model could not
run at all on the early curve. Weekly bars are only viable with ≥3 weeks of history,
which no recent publish-curve video in this dataset has.

**Weakness of the chosen construction (material):** with OHLC identical, the bar
carries no range/volume information at all — the model sees a single repeated number
per day, plus a `volume` column that is just the same number again. Kronos was trained
on real financial K-lines where open/high/low/close/volume disagree; a degenerate bar
is out-of-distribution by construction. Any verdict here is therefore a verdict on
*zero-shot Kronos fed degenerate daily bars*, not on Kronos in general.

## 3. Test design

- **6 videos, 3 viral + 3 flat**, all with October-2026 publish curves:
  - Viral: `5gcdjQ0SdrU` (1358 snapshot), `plspTkhTHT8` (1132), `xtcUVlQKmIM` (972).
  - Flat: `9rSkwMt6_6g` (159), `pnN5V1NKJ2E` (138), `dHdnBH9q-mg` (128).
- **Primary split: first 2 days → forecast the rest** (leaves 2–9 remaining days per
  video). **Sensitivity split: first 3 days → forecast the rest** (leaves 1–8 days).
  12 Kronos runs total, all completed (`kronos_status: ok` in every record).
- **Scoring:** per-day MAE on the remaining days, and MAPE on the *total* remaining
  views (the number a publishing decision would actually use). Negative raw Kronos
  forecasts are clipped to 0 before scoring (a video cannot have negative views);
  raw values are preserved in the JSON.
- **Baselines (same splits):**
  - *Carry-forward:* every remaining day = last early-day value.
  - *Exponential decay:* log-linear least squares on positive early values, slope
    clipped to ≤ 0 (a decay model cannot grow). **Correction applied and documented:**
    when the slope is clipped, the intercept is refit as mean(log y); clipping slope
    alone would silently forecast the day-0 level (this changed only `pnN5V1NKJ2E`,
    whose early curve *rises* 2 → 101 — a decay model is misspecified there by
    definition, and its decay baseline is correspondingly weak).

## 4. Results

### Primary split: early = 2 days

| Video (label) | Early curve | Actual remaining (sum) | Kronos forecast (sum) | Carry f'cast (sum) | Exp-decay f'cast (sum) | MAE Kronos / Carry / Decay |
|---|---|---|---|---|---|---|
| 5gcdjQ0SdrU (viral) | 1337, 1 | 8, 8, 2, 2, 1 (21) | 164, 91, 213, 0*, 0* (469) | 1/day (5) | ~0/day (0) | **90.7 / 3.2 / 4.2** |
| plspTkhTHT8 (viral) | 953, 178 | 76, 6 (82) | 330, 49 (379) | 178/day (356) | 33, 6 (40) | **148.5 / 137.0 / 21.5** |
| xtcUVlQKmIM (viral) | 618, 262 | 66, 21, 2, 2 (91) | 306, 286, 319, 256 (1166) | 262/day (1048) | 111, 47, 20, 9 (187) | **268.7 / 239.3 / 23.9** |
| 9rSkwMt6_6g (flat) | 90, 32 | 6, 4, 6, 4, 0, 2, 7 (29) | 41, 32, 61, 42, 38, 24, 27 (265) | 32/day (224) | 11, 4, 1, 1, 0, 0, 0 (18) | **33.6 / 27.9 / 3.2** |
| pnN5V1NKJ2E (flat) | 2, 101 | 27, 0, 0, 1, 2, 1, 1, 0, 3 (35) | 81, 81, 78, 53, 63, 60, 63, 47, 33 (560) | 101/day (909) | 14/day (128) | **58.3 / 97.1 / 13.2** |
| dHdnBH9q-mg (flat) | 58, 38 | 14, 2, 2, 1, 4, 4 (27) | 42, 41, 44, 39, 34, 34 (234) | 38/day (228) | 25, 16, 11, 7, 5, 3 (67) | **34.6 / 33.5 / 6.9** |

\* Raw Kronos forecasts were negative (−22.2, −65.2) and clipped to 0 for scoring.

**Aggregate, early = 2:** mean MAE **Kronos 105.7, carry-forward 89.7, exp-decay 12.2**.
Mean total-MAPE: **Kronos 1126%, carry 896%, exp-decay 118%**.
Per-video MAE wins: **exp-decay 5/6, carry-forward 1/6, Kronos 0/6.**

### Sensitivity split: early = 3 days

| Video | Actual remaining (sum) | Kronos (sum) | Carry (sum) | Decay (sum) | MAE Kronos / Carry / Decay |
|---|---|---|---|---|---|
| 5gcdjQ0SdrU | 8, 2, 2, 1 (13) | −32*, 108, 56, 38 → 202 | 32 | 0 | **51.1 / 4.8 / 3.2** |
| plspTkhTHT8 | 6 (6) | −55* → 0 | 76 | 19 | **6.0 / 70.0 / 12.7** |
| xtcUVlQKmIM | 21, 2, 2 (25) | 14, 25, 48 (88) | 198 | 34 | **25.4 / 57.7 / 2.9** |
| 9rSkwMt6_6g | 4, 6, 4, 0, 2, 7 (23) | all negative → 0 | 36 | 2 | **3.8 / 2.5 / 3.5** |
| pnN5V1NKJ2E | 0, 0, 1, 2, 1, 1, 0, 3 (8) | 23, 37, 27, 35, 12, 16, 14, −19* → 165 | 216 | 141 | **20.4 / 26.0 / 16.6** |
| dHdnBH9q-mg | 2, 2, 1, 4, 4 (13) | 8, 18, 13, 6, 7 (54) | 70 | 15 | **8.1 / 11.4 / 3.0** |

**Aggregate, early = 3:** mean MAE **Kronos 19.1, carry-forward 28.7, exp-decay 7.0**.
Mean total-MAPE: Kronos 696%, carry 850%, decay 351%.
Per-video MAE wins: exp-decay 4/6, carry 1/6, Kronos 1/6 — and Kronos's single win
(`plspTkhTHT8`, 1 remaining day) is just "clipped a negative forecast to 0", not a
demonstration of curve understanding.

### What Kronos actually predicted (the mechanism of failure)

Kronos's forecasts are roughly **level-anchored and flat**: e.g. `xtcUVlQKmIM`
early = 2 → 306, 286, 319, 256 against an actual decay 66 → 2; `dHdnBH9q-mg`
early = 2 → ~34–44/day against an actual 14 → 1. It does not reproduce the defining
shape of a Shorts curve — a huge day-0/1 spike collapsing to low single digits within
2–4 days. With a 2-point input, the predictor normalises by that pair's mean/std,
tokenises it, and samples finance-like continuations; nothing in that pipeline encodes
"Shorts decay to near-zero". It also emits **impossible negative view counts** in 5 of
12 runs (all four early = 3 runs for 5gcd/plsp/9rS/pnN, plus 5gcd early = 2), which is
why clipping was needed at all. Full per-day raw forecasts are in `track_a_results.json`.

## 5. Verdict

**Kronos does NOT beat naive on this task.** On the primary (2-day) split, the
exponential-decay baseline beats Kronos by **8.7× on mean MAE (12.2 vs 105.7)** and
wins 5 of 6 videos outright; Kronos wins none. On the 3-day sensitivity split, decay
still wins (7.0 vs 19.1). The gap is not close, and it is not a sample-size artefact
in Kronos's favour: the same ranking holds for viral and flat videos alike, and
Kronos's errors are systematic (flat, level-anchored, sometimes negative), not noise.

**History length, stated with numbers:** the histories are indeed extremely short —
**4–11 daily points per video, 2–3 points fed to the model** — versus Kronos's design
context (lookback up to 512–2048 bars in the README/examples, typically hundreds of
5-minute bars). A 2-point input is two tokens of context for a model trained on long
financial series; that it produces *anything* coherent-looking is the surprising part.
So the honest two-part verdict is: **(a) zero-shot Kronos on degenerate daily bars
loses decisively to a 2-parameter decay fit; (b) the test itself is at the extreme
low end of what the model is built for, so this rules out zero-shot daily-bar use,
not Kronos as a model.**

Two data anomalies worth noting for any follow-up: `5gcdjQ0SdrU` collapses
1337 → 1 on day 1 then sits at 8, 8, 2, 2, 1 — no smooth decay model (or Kronos)
explains that day-1 cliff; and `pnN5V1NKJ2E` peaks on day 1 (2 → 101), breaking the
decay assumption from the other side. Both are real in the shared dataset, not
cleaning artefacts.

## 6. Limitations

1. **n = 6 videos, 12 runs.** Small, and all from one October-2026 publish window.
   No claim about other months, formats, or longer horizons is supported.
2. **Degenerate bars.** OHLC-identical bars are out-of-distribution for a K-line model
   (see §2). A fairer test needs real OHLC structure — which daily view data cannot supply.
3. **No hourly resolution.** The decision-relevant window for Shorts is arguably the
   first 24–48 hours, but the dataset has no hourly bars, so "early curve" here means
   2–3 *days*, by which time most of the lifetime views have already happened
   (e.g. `plspTkhTHT8`: 953 of 1213 on day 0). Predicting the *remainder* after day 2
   is predicting a small tail — the economically interesting question (will it go
   viral?) is mostly already answered by day-0 views.
4. **Zero-shot only.** No fine-tuning, no prompt/context engineering, no ensembling,
   single seed per video with 5 averaged sample paths. Sampling variance was not
   measured (re-running with other seeds could move individual forecasts, but the
   8.7× aggregate gap leaves no plausible seed effect that reverses the verdict).
5. **Remaining-day totals are small** (6–91 views on the primary split), so total-MAPE
   percentages look dramatic; MAE is the more interpretable metric here.
6. **No YouTube API pulls** were made (quota protection); any data gap is reported,
   not filled. Telemetry snapshots (~24 h apart, 669 rows) were inspected but not used
   as a second series, because their increments would duplicate the daily series at
   coarser, irregular spacing, not add hourly resolution.

## 7. What productionizing would need (if this were ever revisited)

1. **Don't use zero-shot Kronos for this.** The decay baseline is free, instant, and
   8.7× more accurate here. Any Kronos-based path must first *beat decay* on a held-out
   set before it touches a publishing decision.
2. **Real bar structure.** Hourly (or finer) view flow to build genuine OHLC bars, or
   a different framing entirely (e.g. predict cumulative-view saturation, or classify
   viral/flat, rather than forecasting a K-line).
3. **Fine-tuning on Shorts curves.** Hundreds of publish curves in-domain, with the
   model learning the Shorts decay shape (spike → near-zero in days) instead of
   financial mean-reversion. Zero-shot transfer from finance to Shorts is what failed.
4. **Longer histories and a decision-relevant target.** Predict at publish + few hours,
   not +2 days; evaluate on total lifetime views and on viral/flat classification, not
   only on tail-day MAE.
5. **Sanity guards if ever deployed:** clip negatives, cap forecasts at a multiple of
   observed views, and always report the decay-baseline forecast alongside — the day
   Kronos cannot beat decay on backtest, it does not ship.

## 8. Files

- This report: `track_a_report.md` (this directory).
- Machine-readable results: `track_a_results.json` — per video: video_id,
  outcome_label, early_days_used, early_curve, actual_remaining, kronos_forecast
  (clipped) + kronos_forecast_raw_close, naive_carryforward, naive_expdecay, errors
  (MAE + total MAPE per method), plus model/tokenizer ids and data caveats.
- Reproducible runner: `track_a_run.py` (venv `~/workspace/kronos/.venv`,
  CPU-only torch 2.14.1+cpu).
- Model code: `~/workspace/kronos/` (cloned MIT repo, unmodified except the added
  `.venv/`).

*No YouTube writes, uploads, publishes, deletes, renames, or metadata changes were
made. No credentials were changed. No external agents were contacted.*
