import asyncio
import logging
import os
from datetime import datetime
from typing import Dict

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
from payroll import CSV_HEADER, SHIFT_CONFIG, ShiftPayload

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

ASK_DATE, ASK_VENUE, ASK_EVENT, ASK_PERFORMER, ASK_END_TIME = range(5)

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
        "Chào bạn! Gõ /newshift để tạo log mới.\n"
        f"Hỗ trợ các sự kiện: {event_types}.\n"
        "Trong quá trình nhập, gõ /cancel nếu muốn huỷ."
    )


async def new_shift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _ensure_allowed(update):
        await update.message.reply_text("Xin lỗi, bot này chỉ dành cho chủ sở hữu.")
        return ConversationHandler.END
    context.user_data["shift_form"] = {}
    await update.message.reply_text(
        "Nhập ngày sự kiện (định dạng YYYY-MM-DD):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_DATE


async def handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        event_date = datetime.strptime(update.message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Ngày không hợp lệ. Ví dụ hợp lệ: 2024-05-30")
        return ASK_DATE

    context.user_data["shift_form"]["date"] = event_date
    await update.message.reply_text("Nhập tên quán/địa điểm:")
    return ASK_VENUE


async def handle_venue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    venue = update.message.text.strip()
    if not venue:
        await update.message.reply_text("Tên địa điểm không được để trống.")
        return ASK_VENUE

    context.user_data["shift_form"]["venue"] = venue
    keyboard = [[cfg["label"]] for cfg in SHIFT_CONFIG.values()]
    await update.message.reply_text(
        "Chọn loại sự kiện:",
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
        "Ai trực sự kiện này?",
        reply_markup=ReplyKeyboardMarkup(
            [["Tôi trực", "Thuê người khác"]], one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ASK_PERFORMER


async def handle_performer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if "tôi" in text:
        performer = "self"
    elif "thuê" in text or "khác" in text:
        performer = "outsourced"
    else:
        await update.message.reply_text("Vui lòng chọn 'Tôi trực' hoặc 'Thuê người khác'.")
        return ASK_PERFORMER

    context.user_data["shift_form"]["performed_by"] = performer
    await update.message.reply_text(
        "Giờ kết thúc thực tế (HH:MM, ví dụ 23:45):", reply_markup=ReplyKeyboardRemove()
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
        entry_points=[CommandHandler("newshift", new_shift)],
        states={
            ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_date)],
            ASK_VENUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_venue)],
            ASK_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_event)],
            ASK_PERFORMER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_performer)
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
