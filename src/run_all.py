"""Reproduce the whole project with one command.

    python src/run_all.py

Runs every stage in dependency order and stops at the first failure. The split
freeze is respected: if data/processed/splits.json already exists it is NOT
overwritten, so re-running cannot quietly change the test set.

Expect roughly 15-25 minutes on a laptop, dominated by the five ablation
retrains. Add --skip-ablation to cut that.
"""

import subprocess
import sys
import time
from pathlib import Path

import config as C

HERE = Path(__file__).resolve().parent

STAGES = [
    ("D1-D3  ingest, clean, geocode", "clean.py"),
    ("D5     freeze train/calib/test split", "split.py"),
    ("D4     feature engineering", "features.py"),
    ("H1     harness gate on fabricated predictions", "make_fake_predictions.py"),
    ("M1     baselines", "baselines.py"),
    ("M2     point model: LightGBM vs XGBoost", "train_point.py"),
    ("M3     quantile + conformal intervals", "train_interval.py"),
    ("v2     market-drift correction", "improve_v2.py"),
    ("M4     comparable-sales index", "comps.py"),
    ("M5     calibration residual distribution", "residuals.py"),
    ("ABL    feature-group ablations", "ablation.py"),
]


def main(skip_ablation=False):
    t_all = time.time()
    for label, script in STAGES:
        if skip_ablation and script == "ablation.py":
            print(f"\n=== SKIP  {label}\n")
            continue
        print(f"\n{'='*72}\n=== {label}\n{'='*72}")
        t0 = time.time()
        r = subprocess.run([sys.executable, str(HERE / script)], cwd=HERE)
        if r.returncode != 0:
            print(f"\nFAILED at {script} (exit {r.returncode})")
            return r.returncode
        print(f"--- {script} done in {time.time()-t0:.0f}s")

    # The fabricated probe proves the harness, but must not pollute the real
    # results table.
    (C.PRED / "fake_probe.csv").unlink(missing_ok=True)

    print(f"\n{'='*72}\n=== SCORE  everything on the frozen test set\n{'='*72}")
    subprocess.run([sys.executable, str(HERE / "harness.py")], cwd=HERE)
    print(f"\nTOTAL {time.time()-t_all:.0f}s")
    print(f"Results in {C.RESULTS}")
    print("Demo:  streamlit run app/streamlit_app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main("--skip-ablation" in sys.argv))
