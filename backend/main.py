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
import math

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # WORKING CHANNELS (from your logs)
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]  # Movies Link, DISKWALA MOVIES
    POSTER_CHANNEL_ID = -1001891090100  # Use Movies Link for posters
    
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
    """Enhanced text formatting for proper display"""
    if not text:
        return ""
    
    # Basic HTML escape
    text = html.escape(text)
    
    # Convert URLs to clickable links
    text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff;">\1</a>', text)
    
    # Convert newlines to HTML breaks
    text = text.replace('\n', '<br>')
    
    # Format movie information
    text = re.sub(r'📁\s*(Size[^|]*)', r'<span class="text-info">📁 \1</span>', text)
    text = re.sub(r'📹\s*(Quality[^|]*)', r'<span class="text-success">📹 \1</span>', text)
    text = re.sub(r'⭐\s*(Rating[^|]*)', r'<span class="text-warning">⭐ \1</span>', text)
    text = re.sub(r'🎭\s*(Genre[^|]*)', r'<span class="text-primary">🎭 \1</span>', text)
    
    return text

async def initialize_telegram():
    """Initialize Telegram client with robust error handling"""
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
            workdir="/tmp"
        )
        
        await User.start()
        logger.info("✅ Telegram User Client started successfully!")
        
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username})")
        
        # Test channel access
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Access confirmed to channel: {chat.title}")
                working_channels.append(channel_id)
            except errors.PeerIdInvalid:
                logger.error(f"❌ Invalid peer ID: {channel_id}")
            except Exception as e:
                logger.warning(f"⚠️ Cannot access {channel_id}: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            Config.POSTER_CHANNEL_ID = working_channels[0]
            bot_started = True
            return True
        else:
            logger.error("❌ No accessible channels found!")
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization failed: {e}")
        return False

async def search_telegram_channels(query, limit=20, offset=0):
    """ENHANCED: Search with pagination support"""
    if not User or not bot_started:
        return {"results": [], "total": 0, "has_more": False}
    
    all_results = []
    logger.info(f"🔍 Searching for: '{query}' in {len(Config.TEXT_CHANNEL_IDS)} channels (offset: {offset}, limit: {limit})")
    
    try:
        # Search in all text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching in channel: {channel_id}")
                
                # Get more messages for pagination
                search_limit = max(50, limit + offset + 20)
                message_count = 0
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=search_limit
                ):
                    message_count += 1
                    if message.text:
                        # Enhanced result with more metadata
                        result = {
                            'type': 'text',
                            'content': format_result(message.text)[:1000] + ("..." if len(message.text) > 1000 else ""),
                            'raw_content': message.text[:200] + ("..." if len(message.text) > 200 else ""),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'has_links': bool(re.search(r'https?://', message.text or '')),
                            'movie_info': extract_movie_info(message.text)
                        }
                        all_results.append(result)
                        
                logger.info(f"✅ Found {message_count} messages in channel {channel_id}")
                
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} search error: {e}")
                continue
        
        # Search in poster channel for images
        try:
            logger.info(f"🔍 Searching posters in channel: {Config.POSTER_CHANNEL_ID}")
            poster_count = 0
            
            async for message in User.search_messages(
                chat_id=Config.POSTER_CHANNEL_ID,
                query=query,
                limit=30
            ):
                poster_count += 1
                if message.caption and message.photo:
                    result = {
                        'type': 'poster',
                        'content': format_result(message.caption)[:800] + ("..." if len(message.caption) > 800 else ""),
                        'raw_content': message.caption[:200] + ("..." if len(message.caption) > 200 else ""),
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': Config.POSTER_CHANNEL_ID,
                        'channel_name': 'Movies Link',
                        'photo': message.photo.file_id,
                        'has_links': bool(re.search(r'https?://', message.caption or '')),
                        'movie_info': extract_movie_info(message.caption)
                    }
                    all_results.append(result)
                    
            logger.info(f"✅ Found {poster_count} poster messages")
            
        except Exception as e:
            logger.warning(f"⚠️ Poster channel search error: {e}")
        
        # Sort by date (newest first)
        all_results.sort(key=lambda x: x['date'], reverse=True)
        
        # Calculate pagination
        total_results = len(all_results)
        start_index = offset
        end_index = offset + limit
        paginated_results = all_results[start_index:end_index]
        has_more = end_index < total_results
        
        logger.info(f"✅ Total search results: {total_results}, returning {len(paginated_results)} (offset: {offset})")
        
        return {
            "results": paginated_results,
            "total": total_results,
            "has_more": has_more,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"❌ Search function error: {e}")
        return {"results": [], "total": 0, "has_more": False}

def extract_movie_info(text):
    """Extract movie metadata from text"""
    if not text:
        return {}
    
    info = {}
    
    # Extract common patterns
    size_match = re.search(r'📁[^|]*Size[^|]*?([0-9.]+\s*[GMK]B)', text, re.IGNORECASE)
    if size_match:
        info['size'] = size_match.group(1)
    
    quality_match = re.search(r'📹[^|]*Quality[^|]*?([0-9]+p)', text, re.IGNORECASE)
    if quality_match:
        info['quality'] = quality_match.group(1)
    
    rating_match = re.search(r'⭐[^|]*Rating[^|]*?([0-9.]+)', text, re.IGNORECASE)
    if rating_match:
        info['rating'] = rating_match.group(1)
    
    # Extract year
    year_match = re.search(r'\((\d{4})\)', text)
    if year_match:
        info['year'] = year_match.group(1)
    
    return info

async def get_real_posters(limit=12, offset=0):
    """Get posters with pagination support"""
    if not User or not bot_started:
        return {"posters": [], "total": 0, "has_more": False}
    
    all_posters = []
    
    try:
        logger.info(f"🖼️ Getting posters (offset: {offset}, limit: {limit})...")
        
        # Get from all working channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                poster_limit = max(50, limit + offset + 20)
                
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=poster_limit
                ):
                    if message.photo and message.caption:
                        caption_lines = message.caption.split('\n')
                        movie_name = caption_lines[0] if caption_lines else "Movie"
                        
                        poster = {
                            'photo': message.photo.file_id,
                            'caption': message.caption[:200] + ("..." if len(message.caption) > 200 else ""),
                            'full_caption': message.caption,
                            'search_query': movie_name.replace('📽️', '').replace('🎬', '').strip(),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'movie_info': extract_movie_info(message.caption)
                        }
                        all_posters.append(poster)
                        
                logger.info(f"✅ Found posters in channel {channel_id}")
                
            except Exception as e:
                logger.warning(f"⚠️ Poster channel {channel_id} error: {e}")
                continue
        
        # Sort by date (newest first)
        all_posters.sort(key=lambda x: x['date'], reverse=True)
        
        # Calculate pagination
        total_posters = len(all_posters)
        start_index = offset
        end_index = offset + limit
        paginated_posters = all_posters[start_index:end_index]
        has_more = end_index < total_posters
        
        logger.info(f"✅ Total posters: {total_posters}, returning {len(paginated_posters)}")
        
        return {
            "posters": paginated_posters,
            "total": total_posters,
            "has_more": has_more,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_posters / limit) if total_posters > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting posters: {e}")
        return {"posters": [], "total": 0, "has_more": False}

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
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM API",
        "mode": "REAL_DATA_WITH_PAGINATION",
        "telegram_connected": bot_started,
        "channels_working": len(Config.TEXT_CHANNEL_IDS) if bot_started else 0,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
async def health():
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_ready": bot_started,
        "channels_count": len(Config.TEXT_CHANNEL_IDS) if bot_started else 0
    })

@app.route('/api/search')
async def api_search():
    """ENHANCED: Search with pagination support"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 10))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
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
        
        logger.info(f"🔍 API Search request: '{query}' (page: {page}, limit: {limit})")
        
        # Perform search with timeout
        try:
            search_result = await asyncio.wait_for(
                search_telegram_channels(query, limit, offset),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Search timeout for query: {query}")
            return jsonify({
                "status": "error",
                "message": "Search timeout - please try again"
            }), 408
        
        response_data = {
            "status": "success",
            "query": query,
            "results": search_result["results"],
            "pagination": {
                "current_page": search_result["current_page"],
                "total_pages": search_result["total_pages"],
                "has_more": search_result["has_more"],
                "total_results": search_result["total"],
                "results_per_page": limit
            },
            "source": "REAL_TELEGRAM_CHANNELS",
            "searched_channels": len(Config.TEXT_CHANNEL_IDS),
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"✅ Search completed: {len(search_result['results'])} results (page {page}/{search_result['total_pages']})")
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
    """ENHANCED: Latest posters with pagination"""
    try:
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available",
                "telegram_connected": False
            }), 503
        
        logger.info(f"🖼️ API Posters request (page: {page}, limit: {limit})")
        
        try:
            poster_result = await asyncio.wait_for(
                get_real_posters(limit, offset),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error("❌ Posters request timeout")
            return jsonify({
                "status": "error",
                "message": "Request timeout"
            }), 408
        
        response_data = {
            "status": "success",
            "posters": poster_result["posters"],
            "pagination": {
                "current_page": poster_result["current_page"],
                "total_pages": poster_result["total_pages"],
                "has_more": poster_result["has_more"],
                "total_posters": poster_result["total"],
                "results_per_page": limit
            },
            "source": "REAL_TELEGRAM_CHANNELS",
            "timestamp": datetime.now().isoformat()
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Posters API error: {e}")
        return jsonify({
            "status": "error",
            "message": "Failed to get posters",
            "error_details": str(e)
        }), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster images with caching"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id or file_id == 'null':
            svg = '''<svg width="300" height="400" fill="#333333"><rect width="300" height="400" fill="#333333"/><text x="50%" y="50%" font-family="Arial" font-size="18" fill="#ffffff" text-anchor="middle" dy=".3em">No Poster Available</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            svg = '''<svg width="300" height="400" fill="#ff6600"><rect width="300" height="400" fill="#ff6600"/><text x="50%" y="50%" font-family="Arial" font-size="16" fill="#ffffff" text-anchor="middle" dy=".3em">Service Unavailable</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        # Download with timeout
        try:
            file_data = await asyncio.wait_for(
                User.download_media(file_id, in_memory=True),
                timeout=20.0
            )
            
            return Response(
                file_data.getvalue(),
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'public, max-age=86400',  # 24 hours cache
                    'Content-Type': 'image/jpeg',
                    'X-Content-Source': 'telegram'
                }
            )
        except asyncio.TimeoutError:
            svg = '''<svg width="300" height="400" fill="#ff9900"><rect width="300" height="400" fill="#ff9900"/><text x="50%" y="50%" font-family="Arial" font-size="14" fill="#ffffff" text-anchor="middle" dy=".3em">Loading Timeout</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
            
    except Exception as e:
        logger.error(f"❌ Poster download error: {e}")
        svg = '''<svg width="300" height="400" fill="#ff0000"><rect width="300" height="400" fill="#ff0000"/><text x="50%" y="50%" font-family="Arial" font-size="16" fill="#ffffff" text-anchor="middle" dy=".3em">Error Loading</text></svg>'''
        return Response(svg, mimetype='image/svg+xml')

# FIXED: Proper async lifecycle
async def cleanup():
    global User, bot_started
    
    logger.info("🔄 Shutting down gracefully...")
    bot_started = False
    
    if User:
        try:
            await asyncio.wait_for(User.stop(), timeout=5.0)
            logger.info("✅ Telegram client stopped")
        except:
            logger.warning("⚠️ Telegram shutdown timeout")
        finally:
            User = None

def signal_handler(signum, frame):
    logger.info(f"🛑 Received signal {signum}")
    shutdown_event.set()

async def run_server():
    global shutdown_event
    
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting SK4FiLM Backend...")
        
        # Initialize services
        success = await initialize_telegram()
        
        if success:
            logger.info("✅ All services ready!")
            logger.info("✅ Real Telegram search with PAGINATION active!")
        else:
            logger.error("❌ Service initialization failed!")
        
        # Start server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.use_reloader = False
        
        logger.info(f"🌐 Server starting on port {Config.WEB_SERVER_PORT}")
        
        server_task = asyncio.create_task(serve(app, config))
        await shutdown_event.wait()
        
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            logger.info("✅ Server stopped")
        
    except Exception as e:
        logger.error(f"💥 Server error: {e}")
    finally:
        await cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)
