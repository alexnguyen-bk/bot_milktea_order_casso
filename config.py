import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # PayOS (để trống => dùng mock)
    PAYOS_CLIENT_ID: str = os.getenv("PAYOS_CLIENT_ID", "")
    PAYOS_API_KEY: str = os.getenv("PAYOS_API_KEY", "")
    PAYOS_CHECKSUM_KEY: str = os.getenv("PAYOS_CHECKSUM_KEY", "")

    # Admin group chat ID
    ADMIN_TELEGRAM_CHAT_ID: str = os.getenv("ADMIN_TELEGRAM_CHAT_ID", "")

    # Webhook (trống = polling)
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "data/boba_bot.db")

    @property
    def use_mock_payment(self) -> bool:
        return not all([self.PAYOS_CLIENT_ID, self.PAYOS_API_KEY, self.PAYOS_CHECKSUM_KEY])

    @property
    def has_gemini(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def use_webhook(self) -> bool:
        return bool(self.WEBHOOK_URL)


settings = Settings()
