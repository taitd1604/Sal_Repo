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
        "base_pay": 600_000,
    },
    "openmic": {
        "label": "Openmic",
        "start_time": time(hour=20, minute=0),
        "scheduled_end": time(hour=22, minute=30),
        "base_pay": 500_000,
    },
}

OUTSOURCED_PAY_CHOICES = (300_000, 500_000, 600_000)
OT_BLOCK_MINUTES = 15
OT_BLOCK_PAY = 50_000

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
    "worker_payment",
    "net_income",
]


@dataclass
class ShiftPayload:
    date: date
    venue: str
    event_type: str
    performed_by: str
    actual_end_time: time
    worker_payment: int = 0

    def compute(self) -> Dict[str, str]:
        cfg = SHIFT_CONFIG[self.event_type]
        scheduled_start_dt = datetime.combine(self.date, cfg["start_time"])
        scheduled_end_dt = datetime.combine(self.date, cfg["scheduled_end"])
        actual_end_dt = datetime.combine(self.date, self.actual_end_time)
        if actual_end_dt < scheduled_start_dt:
            actual_end_dt += timedelta(days=1)

        base_pay = cfg["base_pay"]
        ot_minutes = _calculate_ot_minutes(scheduled_end_dt, actual_end_dt)
        ot_pay = _calculate_ot_pay(ot_minutes)
        total_pay = base_pay + ot_pay
        worker_payment = self.worker_payment if self.performed_by == "outsourced" else 0
        net_income = total_pay - worker_payment
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
            "worker_payment": f"{worker_payment:.0f}",
            "net_income": f"{net_income:.0f}",
        }

    @property
    def summary(self) -> str:
        computed = self.compute()
        return (
            "💾 Đã lưu!\n"
            f"🗓️ {computed['date']} – {computed['event_type']} tại {computed['venue']}\n"
            f"👤 Người trực: {computed['performed_by']}\n"
            f"💰 Base pay: {computed['base_pay']} | ⏱️ OT: {computed['ot_pay']} | 💵 Tổng: {computed['total_pay']} | 📉 Ròng: {computed['net_income']}"
        )


def _calculate_ot_minutes(scheduled_end: datetime, actual_end: datetime) -> int:
    if actual_end <= scheduled_end:
        return 0
    diff_minutes = (actual_end - scheduled_end).total_seconds() / 60
    return int(math.ceil(diff_minutes / OT_BLOCK_MINUTES) * OT_BLOCK_MINUTES)


def _calculate_ot_pay(ot_minutes: int) -> int:
    if ot_minutes <= 0:
        return 0
    ot_blocks = int(math.ceil(ot_minutes / OT_BLOCK_MINUTES))
    return ot_blocks * OT_BLOCK_PAY


def available_event_types() -> Dict[str, Tuple[str, str]]:
    return {key: (cfg["label"], cfg["start_time"].strftime("%H:%M")) for key, cfg in SHIFT_CONFIG.items()}
