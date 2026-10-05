"""Comps-anchored valuation -- the model adjusts comparables rather than
predicting a price directly.

Why this way round. Measured on 1,500 Sydney-metro houses, the median of five
comparable sales lands at 99.8% of the eventual price, while the model's own
lower bound sits at 73.9%. The comparables are the better-centred estimator.
So we use them as the anchor and use the model only for what it is good at --
judging how much MORE or LESS the subject is worth than each comparable.

    adjusted_comp = comp_sale_price x [ model(subject) / model(comp) ]

Taking a ratio cancels much of the model's level error: if it is 8% low on the
subject it is usually 8% low on a near-identical neighbour too. This is also
how a human valuer works, and -- the point for this project -- it is the
standard NSW underquoting law actually applies. An agent must justify a price
guide against comparable sales, so we assess the guide against the same thing.

The spread of adjusted comps gives an empirical distribution, which is what
lets us quote a percentile instead of a yes/no flag.
"""

import numpy as np
import pandas as pd

import comps as CM
from features import FEATURES

# More comps than we display: 5 is what a workpaper shows, but a percentile
# computed from 5 numbers is far too granular to mean anything.
N_DISTRIBUTION = 25
N_DISPLAY = 5


def _model_log(model, iv, frame, feat_ref):
    X = frame[FEATURES].copy()
    for c in X.columns:
        if str(feat_ref[c].dtype) == "category":
            X[c] = pd.Categorical(X[c], categories=feat_ref[c].cat.categories)
    return model.predict(X, num_iteration=model.best_iteration) + iv["delta"]


def estimate(row, model, iv, art_comps, feat_ref, key=None):
    """Return a comps-anchored estimate and the adjusted-comparable distribution."""
    pool = CM.query(art_comps, row, k=N_DISTRIBUTION, exclude_key=key)
    if pool.empty:
        return None

    # The comparables need the same feature columns as the subject before the
    # model can score them, so pull them from the feature table by key.
    have = pool.index.intersection(feat_ref.index)
    pool = pool.loc[have]
    if len(pool) < 3:
        return None
    comp_feat = feat_ref.loc[pool.index]

    subj_log = float(_model_log(model, iv, pd.DataFrame([row]), feat_ref)[0])
    comp_log = _model_log(model, iv, comp_feat, feat_ref)

    # Ratio adjustment in log space, clipped so one wild comparable cannot
    # dominate: beyond +/-0.7 log (about half to double) the two properties are
    # not really comparable and the adjustment is not trustworthy.
    adj = np.clip(subj_log - comp_log, -0.7, 0.7)
    adjusted = pool["sale_price"].to_numpy(float) * np.exp(adj)

    out = pool.copy()
    out["adjustment_pct"] = (np.exp(adj) - 1) * 100
    out["adjusted_price"] = adjusted
    out = out.sort_values("distance")

    return {
        "estimate": float(np.median(adjusted)),
        "distribution": np.sort(adjusted),
        "n_comps": int(len(adjusted)),
        "table": out.head(N_DISPLAY),
        "all": out,
        "spread_pct": float((np.percentile(adjusted, 75)
                             - np.percentile(adjusted, 25))
                            / np.median(adjusted) * 100),
    }


def guide_percentile(distribution, guide):
    """Where an advertised guide sits among the adjusted comparable sales.

    Returned as a percentage: 4 means the guide is below 96% of the comparable
    evidence. This replaces the binary flag -- no arbitrary threshold, and the
    number degrades gracefully instead of falling off a cliff.
    """
    d = np.asarray(distribution, float)
    return float((d < guide).mean() * 100)
