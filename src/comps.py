"""M4: comparable-sales retrieval -- the evidence.

k-nearest-neighbours in scaled feature space, restricted to the same property
type and nearby geography, returning the closest recent sales as the
human-readable justification for an assessment. The comparables ARE the
output: NSW law asks an agent to justify a price guide against comparable
sales, so the tool has to show the same evidence rather than a model score.

The index is built from sales up to the end of the calibration window, so it
never contains a test-set sale -- a comparable drawn from the future would be
both leakage and, for a real valuation, impossible.
"""

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

import config as C

# Recency window for eligible comparables, in days before the index cutoff.
LOOKBACK_DAYS = 730
KNN_FEATURES = ["lat", "lon", "log_area_filled", "days_since_start"]
# Geography dominates; area matters; recency matters least of the three.
WEIGHTS = np.array([3.0, 3.0, 1.5, 0.8])


def build():
    meta = json.loads(C.SPLITS.read_text())
    df = pd.read_parquet(C.FEAT_PQ)

    # Eligible pool: everything up to the end of the calibration window.
    pool = df.loc[meta["train_ids"] + meta["calib_ids"]].copy()
    cutoff = pool["contract_date"].max()
    pool = pool[pool["contract_date"] >= cutoff - pd.Timedelta(days=LOOKBACK_DAYS)]

    med_area = pool.groupby("property_type", observed=True)["land_area_m2"].median()
    pool["log_area_filled"] = np.log(
        pool["land_area_m2"].fillna(pool["property_type"].map(med_area)))

    scaler = StandardScaler().fit(pool[KNN_FEATURES])
    idx = {}
    for ptype, g in pool.groupby("property_type", observed=True):
        X = scaler.transform(g[KNN_FEATURES]) * WEIGHTS
        nn = NearestNeighbors(n_neighbors=min(50, len(g)), algorithm="auto").fit(X)
        idx[str(ptype)] = {
            "nn": nn,
            "keys": g.index.to_numpy(),
            "table": g[["address", "suburb", "postcode", "property_type",
                        "land_area_m2", "contract_date", "sale_price"]],
        }
        print(f"    {ptype:<6} {len(g):>8,} eligible comparables")

    joblib.dump({"scaler": scaler, "index": idx, "med_area": med_area,
                 "weights": WEIGHTS, "features": KNN_FEATURES,
                 "cutoff": str(cutoff.date())}, C.ART / "comps_index.pkl")
    print(f"    saved {C.ART / 'comps_index.pkl'}  (pool cutoff {cutoff.date()})")


def query(art, row, k=C.N_COMPS, exclude_key=None):
    """Return the k closest recent sales to `row` (a dict-like with the
    KNN_FEATURES plus property_type)."""
    ptype = str(row["property_type"])
    if ptype not in art["index"]:
        ptype = list(art["index"])[0]
    e = art["index"][ptype]

    area = row.get("land_area_m2")
    if area is None or not np.isfinite(area) or area <= 0:
        area = float(art["med_area"].get(ptype, np.nan))
    vec = pd.DataFrame([{
        "lat": row["lat"], "lon": row["lon"],
        "log_area_filled": np.log(area),
        "days_since_start": row["days_since_start"],
    }])[art["features"]]
    X = art["scaler"].transform(vec) * art["weights"]

    k_search = min(k + 5, e["nn"].n_samples_fit_)
    dist, pos = e["nn"].kneighbors(X, n_neighbors=k_search)
    keys = e["keys"][pos[0]]
    out = e["table"].loc[keys].copy()
    out["distance"] = dist[0]
    if exclude_key is not None:
        out = out[out.index != exclude_key]
    return out.head(k)


if __name__ == "__main__":
    print("M4  building comparable-sales index ...")
    build()
