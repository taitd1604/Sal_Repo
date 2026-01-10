from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Tuple

SHIFT_CONFIG = {
    "dem_nhac": {
        "label": "Đêm nhạc",
        "start_time": time(hour=19, minute=30),
        "scheduled_end": time(hour=23, minute=0),
        "base_pay": {"self": 600_000, "outsourced": 300_000},
    },
    "openmic": {
        "label": "Openmic",
        "start_time": time(hour=20, minute=0),
        "scheduled_end": time(hour=23, minute=0),
        "base_pay": {"self": 500_000, "outsourced": 200_000},
    },
}

CSV_HEADER = [
    "date",
    "venue",
    "event_type",
    "performed_by",
    "start_time",
    "scheduled_end_time",
    "actual_end_time",
    "base_pay",
    "ot_minutes",
    "ot_pay",
    "total_pay",
]


@dataclass
class ShiftPayload:
    date: date
    venue: str
    event_type: str
    performed_by: str
    actual_end_time: time

    def compute(self) -> Dict[str, str]:
        cfg = SHIFT_CONFIG[self.event_type]
        scheduled_start_dt = datetime.combine(self.date, cfg["start_time"])
        scheduled_end_dt = datetime.combine(self.date, cfg["scheduled_end"])
        actual_end_dt = datetime.combine(self.date, self.actual_end_time)
        if actual_end_dt < scheduled_start_dt:
            actual_end_dt += timedelta(days=1)

        duration_hours = (scheduled_end_dt - scheduled_start_dt).total_seconds() / 3600
        base_pay = cfg["base_pay"][self.performed_by]
        ot_minutes = _calculate_ot_minutes(scheduled_end_dt, actual_end_dt)
        ot_pay = _calculate_ot_pay(base_pay, duration_hours, ot_minutes)
        total_pay = base_pay + ot_pay
        return {
            "date": self.date.isoformat(),
            "venue": self.venue,
            "event_type": cfg["label"],
            "performed_by": "Tự làm" if self.performed_by == "self" else "Thuê ngoài",
            "start_time": cfg["start_time"].strftime("%H:%M"),
            "scheduled_end_time": cfg["scheduled_end"].strftime("%H:%M"),
            "actual_end_time": actual_end_dt.strftime("%H:%M"),
            "base_pay": f"{base_pay:.0f}",
            "ot_minutes": str(ot_minutes),
            "ot_pay": f"{ot_pay:.0f}",
            "total_pay": f"{total_pay:.0f}",
        }

    @property
    def summary(self) -> str:
        computed = self.compute()
        return (
            f"{computed['date']} – {computed['event_type']} tại {computed['venue']}\n"
            f"Người trực: {computed['performed_by']}\n"
            f"Base pay: {computed['base_pay']} | OT: {computed['ot_pay']} | Tổng: {computed['total_pay']}"
        )


def _calculate_ot_minutes(scheduled_end: datetime, actual_end: datetime) -> int:
    if actual_end <= scheduled_end:
        return 0
    diff_minutes = (actual_end - scheduled_end).total_seconds() / 60
    return int(math.ceil(diff_minutes / 15) * 15)


def _calculate_ot_pay(base_pay: float, duration_hours: float, ot_minutes: int) -> float:
    if ot_minutes <= 0:
        return 0.0
    hourly_rate = base_pay / duration_hours
    ot_blocks = ot_minutes / 15
    return ot_blocks * hourly_rate * 0.25


def available_event_types() -> Dict[str, Tuple[str, str]]:
    return {key: (cfg["label"], cfg["start_time"].strftime("%H:%M")) for key, cfg in SHIFT_CONFIG.items()}
