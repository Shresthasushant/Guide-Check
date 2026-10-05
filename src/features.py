"""D4: feature engineering.

Runs AFTER the split, not before. The suburb price index is a target-derived
feature, so computing it over all rows would leak test information into
training. It is fitted on the training window only and then applied everywhere
-- the standard fit/transform discipline.

Feature groups (used by the ablation in the harness):
  structural : land_area_m2, log_area, has_area, property_type
  spatial    : suburb, sa2_code, postcode, lat, lon, dist_cbd_km, zoning
  temporal   : sale_year, sale_month, days_since_start
  index      : suburb_median_logprice, suburb_n_sales
"""

import json

import numpy as np
import pandas as pd

import config as C

CAT = ["property_type", "zoning", "suburb", "sa2_code", "postcode"]
NUM = ["land_area_m2", "log_area", "has_area", "lat", "lon", "dist_cbd_km",
       "sale_year", "sale_month", "days_since_start",
       "suburb_median_logprice", "suburb_n_sales"]
FEATURES = NUM + CAT

GROUPS = {
    "structural": ["land_area_m2", "log_area", "has_area", "property_type"],
    "spatial": ["suburb", "sa2_code", "postcode", "lat", "lon",
                "dist_cbd_km", "zoning"],
    "temporal": ["sale_year", "sale_month", "days_since_start"],
    "index": ["suburb_median_logprice", "suburb_n_sales"],
}


def build(df, train_idx):
    df = df.copy()
    df["has_area"] = df["land_area_m2"].notna().astype("int8")
    df["log_area"] = np.log(df["land_area_m2"].where(df["land_area_m2"] > 0))
    t0 = df["contract_date"].min()
    df["days_since_start"] = (df["contract_date"] - t0).dt.days.astype("int32")

    # --- suburb price index, fitted on TRAIN ONLY ---------------------------
    tr = df.loc[train_idx]
    idx = tr.groupby("suburb")["log_price"].agg(["median", "size"])
    idx.columns = ["suburb_median_logprice", "suburb_n_sales"]
    global_median = float(tr["log_price"].median())

    df = df.join(idx, on="suburb")
    df["suburb_median_logprice"] = df["suburb_median_logprice"].fillna(global_median)
    df["suburb_n_sales"] = df["suburb_n_sales"].fillna(0).astype("int32")

    for c in CAT:
        df[c] = df[c].astype("category")
    return df


def main():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.CLEAN_PQ)
    df.index.name = "row_id"
    df = build(df, meta["train_ids"])
    df.to_parquet(C.FEAT_PQ)
    print(f"wrote {C.FEAT_PQ}  ({len(df):,} rows, {len(FEATURES)} features)")
    print(f"  suburb index fitted on {len(meta['train_ids']):,} training rows only")
    print(f"  land area present on {df['has_area'].mean():.1%} of rows")


if __name__ == "__main__":
    main()
