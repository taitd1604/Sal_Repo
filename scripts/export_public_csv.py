#!/usr/bin/env python3
"""Generate a sanitized CSV for sharing only limited shift info."""

from __future__ import annotations

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "shifts.csv"
DESTINATION = REPO_ROOT / "data" / "shifts_public.csv"

# Columns that are safe to expose on the public dashboard
PUBLIC_COLUMNS = [
    "date",
    "event_type",
    "actual_end_time",
    "ot_minutes",
    "ot_pay",
    "total_pay",
]


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source file not found: {SOURCE}")

    with SOURCE.open("r", encoding="utf-8") as src, DESTINATION.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=PUBLIC_COLUMNS)
        writer.writeheader()
        for row in reader:
            if not row.get("date"):
                continue
            sanitized = {column: row.get(column, "") for column in PUBLIC_COLUMNS}
            writer.writerow(sanitized)

    print(f"Wrote sanitized data to {DESTINATION.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
