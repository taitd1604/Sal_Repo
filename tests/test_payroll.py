import csv
import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from unittest.mock import patch

from bot.payroll import ShiftPayload
from scripts import export_public_csv, recompute_ot_pay


class ShiftPayloadTests(unittest.TestCase):
    def test_ot_rate_depends_on_event_type(self) -> None:
        cases = [
            (date(2026, 9, 30), "dem_nhac", time(23, 35), "150500", "750500"),
            (date(2026, 9, 30), "openmic", time(22, 36), "30000", "530000"),
            (date(2026, 8, 28), "dem_nhac", time(23, 40), "200000", "800000"),
        ]

        for shift_date, event_type, actual_end_time, expected_ot_pay, expected_total in cases:
            with self.subTest(shift_date=shift_date, event_type=event_type):
                computed = ShiftPayload(
                    date=shift_date,
                    venue="Bee Night",
                    event_type=event_type,
                    performed_by="self",
                    actual_end_time=actual_end_time,
                ).compute()

                self.assertEqual(computed["ot_pay"], expected_ot_pay)
                self.assertEqual(computed["total_pay"], expected_total)


class RecomputeSeptemberTests(unittest.TestCase):
    def test_recomputes_september_with_event_rate_and_preserves_august(self) -> None:
        fieldnames = recompute_ot_pay.CSV_HEADER if hasattr(recompute_ot_pay, "CSV_HEADER") else [
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
        rows = [
            {
                "date": "2026-08-28",
                "venue": "Bee Night",
                "event_type": "Đêm nhạc",
                "performed_by": "Tự làm",
                "start_time": "19:30",
                "scheduled_end_time": "23:00",
                "actual_end_time": "23:40",
                "base_pay": "600000",
                "ot_minutes": "40",
                "ot_pay": "200000",
                "total_pay": "800000",
                "worker_payment": "0",
                "net_income": "800000",
            },
            {
                "date": "2026-09-04",
                "venue": "Bee Night",
                "event_type": "Đêm nhạc",
                "performed_by": "Tự làm",
                "start_time": "19:30",
                "scheduled_end_time": "23:00",
                "actual_end_time": "23:35",
                "base_pay": "600000",
                "ot_minutes": "35",
                "ot_pay": "175000",
                "total_pay": "775000",
                "worker_payment": "0",
                "net_income": "775000",
            },
            {
                "date": "2026-09-05",
                "venue": "Bee Night",
                "event_type": "Openmic",
                "performed_by": "Tự làm",
                "start_time": "20:00",
                "scheduled_end_time": "22:30",
                "actual_end_time": "22:36",
                "base_pay": "500000",
                "ot_minutes": "6",
                "ot_pay": "30000",
                "total_pay": "530000",
                "worker_payment": "0",
                "net_income": "530000",
            },
        ]

        with tempfile.TemporaryDirectory(dir=recompute_ot_pay.REPO_ROOT) as tmpdir:
            source = Path(tmpdir) / "shifts.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)

            with patch.object(recompute_ot_pay, "SOURCE", source):
                recompute_ot_pay.main()

            with source.open("r", encoding="utf-8", newline="") as handle:
                updated = list(csv.DictReader(handle))

        self.assertEqual(updated[0]["ot_pay"], "200000")
        self.assertEqual(updated[0]["total_pay"], "800000")
        self.assertEqual(updated[1]["ot_pay"], "150500")
        self.assertEqual(updated[1]["total_pay"], "750500")
        self.assertEqual(updated[1]["net_income"], "750500")
        self.assertEqual(updated[2]["ot_pay"], "30000")


class PublicExportTests(unittest.TestCase):
    def test_export_uses_unix_line_endings(self) -> None:
        with tempfile.TemporaryDirectory(dir=export_public_csv.REPO_ROOT) as tmpdir:
            source = Path(tmpdir) / "shifts.csv"
            destination = Path(tmpdir) / "shifts_public.csv"
            source.write_text(
                "date,venue,event_type,performed_by,start_time,scheduled_end_time,"
                "actual_end_time,base_pay,ot_minutes,ot_pay,total_pay,worker_payment,net_income\n"
                "2026-09-04,Bee Night,Đêm nhạc,Tự làm,19:30,23:00,23:35,"
                "600000,35,150500,750500,0,750500\n",
                encoding="utf-8",
            )

            with (
                patch.object(export_public_csv, "SOURCE", source),
                patch.object(export_public_csv, "DESTINATION", destination),
            ):
                export_public_csv.main()

            exported = destination.read_bytes()

        self.assertNotIn(b"\r\n", exported)
        self.assertTrue(exported.endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
