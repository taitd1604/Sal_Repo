import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Dict, Optional

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

ASK_DATE, ASK_VENUE, ASK_EVENT, ASK_PERFORMER, ASK_PAYMENT, ASK_END_TIME = range(6)
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
        "📍 Nhập tên quán/địa điểm:", reply_markup=ReplyKeyboardRemove()
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
        await asyncio.to_thread(GITHUB_CLIENT.append_row, CSV_HEADER, payload.compute())
    except Exception as exc:  # pragma: no cover - network code
        logger.exception("Không thể lưu dữ liệu: %s", exc)
        await update.message.reply_text("Có lỗi khi ghi dữ liệu lên GitHub, thử lại sau nhé.")
        return ConversationHandler.END

    await update.message.reply_text(f"Đã lưu!\n{payload.summary}")
    context.user_data.pop("shift_form", None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("shift_form", None)
    await update.message.reply_text("Đã huỷ, cần nhập lại thì gõ /newshift nhé.")
    return ConversationHandler.END


def main() -> None:
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
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
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    logger.info("Bot started and polling ...")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
