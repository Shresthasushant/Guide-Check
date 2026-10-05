"""H1: the evaluation harness.

Built BEFORE any model exists (plan rule 2). It reads only the frozen split and
a predictions file conforming to contract 1.2, so it can be developed and proven
against a fabricated predictions file while modelling has not started.

Run directly to score every predictions/*.csv and write a timestamped report:

    python harness.py

Contract note: the plan specified `property_id` as the join key, but a property
can sell more than once, so property_id is NOT unique in PSI. The key is
`row_id` (the row index of sales_clean.parquet). property_id is kept alongside
for display.
"""

import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import config as C

REQUIRED = ["row_id", "arm", "y_pred", "model_version"]


# --------------------------------------------------------------- metrics ----
def point_metrics(y, yhat):
    err = yhat - y
    return {
        "n": int(len(y)),
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MAPE_%": float(np.mean(np.abs(err / y)) * 100),
        "MedAPE_%": float(np.median(np.abs(err / y)) * 100),
    }


def pinball(y, q_pred, q):
    d = y - q_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def interval_metrics(y, lo, hi, nominal):
    ok = np.isfinite(lo) & np.isfinite(hi)
    if ok.sum() == 0:
        return None
    y, lo, hi = y[ok], lo[ok], hi[ok]
    covered = (y >= lo) & (y <= hi)
    lo_q, hi_q = (1 - nominal) / 2, 1 - (1 - nominal) / 2
    return {
        "n_with_interval": int(ok.sum()),
        "nominal_coverage_%": float(nominal * 100),
        "empirical_coverage_%": float(covered.mean() * 100),
        "coverage_gap_pp": float(covered.mean() * 100 - nominal * 100),
        "mean_width_$": float(np.mean(hi - lo)),
        "median_width_$": float(np.median(hi - lo)),
        "mean_width_%_of_price": float(np.mean((hi - lo) / y) * 100),
        "pinball_lower": pinball(y, lo, lo_q),
        "pinball_upper": pinball(y, hi, hi_q),
    }


# ------------------------------------------------------------------ core ----
def load_truth():
    # The cleaned table is the natural source, but the feature table carries the
    # same rows and the same index, so the submitted bundle can ship one parquet
    # instead of two nearly identical 60MB files.
    src = C.CLEAN_PQ if C.CLEAN_PQ.exists() else C.FEAT_PQ
    df = pd.read_parquet(src, columns=["property_id", "sale_price",
                                       "suburb", "contract_date"])
    df.index.name = "row_id"
    return df.reset_index()


def score_file(path, truth, test_ids):
    pred = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in pred.columns]
    if missing:
        raise ValueError(f"{path.name}: missing required columns {missing}")

    for c in ("y_lower", "y_upper"):
        if c not in pred.columns:
            pred[c] = np.nan
    nominal = float(pred["nominal_coverage"].dropna().iloc[0]) \
        if "nominal_coverage" in pred.columns and pred["nominal_coverage"].notna().any() \
        else C.NOMINAL_COVERAGE

    test = set(test_ids)
    pred = pred[pred["row_id"].isin(test)]
    m = truth.merge(pred, on="row_id", how="inner", validate="one_to_many")
    if m.empty:
        raise ValueError(f"{path.name}: no rows overlap the frozen test set")

    out = []
    for arm, g in m.groupby("arm"):
        y = g["sale_price"].to_numpy(float)
        res = {"arm": arm,
               "model_version": g["model_version"].iloc[0],
               **point_metrics(y, g["y_pred"].to_numpy(float))}
        iv = interval_metrics(y, g["y_lower"].to_numpy(float),
                              g["y_upper"].to_numpy(float), nominal)
        if iv:
            res.update(iv)
        out.append(res)
    return out


def fmt_table(rows, cols, title):
    rows = [r for r in rows if any(c in r for c in cols[1:])]
    if not rows:
        return ""
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if isinstance(v, float):
                v = f"{v:,.1f}" if abs(v) >= 100 else f"{v:,.3f}"
            elif isinstance(v, int):
                v = f"{v:,}"
            cells.append(str(v))
        body.append("| " + " | ".join(cells) + " |")
    return f"\n### {title}\n\n" + "\n".join([head, sep] + body) + "\n"


def main(pattern="*.csv*"):
    # *.csv* rather than *.csv: the submitted predictions are gzipped (151MB of
    # CSV compresses to about a fifth). pandas reads .csv.gz by extension.
    meta = json.loads(C.SPLITS.read_text())
    truth = load_truth()
    files = sorted(C.PRED.glob(pattern))
    if not files:
        print(f"no predictions files in {C.PRED}")
        return

    allrows = []
    for f in files:
        try:
            allrows += score_file(f, truth, meta["test_ids"])
            print(f"  scored {f.name}")
        except Exception as e:
            print(f"  SKIP {f.name}: {e}")

    allrows.sort(key=lambda r: r.get("MAPE_%", 9e9))
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    lines = [
        "# Guide Check -- evaluation results",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M}",
        f"Frozen split: {meta['freeze_date']} "
        f"({meta['split_method']}, grouped by {meta['group_key']})",
        f"Test set: {meta['n_test']:,} sales from "
        f"{meta['temporal_cutoffs']['calib_end']} onward -- untouched until now.",
        "",
        fmt_table(allrows,
                  ["arm", "model_version", "n", "MAE", "RMSE", "MAPE_%",
                   "MedAPE_%"],
                  "Point accuracy (lower is better)"),
        fmt_table(allrows,
                  ["arm", "n_with_interval", "nominal_coverage_%",
                   "empirical_coverage_%", "coverage_gap_pp", "mean_width_$",
                   "mean_width_%_of_price", "pinball_lower", "pinball_upper"],
                  "Interval calibration"),
    ]

    base = next((r for r in allrows if r["arm"] == "baseline_median"), None)
    best = allrows[0] if allrows else None
    if base and best and best["arm"] != base["arm"]:
        imp = (base["MAPE_%"] - best["MAPE_%"]) / base["MAPE_%"] * 100
        lines += ["", "### Headline", "",
                  f"- Best arm: **{best['arm']}** at {best['MAPE_%']:.2f}% MAPE",
                  f"- Baseline (suburb median $/m2): {base['MAPE_%']:.2f}% MAPE",
                  f"- Improvement over baseline: **{imp:.1f}%** relative", ""]

    out = C.RESULTS / f"results-{ts}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    (C.RESULTS / f"results-{ts}.json").write_text(json.dumps(allrows, indent=2))
    print(f"\nwrote {out}")
    print("\n".join(lines))
    return allrows


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "*.csv*")
