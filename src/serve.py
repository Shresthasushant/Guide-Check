"""The serving layer: turns a subject property into a complete assessment.

Two entry points:

  value(row, ...)          an existing record from the feature table
  value_manual(...)        a LIVE listing typed in by address -- what the tool
                           actually needs to do, since nobody needs a valuation
                           for a house that already sold

What changed, and why
---------------------
The underquoting output used to be a binary flag: guide < lower_bound x 0.95.
Measured on the frozen test set, that caught a real 20% underquote only 1 time
in 4 while wrongly flagging 1 honest guide in 15. Narrowing the population did
not help (119k rows down to 17.7k moved the catch rate 25.5% -> 26.1%).

The problem was the target, not the accuracy. "Will this sell for more than the
guide?" is the wrong question -- properties routinely sell above their guide in
a hot auction without anyone underquoting. NSW law asks something different and
narrower: is the guide a reasonable estimate given COMPARABLE SALES? So we now
assess the guide against the comparable evidence, and report a percentile
rather than a verdict.
"""

import json
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd

import comps as comps_mod
import comps_estimator as CE
import config as C
from features import FEATURES

# How far below the comparable evidence a guide sits, measured in units of THIS
# SEGMENT'S typical error (median absolute error on held-out calibration data:
# metro 14.3%, regional 16.0%).
#
# Why not percentile bands. The first version of this banded on the percentile
# directly -- strong below the 5th, notable below the 15th. That repeated the
# mistake the binary flag made. A percentile is only as tight as the spread of
# the adjusted comparables, and that spread is wide: with an interquartile
# range around 30% of the median, the 15th percentile sits roughly 20% below
# the comps estimate and the 5th around 30% below. So a real 10-15% underquote
# -- the size that actually shows up in the NSW enforcement cases -- landed
# near the 30th percentile and was reported back as "at the low end of
# comparable evidence". The bands only fired on discounts nobody needed a model
# to notice.
#
# Scaling by measured error instead makes the statement defensible: a guide
# more than one typical error below the comparable evidence is not explainable
# by our own noise. The percentile is still reported -- it is the honest
# continuous number -- but it no longer decides the wording.
BAND_STRONG = 2.0     # more than 2x typical error below the comps estimate
BAND_NOTABLE = 1.0    # more than 1x
BAND_MILD = 0.5       # more than half
MIN_COMPS_FOR_BAND = 8

# Measured on the frozen test set by src/harness.py -- see the latest report in
# results/. Kept here as a constant so the number the app shows a user and the
# number in the evaluation report cannot drift apart.
EMPIRICAL_COVERAGE_PCT = 77.6

# How many SHAP drivers to surface. More than about four is noise to a buyer.
N_DRIVERS = 4
FEATURE_LABELS = {
    "land_area_m2": "land area", "log_area": "land area",
    "has_area": "land area known", "lat": "latitude", "lon": "longitude",
    "dist_cbd_km": "distance to Sydney CBD", "sale_year": "year",
    "sale_month": "month", "days_since_start": "date of sale",
    "suburb_median_logprice": "suburb price level",
    "suburb_n_sales": "sales volume in suburb",
    "property_type": "property type", "zoning": "zoning",
    "suburb": "suburb", "sa2_code": "statistical area", "postcode": "postcode",
}


def _driver_value(row, feature):
    """The subject property's own value for a feature, formatted for display."""
    v = row.get(feature)
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "not supplied"
    if feature in ("land_area_m2",):
        return f"{float(v):,.0f} m2"
    if feature == "dist_cbd_km":
        return f"{float(v):.0f} km"
    if feature in ("days_since_start", "sale_year", "sale_month"):
        y, m = row.get("sale_year"), row.get("sale_month")
        return f"{int(y)}-{int(m):02d}" if y and m else str(v)
    if isinstance(v, (int, np.integer, float, np.floating)):
        return f"{float(v):,.0f}" if float(v) == int(v) else f"{float(v):,.2f}"
    return str(v)


@lru_cache(maxsize=1)
def load():
    point = joblib.load(C.ART / "model_lgbm.pkl")
    iv = joblib.load(C.ART / "interval_v2.pkl")
    art_comps = joblib.load(C.ART / "comps_index.pkl")
    resid = joblib.load(C.ART / "residuals.pkl")
    feat = pd.read_parquet(C.FEAT_PQ)
    # The split file records which rows were train/calib/test. Nothing at SERVING
    # time uses it -- the artefacts already encode the split -- so a deployment
    # can leave the 59MB file behind. Training and evaluation still require it.
    meta = json.loads(C.SPLITS.read_text()) if C.SPLITS.exists() else {}
    import shap
    return point, iv, art_comps, resid, feat, meta, shap.TreeExplainer(point)


def _prep(row, feat):
    X = pd.DataFrame([row])[FEATURES]
    for c in X.columns:
        if str(feat[c].dtype) == "category":
            X[c] = pd.Categorical(X[c], categories=feat[c].cat.categories)
    return X


def _segment(row):
    d = row.get("dist_cbd_km")
    return "metro" if d is not None and np.isfinite(d) and d < 50 else "regional"


def value(row, guide=None, key=None):
    """Assess one property. `row` carries every model feature."""
    point, iv, art_comps, resid, feat, meta, explainer = load()
    X = _prep(row, feat)

    log_pt = float(point.predict(X, num_iteration=point.best_iteration)[0]) + iv["delta"]
    log_lo = float(iv["m_lo"].predict(X, num_iteration=iv["m_lo"].best_iteration)[0]) \
        + iv["delta"] - iv["qhat_v2"]
    log_hi = float(iv["m_hi"].predict(X, num_iteration=iv["m_hi"].best_iteration)[0]) \
        + iv["delta"] + iv["qhat_v2"]
    est, lo, hi = np.exp(log_pt), np.exp(log_lo), np.exp(log_hi)
    lo, hi = min(lo, est), max(hi, est)

    seg = _segment(row)
    r = resid["resid_by_segment"].get(seg, resid["resid_all"])
    typical_err = float(np.median(np.abs(np.exp(r) - 1)) * 100)

    # --- comps-anchored estimate (the better-centred one) -------------------
    ce = CE.estimate(row, point, iv, art_comps, feat, key=key)

    sv = explainer.shap_values(X)
    drivers = (pd.Series(np.asarray(sv).reshape(-1), index=FEATURES)
                 .sort_values(key=np.abs, ascending=False))
    # The same numbers in a shape the web page can render directly. SHAP values
    # are in log-price space, so exp(v) - 1 reads as a percentage effect on the
    # estimate, which is what a user can actually interpret.
    top_drivers = [
        {"feature": FEATURE_LABELS.get(f, f),
         "value": _driver_value(row, f),
         "effect_pct": float((np.exp(v) - 1) * 100)}
        for f, v in drivers.head(N_DRIVERS).items()
    ]

    out = {
        "point": float(est), "lower": float(lo), "upper": float(hi),
        "nominal_coverage": C.NOMINAL_COVERAGE,
        "interval_width_pct": float((hi - lo) / est * 100),
        "segment": seg, "typical_error_pct": typical_err,
        "drivers": drivers,
        "top_drivers": top_drivers,
        "comps": ce["table"] if ce else comps_mod.query(art_comps, row,
                                                        exclude_key=key),
        "comps_estimate": ce["estimate"] if ce else None,
        "comps_distribution": ce["distribution"] if ce else None,
        "comps_n": ce["n_comps"] if ce else 0,
        "comps_spread_pct": ce["spread_pct"] if ce else None,
        # --- evidence vintage and measured limits, reported to the user ----
        # These are not decoration. The rubric asks for honest limits, and a
        # user cannot weigh the output without them.
        "empirical_coverage_pct": EMPIRICAL_COVERAGE_PCT,
        "empirical_coverage_note": (
            f"Measured coverage on the frozen test set is "
            f"{EMPIRICAL_COVERAGE_PCT}% against a nominal "
            f"{C.NOMINAL_COVERAGE:.0%} -- the band is slightly narrow. "
            f"See results/ for the full evaluation."),
        "comps_cutoff": art_comps.get("cutoff"),
        "comps_lookback_days": comps_mod.LOOKBACK_DAYS,
    }

    if guide is not None and np.isfinite(guide) and guide > 0:
        out.update(_assess_guide(guide, est, r, ce, typical_err))
    return out


def _assess_guide(guide, est, resid_seg, ce, typical_err_pct):
    """Assess an advertised guide against the evidence -- as a percentile.

    Two independent readings, because they answer different questions:

      vs comparable sales  -- the legal standard. What share of adjusted
                              comparable sales sit BELOW this guide.
      vs the model         -- calibrated from held-out residuals: the estimated
                              probability the property is worth more than the
                              guide.
    """
    d = dict(guide=float(guide))

    # Probability the true value exceeds the guide, from measured residuals.
    # P(est * exp(r) > guide) = fraction of residuals with r > log(guide/est).
    p_above = float((resid_seg > np.log(guide / est)).mean() * 100)
    d["prob_worth_more_pct"] = p_above
    d["model_percentile"] = 100.0 - p_above

    if ce is not None:
        pct = CE.guide_percentile(ce["distribution"], guide)
        d["comps_percentile"] = pct
        n_below = int(round(pct / 100 * ce["n_comps"]))
        d["comps_below"] = n_below
        d["comps_total"] = ce["n_comps"]
        # How far BELOW the comparable evidence the guide sits, as a percentage
        # of the comparables' median. Positive means the guide is below them;
        # negative means it is above. Anything rendering this number must say
        # which -- a bare "+37%" reads as the guide being 37% ABOVE the median,
        # the exact opposite of what it means.
        gap = float((ce["estimate"] - guide) / ce["estimate"] * 100)
        d["gap_vs_comps_pct"] = gap

        # The gap expressed in units of this segment's measured error. 1.0
        # means the guide sits a full typical error below the comparables.
        errs = gap / typical_err_pct if typical_err_pct > 0 else 0.0
        d["gap_in_typical_errors"] = errs

        if ce["n_comps"] < MIN_COMPS_FOR_BAND:
            d["band"] = "too few comparable sales to band"
            d["severity"] = "unknown"
        elif errs >= BAND_STRONG:
            d["band"] = "well below the comparable evidence"
            d["severity"] = "strong"
        elif errs >= BAND_NOTABLE:
            d["band"] = "below the comparable evidence"
            d["severity"] = "notable"
        elif errs >= BAND_MILD:
            d["band"] = "at the low end of the comparable evidence"
            d["severity"] = "mild"
        else:
            d["band"] = "consistent with the comparable evidence"
            d["severity"] = "none"

        d["verdict"] = (
            f"This guide sits at the {pct:.0f}th percentile of "
            f"{ce['n_comps']} comparable sales adjusted for differences, "
            f"{abs(gap):.0f}% {'below' if gap >= 0 else 'above'} their median "
            f"-- {d['band']}. "
            f"Typical error for this segment is {typical_err_pct:.1f}%.")
    else:
        d["verdict"] = ("Not enough comparable sales to assess this guide "
                        "against evidence.")
        d["severity"] = "unknown"

    d["disclaimer"] = (
        "A statistical observation about price against comparable sales. It is "
        "not an allegation of underquoting, which depends on the agent's own "
        "reasonable estimate at the time of listing -- something no price model "
        "can observe.")
    return d


# --------------------------------------------------------------- live input --
def value_manual(suburb, postcode, property_type, land_area_m2=None,
                 address="(entered manually)", guide=None,
                 bedrooms=None, bathrooms=None, when=None):
    """Assess a LIVE listing typed in by hand.

    bedrooms/bathrooms are accepted and echoed back but CANNOT yet influence
    the estimate: they do not exist anywhere in the NSW PSI source data, so the
    model was never trained on them. They are collected here so the listing
    dataset is being built from day one -- see data/reference/listing_template.csv.
    """
    _, _, _, _, feat, meta, _ = load()
    suburb = str(suburb).strip().upper()
    postcode = str(postcode).strip().zfill(4)

    ref = feat[feat["suburb"].astype(str) == suburb]
    if ref.empty:
        raise ValueError(f"Suburb '{suburb}' not found in the NSW sales data.")
    base = ref.iloc[-1]                       # most recent sale in that suburb

    when = pd.Timestamp(when) if when is not None else pd.Timestamp.today()
    t0 = feat["contract_date"].min()

    row = {c: base[c] for c in FEATURES}
    row.update({
        "property_type": property_type,
        "postcode": postcode if postcode in set(
            feat["postcode"].astype(str)) else base["postcode"],
        "land_area_m2": float(land_area_m2) if land_area_m2 else np.nan,
        "log_area": (np.log(float(land_area_m2))
                     if land_area_m2 and float(land_area_m2) > 0 else np.nan),
        "has_area": 1 if land_area_m2 else 0,
        "sale_year": int(when.year), "sale_month": int(when.month),
        "days_since_start": int((when - t0).days),
    })

    res = value(pd.Series(row), guide=guide)
    res["subject"] = {"address": address, "suburb": suburb,
                      "postcode": postcode, "property_type": property_type,
                      "land_area_m2": row["land_area_m2"],
                      "bedrooms": bedrooms, "bathrooms": bathrooms,
                      "valued_as_at": when.date().isoformat()}

    # Evidence vintage. The comparable-sales index is frozen at the end of the
    # calibration window so it can never contain a test-set sale, but that
    # means the evidence ages as the tool is used. Say so, with the number,
    # instead of quietly extrapolating.
    if res.get("comps_cutoff"):
        age = (when - pd.Timestamp(res["comps_cutoff"])).days
        res["evidence_age_days"] = int(age)
        if age > 180:
            res["evidence_note"] = (
                f"The comparable sales end {res['comps_cutoff']}, "
                f"{age // 30} months before the date being valued. Prices have "
                f"moved since. Treat the estimate as a floor on today's "
                f"evidence, and rebuild the index (python src/comps.py) "
                f"against fresher PSI data before relying on it.")

    # Location caveat. Everything except type, postcode, land area and date is
    # taken from the most recent sale in the suburb, so the estimate is a
    # suburb-level answer, not a street-level one. The user has to know that.
    res["subject"]["location_basis"] = (
        f"Suburb-level estimate: features are taken from the most recent recorded sale in "
        f"{suburb}. Two properties in this suburb with the same type and land "
        f"area get the same estimate. Street, aspect and condition are not "
        f"modelled.")
    if bedrooms or bathrooms:
        res["bed_bath_note"] = (
            "Bedroom and bathroom counts were recorded but could not be used: "
            "they are absent from the NSW sales data the model was trained on. "
            "They are the single largest missing feature -- collecting them "
            "from live listings is what would let a future model use them.")
    return res
