"""Harness gate (plan Week 2): fabricate a predictions file with KNOWN error
and interval coverage, so we can prove the harness measures them correctly
before any real model exists.

We inject a deliberate +12% bias and a band engineered to cover ~70% of cases
against a nominal 80%. A correct harness must report roughly those numbers --
if it reports 80% coverage here, the harness is lying and would have lied about
the real model too.
"""

import json

import numpy as np
import pandas as pd

import config as C

RNG = np.random.default_rng(C.SEED)
TRUE_BIAS = 0.12          # predictions are 12% high on average
TARGET_COVERAGE = 0.70    # band deliberately too narrow for a nominal 80%


def main():
    meta = json.loads(C.SPLITS.read_text())
    src = C.CLEAN_PQ if C.CLEAN_PQ.exists() else C.FEAT_PQ
    df = pd.read_parquet(src, columns=["sale_price"])
    df.index.name = "row_id"
    test = df.loc[meta["test_ids"]].reset_index()

    y = test["sale_price"].to_numpy(float)
    noise = RNG.normal(0, 0.15, len(y))
    y_pred = y * (1 + TRUE_BIAS) * np.exp(noise)

    # Build a band around y_pred that contains y for ~TARGET_COVERAGE of rows.
    half = np.abs(np.log(y / y_pred))
    k = np.quantile(half, TARGET_COVERAGE)
    out = pd.DataFrame({
        "row_id": test["row_id"],
        "arm": "fake_probe",
        "y_pred": y_pred,
        "y_lower": y_pred * np.exp(-k),
        "y_upper": y_pred * np.exp(k),
        "nominal_coverage": C.NOMINAL_COVERAGE,
        "model_version": "v0-fake",
        "run_timestamp": pd.Timestamp.now().isoformat(),
    })
    p = C.PRED / "fake_probe.csv"
    out.to_csv(p, index=False)

    print(f"wrote {p}  ({len(out):,} rows)")
    print(f"  injected bias            {TRUE_BIAS:+.0%}")
    print(f"  engineered coverage      {TARGET_COVERAGE:.0%} against a nominal "
          f"{C.NOMINAL_COVERAGE:.0%}")
    print("  the harness must recover approximately these numbers.")


if __name__ == "__main__":
    main()
