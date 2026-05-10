from __future__ import annotations

import asyncio
import logging
from html import escape

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot_config import BotConfig, ConfigError, load_config
from downloader_service import (
    DownloadFailure,
    artifact_filename,
    download_artifact,
    existing_artifact_file,
    make_cache_key,
)
from media_settings import MediaSettings
from state_store import ArtifactRecord, StateStore, now_iso
from url_tools import UrlError, clean_url


LOGGER = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size_bytes} B"


class TelegramYtdlpBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.default_settings = MediaSettings.from_config(config)
        self.state = StateStore(config.data_dir / "state.json", config.error_history_limit)
        self.state_lock = asyncio.Lock()
        self.download_locks: dict[str, asyncio.Lock] = {}

    def build_application(self) -> Application:
        application = ApplicationBuilder().token(self.config.token).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help))
        application.add_handler(CommandHandler("settings", self.settings))
        application.add_handler(CommandHandler("set", self.set_setting))
        application.add_handler(CommandHandler("resetsettings", self.reset_settings))
        application.add_handler(CommandHandler("stats", self.stats))
        application.add_handler(CommandHandler("errors", self.errors))
        application.add_handler(CommandHandler("cleanup", self.cleanup))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url))
        application.add_error_handler(self.unhandled_error)
        return application

    def is_allowed(self, chat_id: int) -> bool:
        return chat_id in self.config.allowed_chat_ids

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.config.admin_chat_ids

    async def require_allowed(self, update: Update) -> bool:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if self.is_allowed(chat_id):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("This bot is private.")
        return False

    async def require_admin(self, update: Update) -> bool:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if self.is_admin(chat_id):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("Admin command.")
        return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_allowed(update):
            return
        await update.effective_message.reply_text(
            "Send a YouTube link and I will download it with your current defaults.\n"
            "Commands: /settings, /set, /resetsettings, /help"
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_allowed(update):
            return
        await update.effective_message.reply_text(
            "Commands:\n"
            "/settings - show your defaults\n"
            "/set media audio|video\n"
            "/set resolution 720\n"
            "/set audio_quality 192\n"
            "/set audio_format mp3\n"
            "/resetsettings - use global defaults again\n"
            "\n"
            "Admins: /stats, /errors, /cleanup"
        )

    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_allowed(update):
            return
        chat_id = update.effective_chat.id
        async with self.state_lock:
            settings = self.state.get_user_settings(chat_id, self.default_settings)
            self.state.save()
        await update.effective_message.reply_text(f"Current defaults: {settings.describe()}")

    async def set_setting(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_allowed(update):
            return
        chat_id = update.effective_chat.id
        if len(context.args) < 2:
            await update.effective_message.reply_text(
                "Use: /set media audio|video, /set resolution 720, "
                "/set audio_quality 192, or /set audio_format mp3"
            )
            return

        name = context.args[0]
        value = " ".join(context.args[1:])
        try:
            async with self.state_lock:
                current = self.state.get_user_settings(chat_id, self.default_settings)
                updated = current.update(name, value)
                self.state.set_user_settings(chat_id, updated)
                self.state.save()
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return

        await update.effective_message.reply_text(f"Saved: {updated.describe()}")

    async def reset_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_allowed(update):
            return
        chat_id = update.effective_chat.id
        async with self.state_lock:
            self.state.reset_user_settings(chat_id)
            settings = self.state.get_user_settings(chat_id, self.default_settings)
            self.state.save()
        await update.effective_message.reply_text(f"Defaults reset: {settings.describe()}")

    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_allowed(update):
            return

        chat_id = update.effective_chat.id
        message = update.effective_message
        try:
            cleaned_url = clean_url(message.text or "")
        except UrlError as exc:
            await message.reply_text(str(exc))
            return

        async with self.state_lock:
            self.state.record_request()
            settings = self.state.get_user_settings(chat_id, self.default_settings)
            self.state.cleanup_storage(self.config.max_storage_bytes)
            self.state.save()

        status = await message.reply_text(
            f"URL: {cleaned_url}\nProfile: {settings.describe()}\nChecking cache..."
        )

        key = make_cache_key(cleaned_url, settings)
        lock = self.download_locks.setdefault(key, asyncio.Lock())

        try:
            async with lock:
                record = await self.get_or_download_artifact(cleaned_url, settings, key, status)

            await self.send_artifact(chat_id, message, record)
            await status.edit_text("Done.")
        except Exception as exc:
            await self.report_error(
                update,
                stage="download_or_send",
                exc=exc,
                context={"url": cleaned_url, "settings": settings.to_dict(), "cache_key": key},
            )

    async def get_or_download_artifact(
        self,
        cleaned_url: str,
        settings: MediaSettings,
        key: str,
        status_message,
    ) -> ArtifactRecord:
        async with self.state_lock:
            cached = self.state.get_artifact(key)
            if cached:
                self.state.touch_artifact(key)
                self.state.record_cache_hit()
                self.state.save()
                return cached

            orphan_path = existing_artifact_file(self.config, key, settings)
            if orphan_path:
                created_at = now_iso()
                record = ArtifactRecord(
                    key=key,
                    path=orphan_path.resolve(),
                    title=key,
                    size_bytes=orphan_path.stat().st_size,
                    media=settings.media,
                    created_at=created_at,
                    last_accessed_at=created_at,
                    url=cleaned_url,
                    profile=settings.cache_profile(),
                )
                self.state.set_artifact(record)
                self.state.record_cache_hit()
                self.state.save()
                return record

        await status_message.edit_text("Downloading...")
        record = await asyncio.to_thread(download_artifact, cleaned_url, settings, self.config)
        if record.size_bytes > self.config.max_storage_bytes:
            record.path.unlink(missing_ok=True)
            raise DownloadFailure(
                f"Artifact is {format_size(record.size_bytes)}, above total storage limit "
                f"{format_size(self.config.max_storage_bytes)}."
            )

        async with self.state_lock:
            self.state.set_artifact(record)
            self.state.record_download()
            self.state.cleanup_storage(self.config.max_storage_bytes, keep_keys={record.key})
            self.state.save()
        return record

    async def send_artifact(self, chat_id: int, message, record: ArtifactRecord) -> None:
        if record.size_bytes > self.config.telegram_max_upload_bytes:
            raise DownloadFailure(
                "Telegram refused this file because it is too large for Bot API upload.\n"
                f"File size: {format_size(record.size_bytes)}\n"
                f"Configured upload limit: {format_size(self.config.telegram_max_upload_bytes)}\n"
                "Try lower video resolution or lower audio quality."
            )

        async with self.state_lock:
            if not self.state.can_add_week_usage(
                chat_id,
                record.size_bytes,
                self.config.weekly_user_limit_bytes,
            ):
                used = self.state.get_week_usage(chat_id)
                raise DownloadFailure(
                    "Weekly limit exceeded. "
                    f"Used {format_size(used)} of "
                    f"{format_size(self.config.weekly_user_limit_bytes)}; "
                    f"this file is {format_size(record.size_bytes)}."
                )
            self.state.add_week_usage(chat_id, record.size_bytes)
            self.state.record_bytes_sent(record.size_bytes)
            self.state.touch_artifact(record.key)
            self.state.save()

        try:
            with record.path.open("rb") as handle:
                await message.reply_document(
                    document=InputFile(handle, filename=artifact_filename(record)),
                    caption=f"{record.title}\n{format_size(record.size_bytes)}",
                )
        except Exception:
            async with self.state_lock:
                self.state.add_week_usage(chat_id, -record.size_bytes)
                self.state.record_bytes_sent(-record.size_bytes)
                self.state.save()
            raise

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_admin(update):
            return
        async with self.state_lock:
            self.state.cleanup_missing_artifacts()
            stats = self.state.state["stats"]
            total_storage = self.state.total_artifact_bytes()
            artifact_count = len(self.state.state["artifacts"])
            user_lines = []
            for chat_id in sorted(self.config.allowed_chat_ids):
                used = self.state.get_week_usage(chat_id)
                user_lines.append(f"{chat_id}: {format_size(used)}")
            self.state.save()

        await update.effective_message.reply_text(
            "Stats:\n"
            f"Requests: {stats.get('requests', 0)}\n"
            f"Downloads: {stats.get('downloads', 0)}\n"
            f"Cache hits: {stats.get('cache_hits', 0)}\n"
            f"Bytes sent: {format_size(int(stats.get('bytes_sent', 0)))}\n"
            f"Errors: {stats.get('errors_total', 0)}\n"
            f"Artifacts: {artifact_count}\n"
            f"Storage: {format_size(total_storage)} / {format_size(self.config.max_storage_bytes)}\n"
            "Weekly usage:\n"
            + "\n".join(user_lines)
        )

    async def errors(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_admin(update):
            return
        limit = 5
        if context.args and context.args[0].isdigit():
            limit = min(10, max(1, int(context.args[0])))

        async with self.state_lock:
            errors = self.state.recent_errors(limit)

        if not errors:
            await update.effective_message.reply_text("No errors recorded.")
            return

        parts = []
        for entry in errors:
            traceback_text = entry.get("traceback", "").strip()
            if len(traceback_text) > 1200:
                traceback_text = traceback_text[-1200:]
            parts.append(
                f"<b>{escape(entry['id'])}</b> {escape(entry.get('stage', ''))}\n"
                f"chat_id={escape(str(entry.get('chat_id')))} "
                f"type={escape(str(entry.get('exception_type')))}\n"
                f"{escape(str(entry.get('message')))}\n"
                f"<pre>{escape(traceback_text)}</pre>"
            )

        await update.effective_message.reply_text(
            "\n\n".join(parts)[:3900],
            parse_mode=ParseMode.HTML,
        )

    async def cleanup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.require_admin(update):
            return
        async with self.state_lock:
            removed = self.state.cleanup_storage(self.config.max_storage_bytes)
            total = self.state.total_artifact_bytes()
            self.state.save()
        await update.effective_message.reply_text(
            f"Removed {len(removed)} old artifact(s). "
            f"Storage now {format_size(total)} / {format_size(self.config.max_storage_bytes)}."
        )

    async def report_error(
        self,
        update: Update,
        stage: str,
        exc: BaseException,
        context: dict,
    ) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        async with self.state_lock:
            error_id = self.state.record_error(
                chat_id=chat_id,
                stage=stage,
                message=str(exc),
                exc=exc,
                context=context,
            )
            self.state.save()

        LOGGER.exception(
            "Bot error %s at %s",
            error_id,
            stage,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        await update.effective_message.reply_text(
            "Failed.\n"
            f"Error id: {error_id}\n"
            f"{type(exc).__name__}: {str(exc)[:900]}"
        )

    async def unhandled_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if isinstance(update, Update) and update.effective_chat else None
        async with self.state_lock:
            error_id = self.state.record_error(
                chat_id=chat_id,
                stage="telegram_handler",
                message=str(context.error),
                exc=context.error,
            )
            self.state.save()
        LOGGER.exception(
            "Unhandled Telegram error %s",
            error_id,
            exc_info=(
                type(context.error),
                context.error,
                context.error.__traceback__,
            ),
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.download_dir.mkdir(parents=True, exist_ok=True)
    bot = TelegramYtdlpBot(config)
    bot.build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
