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
from io import BytesIO

# Configuration with validation
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Channel IDs
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    POSTER_CHANNEL_ID = -1002708802395
    
    # Server Config
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    @classmethod
    def validate(cls):
        missing = []
        if not cls.API_ID or cls.API_ID == 0:
            missing.append("API_ID")
        if not cls.API_HASH:
            missing.append("API_HASH")
        if not cls.USER_SESSION_STRING:
            missing.append("USER_SESSION_STRING")
        
        if missing:
            return False, f"Missing: {', '.join(missing)}"
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

def format_result(text):
    """Format the result text with HTML"""
    if not text:
        return ""
    
    # Escape HTML and convert links
    text = html.escape(text)
    text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank">\1</a>', text)
    text = text.replace('\n', '<br>')
    return text

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
                logger.info(f"✅ Access confirmed: {chat.title}")
            except Exception as e:
                logger.warning(f"⚠️ Cannot access {channel_id}: {e}")
        
        bot_started = True
        return True
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization failed: {e}")
        bot_started = False
        return False

async def search_telegram_channels(query, limit=50):
    """Search in all Telegram channels - REAL DATA ONLY"""
    if not User or not bot_started:
        logger.error("❌ Telegram client not ready!")
        return []
    
    results = []
    logger.info(f"🔍 Searching for: '{query}'")
    
    try:
        # Search in text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching in channel: {channel_id}")
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=20
                ):
                    if message.text:
                        results.append({
                            'type': 'text',
                            'content': format_result(message.text)[:300] + "...",
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id
                        })
                        
            except errors.ChatAdminRequired:
                logger.error(f"❌ Admin required for {channel_id}")
            except errors.ChannelPrivate:
                logger.error(f"❌ Channel private: {channel_id}")
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} error: {e}")
                continue
        
        # Search in poster channel
        try:
            logger.info(f"🔍 Searching posters in: {Config.POSTER_CHANNEL_ID}")
            async for message in User.search_messages(
                chat_id=Config.POSTER_CHANNEL_ID,
                query=query,
                limit=20
            ):
                if message.caption:
                    result = {
                        'type': 'poster',
                        'content': format_result(message.caption)[:200] + "...",
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': Config.POSTER_CHANNEL_ID
                    }
                    
                    if message.photo:
                        result['photo'] = message.photo.file_id
                    
                    results.append(result)
                        
        except Exception as e:
            logger.warning(f"⚠️ Poster search error: {e}")
    
    except Exception as e:
        logger.error(f"❌ Search function error: {e}")
    
    # Sort by date (newest first)
    results.sort(key=lambda x: x['date'], reverse=True)
    final_results = results[:limit]
    
    logger.info(f"✅ Search completed: {len(final_results)} results")
    return final_results

async def get_real_posters(limit=12):
    """Get real posters from Telegram - NO MOCK DATA"""
    if not User or not bot_started:
        logger.error("❌ Telegram client not ready for posters!")
        return []
    
    posters = []
    try:
        logger.info(f"🖼️ Getting {limit} real posters...")
        
        async for message in User.get_chat_history(
            chat_id=Config.POSTER_CHANNEL_ID,
            limit=50  # Get more to filter for posters
        ):
            if message.caption and message.photo:
                # Extract movie name from caption
                caption_lines = message.caption.split('\n')
                movie_name = caption_lines[0] if caption_lines else "Movie"
                
                posters.append({
                    'photo': message.photo.file_id,
                    'caption': message.caption[:100] + "..." if len(message.caption) > 100 else message.caption,
                    'search_query': movie_name.replace('📽️', '').replace('🎬', '').strip(),
                    'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                    'message_id': message.id
                })
                
                if len(posters) >= limit:
                    break
        
        logger.info(f"✅ Found {len(posters)} real posters")
        
    except Exception as e:
        logger.error(f"❌ Error getting posters: {e}")
    
    return posters

# CORS setup
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'false')
    return response

@app.route('/options/<path:path>')
async def handle_options():
    return '', 200

# API endpoints
@app.route('/')
async def home():
    """Home endpoint with status"""
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM API",
        "mode": "REAL_DATA_ONLY",
        "telegram_connected": bot_started,
        "channels_configured": len(Config.TEXT_CHANNEL_IDS) + 1,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
async def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_ready": bot_started,
        "uptime": "running"
    })

@app.route('/api/health')
async def api_health():
    """API health check"""
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_connected": bot_started,
        "api_version": "1.0"
    })

@app.route('/api/search')
async def api_search():
    """Real search endpoint - NO MOCK DATA"""
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
        
        logger.info(f"🔍 API Search: '{query}' (limit: {limit})")
        
        # Perform real search
        results = await search_telegram_channels(query, limit)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results),
            "source": "REAL_TELEGRAM_CHANNELS",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Search API error: {e}")
        return jsonify({
            "status": "error",
            "message": "Search service temporarily unavailable"
        }), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """Real posters endpoint - NO MOCK DATA"""
    try:
        limit = int(request.args.get('limit', 8))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available",
                "telegram_connected": False
            }), 503
        
        logger.info(f"🖼️ API Posters request (limit: {limit})")
        
        # Get real posters
        posters = await get_real_posters(limit)
        
        return jsonify({
            "status": "success",
            "posters": posters,
            "count": len(posters),
            "source": "REAL_TELEGRAM_CHANNEL",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Posters API error: {e}")
        return jsonify({
            "status": "error",
            "message": "Failed to get posters"
        }), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve real poster images from Telegram"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id or file_id == 'null' or file_id == 'None':
            # Return placeholder SVG
            svg = '''<svg width="200" height="300" viewBox="0 0 200 300" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="200" height="300" fill="#333333"/>
                <text x="100" y="150" font-family="Arial, sans-serif" font-size="16" fill="#ffffff" text-anchor="middle">No Poster</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            logger.error("❌ Telegram not available for poster")
            return jsonify({"status": "service_unavailable"}), 503
        
        # Download image from Telegram
        file_data = await User.download_media(file_id, in_memory=True)
        
        return Response(
            file_data.getvalue(),
            mimetype='image/jpeg',
            headers={
                'Cache-Control': 'public, max-age=3600',
                'Content-Type': 'image/jpeg'
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Poster download error: {e}")
        # Return error SVG
        svg = '''<svg width="200" height="300" viewBox="0 0 200 300" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="200" height="300" fill="#ff0000"/>
            <text x="100" y="150" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Error Loading</text>
        </svg>'''
        return Response(svg, mimetype='image/svg+xml')

# FIXED: Proper async server startup
async def startup_app():
    """Initialize all services properly"""
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
        logger.info("✅ Real Telegram search ACTIVE!")
    else:
        logger.error("❌ Service initialization failed!")
    
    return success

async def shutdown_app():
    """Cleanup resources"""
    logger.info("🔄 Shutting down...")
    if User:
        try:
            await User.stop()
            logger.info("✅ Telegram client stopped")
        except:
            pass

# FIXED: Main execution
if __name__ == "__main__":
    async def main():
        """Main async function"""
        try:
            # Initialize services
            startup_success = await startup_app()
            
            if not startup_success:
                logger.error("❌ Cannot start server - initialization failed")
                return
            
            # Configure server
            config = HyperConfig()
            config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
            config.use_reloader = False
            
            logger.info(f"🌐 Server starting on port {Config.WEB_SERVER_PORT}")
            logger.info(f"🔗 Health check: http://localhost:{Config.WEB_SERVER_PORT}/health")
            
            # Start server
            await serve(app, config)
            
        except KeyboardInterrupt:
            logger.info("🛑 Server stopped by user")
        except Exception as e:
            logger.error(f"💥 Server startup failed: {e}")
        finally:
            await shutdown_app()
    
    # Run the main function
    asyncio.run(main())
