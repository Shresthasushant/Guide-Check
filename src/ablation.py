"""Ablations (plan S9 item 4): retrain the point model with one feature group
removed at a time, on the IDENTICAL frozen split, and let the harness report
the deltas.

This answers "which feature groups are actually carrying the model?" with
measurements rather than intuition -- and it is the slot the optional CNN
condition score would drop into as `vision_on` vs `vision_off`.
"""

import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

import config as C
from features import CAT, FEATURES, GROUPS
from train_point import LGB_PARAMS, N_ROUNDS


def run(tr, ca, te, feats, arm):
    cats = [c for c in CAT if c in feats]
    dtr = lgb.Dataset(tr[feats], tr["log_price"], categorical_feature=cats)
    dca = lgb.Dataset(ca[feats], ca["log_price"], categorical_feature=cats,
                      reference=dtr)
    t0 = time.time()
    m = lgb.train(LGB_PARAMS, dtr, num_boost_round=N_ROUNDS, valid_sets=[dca],
                  callbacks=[lgb.early_stopping(100, verbose=False),
                             lgb.log_evaluation(0)])
    pred = np.exp(m.predict(te[feats], num_iteration=m.best_iteration))
    pd.DataFrame({
        "row_id": te.index, "arm": arm, "y_pred": pred,
        "y_lower": np.nan, "y_upper": np.nan, "nominal_coverage": np.nan,
        "model_version": "ablation",
        "run_timestamp": pd.Timestamp.now().isoformat(),
    }).to_csv(C.PRED / f"{arm}.csv", index=False)
    y = te["sale_price"].to_numpy(float)
    mape = float(np.mean(np.abs(pred - y) / y) * 100)
    print(f"    {arm:<24} {len(feats):>2} feats  MAPE {mape:6.2f}%  "
          f"({time.time()-t0:.0f}s)")
    return mape


def main():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.FEAT_PQ)
    tr, ca, te = (df.loc[meta["train_ids"]], df.loc[meta["calib_ids"]],
                  df.loc[meta["test_ids"]])

    print("Ablations -- one feature group removed at a time")
    full = run(tr, ca, te, FEATURES, "abl_all_features")
    rows = [{"arm": "abl_all_features", "removed": "(none)", "MAPE_%": full,
             "delta_pp": 0.0}]
    for name, cols in GROUPS.items():
        feats = [f for f in FEATURES if f not in cols]
        if not feats:
            continue
        m = run(tr, ca, te, feats, f"abl_no_{name}")
        rows.append({"arm": f"abl_no_{name}", "removed": name, "MAPE_%": m,
                     "delta_pp": round(m - full, 3)})

    out = pd.DataFrame(rows).sort_values("MAPE_%")
    md = ["| arm | removed | MAPE_% | delta_pp |", "|---|---|---|---|"]
    md += [f"| {r.arm} | {r.removed} | {r._3:.2f} | {r.delta_pp:+.2f} |"
           for r in out.itertuples()]
    (C.RESULTS / "ablation.md").write_text(
        "# Ablation -- feature groups\n\n"
        "Point model retrained with one group removed, identical frozen split.\n"
        "Positive delta means removing the group made the model worse, i.e. the\n"
        "group was carrying real signal.\n\n"
        + "\n".join(md) + "\n", encoding="utf-8")
    print("\n" + out.to_string(index=False))
    print(f"\nwrote {C.RESULTS / 'ablation.md'}")


if __name__ == "__main__":
    main()
