"""Track A: Kronos-mini zero-shot forecast of daily view curves (CPU only).

Bar construction (degenerate daily bars, stated plainly):
  open = high = low = close = daily views, volume = daily views.
  `amount` is left for KronosPredictor to auto-fill (volume * mean price cols).
Daily series: shared_dataset.json daily_views, pre-publish rows dropped,
missing calendar days inside the span filled with 0 (Analytics day-query
returns only days with views; a gap day is a 0-view day).

Baselines (same split):
  carry-forward: every remaining day = last early day value.
  exp-decay: log-linear least squares on positive early values, slope
    clipped to <= 0 (a decay model cannot grow); forecast = exp(a*t + b),
    floored at 0. If <2 positive early values, falls back to carry-forward.
    NOTE: pnN5V1NKJ2E rises 2 -> 101 in the early window, so the clipped
    decay fit is a flat ~14.2/day; the unclipped fit explodes (documented
    in the report, not used as the headline baseline).

Kronos: NeoQuasar/Kronos-mini (4.1M) + NeoQuasar/Kronos-Tokenizer-2k,
  zero-shot predict(), T=1.0, top_p=0.9, sample_count=5 (averaged paths,
  matching the library default sample_count=5 in auto_regressive_inference),
  seeds fixed per video for reproducibility. Forecast 'close' is the
  predicted daily views; negative forecasts are clipped to 0 for scoring
  (raw values also saved).
Primary split: early_days_used=2 for every video (leaves >=2 remaining
  days for all 6 test videos). Sensitivity split early=3 also run.
"""
import json, math, sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SHARED = Path.home() / "workspace/goals/karenvsai/hidden_files/kronos-tracks/shared_dataset.json"
OUT = Path.home() / "workspace/goals/karenvsai/hidden_files/kronos-tracks/track_a_results.json"
KRONOS_DIR = Path.home() / "workspace/kronos"

TEST = {
    # video_id: (outcome_label, note)
    "5gcdjQ0SdrU": ("viral", "1358 snapshot views; day0=1337 then collapse to 1"),
    "plspTkhTHT8": ("viral", "1132 snapshot views"),
    "xtcUVlQKmIM": ("viral", "972 snapshot views"),
    "9rSkwMt6_6g": ("flat", "159 snapshot views"),
    "pnN5V1NKJ2E": ("flat", "138 snapshot views; delayed peak day1=101 after day0=2"),
    "dHdnBH9q-mg": ("flat", "128 snapshot views; pre-publish 0-row dropped"),
}


def load_series(vid):
    d = json.load(open(SHARED))
    v = d["videos"][vid]
    dv = {x[0]: x[1] for x in v["daily_views"]}
    pub = v["published_at_derived"][:10]
    dates = sorted(k for k in dv if k >= pub)
    start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    vals, dts, cur = [], [], start
    while cur <= end:
        vals.append(dv.get(cur.isoformat(), 0))
        dts.append(cur)
        cur += timedelta(days=1)
    return vals, dts, pub


def baselines(early, n_rem):
    carry = [float(early[-1])] * n_rem
    xs = np.arange(len(early))
    ys = np.array(early, float)
    pos = ys > 0
    if pos.sum() >= 2:
        a, b = np.polyfit(xs[pos], np.log(ys[pos]), 1)
        if a > 0:
            # Rising early curve: clipping slope alone would leave the
            # unclipped intercept (day-0 level). Refit intercept as mean(log y).
            a = 0.0
            b = float(np.mean(np.log(ys[pos])))
            dec_note = f"log-linear slope was positive -> clipped to 0, intercept refit to mean(log y)={b:.3f}"
        else:
            dec_note = f"log-linear slope={a:.3f}, intercept={b:.3f}"
        dec = [max(0.0, math.exp(a * (len(early) + i) + b)) for i in range(n_rem)]
    else:
        dec = list(carry)
        dec_note = "fallback to carry-forward (<2 positive early values)"
    return carry, dec, dec_note


def mae(a, b):
    return float(np.mean([abs(x - y) for x, y in zip(a, b)]))


def mape_total(forecast_sum, actual_sum):
    return float(abs(forecast_sum - actual_sum) / actual_sum) if actual_sum else None


def main():
    sys.path.insert(0, str(KRONOS_DIR))
    from model import Kronos, KronosTokenizer, KronosPredictor
    import torch

    torch.manual_seed(0)
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=2048)

    results = []
    for vid, (label, note) in TEST.items():
        vals, dts, pub = load_series(vid)
        for early_n in (2, 3):
            if len(vals) <= early_n:
                continue
            early, rem = vals[:early_n], vals[early_n:]
            x_ts = pd.Series(pd.to_datetime([d.isoformat() for d in dts[:early_n]]))
            y_ts = pd.Series(pd.to_datetime([d.isoformat() for d in dts[early_n:]]))
            df = pd.DataFrame({
                "open": [float(x) for x in early],
                "high": [float(x) for x in early],
                "low": [float(x) for x in early],
                "close": [float(x) for x in early],
                "volume": [float(x) for x in early],
            })
            torch.manual_seed(1234)
            try:
                pred_df = predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts,
                                            pred_len=len(rem), T=1.0, top_p=0.9,
                                            sample_count=5, verbose=False)
                kron_raw = [float(x) for x in pred_df["close"].tolist()]
                kron_status = "ok"
            except Exception as e:  # noqa: BLE001 - report exact failure
                kron_raw = [None] * len(rem)
                kron_status = f"FAILED: {type(e).__name__}: {e}"
            kron = [max(0.0, x) if x is not None else None for x in kron_raw]
            carry, dec, dec_note = baselines(early, len(rem))
            rec = {
                "video_id": vid, "outcome_label": label, "note": note,
                "published_at_derived": pub,
                "full_daily_series": vals, "full_dates": [d.isoformat() for d in dts],
                "early_days_used": early_n, "early_curve": early,
                "actual_remaining": rem, "actual_remaining_sum": int(sum(rem)),
                "kronos_forecast_raw_close": kron_raw,
                "kronos_forecast": kron,
                "kronos_forecast_sum": float(sum(kron)) if all(x is not None for x in kron) else None,
                "kronos_status": kron_status,
                "naive_carryforward": carry, "naive_carryforward_sum": float(sum(carry)),
                "naive_expdecay": dec, "naive_expdecay_sum": float(sum(dec)),
                "naive_expdecay_note": dec_note,
            }
            if all(x is not None for x in kron):
                rec["errors"] = {
                    "kronos_mae": mae(kron, rem),
                    "carryforward_mae": mae(carry, rem),
                    "expdecay_mae": mae(dec, rem),
                    "kronos_total_mape": mape_total(sum(kron), sum(rem)),
                    "carryforward_total_mape": mape_total(sum(carry), sum(rem)),
                    "expdecay_total_mape": mape_total(sum(dec), sum(rem)),
                }
            results.append(rec)
            print(vid, f"early={early_n}", "early=", early, "actual_rem=", rem,
                  "kronos=", [round(x, 2) if x is not None else None for x in kron_raw],
                  "carry_sum=", round(sum(carry), 1), "dec_sum=", round(sum(dec), 1),
                  "status=", kron_status, flush=True)

    payload = {
        "model": "NeoQuasar/Kronos-mini",
        "model_params": "4.1M (per project README table)",
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-2k",
        "tokenizer_vocab": 2048,
        "max_context_used": 2048,
        "predict_params": {"T": 1.0, "top_p": 0.9, "sample_count": 5, "device": "cpu", "zero_shot": True},
        "bar_construction": "degenerate daily bars: open=high=low=close=daily views, volume=daily views; amount auto-filled by KronosPredictor (volume * mean price cols)",
        "data_caveats": [
            "Daily granularity only; no hourly bars exist in the shared dataset (Analytics API has no hour dimension; day+video combo rejected).",
            "Pre-publish daily rows dropped; missing calendar days inside a video's span filled with 0.",
            "Old videos' in-window views are near-zero because views predate the 90-day window; excluded from curve tests (only Oct-2026 publish-curve videos used).",
            "2ySJM2uTqZU excluded: published 2025-07, its 62 in-window days are a sparse long tail, not a publish curve.",
        ],
        "results": results,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
