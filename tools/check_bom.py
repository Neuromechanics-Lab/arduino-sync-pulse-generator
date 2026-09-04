#!/usr/bin/env python3
"""
check_bom.py - report what the BOM is still missing.

A bill of materials with blank prices and no suppliers is not a bill of
materials, and a fabricated one is worse than a blank. This prints exactly
which fields are unfilled so the gaps stay visible rather than being
discovered at submission.

    python3 tools/check_bom.py
"""
import csv
import sys
from pathlib import Path

BOM = Path(__file__).resolve().parent.parent / "docs" / "BOM.csv"
NEEDED = ["mpn", "supplier", "unit_price", "price_date"]


def main():
    rows = list(csv.DictReader(BOM.open()))
    incomplete, verify = [], []
    for r in rows:
        missing = [f for f in NEEDED if not (r.get(f) or "").strip()]
        if missing:
            incomplete.append((r["ref"], r["item"], missing))
        if "VERIFY" in (r.get("notes") or ""):
            verify.append((r["ref"], r["notes"]))

    n = len(rows)
    print(f"{BOM.name}: {n} line items")
    print(f"  complete: {n - len(incomplete)}")
    print(f"  incomplete: {len(incomplete)}")
    if incomplete:
        print("\nMissing sourcing data (needed before submission):")
        for ref, item, miss in incomplete:
            print(f"  {ref:<10} {item[:34]:<36} {', '.join(miss)}")
    if verify:
        print("\nFlagged VERIFY — measure before ordering or printing:")
        for ref, note in verify:
            print(f"  {ref:<10} {note}")

    total = 0.0
    priced = 0
    for r in rows:
        p = (r.get("unit_price") or "").strip()
        if p:
            try:
                total += float(p) * int(r["qty"])
                priced += 1
            except ValueError:
                pass
    print(f"\nPriced items: {priced}/{n}")
    if priced:
        print(f"Subtotal of priced items: {total:.2f}")
    if priced < n:
        print("Total build cost: NOT AVAILABLE until every line is priced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
