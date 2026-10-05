"""M3: calibrated prediction intervals -- the centrepiece.

Three arms, all scored on the identical frozen test set so the harness can
report them side by side:

  quantile_raw  LightGBM quantile objective at the 10th and 90th percentiles.
                A nominal 80% band with NO calibration guarantee.
  cqr           Conformalized quantile regression (Romano et al. 2019). The raw
                quantile band is widened or narrowed by a single constant
                learned from the calibration window, giving a distribution-free
                marginal coverage guarantee.
  mapie_split   MAPIE's SplitConformalRegressor around the selected point model,
                as an independent check that our CQR implementation agrees.

Everything is done in LOG price space, so the conformity correction is
multiplicative once exponentiated -- which is what prices need. A flat +/- in
dollars would be far too wide for a $400k unit and far too narrow for a $8M
house.

Why this matters more than the point estimate: an uncalibrated interval is a
failure even if it is tight. If a nominal 80% band only covers 62%, we report
62% (plan S4.3).
"""

import json

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

import config as C
from features import CAT, FEATURES

ALPHA = 1 - C.NOMINAL_COVERAGE          # 0.20
Q_LO, Q_HI = C.QUANTILES                # 0.10, 0.90

QPARAMS = dict(objective="quantile", learning_rate=0.05, num_leaves=255,
               min_data_in_leaf=40, feature_fraction=0.85,
               bagging_fraction=0.85, bagging_freq=1, lambda_l2=1.0,
               max_cat_threshold=64, num_threads=0, verbosity=-1, seed=C.SEED)


def fit_quantile(tr, ca, alpha):
    p = dict(QPARAMS, alpha=alpha)
    dtr = lgb.Dataset(tr[FEATURES], tr["log_price"], categorical_feature=CAT)
    dca = lgb.Dataset(ca[FEATURES], ca["log_price"], categorical_feature=CAT,
                      reference=dtr)
    return lgb.train(p, dtr, num_boost_round=2000, valid_sets=[dca],
                     callbacks=[lgb.early_stopping(80, verbose=False),
                                lgb.log_evaluation(0)])


def write(idx, arm, pred, lo, hi, version="v1"):
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
    tr, ca, te = (df.loc[meta["train_ids"]], df.loc[meta["calib_ids"]],
                  df.loc[meta["test_ids"]])
    point = joblib.load(C.ART / "model_lgbm.pkl")

    print("M3  fitting quantile models ...")
    m_lo = fit_quantile(tr, ca, Q_LO)
    m_hi = fit_quantile(tr, ca, Q_HI)
    print(f"    q{Q_LO:.2f}: {m_lo.best_iteration} rounds   "
          f"q{Q_HI:.2f}: {m_hi.best_iteration} rounds")

    ca_lo = m_lo.predict(ca[FEATURES], num_iteration=m_lo.best_iteration)
    ca_hi = m_hi.predict(ca[FEATURES], num_iteration=m_hi.best_iteration)
    te_lo = m_lo.predict(te[FEATURES], num_iteration=m_lo.best_iteration)
    te_hi = m_hi.predict(te[FEATURES], num_iteration=m_hi.best_iteration)
    te_pt = np.exp(point.predict(te[FEATURES],
                                 num_iteration=point.best_iteration))

    # ---- arm 1: raw quantile band, no calibration --------------------------
    write(te.index, "quantile_raw", te_pt, np.exp(te_lo), np.exp(te_hi))

    # ---- arm 2: conformalized quantile regression --------------------------
    # Conformity score on the calibration window: how far outside its own band
    # each calibration point fell. Negative when the point sits inside.
    y_ca = ca["log_price"].to_numpy()
    scores = np.maximum(ca_lo - y_ca, y_ca - ca_hi)
    n = len(scores)
    k = min(int(np.ceil((n + 1) * (1 - ALPHA))), n)      # finite-sample rank
    qhat = float(np.sort(scores)[k - 1])
    print(f"    CQR correction qhat = {qhat:+.4f} in log space "
          f"(x{np.exp(qhat):.3f} multiplicative)")

    cqr_lo, cqr_hi = np.exp(te_lo - qhat), np.exp(te_hi + qhat)
    write(te.index, "cqr", te_pt, cqr_lo, cqr_hi)

    # ---- arm 3: MAPIE split conformal around the point model ---------------
    try:
        from mapie.regression import SplitConformalRegressor
        from sklearn.base import BaseEstimator, RegressorMixin

        class Wrapped(BaseEstimator, RegressorMixin):
            """Expose the already-fitted LightGBM booster to MAPIE."""
            def __init__(self, booster=None):
                self.booster = booster

            def fit(self, X, y):
                self.is_fitted_ = True
                return self

            def predict(self, X):
                return self.booster.predict(
                    X, num_iteration=self.booster.best_iteration)

            def __sklearn_is_fitted__(self):
                return True

        mp = SplitConformalRegressor(estimator=Wrapped(point),
                                     confidence_level=C.NOMINAL_COVERAGE,
                                     prefit=True)
        mp.conformalize(ca[FEATURES], ca["log_price"])
        _, iv = mp.predict_interval(te[FEATURES])
        write(te.index, "mapie_split", te_pt,
              np.exp(iv[:, 0, 0]), np.exp(iv[:, 1, 0]))
    except Exception as e:
        print(f"    MAPIE arm skipped: {type(e).__name__}: {e}")

    joblib.dump({"m_lo": m_lo, "m_hi": m_hi, "qhat": qhat,
                 "alpha": ALPHA, "quantiles": C.QUANTILES,
                 "n_calib": n}, C.ART / "interval.pkl")
    print(f"    saved {C.ART / 'interval.pkl'}")


if __name__ == "__main__":
    main()
