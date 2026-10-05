"""D1-D3: ingest the NSW VG PSI extract, clean it, and attach geography.

Produces sales_clean.parquet against contract 1.1 of the build plan.

Cleaning decisions are all in config.py so they are auditable. Three of them
came out of actually profiling the file (docs/DATA-REPORT.md) and are NOT in the
original plan:

  * Area type is M or H -- 6.4% of rows are in HECTARES. Treating those as
    square metres is a 10,000x error that would silently wreck every area
    feature and the median $/m2 baseline.
  * Part interest flag marks sales of a partial share, where the price is not
    the value of the whole property. Must be dropped.
  * The Non-market price flag catches only 687 rows in 1.5M, so a price floor
    is needed as well -- there are 5,198 sales under $10,000.
"""

import io
import json
import zipfile

import numpy as np
import pandas as pd

import config as C

USECOLS = [
    "Property ID", "Property unit number", "Property house number",
    "Property street name", "Property locality", "Property post code",
    "Area (m2)", "Area type (source)", "Contract date", "Settlement date",
    "Purchase price", "Zoning", "Primary purpose (normalised)",
    "Strata lot number", "Part interest flag", "Non-market price flag",
    "Date error flag", "District code",
]

RENAME = {
    "Property ID": "property_id",
    "Property locality": "suburb",
    "Property post code": "postcode",
    "Area (m2)": "area_raw",
    "Area type (source)": "area_type",
    "Contract date": "contract_date",
    "Settlement date": "settlement_date",
    "Purchase price": "sale_price",
    "Zoning": "zoning",
    "Primary purpose (normalised)": "purpose",
    "Strata lot number": "strata_lot",
    "District code": "district_code",
}


def _addr(df):
    parts = [
        df["Property unit number"].fillna("").str.strip(),
        df["Property house number"].fillna("").str.strip(),
        df["Property street name"].fillna("").str.strip(),
    ]
    unit = np.where(parts[0] != "", parts[0] + "/", "")
    return (pd.Series(unit, index=df.index) + parts[1] + " " + parts[2]).str.strip()


def fetch(url, dest, label):
    """Download an input file if it is not already present.

    Both inputs are free public downloads, so a clean checkout can rebuild
    everything without anyone hand-placing files.
    """
    if dest.exists() and dest.stat().st_size > 0:
        print(f"    {label}: already present ({dest.stat().st_size/1e6:.0f} MB)")
        return
    import urllib.request
    print(f"    {label}: downloading from {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r      {done/1e6:,.0f} / {total/1e6:,.0f} MB",
                      end="", flush=True)
    print()
    tmp.replace(dest)
    print(f"    {label}: saved {dest.stat().st_size/1e6:.0f} MB")


def load_raw():
    """Stream the zipped CSV in chunks so we never hold 389MB of strings."""
    z = zipfile.ZipFile(C.PSI_ZIP)
    name = z.namelist()[0]
    out = []
    with z.open(name) as fh:
        for ch in pd.read_csv(fh, usecols=USECOLS, dtype=str,
                              chunksize=400_000, low_memory=False):
            ch = ch[ch["Primary purpose (normalised)"].fillna("").str.strip()
                    == C.KEEP_PURPOSE]                      # residential only
            ch = ch[ch["Part interest flag"].fillna("False") != "True"]
            ch = ch[ch["Non-market price flag"].fillna("False") != "True"]
            ch = ch[ch["Date error flag"].fillna("False") != "True"]
            if len(ch):
                ch = ch.copy()
                ch["address"] = _addr(ch)
                out.append(ch.drop(columns=[
                    "Property unit number", "Property house number",
                    "Property street name", "Part interest flag",
                    "Non-market price flag", "Date error flag"]))
    df = pd.concat(out, ignore_index=True)
    return df.rename(columns=RENAME)


def clean(df, report):
    n0 = len(df)
    report["rows_after_purpose_and_flag_filters"] = n0

    df["sale_price"] = pd.to_numeric(df["sale_price"], errors="coerce")
    df["contract_date"] = pd.to_datetime(df["contract_date"], errors="coerce")
    df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce")

    # --- area: convert hectares to square metres before anything touches it --
    area = pd.to_numeric(df["area_raw"], errors="coerce")
    is_ha = df["area_type"].fillna("").str.upper().eq("H")
    report["rows_area_in_hectares_converted"] = int((is_ha & area.notna()).sum())
    df["land_area_m2"] = np.where(is_ha, area * 10_000.0, area)
    df.loc[~df["land_area_m2"].between(C.MIN_AREA, C.MAX_AREA), "land_area_m2"] = np.nan

    # --- drop rows we cannot use -------------------------------------------
    before = len(df)
    df = df[df["contract_date"].notna()]
    report["dropped_missing_contract_date"] = before - len(df)

    before = len(df)
    df = df[df["sale_price"].between(C.MIN_PRICE, C.MAX_PRICE)]
    report["dropped_price_outside_bounds"] = before - len(df)

    before = len(df)
    df = df[df["suburb"].notna() & (df["suburb"].str.strip() != "")]
    df = df[df["postcode"].notna() & (df["postcode"].str.strip() != "")]
    report["dropped_missing_suburb_or_postcode"] = before - len(df)

    # --- de-duplicate -------------------------------------------------------
    before = len(df)
    df = df.drop_duplicates(subset=["property_id", "contract_date", "sale_price"])
    report["dropped_duplicates"] = before - len(df)

    # --- normalise ----------------------------------------------------------
    df["suburb"] = df["suburb"].str.strip().str.upper()
    df["postcode"] = df["postcode"].str.strip().str.zfill(4)
    df["zoning"] = df["zoning"].fillna("UNKNOWN").str.strip().str.upper()
    # Strata lot number present == a unit/apartment. Cleaner than guessing from
    # the purpose field, and it is the only reliable house/unit signal here.
    df["property_type"] = np.where(
        df["strata_lot"].notna() & (df["strata_lot"].str.strip() != ""),
        "unit", "house")
    df["log_price"] = np.log(df["sale_price"])

    # --- nominal transfers the Non-market price flag missed -----------------
    # Relative to the suburb x property-type median, not a flat floor, and not
    # relative to the suburb alone. See config for the reasoning.
    g = df.groupby(["suburb", "property_type"], observed=True)["sale_price"]
    ratio = df["sale_price"] / g.transform("median")
    drop = (ratio < C.NOMINAL_RATIO) & (g.transform("size") >= C.NOMINAL_MIN_CELL)
    report["dropped_nominal_vs_suburb_type_median"] = int(drop.sum())
    df = df[~drop]

    # --- stable identity ----------------------------------------------------
    # The join key must not be a positional index: any change to cleaning would
    # silently renumber every row and invalidate the frozen split.
    before = len(df)
    df = df[df["property_id"].notna() & (df["property_id"].astype(str) != "")]
    report["dropped_missing_property_id"] = before - len(df)
    df["sale_key"] = (df["property_id"].astype(str) + "-"
                      + df["contract_date"].dt.strftime("%Y%m%d") + "-"
                      + df["sale_price"].astype("int64").astype(str))
    return df.drop(columns=["area_raw", "area_type", "strata_lot", "purpose"])


def attach_geography(df, report):
    """D3. No lat/long exists in PSI, and street-level geocoding 1.2M addresses
    is not available to us (see open issue O1), so every row is resolved to its
    suburb centroid and flagged as such -- the documented fallback in plan S3.3.
    The spatial split groups by SA2, which suburb-level precision fully supports.
    """
    pc = pd.read_csv(C.POSTCODES, low_memory=False)
    pc = pc[pc["state"] == "NSW"].copy()
    pc["suburb"] = pc["locality"].astype(str).str.strip().str.upper()
    pc["postcode"] = pc["postcode"].astype(str).str.strip().str.zfill(4)
    pc["lat"] = pd.to_numeric(pc["Lat_precise"], errors="coerce").fillna(
        pd.to_numeric(pc["lat"], errors="coerce"))
    pc["lon"] = pd.to_numeric(pc["Long_precise"], errors="coerce").fillna(
        pd.to_numeric(pc["long"], errors="coerce"))
    # SA2_CODE_2021 arrives as a float, which would stringify as "116021632.0".
    pc["sa2_code"] = (pd.to_numeric(pc["SA2_CODE_2021"], errors="coerce")
                        .astype("Int64").astype(str))
    pc["sa2_name"] = pc["SA2_NAME_2021"].astype(str)
    pc = pc[pc["lat"].notna() & pc["lon"].notna() & pc["lat"].between(-38, -27)]
    ref = (pc.sort_values("id")
             .drop_duplicates(subset=["suburb", "postcode"])
             [["suburb", "postcode", "lat", "lon", "sa2_code", "sa2_name"]])

    out = df.merge(ref, on=["suburb", "postcode"], how="left")

    # Fall back to suburb name alone where the suburb/postcode pair missed.
    miss = out["lat"].isna()
    if miss.any():
        ref2 = (ref.sort_values("suburb").drop_duplicates(subset=["suburb"])
                   .set_index("suburb"))
        for col in ["lat", "lon", "sa2_code", "sa2_name"]:
            out.loc[miss, col] = out.loc[miss, "suburb"].map(ref2[col])

    # A handful of rows resolve a centroid but no SA2. Fall back to a
    # postcode-derived group so every row has a spatial group for GroupKFold.
    no_sa2 = out["sa2_code"].isna() | out["sa2_code"].astype(str).isin(
        ["nan", "<NA>", ""])
    report["sa2_filled_from_postcode"] = int(no_sa2.sum())
    out.loc[no_sa2, "sa2_code"] = "PC" + out.loc[no_sa2, "postcode"].astype(str)
    out.loc[no_sa2, "sa2_name"] = "(postcode fallback)"
    out["sa2_code"] = out["sa2_code"].astype(str)

    out["geocode_quality"] = np.where(out["lat"].notna(), "centroid", "failed")
    report["geocode_matched"] = int((out["geocode_quality"] == "centroid").sum())
    report["geocode_failed"] = int((out["geocode_quality"] == "failed").sum())
    out = out[out["lat"].notna()].copy()

    # Distance to the Sydney CBD, in km (haversine).
    lat1, lon1 = np.radians(C.SYDNEY_CBD)
    lat2, lon2 = np.radians(out["lat"].values), np.radians(out["lon"].values)
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    out["dist_cbd_km"] = 6371.0 * 2 * np.arcsin(np.sqrt(a))
    return out


def main():
    report = {}
    print("D0  fetching inputs ...")
    fetch(C.PSI_URL, C.PSI_ZIP, "NSW PSI sales extract")
    fetch(C.POSTCODES_URL, C.POSTCODES, "suburb centroids + SA2")

    print("D1  reading zipped PSI extract ...")
    df = load_raw()
    print(f"    {len(df):,} residential rows after flag filters")

    print("D2  cleaning ...")
    df = clean(df, report)
    print(f"    {len(df):,} rows after cleaning")

    print("D3  attaching geography ...")
    df = attach_geography(df, report)
    print(f"    {len(df):,} rows geocoded to suburb centroid + SA2")

    df["sale_year"] = df["contract_date"].dt.year.astype("int16")
    df["sale_month"] = df["contract_date"].dt.month.astype("int8")
    df = df.sort_values("contract_date")
    df = df.drop_duplicates(subset=["sale_key"]).set_index("sale_key")
    df.index.name = "row_id"

    df.to_parquet(C.CLEAN_PQ)
    report["rows_final"] = len(df)
    report["date_min"] = str(df["contract_date"].min().date())
    report["date_max"] = str(df["contract_date"].max().date())
    report["pct_with_land_area"] = round(
        float(df["land_area_m2"].notna().mean()) * 100, 1)
    report["n_suburbs"] = int(df["suburb"].nunique())
    report["n_sa2"] = int(df["sa2_code"].nunique())
    (C.PROC / "clean_report.json").write_text(json.dumps(report, indent=2))

    print(f"\nwrote {C.CLEAN_PQ}")
    for k, v in report.items():
        print(f"    {k:<38} {v:>12,}" if isinstance(v, int)
              else f"    {k:<38} {v:>12}")


if __name__ == "__main__":
    main()
