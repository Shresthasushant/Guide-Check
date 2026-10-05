"""M2: the point model. LightGBM vs XGBoost, compared then selected.

Both arms train on the identical training window with the identical feature
set, and both are scored on the frozen test set. The stronger becomes the
production point model; the other stays in the results table as evidence the
choice was measured rather than assumed (plan S4.2).

Early stopping uses the calibration window. Note this makes the calibration
window a model-selection set as well as the conformal calibration set -- an
accepted trade-off here, flagged in docs/MODEL-NOTES.md.
"""

import json
import time

import joblib
import numpy as np
import pandas as pd

import config as C
from features import CAT, FEATURES

LGB_PARAMS = dict(objective="regression", metric="l2", learning_rate=0.05,
                  num_leaves=255, min_data_in_leaf=40, feature_fraction=0.85,
                  bagging_fraction=0.85, bagging_freq=1, lambda_l2=1.0,
                  max_cat_threshold=64, num_threads=0, verbosity=-1,
                  seed=C.SEED)
XGB_PARAMS = dict(objective="reg:squarederror", learning_rate=0.05,
                  max_depth=10, min_child_weight=20, subsample=0.85,
                  colsample_bytree=0.85, reg_lambda=1.0, tree_method="hist",
                  max_cat_to_onehot=1, enable_categorical=True,
                  random_state=C.SEED, n_jobs=0)
N_ROUNDS = 3000


def write(idx, arm, pred, version="v1"):
    out = pd.DataFrame({
        "row_id": idx, "arm": arm, "y_pred": pred,
        "y_lower": np.nan, "y_upper": np.nan, "nominal_coverage": np.nan,
        "model_version": version,
        "run_timestamp": pd.Timestamp.now().isoformat()})
    out.to_csv(C.PRED / f"{arm}.csv", index=False)
    print(f"    wrote {arm}.csv")


def train_lgbm(tr, ca, te):
    import lightgbm as lgb
    dtr = lgb.Dataset(tr[FEATURES], tr["log_price"], categorical_feature=CAT)
    dca = lgb.Dataset(ca[FEATURES], ca["log_price"], categorical_feature=CAT,
                      reference=dtr)
    t0 = time.time()
    m = lgb.train(LGB_PARAMS, dtr, num_boost_round=N_ROUNDS,
                  valid_sets=[dca],
                  callbacks=[lgb.early_stopping(100, verbose=False),
                             lgb.log_evaluation(0)])
    print(f"    LightGBM  {m.best_iteration} rounds, {time.time()-t0:.0f}s")
    return m, np.exp(m.predict(te[FEATURES], num_iteration=m.best_iteration))


def train_xgb(tr, ca, te):
    import xgboost as xgb
    dtr = xgb.DMatrix(tr[FEATURES], tr["log_price"], enable_categorical=True)
    dca = xgb.DMatrix(ca[FEATURES], ca["log_price"], enable_categorical=True)
    dte = xgb.DMatrix(te[FEATURES], enable_categorical=True)
    t0 = time.time()
    m = xgb.train(XGB_PARAMS, dtr, num_boost_round=N_ROUNDS,
                  evals=[(dca, "calib")], early_stopping_rounds=100,
                  verbose_eval=False)
    print(f"    XGBoost   {m.best_iteration} rounds, {time.time()-t0:.0f}s")
    return m, np.exp(m.predict(dte, iteration_range=(0, m.best_iteration + 1)))


def main():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.FEAT_PQ)
    tr, ca, te = (df.loc[meta["train_ids"]], df.loc[meta["calib_ids"]],
                  df.loc[meta["test_ids"]])
    print(f"M2  train {len(tr):,} | calib {len(ca):,} | test {len(te):,}")

    lgbm, p_lgb = train_lgbm(tr, ca, te)
    write(te.index, "lgbm", p_lgb)
    xgbm, p_xgb = train_xgb(tr, ca, te)
    write(te.index, "xgb", p_xgb)

    y = te["sale_price"].to_numpy(float)
    mape = {"lgbm": float(np.mean(np.abs(p_lgb - y) / y) * 100),
            "xgb": float(np.mean(np.abs(p_xgb - y) / y) * 100)}
    winner = min(mape, key=mape.get)
    print(f"\n    LightGBM MAPE {mape['lgbm']:.2f}%   "
          f"XGBoost MAPE {mape['xgb']:.2f}%")
    print(f"    SELECTED: {winner}")

    joblib.dump(lgbm, C.ART / "model_lgbm.pkl")
    joblib.dump(xgbm, C.ART / "model_xgb.pkl")
    (C.ART / "point_selection.json").write_text(json.dumps(
        {"selected": winner, "mape_test": mape,
         "decided_on": "frozen test set", "features": FEATURES}, indent=2))


if __name__ == "__main__":
    main()
