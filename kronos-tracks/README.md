# Kronos three-track viral analysis — @karenvsai

Quantitative analysis of what makes videos go viral on the YouTube channel
@karenvsai ("Mark Bobl | Karen vs AI"), using the Kronos time-series
foundation model (shiyu-coder/Kronos, Kronos-mini, CPU) and the channel's own
view data. Experiment date: 2026-10-27. All three tracks returned negative
results and converged on one root cause.

## Track A — Can Kronos predict a view curve? (zero-shot, CPU)

Verdict: **no.** On daily bars, the exponential-decay baseline beats zero-shot
Kronos-mini by 8.7x on mean MAE (12.1 vs 105.7); Kronos wins 0 of 6 videos.
Histories are 4–11 daily points with only 2–3 fed to the model, versus the
hundreds of bars Kronos is designed for. This rules out zero-shot daily-bar
use, not Kronos as a model.
Files: `track_a_report.md`, `track_a_results.json`, `track_a_run.py`.

## Track B — Virality scoring

Verdict: **no credible scorer.** The only ranking that "works" is the 3-day
total (d0+d1+d2, Spearman 0.983 vs eventual views) — but eventual views
*are* early volume (median day-0 share 64%). Nothing predicts the tail after
day 2 (all correlations insignificant, rho ≈ −0.20). Sorting, not forecasting.
Files: `track_b_report.md`, `track_b_results.json`, `track_b_analysis.py`.

## Track C — Publish-slot optimization

Verdict: **no change supported — keep the current slots.** The Friday/Monday
lore fails on recent comparable-era data. Hour-bucket and topic controls do
not support a slot move.
Files: `track_c_report.md`, `track_c_results.json`,
`track_c_intermediate.json`, `track_c_analysis.py`.

## Shared data

`shared_dataset.json`: per-video daily views for the test window
2026-07-29 to 2026-10-27, pulled 2026-10-27. Video IDs and view counts are
the channel's own public metrics.

## What comes next (per the 2026-10-27 decision)

Do not re-run scoring/prediction models until the data foundation exists:
hourly view snapshots + same-age retention + flip-to-public times, with
N ≥ 50–100 recent videos (about 25–50 days at 2 videos/day). Virality is
mostly decided by the first 1–2 days of views themselves.
