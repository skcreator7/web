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
import base64

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # WORKING CHANNELS (confirmed from logs)
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

def safe_format_text(text):
    """FIXED: Safe text formatting to avoid UTF errors"""
    if not text:
        return ""
    
    try:
        # Handle encoding issues
        if isinstance(text, bytes):
            try:
                text = text.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text = text.decode('latin-1')
                except UnicodeDecodeError:
                    text = str(text, errors='replace')
        
        # Clean text of problematic characters
        text = text.replace('\u0000', '').replace('\ufffd', '')
        
        # Escape HTML
        text = html.escape(text)
        
        # Convert URLs to links
        text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff;">\1</a>', text)
        
        # Convert newlines
        text = text.replace('\n', '<br>')
        
        # Format movie info tags
        text = re.sub(r'📁\s*(Size[^|]*)', r'<span class="badge bg-info">📁 \1</span>', text)
        text = re.sub(r'📹\s*(Quality[^|]*)', r'<span class="badge bg-success">📹 \1</span>', text)
        text = re.sub(r'⭐\s*(Rating[^|]*)', r'<span class="badge bg-warning">⭐ \1</span>', text)
        text = re.sub(r'🎭\s*(Genre[^|]*)', r'<span class="badge bg-primary">🎭 \1</span>', text)
        
        return text
        
    except Exception as e:
        logger.warning(f"⚠️ Text formatting error: {e}")
        return "Content formatting error"

async def initialize_telegram():
    """Initialize Telegram with enhanced error handling"""
    global User, bot_started
    
    is_valid, missing = Config.validate()
    if not is_valid:
        logger.error(f"❌ Missing config: {', '.join(missing)}")
        return False
    
    try:
        logger.info("🔄 Initializing Telegram User Client...")
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp",
            sleep_threshold=60
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username})")
        
        # Verify channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Access confirmed to channel: {chat.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} access issue: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            Config.POSTER_CHANNEL_ID = working_channels[0]
            bot_started = True
            logger.info("✅ All services ready!")
            return True
        else:
            logger.error("❌ No working channels!")
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram init failed: {e}")
        return False

async def search_telegram_channels(query, limit=20, offset=0):
    """FIXED: Enhanced search with proper error handling"""
    if not User or not bot_started:
        return {"results": [], "total": 0, "has_more": False}
    
    all_results = []
    logger.info(f"🔍 Searching for: '{query}' in {len(Config.TEXT_CHANNEL_IDS)} channels (offset: {offset}, limit: {limit})")
    
    try:
        # Search in text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching in channel: {channel_id}")
                message_count = 0
                
                # FIXED: Better search handling
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=max(50, limit + offset + 10)
                ):
                    message_count += 1
                    if message.text:
                        try:
                            # FIXED: Safe content processing
                            content = safe_format_text(message.text)
                            raw_content = message.text[:300] + ("..." if len(message.text) > 300 else "")
                            
                            result = {
                                'type': 'text',
                                'content': content[:1200] + ("..." if len(content) > 1200 else ""),
                                'raw_content': raw_content,
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'has_links': bool(re.search(r'https?://', message.text or '')),
                                'movie_info': extract_movie_info(message.text)
                            }
                            all_results.append(result)
                            
                        except Exception as e:
                            logger.warning(f"⚠️ Message processing error: {e}")
                            continue
                            
                logger.info(f"✅ Found {message_count} messages in channel {channel_id}")
                
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} search error: {e}")
                continue
        
        # FIXED: Search in poster channel for images
        try:
            logger.info(f"🔍 Searching posters in channel: {Config.POSTER_CHANNEL_ID}")
            poster_count = 0
            
            # Get messages with photos and captions
            async for message in User.get_chat_history(
                chat_id=Config.POSTER_CHANNEL_ID,
                limit=50
            ):
                if message.caption and message.photo and query.lower() in message.caption.lower():
                    poster_count += 1
                    try:
                        # Process poster result
                        content = safe_format_text(message.caption)
                        raw_content = message.caption[:300] + ("..." if len(message.caption) > 300 else "")
                        
                        result = {
                            'type': 'poster',
                            'content': content[:1000] + ("..." if len(content) > 1000 else ""),
                            'raw_content': raw_content,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': Config.POSTER_CHANNEL_ID,
                            'channel_name': 'Movies Link',
                            'photo': message.photo.file_id,  # REAL FILE ID
                            'has_links': bool(re.search(r'https?://', message.caption or '')),
                            'movie_info': extract_movie_info(message.caption)
                        }
                        all_results.append(result)
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Poster processing error: {e}")
                        continue
                        
            logger.info(f"✅ Found {poster_count} poster messages")
            
        except Exception as e:
            logger.warning(f"⚠️ Poster search error: {e}")
        
        # Sort and paginate
        all_results.sort(key=lambda x: x['date'], reverse=True)
        
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
    """Enhanced movie info extraction"""
    if not text:
        return {}
    
    info = {}
    
    try:
        # Extract file size
        size_match = re.search(r'(?:📁|Size)[^|]*?([0-9.]+\s*[GMK]B)', text, re.IGNORECASE)
        if size_match:
            info['size'] = size_match.group(1)
        
        # Extract quality
        quality_match = re.search(r'(?:📹|Quality)[^|]*?([0-9]+p)', text, re.IGNORECASE)
        if quality_match:
            info['quality'] = quality_match.group(1)
        
        # Extract rating
        rating_match = re.search(r'(?:⭐|Rating)[^|]*?([0-9.]+(?:/10)?)', text, re.IGNORECASE)
        if rating_match:
            info['rating'] = rating_match.group(1)
        
        # Extract year
        year_match = re.search(r'\((\d{4})\)', text)
        if year_match:
            info['year'] = year_match.group(1)
        
        # Extract genre
        genre_match = re.search(r'(?:🎭|Genre)[^|]*?([A-Za-z, ]+)', text, re.IGNORECASE)
        if genre_match:
            info['genre'] = genre_match.group(1).strip()
        
        return info
        
    except Exception as e:
        logger.warning(f"⚠️ Movie info extraction error: {e}")
        return {}

async def get_real_posters(limit=12, offset=0):
    """FIXED: Get real posters only from Telegram"""
    if not User or not bot_started:
        return {"posters": [], "total": 0, "has_more": False}
    
    all_posters = []
    
    try:
        logger.info(f"🖼️ Getting posters (offset: {offset}, limit: {limit})...")
        
        # Get from working channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                # Get recent messages with photos
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=100  # Get enough messages to find posters
                ):
                    # FIXED: Only process messages with actual photos
                    if message.photo and message.caption:
                        try:
                            caption_lines = message.caption.split('\n')
                            movie_name = caption_lines[0] if caption_lines else "Movie"
                            
                            poster = {
                                'photo': message.photo.file_id,  # REAL Telegram file_id
                                'caption': message.caption[:200] + ("..." if len(message.caption) > 200 else ""),
                                'full_caption': message.caption,
                                'search_query': movie_name.replace('📽️', '').replace('🎬', '').replace('🎭', '').replace('🎪', '').strip(),
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'movie_info': extract_movie_info(message.caption)
                            }
                            all_posters.append(poster)
                            
                        except Exception as e:
                            logger.warning(f"⚠️ Poster processing error: {e}")
                            continue
                
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
    return response

@app.route('/options/<path:path>')
async def handle_options():
    return '', 200

# API endpoints
@app.route('/')
async def home():
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM API v2.0",
        "mode": "REAL_DATA_WITH_PAGINATION",
        "telegram_connected": bot_started,
        "channels_working": len(Config.TEXT_CHANNEL_IDS) if bot_started else 0,
        "features": ["search", "pagination", "posters", "real_data"],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
async def health():
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_ready": bot_started,
        "channels_count": len(Config.TEXT_CHANNEL_IDS) if bot_started else 0,
        "version": "2.0"
    })

@app.route('/api/search')
async def api_search():
    """ENHANCED: Search with proper pagination"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 10))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        # Validate inputs
        if not query:
            return jsonify({
                "status": "error",
                "message": "Search query is required"
            }), 400
        
        if limit > 100:
            limit = 100  # Max limit
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available - Please wait for startup",
                "telegram_connected": False
            }), 503
        
        logger.info(f"🔍 API Search request: '{query}' (page: {page}, limit: {limit})")
        
        # Perform search with timeout
        try:
            search_result = await asyncio.wait_for(
                search_telegram_channels(query, limit, offset),
                timeout=35.0
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Search timeout for query: {query}")
            return jsonify({
                "status": "error",
                "message": "Search timeout - please try with shorter query"
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
                "results_per_page": limit,
                "showing_start": offset + 1,
                "showing_end": min(offset + limit, search_result["total"])
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
            "message": "Search service error",
            "error_details": str(e)
        }), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """ENHANCED: Latest posters with pagination"""
    try:
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if limit > 50:
            limit = 50  # Max limit for posters
        
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
                "message": "Posters request timeout"
            }), 408
        
        response_data = {
            "status": "success",
            "posters": poster_result["posters"],
            "pagination": {
                "current_page": poster_result["current_page"],
                "total_pages": poster_result["total_pages"],
                "has_more": poster_result["has_more"],
                "total_posters": poster_result["total"],
                "results_per_page": limit,
                "showing_start": offset + 1,
                "showing_end": min(offset + limit, poster_result["total"])
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
    """FIXED: Proper poster serving with validation"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        # FIXED: Validate file_id format
        if not file_id or file_id == 'null' or file_id == 'None' or 'placeholder' in file_id:
            # Return proper placeholder SVG
            svg = '''<svg width="300" height="400" viewBox="0 0 300 400" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="300" height="400" fill="#1a1a2e"/>
                <rect x="50" y="100" width="200" height="200" rx="10" fill="#16213e"/>
                <text x="150" y="210" font-family="Arial, sans-serif" font-size="16" fill="#ffffff" text-anchor="middle">No Poster</text>
                <text x="150" y="230" font-family="Arial, sans-serif" font-size="12" fill="#cccccc" text-anchor="middle">Available</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            svg = '''<svg width="300" height="400" viewBox="0 0 300 400" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="300" height="400" fill="#ff6600"/>
                <text x="150" y="200" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Service</text>
                <text x="150" y="220" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Unavailable</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        # FIXED: Validate file_id is proper Telegram format
        if not re.match(r'^[A-Za-z0-9_-]+$', file_id) or len(file_id) < 10:
            logger.warning(f"⚠️ Invalid file_id format: {file_id}")
            svg = '''<svg width="300" height="400" viewBox="0 0 300 400" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="300" height="400" fill="#ff3333"/>
                <text x="150" y="200" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Invalid</text>
                <text x="150" y="220" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">File ID</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        # Download image with timeout
        try:
            logger.info(f"📥 Downloading poster: {file_id}")
            file_data = await asyncio.wait_for(
                User.download_media(file_id, in_memory=True),
                timeout=20.0
            )
            
            logger.info(f"✅ Poster downloaded successfully: {len(file_data.getvalue())} bytes")
            
            return Response(
                file_data.getvalue(),
                mimetype='image/jpeg',
                headers={
                    'Cache-Control': 'public, max-age=86400',
                    'Content-Type': 'image/jpeg',
                    'X-Content-Source': 'telegram-real'
                }
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ Poster download timeout: {file_id}")
            svg = '''<svg width="300" height="400" viewBox="0 0 300 400" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="300" height="400" fill="#ff9900"/>
                <text x="150" y="200" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Download</text>
                <text x="150" y="220" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Timeout</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
            
    except Exception as e:
        logger.error(f"❌ Poster download error: {e}")
        svg = '''<svg width="300" height="400" viewBox="0 0 300 400" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="300" height="400" fill="#dc3545"/>
            <text x="150" y="200" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Download</text>
            <text x="150" y="220" font-family="Arial, sans-serif" font-size="14" fill="#ffffff" text-anchor="middle">Error</text>
        </svg>'''
        return Response(svg, mimetype='image/svg+xml')

# FIXED: Enhanced cleanup
async def cleanup():
    global User, bot_started
    
    logger.info("🔄 Shutting down gracefully...")
    bot_started = False
    
    if User:
        try:
            await asyncio.wait_for(User.stop(), timeout=3.0)
            logger.info("✅ Telegram client stopped")
        except:
            logger.warning("⚠️ Telegram shutdown timeout")
        finally:
            User = None

def signal_handler(signum, frame):
    logger.info(f"🛑 Received signal {signum}")
    shutdown_event.set()

# FIXED: Main server function
async def run_server():
    global shutdown_event
    
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting SK4FiLM Backend...")
        
        # Initialize Telegram
        success = await initialize_telegram()
        
        if success:
            logger.info("✅ Real Telegram search with PAGINATION active!")
        else:
            logger.error("❌ Service initialization failed!")
        
        # Configure server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.use_reloader = False
        config.accesslog = None
        
        logger.info(f"🌐 Server starting on port {Config.WEB_SERVER_PORT}")
        
        # Start server
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
