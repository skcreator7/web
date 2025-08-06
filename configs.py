import os

class Config:
    # Telegram API
    API_ID = int(os.environ.get("API_ID", ""))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    BOT_SESSION_NAME = os.environ.get("BOT_SESSION_NAME", "SK4FiLM")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Channels Configuration
    TEXT_CHANNEL_IDS = [
        -1001891090100,  # Main text channel 1
        -1002024811395   # Main text channel 2
    ]
    POSTER_CHANNEL_ID = -1002708802395  # Channel for posters only
    
    # Web
    SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "https://your-app-url.koyeb.app/")
    
    # Messages
    START_MSG = """
    👋 Hello {mention}!
    
    🎬 I'm <b>SK4Film Search Bot</b>
    🔍 Send me any movie name to search!
    """

