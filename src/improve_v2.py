"""The improvement loop: v1 -> v2. ONE change, measured on the identical frozen
split (plan rule 4).

The change: a market-drift correction.

Why. The v1 model trains on sales up to 2024-12 and is tested on sales from
2025-10 onward. Diagnostics showed it under-predicts by about 7% (median
pred/actual = 0.913), stable across quarters -- a level shift, not noise. The
trees cannot extrapolate a time trend past the end of their training data, so
they price 2026 sales at 2024 levels.

The fix. Estimate a single multiplicative drift factor on the CALIBRATION
window only -- never the test set -- and apply it to the point estimate and to
both quantile bands before conformalising.

This is also the honest answer to open issue O3: split-conformal assumes the
calibration and test sets are exchangeable, and market drift breaks that. By
removing the level shift first, we make the remaining residuals far closer to
exchangeable, so the conformal guarantee has a better chance of holding.
"""

import json

import joblib
import numpy as np
import pandas as pd

import config as C
from features import CAT, FEATURES

ALPHA = 1 - C.NOMINAL_COVERAGE


def write(idx, arm, pred, lo, hi, version="v2"):
    pd.DataFrame({
        "row_id": idx, "arm": arm, "y_pred": pred, "y_lower": lo,
        "y_upper": hi, "nominal_coverage": C.NOMINAL_COVERAGE,
        "model_version": version,
        "run_timestamp": pd.Timestamp.now().isoformat(),
    }).to_csv(C.PRED / f"{arm}.csv", index=False)
    print(f"    wrote {arm}.csv")


def main():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.FEAT_PQ)
    ca, te = df.loc[meta["calib_ids"]], df.loc[meta["test_ids"]]

    point = joblib.load(C.ART / "model_lgbm.pkl")
    iv = joblib.load(C.ART / "interval.pkl")
    m_lo, m_hi = iv["m_lo"], iv["m_hi"]

    # ---- estimate drift on the calibration window ONLY ---------------------
    ca_pt = point.predict(ca[FEATURES], num_iteration=point.best_iteration)
    delta = float(np.median(ca["log_price"].to_numpy() - ca_pt))
    print(f"    drift correction delta = {delta:+.4f} log "
          f"({np.exp(delta) - 1:+.2%}) -- estimated on calibration only")

    # ---- apply to point and to both quantile bands -------------------------
    te_pt = point.predict(te[FEATURES], num_iteration=point.best_iteration) + delta
    ca_lo = m_lo.predict(ca[FEATURES], num_iteration=m_lo.best_iteration) + delta
    ca_hi = m_hi.predict(ca[FEATURES], num_iteration=m_hi.best_iteration) + delta
    te_lo = m_lo.predict(te[FEATURES], num_iteration=m_lo.best_iteration) + delta
    te_hi = m_hi.predict(te[FEATURES], num_iteration=m_hi.best_iteration) + delta

    # ---- re-conformalise on the drift-corrected calibration residuals ------
    y_ca = ca["log_price"].to_numpy()
    scores = np.maximum(ca_lo - y_ca, y_ca - ca_hi)
    n = len(scores)
    k = min(int(np.ceil((n + 1) * (1 - ALPHA))), n)
    qhat = float(np.sort(scores)[k - 1])
    print(f"    CQR correction qhat  = {qhat:+.4f} "
          f"(v1 was {iv['qhat']:+.4f})")

    write(te.index, "cqr_v2", np.exp(te_pt),
          np.exp(te_lo - qhat), np.exp(te_hi + qhat))

    joblib.dump({**iv, "delta": delta, "qhat_v2": qhat},
                C.ART / "interval_v2.pkl")
    (C.ART / "drift.json").write_text(json.dumps(
        {"delta_log": delta, "delta_pct": float(np.exp(delta) - 1),
         "qhat_v1": iv["qhat"], "qhat_v2": qhat,
         "estimated_on": "calibration window only",
         "calib_window": meta["temporal_cutoffs"]}, indent=2))
    print(f"    saved {C.ART / 'interval_v2.pkl'}")


if __name__ == "__main__":
    main()
