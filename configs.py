import os
from pydantic import BaseSettings

class Config(BaseSettings):
    # Telegram API
    API_ID: int = int(os.environ.get("API_ID", 0))
    API_HASH: str = os.environ.get("API_HASH", "")
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    BOT_SESSION_NAME: str = os.environ.get("BOT_SESSION_NAME", "SK4FiLM")
    USER_SESSION_STRING: str = os.environ.get("USER_SESSION_STRING", "")
    
    # Channels
    CHANNEL_IDS: list[int] = [-1001891090100, -1002024811395]
    UPDATES_CHANNEL: str = os.environ.get("UPDATES_CHANNEL", "sk4film")
    
    # Web
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "your-secret-key-here")
    WEB_SERVER_PORT: int = int(os.environ.get("PORT", 8000))
    WEB_BASE_URL: str = os.environ.get("WEB_BASE_URL", "https://your-app-url.koyeb.app/")
    
    # URL Shortener
    SHORTENER_API_KEY: str = os.environ.get("SHORTENER_API_KEY", "")
    
    # Rate limiting
    RATE_LIMIT: int = int(os.environ.get("RATE_LIMIT", 5))  # requests per minute
    
    # Messages
    START_MSG: str = """
    👋 Hello {mention}!
    
    🎬 I'm <b>SK4Film Search Bot</b>
    🔍 Send me any movie name to search!
    """

    class Config:
        env_file = ".env"

config = Config()
