"""Evaluate the guide assessment against REAL labelled cases.

Why this replaces the simulation. We were measuring the flag by pretending a
guide sat at X% of the eventual sale price. That cannot work, because selling
above the guide is normal auction behaviour, not underquoting. Simulated
discounts therefore conflate market heat with misconduct, and no threshold
tuned against them means anything.

The only sound evaluation is a labelled set: listings where a human has
judged, from the evidence available at the time, whether the guide was
defensible. NSW Fair Trading publishes enforcement outcomes; add clean
listings as negatives. Twenty of each beats a million simulated ones.

    1. python src/hardcases.py --template     writes a CSV to fill in
    2. fill it in                             (this is manual work, by design)
    3. python src/hardcases.py                scores it

Until the file has real rows this prints the template and exits. That is the
honest state: the metric does not exist yet.
"""

import sys

import numpy as np
import pandas as pd

import config as C
import serve

CASES = C.REF / "hardcases.csv"

COLUMNS = ["case_id", "address", "suburb", "postcode", "property_type",
           "land_area_m2", "bedrooms", "bathrooms", "guide_low", "guide_high",
           "listed_date", "sold_price", "sold_date", "label", "source", "notes"]

TEMPLATE = pd.DataFrame([
    {"case_id": "EXAMPLE-1", "address": "1 Example St", "suburb": "MUDGEE",
     "postcode": "2850", "property_type": "house", "land_area_m2": 600,
     "bedrooms": 3, "bathrooms": 1, "guide_low": 500000, "guide_high": 550000,
     "listed_date": "2026-03-01", "sold_price": 720000,
     "sold_date": "2026-03-28", "label": "underquoted",
     "source": "NSW Fair Trading enforcement / media / own judgement",
     "notes": "DELETE THIS ROW. label must be underquoted | defensible"},
])


def write_template():
    CASES.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE.to_csv(CASES, index=False)
    print(f"wrote template to {CASES}")
    print("\nFill it in with real cases. Guidance:")
    print("  label = 'underquoted'  the guide was not defensible on the")
    print("                         comparable sales available when listed")
    print("  label = 'defensible'   the guide was reasonable, even if the")
    print("                         property later sold well above it")
    print("\nThe second kind matters MORE than the first. Without genuine")
    print("defensible-but-sold-high cases, the false-positive rate is")
    print("unmeasurable and the tool cannot be trusted.")


def score():
    df = pd.read_csv(CASES)
    df = df[df["case_id"].astype(str).str.upper() != "EXAMPLE-1"]
    if df.empty:
        print(f"{CASES} has no real cases yet -- only the example row.")
        print("The guide assessment therefore has NO validated accuracy.")
        print("Run with --template for the format, then collect real cases.")
        return None

    rows = []
    for _, c in df.iterrows():
        guide = float(c.get("guide_low") or c.get("guide_high") or np.nan)
        try:
            r = serve.value_manual(
                suburb=c["suburb"], postcode=c["postcode"],
                property_type=c["property_type"],
                land_area_m2=c.get("land_area_m2"),
                address=c.get("address", ""), guide=guide,
                bedrooms=c.get("bedrooms"), bathrooms=c.get("bathrooms"),
                when=c.get("listed_date"))
        except Exception as e:
            print(f"  skip {c['case_id']}: {e}")
            continue
        rows.append({
            "case_id": c["case_id"], "label": c["label"],
            "guide": guide,
            "comps_percentile": r.get("comps_percentile"),
            "gap_in_typical_errors": r.get("gap_in_typical_errors"),
            "severity": r.get("severity"),
            "comps_estimate": r.get("comps_estimate"),
            "sold_price": c.get("sold_price"),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        print("no cases could be scored")
        return None

    print(out.to_string(index=False))

    # Sweep the percentile cutoff rather than fixing one -- with few cases the
    # honest output is the trade-off, not a single headline number.
    pos = out[out["label"] == "underquoted"]
    neg = out[out["label"] == "defensible"]
    if len(pos) and len(neg):
        print(f"\n{len(pos)} underquoted, {len(neg)} defensible cases")
        print("\n  percentile cutoff   caught      wrongly flagged")
        print("  -----------------   ---------   ----------------")
        for cut in (2, 5, 10, 15, 20, 30, 40):
            tp = (pos["comps_percentile"] <= cut).mean() * 100
            fp = (neg["comps_percentile"] <= cut).mean() * 100
            print(f"  {cut:>14}th   {tp:>6.0f}%      {fp:>10.0f}%")

        # The band the tool actually reports is set on this quantity, not on
        # the percentile, so sweep it too -- otherwise we would be measuring a
        # cutoff the product does not use.
        print("\n  gap (typical errors)   caught      wrongly flagged")
        print("  --------------------   ---------   ----------------")
        for cut in (0.5, 0.75, 1.0, 1.5, 2.0, 2.5):
            tp = (pos["gap_in_typical_errors"] >= cut).mean() * 100
            fp = (neg["gap_in_typical_errors"] >= cut).mean() * 100
            print(f"  {cut:>17.2f}x   {tp:>6.0f}%      {fp:>10.0f}%")
        print("\nWith this few cases these rates carry wide error bars. "
              "Report them as indicative, with the counts alongside.")
    else:
        print("\nNeed BOTH labels to measure a trade-off. "
              f"Have {len(pos)} underquoted and {len(neg)} defensible.")
    return out


if __name__ == "__main__":
    if "--template" in sys.argv or not CASES.exists():
        write_template()
    else:
        score()
