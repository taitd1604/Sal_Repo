#!/usr/bin/env python3
"""Recompute OT pay for existing shifts.csv rows.

Rule (áp dụng từ 2026-07-01):
- Lương giờ cơ bản: 200.000đ/giờ.
- OT = 150% lương giờ = 5.000đ/phút, tính theo phút chính xác (không làm tròn).
- Scheduled end: Đêm nhạc & Openmic đều kết thúc lúc 22:30.

Script chỉ cập nhật các dòng có date >= NEW_RULE_FROM_DATE.
Các dòng trước ngày này được giữ nguyên (dùng rule cũ: block 15 phút × 50.000đ).

Columns được cập nhật:
- scheduled_end_time (Đêm nhạc: 23:00 -> 22:30)
- ot_minutes
- ot_pay
- total_pay
- net_income
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "shifts.csv"

# Rule mới áp dụng từ ngày này (gồm). Trước ngày này: giữ nguyên.
NEW_RULE_FROM_DATE = date(2026, 7, 1)

# Lương giờ cơ bản & OT rate (phải khớp với bot/payroll.py).
HOURLY_PAY = 200_000
OT_RATE_PER_MINUTE = HOURLY_PAY * 1.5 / 60  # = 5.000đ/phút

# Scheduled end mới theo loại ca (label trong CSV).
SCHEDULED_END_BY_EVENT = {
    "Đêm nhạc": "22:30",
    "Openmic": "22:30",
}


def _parse_int(value: str, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    normalized = "".join(ch for ch in text if ch.isdigit() or ch == "-")
    if normalized in {"", "-"}:
        return default
    try:
        return int(normalized)
    except ValueError:
        return default


def _parse_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _time_on(date_obj: date, hhmm: str) -> datetime:
    """Combine date with HH:MM string into a datetime."""
    t = datetime.strptime(hhmm, "%H:%M").time()
    return datetime.combine(date_obj, t)


def _calculate_ot_minutes(scheduled_end: datetime, actual_end: datetime) -> int:
    if actual_end <= scheduled_end:
        return 0
    diff_seconds = (actual_end - scheduled_end).total_seconds()
    return int(round(diff_seconds / 60))


def _calculate_ot_pay(ot_minutes: int) -> int:
    if ot_minutes <= 0:
        return 0
    return int(round(ot_minutes * OT_RATE_PER_MINUTE))


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source file not found: {SOURCE}")

    with SOURCE.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("CSV header is missing.")

        required_columns = {
            "date",
            "event_type",
            "actual_end_time",
            "base_pay",
            "ot_minutes",
            "ot_pay",
            "total_pay",
            "worker_payment",
            "net_income",
        }
        missing_columns = required_columns.difference(fieldnames)
        if missing_columns:
            joined = ", ".join(sorted(missing_columns))
            raise SystemExit(f"Missing required column(s) in shifts.csv: {joined}")

        rows: list[dict[str, str]] = []
        changed = 0
        skipped_old = 0
        skipped_unknown_event = 0

        for row in reader:
            if not row.get("date"):
                continue

            row_date = _parse_date(row.get("date", ""))
            if row_date is None:
                rows.append(row)
                continue

            # Chỉ recompute dòng từ NEW_RULE_FROM_DATE trở đi.
            if row_date < NEW_RULE_FROM_DATE:
                skipped_old += 1
                rows.append(row)
                continue

            event_label = (row.get("event_type") or "").strip()
            scheduled_end_str = SCHEDULED_END_BY_EVENT.get(event_label)
            if scheduled_end_str is None:
                skipped_unknown_event += 1
                rows.append(row)
                continue

            actual_end_str = (row.get("actual_end_time") or "").strip()
            if not actual_end_str:
                rows.append(row)
                continue

            scheduled_end_dt = _time_on(row_date, scheduled_end_str)
            actual_end_dt = _time_on(row_date, actual_end_str)
            if actual_end_dt < scheduled_end_dt:
                # Xử lý qua đêm (hiếm nhưng phòng xa).
                actual_end_dt = datetime.combine(
                    row_date + timedelta(days=1),
                    actual_end_dt.time(),
                )

            base_pay = _parse_int(row.get("base_pay", "0"))
            worker_payment = _parse_int(row.get("worker_payment", "0"))

            ot_minutes = _calculate_ot_minutes(scheduled_end_dt, actual_end_dt)
            ot_pay = _calculate_ot_pay(ot_minutes)
            total_pay = base_pay + ot_pay
            net_income = total_pay - worker_payment

            new_vals = {
                "scheduled_end_time": scheduled_end_str,
                "ot_minutes": str(ot_minutes),
                "ot_pay": str(ot_pay),
                "total_pay": str(total_pay),
                "net_income": str(net_income),
            }

            if any(row.get(k, "") != v for k, v in new_vals.items()):
                row.update(new_vals)
                changed += 1

            rows.append(row)

    with SOURCE.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {changed} row(s) in {SOURCE.relative_to(REPO_ROOT)}")
    print(f"Skipped {skipped_old} row(s) before {NEW_RULE_FROM_DATE} (kept old rule)")
    if skipped_unknown_event:
        print(f"Skipped {skipped_unknown_event} row(s) with unknown event_type")


if __name__ == "__main__":
    main()
