"""M1: the two baselines. Beating these is the minimum bar (plan S4.1).

  baseline_median  -- suburb median price per square metre x subject land area.
                      Falls back to the suburb median price where land area is
                      missing, which it is for 60% of units (open issue O4).
  baseline_linreg  -- linear regression on the core numeric features.

Both are fitted on the training window only and scored on the frozen test set.
"""

import json

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import config as C

LIN_FEATURES = ["log_area", "has_area", "lat", "lon", "dist_cbd_km",
                "sale_year", "sale_month", "days_since_start",
                "suburb_median_logprice", "suburb_n_sales"]


def write(rows, name, version="v1"):
    out = pd.DataFrame(rows)
    out["nominal_coverage"] = np.nan
    out["model_version"] = version
    out["run_timestamp"] = pd.Timestamp.now().isoformat()
    p = C.PRED / f"{name}.csv"
    out.to_csv(p, index=False)
    print(f"  wrote {p.name}  ({len(out):,} rows)")


def main():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.FEAT_PQ)
    tr, te = df.loc[meta["train_ids"]], df.loc[meta["test_ids"]]

    # ---- baseline 1: suburb median $/m2 ------------------------------------
    t = tr[tr["land_area_m2"].notna()].copy()
    t["ppsm"] = t["sale_price"] / t["land_area_m2"]
    med_ppsm = t.groupby("suburb", observed=True)["ppsm"].median()
    med_price = tr.groupby("suburb", observed=True)["sale_price"].median()
    g_ppsm = float(t["ppsm"].median())
    g_price = float(tr["sale_price"].median())

    ppsm = te["suburb"].map(med_ppsm).astype(float).fillna(g_ppsm)
    fallback = te["suburb"].map(med_price).astype(float).fillna(g_price)
    pred = np.where(te["land_area_m2"].notna(),
                    ppsm * te["land_area_m2"].fillna(0), fallback)
    n_fb = int(te["land_area_m2"].isna().sum())
    print(f"M1  baseline_median: {n_fb:,} of {len(te):,} test rows "
          f"({n_fb/len(te):.1%}) fell back to suburb median price -- no land area")
    write({"row_id": te.index, "arm": "baseline_median", "y_pred": pred,
           "y_lower": np.nan, "y_upper": np.nan}, "baseline_median")

    # ---- baseline 2: linear regression -------------------------------------
    pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LinearRegression())
    pipe.fit(tr[LIN_FEATURES], tr["log_price"])
    pred = np.exp(pipe.predict(te[LIN_FEATURES]))
    write({"row_id": te.index, "arm": "baseline_linreg", "y_pred": pred,
           "y_lower": np.nan, "y_upper": np.nan}, "baseline_linreg")


if __name__ == "__main__":
    main()
