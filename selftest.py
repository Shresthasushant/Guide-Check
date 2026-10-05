"""One runnable check that the deployed tool still behaves.

    python selftest.py

Not a substitute for the evaluation in results/ -- that measures accuracy on
119,095 held-out sales. This checks the five demo cases in
data/reference/demo-inputs.csv still land in the band the build guide claims, that
the band logic is monotone (a lower guide can never be assessed as safer), and
that a bad suburb is rejected rather than silently scored.

Takes about a minute, most of it loading the model.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import serve  # noqa: E402

CASES = Path(__file__).resolve().parent / "data" / "reference" / "demo-inputs.csv"


def run_case(c):
    return serve.value_manual(
        suburb=c["suburb"], postcode=c["postcode"],
        property_type=c["property_type"],
        land_area_m2=float(c["land_area_m2"]) if c["land_area_m2"] else None,
        guide=float(c["guide"]))


def main():
    rows = list(csv.DictReader(CASES.open(encoding="utf-8")))
    assert rows, f"no demo cases in {CASES}"

    for c in rows:
        r = run_case(c)
        got, want = r["severity"], c["expected_severity"]
        assert got == want, (
            f"{c['case_id']}: expected severity '{want}', got '{got}'. "
            f"If the comparable-sales index was rebuilt this is expected -- "
            f"re-record the demo table in the build guide.")
        assert r["comps_n"] >= 3, f"{c['case_id']}: only {r['comps_n']} comparables"
        assert r["comps_estimate"] > 0
        assert r["lower"] <= r["point"] <= r["upper"], "interval does not bracket the estimate"
        assert 0 <= r["comps_percentile"] <= 100
        print(f"  ok  {c['case_id']:<16} {got:<8} "
              f"percentile {r['comps_percentile']:>5.1f}  "
              f"gap {r['gap_in_typical_errors']:>5.2f}x typical error")

    # Monotonicity: cutting the guide can only make the assessment more severe.
    # If this ever fails the banding is broken, whatever the accuracy numbers say.
    base = rows[0]
    order = ["none", "mild", "notable", "strong"]
    prev = -1
    for guide in (2_000_000, 1_500_000, 1_000_000, 600_000):
        r = serve.value_manual(suburb=base["suburb"], postcode=base["postcode"],
                               property_type=base["property_type"],
                               land_area_m2=float(base["land_area_m2"]),
                               guide=guide)
        rank = order.index(r["severity"])
        assert rank >= prev, (
            f"severity went backwards at ${guide:,}: {r['severity']}")
        prev = rank
        print(f"  ok  monotone  ${guide:>9,} -> {r['severity']}")

    # A suburb we do not hold must be refused, never guessed at.
    try:
        serve.value_manual(suburb="NOT A REAL SUBURB", postcode="2000",
                           property_type="house", guide=500_000)
        raise AssertionError("unknown suburb was scored instead of rejected")
    except ValueError:
        print("  ok  unknown suburb rejected")

    print("\nall checks passed")


if __name__ == "__main__":
    main()
