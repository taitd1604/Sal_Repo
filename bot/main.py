import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Sequence, Tuple

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from github_client import GitHubCSVClient
from payroll import CSV_HEADER, OUTSOURCED_PAY_CHOICES, SHIFT_CONFIG, ShiftPayload

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - optional dependency
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

ASK_DATE, ASK_VENUE, ASK_EVENT, ASK_PERFORMER, ASK_PAYMENT, ASK_END_TIME, ASK_NEXT_ACTION = range(7)
DS_CHOOSE, DS_ACTION, DS_EDIT_FIELD, DS_EDIT_VALUE, DS_EDIT_CONFIRM, DS_DELETE_CONFIRM_1, DS_DELETE_CONFIRM_2 = range(100, 107)
DS_PAGE_SIZE = 10
ENTRY_COMMAND = "ca"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN env variable")

ALLOWED_CHAT_IDS = {
    chat_id.strip()
    for chat_id in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if chat_id.strip()
}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
if not GITHUB_TOKEN or not GITHUB_REPO:
    raise RuntimeError("Missing GITHUB_TOKEN or GITHUB_REPO env variables")

GITHUB_CLIENT = GitHubCSVClient(
    token=GITHUB_TOKEN,
    repo=GITHUB_REPO,
    file_path=os.environ.get("GITHUB_FILE_PATH", "data/shifts.csv"),
    branch=os.environ.get("GITHUB_BRANCH", "main"),
)


def _default_venue_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["Bee Night"]], one_time_keyboard=True, resize_keyboard=True
    )


def _post_save_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["↩️ Hoàn tác ca vừa lưu", "🔁 Nhập ca mới"], ["🏁 Kết thúc"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )

def _ds_number_keyboard(count: int) -> ReplyKeyboardMarkup:
    numbers = [str(i) for i in range(1, count + 1)]
    rows = [numbers[i : i + 5] for i in range(0, len(numbers), 5)]
    rows.append(["🏁 Thoát"])
    return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)


def _ds_action_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["✏️ Sửa", "🗑️ Xoá"], ["⬅️ Danh sách", "🏁 Thoát"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


def _ds_edit_field_keyboard(*, allow_worker_payment: bool) -> ReplyKeyboardMarkup:
    rows = [
        ["🗓️ Ngày", "📍 Địa điểm"],
        ["🎟️ Loại sự kiện", "👥 Người trực"],
        ["⏰ Giờ kết thúc"],
    ]
    if allow_worker_payment:
        rows[2].append("💵 Tiền thuê")
    rows.append(["⬅️ Quay lại", "🏁 Thoát"])
    return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)


def _confirm_keyboard(confirm_label: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[confirm_label], ["❌ Huỷ"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _format_shift_list_item(index: int, row: Dict[str, str]) -> str:
    date_label = row.get("date", "--")
    event_type = row.get("event_type", "--")
    venue = row.get("venue", "--")
    end_time = row.get("actual_end_time") or row.get("scheduled_end_time") or "--"
    total = row.get("total_pay", "--")
    return f"{index}) {date_label} | {event_type} | {venue} | KT {end_time} | Tổng {total}"


def _format_shift_detail(row: Dict[str, str]) -> str:
    return (
        "🧾 Chi tiết ca:\n"
        f"🗓️ Ngày: {row.get('date', '--')}\n"
        f"📍 Địa điểm: {row.get('venue', '--')}\n"
        f"🎟️ Loại: {row.get('event_type', '--')}\n"
        f"👤 Người trực: {row.get('performed_by', '--')}\n"
        f"⏰ Giờ bắt đầu: {row.get('start_time', '--')}\n"
        f"🕙 Giờ kết thúc lịch: {row.get('scheduled_end_time', '--')}\n"
        f"🕚 Giờ kết thúc thực tế: {row.get('actual_end_time', '--')}\n"
        f"💰 Base: {row.get('base_pay', '--')} | OT: {row.get('ot_pay', '--')} ({row.get('ot_minutes', '--')}p)\n"
        f"💵 Tổng: {row.get('total_pay', '--')} | Thuê: {row.get('worker_payment', '--')} | Ròng: {row.get('net_income', '--')}"
    )


def _event_label_to_key() -> Dict[str, str]:
    return {_normalize_text(cfg["label"]): key for key, cfg in SHIFT_CONFIG.items()}


def _infer_event_type_key(label: str) -> Optional[str]:
    normalized = _normalize_text(label)
    mapping = _event_label_to_key()
    if normalized in mapping:
        return mapping[normalized]
    squashed = normalized.replace(" ", "")
    for key_label, key in mapping.items():
        if squashed == key_label.replace(" ", ""):
            return key
    if "open" in normalized:
        return "openmic"
    if "dem" in normalized or "đêm" in normalized:
        return "dem_nhac"
    return None


def _row_to_shift_form(row: Dict[str, str]) -> Optional[Dict[str, object]]:
    raw_date = (row.get("date") or "").strip()
    parsed_date: Optional[date] = None
    if raw_date:
        try:
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = _parse_event_date(raw_date)
    if not parsed_date:
        return None

    event_key = _infer_event_type_key(row.get("event_type", ""))
    if not event_key:
        return None

    performed_by_raw = _normalize_text(row.get("performed_by", ""))
    performer = "outsourced" if ("thuê" in performed_by_raw or "thue" in performed_by_raw) else "self"

    end_raw = (row.get("actual_end_time") or row.get("scheduled_end_time") or "").strip()
    try:
        end_time = datetime.strptime(end_raw, "%H:%M").time()
    except ValueError:
        return None

    worker_payment_raw = (row.get("worker_payment") or "0").strip()
    try:
        worker_payment = int(float(worker_payment_raw))
    except ValueError:
        worker_payment = 0
    if performer == "self":
        worker_payment = 0

    return {
        "date": parsed_date,
        "venue": (row.get("venue") or "").strip(),
        "event_type": event_key,
        "performed_by": performer,
        "actual_end_time": end_time,
        "worker_payment": worker_payment,
    }


async def ds_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _ensure_allowed(update):
        await update.message.reply_text("Xin lỗi, bot này chỉ dành cho chủ sở hữu.")
        return ConversationHandler.END
    await update.message.reply_text("Đang tải danh sách ca gần nhất... ⏳")
    try:
        header, rows = await asyncio.to_thread(GITHUB_CLIENT.read_rows)
    except Exception as exc:  # pragma: no cover - network code
        logger.exception("Không thể tải CSV: %s", exc)
        await update.message.reply_text(
            "Không thể tải dữ liệu từ GitHub, thử lại sau nhé.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    if not rows:
        await update.message.reply_text(
            "Chưa có dữ liệu trong file shifts.csv.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    total = len(rows)
    count = min(DS_PAGE_SIZE, total)
    entries = []
    lines = ["📋 10 ca gần nhất (mới → cũ):"]
    for number in range(1, count + 1):
        row_index = total - number
        row = rows[row_index]
        fingerprint = {col: row.get(col, "") for col in header}
        entries.append(
            {
                "number": number,
                "preferred_index": row_index,
                "fingerprint": fingerprint,
                "snapshot": row,
            }
        )
        lines.append(_format_shift_list_item(number, row))

    context.user_data["ds_session"] = {
        "header": list(header),
        "entries": entries,
        "selected": None,
    }
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=_ds_number_keyboard(count),
    )
    return DS_CHOOSE


async def ds_choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _normalize_text(update.message.text or "")
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    session = context.user_data.get("ds_session") or {}
    entries = session.get("entries") or []
    try:
        chosen = int(text)
    except ValueError:
        await update.message.reply_text("Vui lòng chọn số (1-10) hoặc bấm Thoát.")
        return DS_CHOOSE

    if chosen < 1 or chosen > len(entries):
        await update.message.reply_text("Số không hợp lệ, thử lại nhé.")
        return DS_CHOOSE

    selected = entries[chosen - 1]
    session["selected"] = selected
    context.user_data["ds_session"] = session
    await update.message.reply_text(
        _format_shift_detail(selected["snapshot"]),
        reply_markup=_ds_action_keyboard(),
    )
    return DS_ACTION


async def ds_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _normalize_text(update.message.text or "")
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    session = context.user_data.get("ds_session") or {}
    selected = session.get("selected")
    if not selected:
        await update.message.reply_text("Bạn hãy chọn 1 ca trước.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if "danh sách" in text or "danh sach" in text:
        return await ds_start(update, context)

    if "xoá" in text or "xoa" in text:
        await update.message.reply_text(
            "⚠️ Bạn sắp xoá ca này.\n"
            "Bước 1/2: bấm '➡️ Tiếp tục xoá' để tiếp tục hoặc 'Huỷ' để dừng.",
            reply_markup=_confirm_keyboard("➡️ Tiếp tục xoá"),
        )
        return DS_DELETE_CONFIRM_1

    if "sửa" in text or "sua" in text:
        form = _row_to_shift_form(selected["snapshot"])
        if not form:
            await update.message.reply_text(
                "Không thể đọc dữ liệu ca này để sửa (định dạng không hợp lệ). "
                "Bạn có thể kiểm tra lại file CSV.",
                reply_markup=_ds_action_keyboard(),
            )
            return DS_ACTION
        session["edit_form"] = form
        session.pop("updated_row", None)
        context.user_data["ds_session"] = session
        allow_worker_payment = form.get("performed_by") == "outsourced"
        await update.message.reply_text(
            "Chọn trường bạn muốn sửa:",
            reply_markup=_ds_edit_field_keyboard(allow_worker_payment=allow_worker_payment),
        )
        return DS_EDIT_FIELD

    await update.message.reply_text("Vui lòng chọn Sửa, Xoá, Danh sách hoặc Thoát.")
    return DS_ACTION


async def ds_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _normalize_text(update.message.text or "")
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if "quay lại" in text or "quay lai" in text:
        await update.message.reply_text("Bạn muốn làm gì?", reply_markup=_ds_action_keyboard())
        return DS_ACTION

    session = context.user_data.get("ds_session") or {}
    form = session.get("edit_form")
    if not form:
        await update.message.reply_text("Phiên sửa đã hết hạn, gõ /ds để bắt đầu lại.")
        return ConversationHandler.END

    allow_worker_payment = form.get("performed_by") == "outsourced"
    if "ngày" in text or "ngay" in text:
        session["edit_field"] = "date"
        context.user_data["ds_session"] = session
        await update.message.reply_text(
            "Nhập ngày (DD/MM/YYYY hoặc YYYY-MM-DD):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DS_EDIT_VALUE
    if "địa điểm" in text or "dia diem" in text:
        session["edit_field"] = "venue"
        context.user_data["ds_session"] = session
        await update.message.reply_text(
            "Nhập địa điểm:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DS_EDIT_VALUE
    if "loại" in text or "loai" in text:
        session["edit_field"] = "event_type"
        context.user_data["ds_session"] = session
        keyboard = [[cfg["label"]] for cfg in SHIFT_CONFIG.values()]
        await update.message.reply_text(
            "Chọn loại sự kiện:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard, one_time_keyboard=True, resize_keyboard=True
            ),
        )
        return DS_EDIT_VALUE
    if "người trực" in text or "nguoi truc" in text:
        session["edit_field"] = "performed_by"
        context.user_data["ds_session"] = session
        await update.message.reply_text(
            "Chọn người trực:",
            reply_markup=ReplyKeyboardMarkup(
                [["Trực tiếp", "Thuê người"]],
                one_time_keyboard=True,
                resize_keyboard=True,
            ),
        )
        return DS_EDIT_VALUE
    if "giờ" in text or "gio" in text:
        session["edit_field"] = "actual_end_time"
        context.user_data["ds_session"] = session
        await update.message.reply_text(
            "Nhập giờ kết thúc thực tế (HH:MM, ví dụ 23:45):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return DS_EDIT_VALUE
    if ("tiền thuê" in text or "tien thue" in text) and allow_worker_payment:
        session["edit_field"] = "worker_payment"
        context.user_data["ds_session"] = session
        keyboard = [[f"{amount // 1000}k"] for amount in OUTSOURCED_PAY_CHOICES]
        await update.message.reply_text(
            "Chọn tiền thuê:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard, one_time_keyboard=True, resize_keyboard=True
            ),
        )
        return DS_EDIT_VALUE

    await update.message.reply_text(
        "Trường không hợp lệ, thử lại nhé.",
        reply_markup=_ds_edit_field_keyboard(allow_worker_payment=allow_worker_payment),
    )
    return DS_EDIT_FIELD


async def ds_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    text = _normalize_text(raw)
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    session = context.user_data.get("ds_session") or {}
    form = session.get("edit_form")
    field = session.get("edit_field")
    selected = session.get("selected")
    if not form or not field or not selected:
        await update.message.reply_text("Phiên sửa đã hết hạn, gõ /ds để bắt đầu lại.")
        return ConversationHandler.END

    if field == "date":
        parsed = _parse_event_date(raw)
        if not parsed:
            await update.message.reply_text("Ngày không hợp lệ. Ví dụ: 12/06/2024 hoặc 2024-06-12.")
            return DS_EDIT_VALUE
        form["date"] = parsed
    elif field == "venue":
        if not raw.strip():
            await update.message.reply_text("Địa điểm không được để trống.")
            return DS_EDIT_VALUE
        form["venue"] = raw.strip()
    elif field == "event_type":
        label_to_key = {cfg["label"]: key for key, cfg in SHIFT_CONFIG.items()}
        chosen_label = raw.strip()
        if chosen_label not in label_to_key:
            await update.message.reply_text("Loại sự kiện không hợp lệ, thử lại nhé.")
            return DS_EDIT_VALUE
        form["event_type"] = label_to_key[chosen_label]
    elif field == "performed_by":
        normalized = text.replace("’", "'")
        if any(keyword in normalized for keyword in ("trực tiếp", "tự làm", "toi truc", "tu lam", "tôi trực")):
            form["performed_by"] = "self"
            form["worker_payment"] = 0
        elif "thuê" in normalized or "thue" in normalized:
            form["performed_by"] = "outsourced"
            session["edit_field"] = "worker_payment"
            context.user_data["ds_session"] = session
            keyboard = [[f"{amount // 1000}k"] for amount in OUTSOURCED_PAY_CHOICES]
            await update.message.reply_text(
                "Chọn tiền thuê:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard, one_time_keyboard=True, resize_keyboard=True
                ),
            )
            return DS_EDIT_VALUE
        else:
            await update.message.reply_text("Vui lòng chọn 'Trực tiếp' hoặc 'Thuê người'.")
            return DS_EDIT_VALUE
    elif field == "worker_payment":
        digits = "".join(ch for ch in raw.lower() if ch.isdigit())
        try:
            amount = int(digits) * (1000 if len(digits) <= 3 else 1)
        except ValueError:
            amount = -1
        if amount not in OUTSOURCED_PAY_CHOICES:
            pretty = ", ".join(f"{val // 1000}k" for val in OUTSOURCED_PAY_CHOICES)
            await update.message.reply_text(f"Vui lòng chọn một trong các mức: {pretty}")
            return DS_EDIT_VALUE
        form["worker_payment"] = amount
    elif field == "actual_end_time":
        try:
            end_time = datetime.strptime(raw.strip(), "%H:%M").time()
        except ValueError:
            await update.message.reply_text("Giờ không hợp lệ. Ví dụ hợp lệ: 23:10")
            return DS_EDIT_VALUE
        form["actual_end_time"] = end_time
    else:
        await update.message.reply_text("Trường sửa không hợp lệ, gõ /ds để bắt đầu lại.")
        return ConversationHandler.END

    payload = ShiftPayload(
        date=form["date"],
        venue=form["venue"],
        event_type=form["event_type"],
        performed_by=form["performed_by"],
        actual_end_time=form["actual_end_time"],
        worker_payment=form.get("worker_payment", 0),
    )
    updated_row = payload.compute()
    session["edit_form"] = form
    session["updated_row"] = updated_row
    context.user_data["ds_session"] = session
    before = selected["snapshot"]
    await update.message.reply_text(
        "Xem lại thay đổi:\n"
        f"• Trước: {before.get('date','--')} | {before.get('event_type','--')} | {before.get('venue','--')} | KT {before.get('actual_end_time','--')}\n"
        f"• Sau:   {updated_row.get('date','--')} | {updated_row.get('event_type','--')} | {updated_row.get('venue','--')} | KT {updated_row.get('actual_end_time','--')}\n\n"
        "Bấm '✅ Lưu thay đổi' để cập nhật hoặc 'Huỷ' để bỏ qua.",
        reply_markup=_confirm_keyboard("✅ Lưu thay đổi"),
    )
    return DS_EDIT_CONFIRM


async def ds_edit_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _normalize_text(update.message.text or "")
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    session = context.user_data.get("ds_session") or {}
    selected = session.get("selected")
    updated_row = session.get("updated_row")
    if not selected or not updated_row:
        await update.message.reply_text("Phiên sửa đã hết hạn, gõ /ds để bắt đầu lại.")
        return ConversationHandler.END

    if "huỷ" in text or "huy" in text:
        session.pop("updated_row", None)
        session.pop("edit_field", None)
        context.user_data["ds_session"] = session
        await update.message.reply_text("Đã huỷ thay đổi. Bạn muốn làm gì?", reply_markup=_ds_action_keyboard())
        return DS_ACTION

    if "lưu" not in text and "luu" not in text:
        await update.message.reply_text(
            "Vui lòng bấm '✅ Lưu thay đổi' hoặc 'Huỷ'.",
            reply_markup=_confirm_keyboard("✅ Lưu thay đổi"),
        )
        return DS_EDIT_CONFIRM

    await update.message.reply_text("Đang cập nhật dữ liệu, vui lòng chờ... ⏳")
    fingerprint = selected["fingerprint"]
    preferred_index = selected.get("preferred_index")
    try:
        updated = await asyncio.to_thread(
            GITHUB_CLIENT.update_matching_row,
            fingerprint,
            updated_row,
            preferred_index=preferred_index,
        )
    except Exception as exc:  # pragma: no cover - network code
        logger.exception("Không thể cập nhật dữ liệu: %s", exc)
        await update.message.reply_text(
            "Có lỗi khi cập nhật dữ liệu lên GitHub, thử lại sau nhé.",
            reply_markup=_ds_action_keyboard(),
        )
        return DS_ACTION

    if not updated:
        await update.message.reply_text(
            "Không tìm thấy dòng cần sửa (có thể file đã thay đổi). Vui lòng gõ /ds để tải lại danh sách.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("ds_session", None)
        return ConversationHandler.END

    await update.message.reply_text("✅ Đã cập nhật.")
    context.user_data.pop("ds_session", None)
    return await ds_start(update, context)


async def ds_delete_confirm_1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _normalize_text(update.message.text or "")
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if "huỷ" in text or "huy" in text:
        await update.message.reply_text("Đã huỷ xoá. Bạn muốn làm gì?", reply_markup=_ds_action_keyboard())
        return DS_ACTION

    if "tiếp tục" not in text and "tiep tuc" not in text:
        await update.message.reply_text(
            "Vui lòng bấm '➡️ Tiếp tục xoá' hoặc 'Huỷ'.",
            reply_markup=_confirm_keyboard("➡️ Tiếp tục xoá"),
        )
        return DS_DELETE_CONFIRM_1

    await update.message.reply_text(
        "⚠️ Bước 2/2: bấm '✅ Xoá vĩnh viễn' để xoá hoặc 'Huỷ' để dừng.",
        reply_markup=_confirm_keyboard("✅ Xoá vĩnh viễn"),
    )
    return DS_DELETE_CONFIRM_2


async def ds_delete_confirm_2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _normalize_text(update.message.text or "")
    if "thoát" in text or "thoat" in text:
        context.user_data.pop("ds_session", None)
        await update.message.reply_text("Đã thoát /ds.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    session = context.user_data.get("ds_session") or {}
    selected = session.get("selected")
    if not selected:
        await update.message.reply_text("Phiên xoá đã hết hạn, gõ /ds để bắt đầu lại.")
        return ConversationHandler.END

    if "huỷ" in text or "huy" in text:
        await update.message.reply_text("Đã huỷ xoá. Bạn muốn làm gì?", reply_markup=_ds_action_keyboard())
        return DS_ACTION

    if "xoá" not in text and "xoa" not in text:
        await update.message.reply_text(
            "Vui lòng bấm '✅ Xoá vĩnh viễn' hoặc 'Huỷ'.",
            reply_markup=_confirm_keyboard("✅ Xoá vĩnh viễn"),
        )
        return DS_DELETE_CONFIRM_2

    await update.message.reply_text("Đang xoá dữ liệu, vui lòng chờ... ⏳")
    fingerprint = selected["fingerprint"]
    preferred_index = selected.get("preferred_index")
    try:
        deleted = await asyncio.to_thread(
            GITHUB_CLIENT.delete_matching_row,
            fingerprint,
            preferred_index=preferred_index,
        )
    except Exception as exc:  # pragma: no cover - network code
        logger.exception("Không thể xoá dữ liệu: %s", exc)
        await update.message.reply_text(
            "Có lỗi khi xoá dữ liệu trên GitHub, thử lại sau nhé.",
            reply_markup=_ds_action_keyboard(),
        )
        return DS_ACTION

    if not deleted:
        await update.message.reply_text(
            "Không tìm thấy dòng cần xoá (có thể file đã thay đổi). Vui lòng gõ /ds để tải lại danh sách.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("ds_session", None)
        return ConversationHandler.END

    await update.message.reply_text("✅ Đã xoá.")
    context.user_data.pop("ds_session", None)
    return await ds_start(update, context)


def _ensure_allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    chat_id = str(update.effective_chat.id)
    if chat_id in ALLOWED_CHAT_IDS:
        return True
    logger.warning("Unauthorized access attempt from chat %s", chat_id)
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_allowed(update):
        await update.message.reply_text("Xin lỗi, bot này chỉ dành cho chủ sở hữu.")
        return
    event_types = ", ".join(cfg["label"] for cfg in SHIFT_CONFIG.values())
    await update.message.reply_text(
        f"Chào bạn! Gõ /{ENTRY_COMMAND} để tạo log mới (cũ: /newshift).\n"
        f"Hỗ trợ các sự kiện: {event_types}.\n"
        "Trong quá trình nhập, gõ /cancel nếu muốn huỷ."
    )


async def new_shift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _ensure_allowed(update):
        await update.message.reply_text("Xin lỗi, bot này chỉ dành cho chủ sở hữu.")
        return ConversationHandler.END
    context.user_data["shift_form"] = {}
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)
    keyboard = [
        [f"📆 Hôm nay ({today.strftime('%d/%m/%Y')})"],
        [
            f"⏭️ Ngày mai ({tomorrow.strftime('%d/%m/%Y')})",
            f"⏮️ Hôm qua ({yesterday.strftime('%d/%m/%Y')})",
        ],
    ]
    await update.message.reply_text(
        "📅 Chọn ngày sự kiện (DD/MM/YYYY).\n"
        "Bạn có thể bấm phím nhanh hoặc nhập tay theo định dạng ngày/tháng/năm.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ASK_DATE


async def handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    event_date = _parse_event_date(update.message.text or "")
    if not event_date:
        await update.message.reply_text(
            "Ngày không hợp lệ. Ví dụ hợp lệ: 12/06/2024 hoặc 2024-06-12."
        )
        return ASK_DATE

    context.user_data["shift_form"]["date"] = event_date
    await update.message.reply_text(
        "📍 Nhập tên quán/địa điểm (bấm Bee Night nếu đi show cố định):",
        reply_markup=_default_venue_keyboard(),
    )
    return ASK_VENUE


def _parse_event_date(text: str) -> Optional[date]:
    raw = (text or "").strip()
    if not raw:
        return None
    normalized = raw.lower()
    today = datetime.now().date()
    relative_mapping = {
        "hôm nay": 0,
        "hom nay": 0,
        "ngày mai": 1,
        "ngay mai": 1,
        "hôm qua": -1,
        "hom qua": -1,
    }
    for key, delta in relative_mapping.items():
        if normalized.startswith(key):
            return today + timedelta(days=delta)

    match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", raw)
    candidates = [match.group(1)] if match else []
    candidates.append(raw)

    for candidate in candidates:
        clean = candidate.strip()
        if not clean:
            continue
        normalized_candidate = clean.replace("-", "/")
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                parsed = datetime.strptime(normalized_candidate, fmt).date()
                if fmt.endswith("%y") and parsed.year < 2000:
                    parsed = parsed.replace(year=parsed.year + 2000)
                return parsed
            except ValueError:
                continue
        try:
            return datetime.strptime(clean, "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


async def handle_venue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    venue = update.message.text.strip()
    if not venue:
        await update.message.reply_text("Tên địa điểm không được để trống.")
        return ASK_VENUE

    context.user_data["shift_form"]["venue"] = venue
    keyboard = [[cfg["label"]] for cfg in SHIFT_CONFIG.values()]
    await update.message.reply_text(
        "🎟️ Chọn loại sự kiện:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ASK_EVENT


async def handle_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    label_to_key = {cfg["label"]: key for key, cfg in SHIFT_CONFIG.items()}
    chosen_label = update.message.text.strip()
    if chosen_label not in label_to_key:
        await update.message.reply_text("Loại sự kiện không hợp lệ, thử lại nhé.")
        return ASK_EVENT

    context.user_data["shift_form"]["event_type"] = label_to_key[chosen_label]
    await update.message.reply_text(
        "👥 Ca này do ai phụ trách?",
        reply_markup=ReplyKeyboardMarkup(
            [["Trực tiếp", "Thuê người"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        ),
    )
    return ASK_PERFORMER


async def handle_performer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().lower()
    normalized = text.replace("’", "'")
    if any(keyword in normalized for keyword in ("trực tiếp", "tự làm", "toi truc", "tu lam", "tôi trực")):
        performer = "self"
    elif "thuê" in normalized or "thue" in normalized:
        performer = "outsourced"
    else:
        await update.message.reply_text("Vui lòng chọn 'Trực tiếp' hoặc 'Thuê người'.")
        return ASK_PERFORMER

    context.user_data["shift_form"]["performed_by"] = performer
    if performer == "outsourced":
        keyboard = [[f"{amount // 1000}k"] for amount in OUTSOURCED_PAY_CHOICES]
        await update.message.reply_text(
            "💵 Chọn số tiền bạn sẽ trả cho người được thuê:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard, one_time_keyboard=True, resize_keyboard=True
            ),
        )
        return ASK_PAYMENT

    context.user_data["shift_form"]["worker_payment"] = 0
    await update.message.reply_text(
        "⏰ Giờ kết thúc thực tế (HH:MM, ví dụ 23:45):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_END_TIME


async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    try:
        amount = int(digits) * (1000 if len(digits) <= 3 else 1)
    except ValueError:
        amount = -1
    if amount not in OUTSOURCED_PAY_CHOICES:
        pretty = ", ".join(f"{val // 1000}k" for val in OUTSOURCED_PAY_CHOICES)
        await update.message.reply_text(f"Vui lòng chọn một trong các mức: {pretty}")
        return ASK_PAYMENT

    context.user_data["shift_form"]["worker_payment"] = amount
    await update.message.reply_text(
        "⏰ Giờ kết thúc thực tế (HH:MM, ví dụ 23:45):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_END_TIME


async def handle_end_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        end_time = datetime.strptime(update.message.text.strip(), "%H:%M").time()
    except ValueError:
        await update.message.reply_text("Giờ không hợp lệ. Ví dụ hợp lệ: 23:10")
        return ASK_END_TIME

    form = context.user_data.get("shift_form", {})
    payload = ShiftPayload(
        date=form["date"],
        venue=form["venue"],
        event_type=form["event_type"],
        performed_by=form["performed_by"],
        actual_end_time=end_time,
        worker_payment=form.get("worker_payment", 0),
    )

    await update.message.reply_text("Đang lưu dữ liệu, vui lòng chờ... ⏳")
    try:
        computed = payload.compute()
        await asyncio.to_thread(GITHUB_CLIENT.append_row, CSV_HEADER, computed)
    except Exception as exc:  # pragma: no cover - network code
        logger.exception("Không thể lưu dữ liệu: %s", exc)
        await update.message.reply_text("Có lỗi khi ghi dữ liệu lên GitHub, thử lại sau nhé.")
        return ConversationHandler.END

    context.user_data["last_saved_row"] = computed
    await update.message.reply_text(payload.summary)
    await update.message.reply_text(
        "Bạn muốn làm gì tiếp theo?", reply_markup=_post_save_keyboard()
    )
    context.user_data.pop("shift_form", None)
    return ASK_NEXT_ACTION


async def handle_next_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().lower()
    if "hoàn tác" in text or "hoan tac" in text:
        last_saved = context.user_data.get("last_saved_row")
        if not last_saved:
            await update.message.reply_text(
                "Không có ca vừa lưu để hoàn tác.",
                reply_markup=_post_save_keyboard(),
            )
            return ASK_NEXT_ACTION
        await update.message.reply_text("Đang hoàn tác ca vừa lưu, vui lòng chờ... ⏳")
        try:
            deleted = await asyncio.to_thread(
                GITHUB_CLIENT.delete_matching_row,
                last_saved,
            )
        except Exception as exc:  # pragma: no cover - network code
            logger.exception("Không thể hoàn tác dữ liệu: %s", exc)
            await update.message.reply_text(
                "Có lỗi khi hoàn tác dữ liệu trên GitHub, thử lại sau nhé.",
                reply_markup=_post_save_keyboard(),
            )
            return ASK_NEXT_ACTION
        if deleted:
            context.user_data.pop("last_saved_row", None)
            await update.message.reply_text(
                "✅ Đã hoàn tác ca vừa lưu.",
                reply_markup=_post_save_keyboard(),
            )
            return ASK_NEXT_ACTION
        await update.message.reply_text(
            "Không tìm thấy dòng vừa lưu để hoàn tác (có thể file đã thay đổi). "
            "Bạn có thể dùng /ds để xoá thủ công.",
            reply_markup=_post_save_keyboard(),
        )
        return ASK_NEXT_ACTION
    if "nhập" in text or "nhap" in text:
        return await new_shift(update, context)
    if "kết thúc" in text or "ket thuc" in text or "kết thuc" in text:
        await update.message.reply_text(
            "🏁 Đã kết thúc phiên nhập liệu. Nghỉ ngơi thôi!",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Vui lòng chọn 'Nhập ca mới' hoặc 'Kết thúc'.",
        reply_markup=_post_save_keyboard(),
    )
    return ASK_NEXT_ACTION


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("shift_form", None)
    context.user_data.pop("ds_session", None)
    await update.message.reply_text(
        "Đã huỷ. Bạn có thể nhập lại bằng /ca hoặc quản lý bằng /ds.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


def main() -> None:
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    ds_handler = ConversationHandler(
        entry_points=[CommandHandler("ds", ds_start)],
        states={
            DS_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ds_choose)],
            DS_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ds_action)],
            DS_EDIT_FIELD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ds_edit_field)
            ],
            DS_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ds_edit_value)],
            DS_EDIT_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ds_edit_confirm)
            ],
            DS_DELETE_CONFIRM_1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ds_delete_confirm_1)
            ],
            DS_DELETE_CONFIRM_2: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ds_delete_confirm_2)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler(ENTRY_COMMAND, new_shift),
            CommandHandler("newshift", new_shift),
        ],
        states={
            ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_date)],
            ASK_VENUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_venue)],
            ASK_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_event)],
            ASK_PERFORMER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_performer)
            ],
            ASK_PAYMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment)
            ],
            ASK_END_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_end_time)
            ],
            ASK_NEXT_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_next_action)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(ds_handler)
    application.add_handler(conv_handler)
    logger.info("Bot started and polling ...")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
