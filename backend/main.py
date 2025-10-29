import asyncio
import os
import logging
from pyrogram import Client, errors
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import html
import re
from datetime import datetime

# Configuration with proper validation
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Channel IDs - VERIFY THESE
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    POSTER_CHANNEL_ID = -1002708802395
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    @classmethod
    def validate(cls):
        if not cls.API_ID or cls.API_ID == 0:
            return False, "API_ID missing"
        if not cls.API_HASH:
            return False, "API_HASH missing"
        if not cls.USER_SESSION_STRING:
            return False, "USER_SESSION_STRING missing"
        return True, "OK"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Quart app
app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

# Global variables
User = None
bot_started = False

async def initialize_telegram():
    """Initialize Telegram client with proper error handling"""
    global User, bot_started
    
    # Validate config first
    is_valid, message = Config.validate()
    if not is_valid:
        logger.error(f"❌ Configuration error: {message}")
        return False
    
    try:
        logger.info("🔄 Initializing Telegram User Client...")
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING
        )
        
        await User.start()
        logger.info("✅ Telegram User Client started successfully!")
        
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username})")
        
        # Test channel access
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Access confirmed to channel: {chat.title}")
            except Exception as e:
                logger.warning(f"⚠️ Cannot access channel {channel_id}: {e}")
        
        bot_started = True
        return True
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization failed: {e}")
        bot_started = False
        return False

async def search_telegram_channels(query, limit=50):
    """Enhanced search with better error handling"""
    if not User or not bot_started:
        logger.error("❌ Telegram client not ready for search!")
        return []
    
    results = []
    logger.info(f"🔍 Searching for: '{query}' in {len(Config.TEXT_CHANNEL_IDS)} channels")
    
    try:
        # Search in text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching in channel: {channel_id}")
                message_count = 0
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=20
                ):
                    message_count += 1
                    if message.text:
                        results.append({
                            'type': 'text',
                            'content': format_result(message.text)[:200] + "...",
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id
                        })
                
                logger.info(f"✅ Found {message_count} messages in channel {channel_id}")
                
            except errors.ChatAdminRequired:
                logger.error(f"❌ Admin access required for channel {channel_id}")
            except errors.ChannelPrivate:
                logger.error(f"❌ Channel {channel_id} is private")
            except errors.UsernameNotOccupied:
                logger.error(f"❌ Channel {channel_id} does not exist")
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} search error: {e}")
                continue
        
        # Search in poster channel
        try:
            logger.info(f"🔍 Searching posters in channel: {Config.POSTER_CHANNEL_ID}")
            poster_count = 0
            
            async for message in User.search_messages(
                chat_id=Config.POSTER_CHANNEL_ID,
                query=query,
                limit=20
            ):
                poster_count += 1
                if message.caption:
                    result = {
                        'type': 'poster',
                        'content': format_result(message.caption)[:150] + "...",
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': Config.POSTER_CHANNEL_ID
                    }
                    
                    if message.photo:
                        result['photo'] = message.photo.file_id
                    
                    results.append(result)
            
            logger.info(f"✅ Found {poster_count} posters in poster channel")
            
        except Exception as e:
            logger.warning(f"⚠️ Poster channel search error: {e}")
    
    except Exception as e:
        logger.error(f"❌ Search function error: {e}")
    
    # Sort by date (newest first)
    results.sort(key=lambda x: x['date'], reverse=True)
    final_results = results[:limit]
    
    logger.info(f"✅ Total search results: {len(final_results)}")
    return final_results

def format_result(text):
    """Format the result text"""
    if not text:
        return ""
    
    text = html.escape(text)
    text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank">\1</a>', text)
    text = text.replace('\n', '<br>')
    return text

# CORS setup
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Enhanced API endpoints
@app.route('/')
async def home():
    status_info = {
        "status": "healthy" if bot_started else "unhealthy",
        "service": "SK4FiLM API",
        "telegram_connected": bot_started,
        "channels_configured": len(Config.TEXT_CHANNEL_IDS),
        "mode": "REAL_DATA_ONLY",
        "timestamp": datetime.now().isoformat()
    }
    
    if not bot_started:
        is_valid, message = Config.validate()
        status_info["config_error"] = message if not is_valid else None
    
    return jsonify(status_info)

@app.route('/health')
async def health():
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_ready": bot_started
    })

@app.route('/api/search')
async def api_search():
    """Enhanced search with detailed logging"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 20))
        
        if not query:
            return jsonify({
                "status": "error",
                "message": "Search query is required"
            }), 400
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available",
                "telegram_connected": False
            }), 503
        
        logger.info(f"🔍 API Search request: '{query}' (limit: {limit})")
        
        # Perform search
        results = await search_telegram_channels(query, limit)
        
        response_data = {
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results),
            "source": "REAL_TELEGRAM_CHANNELS",
            "searched_channels": len(Config.TEXT_CHANNEL_IDS) + 1,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"✅ Search completed: {len(results)} results for '{query}'")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Search API error: {e}")
        return jsonify({
            "status": "error",
            "message": "Search service temporarily unavailable",
            "error_type": type(e).__name__
        }), 500

# Startup function
async def startup():
    """Initialize all services"""
    logger.info("🚀 Starting SK4FiLM Backend...")
    
    # Check configuration
    is_valid, message = Config.validate()
    if not is_valid:
        logger.error(f"❌ Configuration invalid: {message}")
        return False
    
    # Initialize Telegram
    success = await initialize_telegram()
    
    if success:
        logger.info("✅ All services ready!")
        logger.info("✅ Real Telegram search is ACTIVE!")
    else:
        logger.error("❌ Service initialization failed!")
        logger.error("❌ Check your environment variables!")
    
    return success

if __name__ == "__main__":
    try:
        # Run startup
        startup_success = asyncio.run(startup())
        
        if startup_success:
            # Start web server
            config = HyperConfig()
            config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
            logger.info(f"🌐 Server starting on port {Config.WEB_SERVER_PORT}")
            asyncio.run(serve(app, config))
        else:
            logger.error("❌ Cannot start server - initialization failed")
            
    except Exception as e:
        logger.error(f"💥 Server startup failed: {e}")
