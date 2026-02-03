#!/usr/bin/env python3
"""Recompute OT pay for existing shifts.csv rows.

Rule:
- OT is paid per 15-minute block (rounded up)
- Each block is 50,000 VND

This script updates:
- ot_pay
- total_pay
- net_income
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "shifts.csv"

OT_BLOCK_MINUTES = 15
OT_BLOCK_PAY = 50_000


def _parse_int(value: str, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def _calculate_ot_pay(ot_minutes: int) -> int:
    if ot_minutes <= 0:
        return 0
    blocks = int(math.ceil(ot_minutes / OT_BLOCK_MINUTES))
    return blocks * OT_BLOCK_PAY


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source file not found: {SOURCE}")

    with SOURCE.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("CSV header is missing.")

        required_columns = {"base_pay", "ot_minutes", "ot_pay", "total_pay", "worker_payment", "net_income"}
        missing_columns = required_columns.difference(fieldnames)
        if missing_columns:
            joined = ", ".join(sorted(missing_columns))
            raise SystemExit(f"Missing required column(s) in shifts.csv: {joined}")

        rows: list[dict[str, str]] = []
        changed = 0
        for row in reader:
            if not row.get("date"):
                continue

            base_pay = _parse_int(row.get("base_pay", "0"))
            ot_minutes = _parse_int(row.get("ot_minutes", "0"))
            worker_payment = _parse_int(row.get("worker_payment", "0"))

            ot_pay = _calculate_ot_pay(ot_minutes)
            total_pay = base_pay + ot_pay
            net_income = total_pay - worker_payment

            if (
                _parse_int(row.get("ot_pay", "0")) != ot_pay
                or _parse_int(row.get("total_pay", "0")) != total_pay
                or _parse_int(row.get("net_income", "0")) != net_income
            ):
                row["ot_pay"] = str(ot_pay)
                row["total_pay"] = str(total_pay)
                row["net_income"] = str(net_income)
                changed += 1

            rows.append(row)

    with SOURCE.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {changed} row(s) in {SOURCE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

