import asyncio
import os
import logging
import signal
import sys
from pyrogram import Client, errors
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import html
import re
from datetime import datetime
from io import BytesIO

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # FIXED: Updated Channel IDs (working channels from logs)
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]  # Movies Link, DISKWALA MOVIES
    POSTER_CHANNEL_ID = -1001891090100  # Use Movies Link for posters too
    
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
        return len(missing) == 0, missing

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
shutdown_event = asyncio.Event()

def format_result(text):
    """Format the result text with proper HTML"""
    if not text:
        return ""
    
    text = html.escape(text)
    text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank">\1</a>', text)
    text = text.replace('\n', '<br>')
    return text

async def initialize_telegram():
    """Initialize Telegram client with better error handling"""
    global User, bot_started
    
    is_valid, missing = Config.validate()
    if not is_valid:
        logger.error(f"❌ Configuration error - Missing: {', '.join(missing)}")
        return False
    
    try:
        logger.info("🔄 Initializing Telegram User Client...")
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"  # Use temp directory
        )
        
        await User.start()
        logger.info("✅ Telegram User Client started successfully!")
        
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username})")
        
        # Test channel access with better error handling
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Access confirmed to channel: {chat.title}")
                working_channels.append(channel_id)
            except errors.PeerIdInvalid:
                logger.error(f"❌ Invalid peer ID: {channel_id}")
            except errors.ChannelPrivate:
                logger.error(f"❌ Private channel: {channel_id}")
            except Exception as e:
                logger.warning(f"⚠️ Cannot access {channel_id}: {e}")
        
        if not working_channels:
            logger.error("❌ No accessible channels found!")
            return False
        
        # Update working channel list
        Config.TEXT_CHANNEL_IDS = working_channels
        Config.POSTER_CHANNEL_ID = working_channels[0]  # Use first working channel
        
        bot_started = True
        return True
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization failed: {e}")
        bot_started = False
        return False

async def search_telegram_channels(query, limit=50):
    """FIXED: Search with proper async handling"""
    if not User or not bot_started:
        logger.error("❌ Telegram client not ready!")
        return []
    
    results = []
    logger.info(f"🔍 Searching for: '{query}' in {len(Config.TEXT_CHANNEL_IDS)} channels")
    
    try:
        # Search in text channels with timeout
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching in channel: {channel_id}")
                message_count = 0
                
                # FIXED: Add timeout and proper error handling
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=15
                ):
                    message_count += 1
                    if message.text:
                        results.append({
                            'type': 'text',
                            'content': format_result(message.text)[:500] + "...",
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id
                        })
                        
                    # Break if we have enough results
                    if len(results) >= limit:
                        break
                
                logger.info(f"✅ Found {message_count} messages in channel {channel_id}")
                
            except errors.PeerIdInvalid:
                logger.error(f"❌ Invalid peer ID: {channel_id}")
                continue
            except errors.ChatAdminRequired:
                logger.error(f"❌ Admin access required for {channel_id}")
                continue
            except errors.ChannelPrivate:
                logger.error(f"❌ Channel private: {channel_id}")
                continue
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} error: {e}")
                continue
        
        # Sort by date (newest first)
        results.sort(key=lambda x: x['date'], reverse=True)
        final_results = results[:limit]
        
        logger.info(f"✅ Search completed: {len(final_results)} results")
        return final_results
        
    except Exception as e:
        logger.error(f"❌ Search function error: {e}")
        return []

async def get_real_posters(limit=12):
    """FIXED: Get posters with proper channel handling"""
    if not User or not bot_started:
        logger.error("❌ Telegram client not ready!")
        return []
    
    posters = []
    try:
        logger.info(f"🖼️ Getting {limit} real posters from working channels...")
        
        # Get from all working channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🖼️ Getting posters from channel: {channel_id}")
                
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=30
                ):
                    # Check if message has photo
                    if message.photo and message.caption:
                        caption_lines = message.caption.split('\n')
                        movie_name = caption_lines[0] if caption_lines else "Movie"
                        
                        posters.append({
                            'photo': message.photo.file_id,
                            'caption': message.caption[:150] + "..." if len(message.caption) > 150 else message.caption,
                            'search_query': movie_name.replace('📽️', '').replace('🎬', '').strip(),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id
                        })
                        
                        if len(posters) >= limit:
                            break
                
                if len(posters) >= limit:
                    break
                    
            except errors.PeerIdInvalid:
                logger.error(f"❌ Invalid poster channel: {channel_id}")
                continue
            except Exception as e:
                logger.warning(f"⚠️ Poster channel {channel_id} error: {e}")
                continue
        
        logger.info(f"✅ Found {len(posters)} real posters")
        return posters[:limit]
        
    except Exception as e:
        logger.error(f"❌ Error getting posters: {e}")
        return []

# CORS setup
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/options/<path:path>')
async def handle_options():
    return '', 200

# API endpoints
@app.route('/')
async def home():
    """Home endpoint with comprehensive status"""
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM API",
        "mode": "REAL_DATA_ONLY",
        "telegram_connected": bot_started,
        "channels_configured": len(Config.TEXT_CHANNEL_IDS) if bot_started else 0,
        "working_channels": Config.TEXT_CHANNEL_IDS if bot_started else [],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
async def health():
    """Enhanced health check"""
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_ready": bot_started,
        "uptime": "running",
        "channels_working": len(Config.TEXT_CHANNEL_IDS) if bot_started else 0
    })

@app.route('/api/search')
async def api_search():
    """FIXED: Enhanced search endpoint"""
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
        
        # Perform search with timeout
        try:
            results = await asyncio.wait_for(
                search_telegram_channels(query, limit),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Search timeout for query: {query}")
            results = []
        
        response_data = {
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results),
            "source": "REAL_TELEGRAM_CHANNELS",
            "searched_channels": len(Config.TEXT_CHANNEL_IDS),
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"✅ Search completed: {len(results)} results for '{query}'")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Search API error: {e}")
        return jsonify({
            "status": "error",
            "message": "Search service temporarily unavailable",
            "error_details": str(e)
        }), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """FIXED: Enhanced posters endpoint"""
    try:
        limit = int(request.args.get('limit', 8))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available",
                "telegram_connected": False
            }), 503
        
        logger.info(f"🖼️ API Posters request (limit: {limit})")
        
        # Get posters with timeout
        try:
            posters = await asyncio.wait_for(
                get_real_posters(limit),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error("❌ Posters request timeout")
            posters = []
        
        return jsonify({
            "status": "success",
            "posters": posters,
            "count": len(posters),
            "source": "REAL_TELEGRAM_CHANNELS",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Posters API error: {e}")
        return jsonify({
            "status": "error",
            "message": "Failed to get posters",
            "error_details": str(e)
        }), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """FIXED: Serve poster images with better error handling"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id or file_id == 'null':
            # Return placeholder SVG
            svg = '''<svg width="300" height="400" fill="#333333"><rect width="300" height="400" fill="#333333"/><text x="50%" y="50%" font-family="Arial" font-size="18" fill="#ffffff" text-anchor="middle" dy=".3em">No Poster Available</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            logger.error("❌ Telegram not available for poster")
            return jsonify({"error": "service_unavailable"}), 503
        
        # Download with timeout
        try:
            file_data = await asyncio.wait_for(
                User.download_media(file_id, in_memory=True),
                timeout=15.0
            )
            
            return Response(
                file_data.getvalue(),
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'public, max-age=86400',  # 24 hours cache
                    'Content-Type': 'image/jpeg'
                }
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Poster download timeout: {file_id}")
            # Return timeout SVG
            svg = '''<svg width="300" height="400" fill="#ff6b00"><rect width="300" height="400" fill="#ff6b00"/><text x="50%" y="50%" font-family="Arial" font-size="14" fill="#ffffff" text-anchor="middle" dy=".3em">Loading Timeout</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
            
    except Exception as e:
        logger.error(f"❌ Poster download error: {e}")
        # Return error SVG
        svg = '''<svg width="300" height="400" fill="#ff0000"><rect width="300" height="400" fill="#ff0000"/><text x="50%" y="50%" font-family="Arial" font-size="16" fill="#ffffff" text-anchor="middle" dy=".3em">Error Loading</text></svg>'''
        return Response(svg, mimetype='image/svg+xml')

# FIXED: Proper shutdown handling
async def cleanup():
    """Clean shutdown without event loop errors"""
    global User, bot_started
    
    logger.info("🔄 Shutting down gracefully...")
    bot_started = False
    
    if User:
        try:
            # Don't wait too long for shutdown
            await asyncio.wait_for(User.stop(), timeout=5.0)
            logger.info("✅ Telegram client stopped")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Telegram shutdown timeout - forcing close")
        except Exception as e:
            logger.warning(f"⚠️ Telegram shutdown error: {e}")
        finally:
            User = None

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"🛑 Received signal {signum}")
    shutdown_event.set()

# FIXED: Proper async server startup
async def run_server():
    """Main server function with proper lifecycle"""
    global shutdown_event
    
    try:
        # Setup signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting SK4FiLM Backend...")
        
        # Initialize Telegram
        success = await initialize_telegram()
        
        if success:
            logger.info("✅ All services ready!")
            logger.info("✅ Real Telegram search is ACTIVE!")
        else:
            logger.error("❌ Service initialization failed!")
            # Continue without Telegram (will use fallback)
        
        # Configure and start server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.use_reloader = False
        config.accesslog = None
        
        logger.info(f"🌐 Server starting on port {Config.WEB_SERVER_PORT}")
        
        # Create server task
        server_task = asyncio.create_task(serve(app, config))
        
        # Wait for shutdown signal
        await shutdown_event.wait()
        
        # Cancel server
        server_task.cancel()
        
        try:
            await server_task
        except asyncio.CancelledError:
            logger.info("✅ Server stopped")
        
    except Exception as e:
        logger.error(f"💥 Server error: {e}")
    finally:
        # Cleanup
        await cleanup()

# FIXED: Main execution
if __name__ == "__main__":
    try:
        # Run server with proper async handling
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)
