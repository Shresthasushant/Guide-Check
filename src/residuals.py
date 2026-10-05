"""Save the calibration residual distribution.

The binary flag is being replaced by a calibrated percentile, and that needs a
full predictive distribution rather than just two quantile bounds.

The honest way to get one without assuming a shape: take the model's errors on
the held-out calibration window and reuse them. For a subject property with
point estimate P, the predictive distribution is P * exp(r) for the empirical
residuals r. The percentile of an advertised guide G is then simply the
fraction of residuals with r < log(G / P).

No normality assumption, no fitted variance -- just measured errors on data the
model never trained on.
"""

import json

import joblib
import numpy as np
import pandas as pd

import config as C
from features import FEATURES


def main():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.FEAT_PQ)
    ca = df.loc[meta["calib_ids"]]

    point = joblib.load(C.ART / "model_lgbm.pkl")
    iv = joblib.load(C.ART / "interval_v2.pkl")

    pred_log = point.predict(ca[FEATURES],
                             num_iteration=point.best_iteration) + iv["delta"]
    resid = ca["log_price"].to_numpy() - pred_log          # log(actual / pred)

    # Keep a segment breakdown too: error is not uniform across the state, and
    # a percentile quoted from statewide residuals would be misleading for a
    # Sydney house. Metro/regional is the split that actually moved the numbers.
    seg = np.where(ca["dist_cbd_km"].to_numpy() < 50, "metro", "regional")

    out = {
        "resid_all": np.sort(resid),
        "resid_by_segment": {s: np.sort(resid[seg == s]) for s in ("metro",
                                                                   "regional")},
        "n_calib": int(len(resid)),
        "median_abs_pct": float(np.median(np.abs(np.exp(resid) - 1)) * 100),
    }
    joblib.dump(out, C.ART / "residuals.pkl")

    print(f"saved {C.ART / 'residuals.pkl'}")
    print(f"  calibration residuals      {out['n_calib']:,}")
    print(f"  typical error (median abs) {out['median_abs_pct']:.1f}%")
    for s, r in out["resid_by_segment"].items():
        print(f"  {s:<9} n={len(r):>7,}  typical error "
              f"{np.median(np.abs(np.exp(r)-1))*100:>5.1f}%")


if __name__ == "__main__":
    main()
