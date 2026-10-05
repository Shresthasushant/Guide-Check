# Guide Check

**Is this advertised NSW price guide defensible against comparable sales?**

FIN80031 AI for Finance and Accounting — Assessment 2.
Sushant Shrestha (106046013), Shrey Patel (105225918), Dheeransh Jain (105311053)

Type a suburb, a property type, a land area and an advertised guide. The tool scores the
property with a LightGBM model trained on 1,249,163 NSW Valuer General sales, pulls the 25
nearest recent comparable sales, adjusts each one to the subject property using the model's
ratio between them, and reports where the guide sits in that adjusted distribution — with the
comparables shown, the drivers shown, and its own measured error shown.

## Run it

```
pip install -r requirements.txt     # Python 3.11.15, versions pinned
python app.py                       # then open http://127.0.0.1:5000
```

First load takes 30–45 seconds (1.25M-row feature table plus the SHAP explainer) and needs
about 1.2 GB of memory. Every check after that is fast.

```
python selftest.py                  # check the five demo cases still band correctly
python src/harness.py               # rescore the frozen test set (~1 min)
python src/run_all.py               # rebuild everything from raw data (15-25 min)
```

## Evidence and documentation

| What | Where |
|---|---|
| Demo cases, with the band each should land in | [`data/reference/demo-inputs.csv`](data/reference/demo-inputs.csv) |
| Evaluation results, every arm | [`results/`](results/) |
| Per-row predictions, every arm (gzipped) | [`predictions/`](predictions/) |
| Cleaning decisions and row counts | [`docs/DATA-REPORT.md`](docs/DATA-REPORT.md) |
| Front-end structure, palette, charts | [`docs/DESIGN-NOTES.md`](docs/DESIGN-NOTES.md) |
| Evaluation code | [`src/harness.py`](src/harness.py), [`src/ablation.py`](src/ablation.py), [`src/hardcases.py`](src/hardcases.py) |

The four assessed documents for Swinburne FIN80031 Assessment 2 are submitted separately to
the university and are not tracked in this repository.

## Headline numbers

| | |
|---|---|
| Test set | 119,095 sales from 2025-10-01, frozen before any modelling |
| Point accuracy | 25.81% MAPE, versus 41.33% for a suburb-median baseline — 37.5% better |
| Interval | nominal 80%, **measured 77.6%** — the measured figure is what the app displays |
| Most valuable feature group | temporal (+4.77pp MAPE when removed) |
| Guide assessment accuracy | **not yet validated** — see Limits in document 3 |

## What is in here

```
app.py                  Flask backend: the five pages, /api/suburbs, POST /api/check
selftest.py             one-command check on the shipped demo cases
static/*.html           the site: what it does, how to use it, the tool, how it
                        works, limits (plus a 404 page)
static/assets/          app.css, app.js (shared chrome), check.js (the tool and
                        its charts), favicon.svg
docs/DESIGN-NOTES.md    front-end structure, the validated palette, the charts
src/serve.py            scoring, banding, the guide assessment
src/comps*.py           comparable-sales index and the comps-anchored estimate
src/features.py         feature engineering (fitted on train only, no leakage)
src/config.py           every tunable and every cleaning decision, in one file
src/clean.py split.py   raw PSI to a frozen train/calib/test split
src/train_*.py          point model, quantile + conformal intervals, drift correction
src/harness.py          the evaluation harness
src/ablation.py         feature-group ablations
src/hardcases.py        labelled-case scoring (template supplied, cases not yet collected)
src/make_fake_predictions.py   proves the harness measures error correctly
src/run_all.py          rebuild the whole project in dependency order
artefacts/              trained models and indexes
data/processed/         feature table and the frozen split
results/ predictions/   evaluation appendices (predictions gzipped)
docs/DATA-REPORT.md     cleaning decisions and row counts
data/reference/         demo cases for selftest.py, labelled hard-case template
render.yaml Procfile    deployment config for Render (see the build guide)
deploy/vm-setup.sh      one-shot VM install from the zip, no Git needed
runtime.txt .gitignore  Python version pin and repository hygiene
```

Not legal or valuation advice. The output is a statistical observation about a price against
comparable sales, not an allegation of underquoting — that depends on the agent's own
reasonable estimate at the time of listing, which no price model can observe.
