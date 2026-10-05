"""Central configuration. Every tunable the pipeline uses lives here so the run
is auditable and reproducible (plan rule 4, open issue O7)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
REF = DATA / "reference"
PROC = DATA / "processed"
ART = ROOT / "artefacts"
PRED = ROOT / "predictions"
RESULTS = ROOT / "results"

for _p in (RAW, REF, PROC, ART, PRED, RESULTS):
    _p.mkdir(parents=True, exist_ok=True)

# --- inputs -----------------------------------------------------------------
PSI_ZIP = RAW / "psi.zip"
PSI_URL = "https://nswpropertysalesdata.com/data/archive.zip"
POSTCODES = REF / "australian_postcodes.csv"
POSTCODES_URL = ("https://raw.githubusercontent.com/matthewproctor/"
                 "australianpostcodes/master/australian_postcodes.csv")

# --- artefacts --------------------------------------------------------------
CLEAN_PQ = PROC / "sales_clean.parquet"
FEAT_PQ = PROC / "sales_features.parquet"
SPLITS = PROC / "splits.json"

SEED = 42

# --- cleaning decisions (open issue O7 -- these were unchosen in the plan) ---
# Keep only residential sales; this is a residential valuation model.
KEEP_PURPOSE = "Residence"
# Token/nominal transfers. The Non-market price flag catches only 687 rows in
# 1.5M, so a price floor is required as well as the flag -- see docs/DATA-REPORT.md.
MIN_PRICE = 50_000
MAX_PRICE = 50_000_000
# Winsorise log price at these quantiles, computed on the training window only.
WINSOR_LO, WINSOR_HI = 0.005, 0.995
# Nominal-transfer filter. A flat price floor cannot work: $110k is a real sale
# in rural NSW and an obvious family transfer in Darling Point (house median
# $8.1M). So we cut relative to the suburb x property-type median, and only
# where that cell has enough sales for its median to be trustworthy.
# Must be within property type -- on suburb alone this deletes genuine cheap
# units in suburbs whose median is set by waterfront houses.
NOMINAL_RATIO = 0.15
NOMINAL_MIN_CELL = 30
# Area sanity bounds, in square metres, after the hectare conversion.
MIN_AREA, MAX_AREA = 20.0, 100_000.0

# --- frozen split ------------------------------------------------------------
# Temporal: train on older sales, calibrate on a middle window, test on newest.
# Never predict the past from the future (plan S3.5).
TRAIN_END = "2025-01-01"   # train:  contract_date <  TRAIN_END
CALIB_END = "2025-10-01"   # calib:  TRAIN_END <= d < CALIB_END
# test:   contract_date >= CALIB_END
GROUP_KEY = "sa2_code"     # spatial grouping for GroupKFold inside training
N_FOLDS = 5

# --- model ------------------------------------------------------------------
NOMINAL_COVERAGE = 0.80
QUANTILES = (0.10, 0.90)
N_COMPS = 5                # comparable sales returned per subject property

SYDNEY_CBD = (-33.8688, 151.2093)
