import os

class AppConfig:
    # Web Configuration
    SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "https://your-app-url.koyeb.app/")
    
    # URL Shortener Configuration
    SHORTENER_API_KEY = os.environ.get("SHORTENER_API_KEY", "")
    SHORTENER_URL = "https://mdiskshortner.link"
    
    # Rate limiting
    RATE_LIMIT = int(os.environ.get("RATE_LIMIT", 5))  # requests per minute

app_config = AppConfig()
