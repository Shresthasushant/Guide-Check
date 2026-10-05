# What is actually in the NSW PSI data

Profiled from the full extract downloaded 16 Sep 2026: `archive.zip`, 74 MB,
containing `nsw-property-sales-data-updated20260914.csv` (389 MB, 33 columns,
**1,508,054 rows**), written 2026-09-14 05:02 — matching the mirror's claim of a
daily refresh around 5am.

## Authenticity

The schema is the official NSW Valuer General PSI layout, unchanged: District
code, Property ID, Valuation number, Sale counter, Zoning, Dealing number,
Property legal description. Scale matches NSW: 4,330 suburbs, 623 postcodes,
144 district codes, median sale $793,000.

The mirror is an **independent project, not official**. It republishes
government `.DAT` files as CSV, and has already removed zero and missing
prices. Recommended check: pull one LGA from the official portal and verify a
few hundred rows match.

## Coverage

Date range reads 1990→2026 but is misleading — only ~33,000 rows predate 2019,
against 164k–255k per year afterwards. Effectively **2019 → Aug 2026**.

| | Rows |
|---|---|
| Total | 1,508,054 |
| Residential (`Primary purpose = Residence`) | 1,286,041 (85.3%) |
| Residential since 2019 | 1,236,024 |
| **After our cleaning** | **1,249,163** |

## Three traps that are not in the original plan

**1. `Area type (source)` is M or H — metres or hectares.** 96,742 rows (6.4%)
are in hectares. Treating them as m² is a 10,000× error that silently wrecks
every area feature and the median $/m² baseline. Our pipeline converts 49,683
such rows in the residential subset.

**2. The `Non-market price flag` barely works.** It flags only **687 rows in
1.5M**, yet there are **5,198 sales under $10,000**. Relying on the flag alone
leaves obvious nominal transfers in the training data.

A flat price floor cannot fix this either: $110,000 is a real sale in rural NSW
and an obvious family transfer in Darling Point, where the house median is
$8.1M. We cut relative to the **suburb × property-type** median instead —
below 15%, where that cell has ≥30 sales. This removes 3,272 rows, including a
$806,250 "sale" in Vaucluse against a $7.65M median.

It must be within property type. On suburb alone, the same rule deletes a
genuine $1.2M Point Piper unit, because Point Piper's median is set by
waterfront houses.

**3. `Part interest flag`** marks 5,374 sales (0.4%) where only a share of the
property changed hands, so the price is not the value of the whole property.
The original plan does not mention this column. We drop them.

## Missing data — open issue O4 confirmed

| | Missing land area |
|---|---|
| All rows | 21.3% |
| Residential | 23.1% |
| **Strata (units)** | **60.1%** |

Units are 37.8% of residential sales. The median $/m² baseline therefore falls
back to a suburb median price for **26.6% of test rows**.

## Confirmed by absence

- **No bedrooms or bathrooms.** Not a single column (open issue O5 confirmed).
- **No latitude or longitude.** Only address text (open issue O1 confirmed).
  Geocoding 1.2M addresses via Nominatim at ~1 request/second would take over
  14 days and breach its usage policy. We resolve to suburb centroids from an
  offline reference instead, which also supplies the ABS SA2 code used as the
  spatial grouping key.

## Free features the plan did not budget for

- **`Zoning`** (R2, R1, R3, RU1 …) — populated on 61.6% of rows. Residential
  density zoning is a genuine price signal and is now a model feature.
- **`Strata lot number`** — a clean house/unit discriminator, better than
  inferring type.
- **`Settlement date`** alongside contract date.
- **`Primary purpose (normalised)`** — already standardised, so part of the
  plan's "standardise property type" step is done for us.

## Duplicates

29,739 rows (2.0%) duplicate on property + date + price. Our pipeline drops
23,219 within the residential subset.

## Cleaning ledger

From 1,281,711 residential rows after flag filters:

| Step | Rows dropped |
|---|---|
| Hectare→m² conversions applied | 49,683 (converted, not dropped) |
| Missing contract date | 259 |
| Price outside $50k–$50M | 4,842 |
| Nominal vs suburb × type median | 3,272 |
| Missing suburb or postcode | 852 |
| Duplicates | 23,219 |
| Missing property_id | 1 |
| Geocoding failed | 61 |
| **Final** | **1,249,163** |
