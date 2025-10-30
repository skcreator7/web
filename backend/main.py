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
    
    # Working channels from logs
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    POSTER_CHANNEL_ID = -1002708802395
    
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize app
app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

# Global variables
User = None
bot_started = False
shutdown_event = asyncio.Event()

def safe_format_text(text, max_length=None):
    """FIXED: Show FULL text without truncation unless specifically limited"""
    if not text:
        return ""
    
    try:
        # Handle encoding
        if isinstance(text, bytes):
            try:
                text = text.decode('utf-8')
            except UnicodeDecodeError:
                text = str(text, errors='replace')
        
        # Clean problematic characters
        text = text.replace('\u0000', '').replace('\ufffd', '')
        
        # FIXED: NO AUTOMATIC TRUNCATION - Show full text
        original_length = len(text)
        
        # Only truncate if specifically requested
        if max_length and len(text) > max_length:
            text = text[:max_length] + "..."
        
        # Escape HTML
        text = html.escape(text)
        
        # Convert URLs to clickable links
        text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; text-decoration: underline;">\1</a>', text)
        
        # Convert newlines to HTML breaks
        text = text.replace('\n', '<br>')
        
        # Enhanced formatting for movie information
        text = re.sub(r'📁\s*(Size[^|<br>]*)', r'<div class="movie-tag size-tag">📁 \1</div>', text)
        text = re.sub(r'📹\s*(Quality[^|<br>]*)', r'<div class="movie-tag quality-tag">📹 \1</div>', text)
        text = re.sub(r'⭐\s*(Rating[^|<br>]*)', r'<div class="movie-tag rating-tag">⭐ \1</div>', text)
        text = re.sub(r'🎭\s*(Genre[^|<br>]*)', r'<div class="movie-tag genre-tag">🎭 \1</div>', text)
        text = re.sub(r'🎵\s*(Audio[^|<br>]*)', r'<div class="movie-tag audio-tag">🎵 \1</div>', text)
        
        # Format movie titles (bold)
        text = re.sub(r'🎬\s*([^<br>]+)', r'<h6 class="movie-title-inline">🎬 \1</h6>', text)
        
        # Add metadata about text length
        logger.info(f"📝 Text processed: {original_length} chars -> {len(text)} chars (formatted)")
        
        return text
        
    except Exception as e:
        logger.warning(f"⚠️ Text formatting error: {e}")
        return f"<p class='text-warning'>Content formatting error: {str(e)}</p>"

async def search_telegram_channels(query, limit=20, offset=0):
    """FIXED: Return FULL message content without truncation"""
    if not User or not bot_started:
        return {"results": [], "total": 0, "has_more": False}
    
    all_results = []
    logger.info(f"🔍 Searching for: '{query}' (offset: {offset}, limit: {limit})")
    
    try:
        # Search in text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching in channel: {channel_id}")
                message_count = 0
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=max(100, limit + offset + 20)  # Get more messages for better results
                ):
                    message_count += 1
                    if message.text:
                        try:
                            # FIXED: Store COMPLETE message text
                            full_text = message.text
                            formatted_content = safe_format_text(full_text)  # NO max_length limit
                            
                            # Keep original text for copying
                            raw_content = full_text  # FULL TEXT for copying
                            
                            result = {
                                'type': 'text',
                                'content': formatted_content,  # COMPLETE formatted content
                                'raw_content': raw_content,    # FULL original text
                                'full_text': full_text,       # COMPLETE original text
                                'text_length': len(full_text),
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'has_links': bool(re.search(r'https?://', full_text or '')),
                                'link_count': len(re.findall(r'https?://[^\s]+', full_text or '')),
                                'movie_info': extract_movie_info(full_text)
                            }
                            all_results.append(result)
                            
                        except Exception as e:
                            logger.warning(f"⚠️ Message processing error: {e}")
                            continue
                            
                logger.info(f"✅ Found {message_count} messages in channel {channel_id}")
                
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} search error: {e}")
                continue
        
        # Search in poster channel
        try:
            logger.info(f"🔍 Searching posters in channel: {Config.POSTER_CHANNEL_ID}")
            poster_count = 0
            
            async for message in User.get_chat_history(
                chat_id=Config.POSTER_CHANNEL_ID,
                limit=100
            ):
                if message.caption and message.photo and query.lower() in message.caption.lower():
                    poster_count += 1
                    try:
                        # FIXED: Store COMPLETE caption text
                        full_caption = message.caption
                        formatted_content = safe_format_text(full_caption)  # NO truncation
                        
                        result = {
                            'type': 'poster',
                            'content': formatted_content,     # COMPLETE formatted caption
                            'raw_content': full_caption,      # FULL original caption
                            'full_text': full_caption,       # COMPLETE original caption
                            'text_length': len(full_caption),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': Config.POSTER_CHANNEL_ID,
                            'channel_name': 'Movies Link',
                            'photo': message.photo.file_id,
                            'has_links': bool(re.search(r'https?://', full_caption or '')),
                            'link_count': len(re.findall(r'https?://[^\s]+', full_caption or '')),
                            'movie_info': extract_movie_info(full_caption)
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
        
        logger.info(f"✅ Search completed: {len(paginated_results)} results (full text preserved)")
        
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
        # Extract all metadata
        size_match = re.search(r'(?:📁|Size)[^|<br>]*?([0-9.]+\s*[GMK]B)', text, re.IGNORECASE)
        if size_match:
            info['size'] = size_match.group(1)
        
        quality_match = re.search(r'(?:📹|Quality)[^|<br>]*?([0-9]+p)', text, re.IGNORECASE)
        if quality_match:
            info['quality'] = quality_match.group(1)
        
        rating_match = re.search(r'(?:⭐|Rating)[^|<br>]*?([0-9.]+(?:/10)?)', text, re.IGNORECASE)
        if rating_match:
            info['rating'] = rating_match.group(1)
        
        year_match = re.search(r'\((\d{4})\)', text)
        if year_match:
            info['year'] = year_match.group(1)
        
        genre_match = re.search(r'(?:🎭|Genre)[^|<br>]*?([A-Za-z, ]+)', text, re.IGNORECASE)
        if genre_match:
            info['genre'] = genre_match.group(1).strip()
            
        # Extract audio info
        audio_match = re.search(r'(?:🎵|Audio)[^|<br>]*?([^|<br>]+)', text, re.IGNORECASE)
        if audio_match:
            info['audio'] = audio_match.group(1).strip()
        
        return info
        
    except Exception as e:
        logger.warning(f"⚠️ Movie info extraction error: {e}")
        return {}

# Rest of the backend code remains same...
# (initialize_telegram, get_real_posters, API endpoints, etc.)

async def initialize_telegram():
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
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username})")
        
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Access confirmed to channel: {chat.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.warning(f"⚠️ Cannot access {channel_id}: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            Config.POSTER_CHANNEL_ID = working_channels[0]
            bot_started = True
            return True
        else:
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram init failed: {e}")
        return False

# CORS
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/')
async def home():
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM API v2.1 - FULL TEXT",
        "mode": "COMPLETE_POST_DISPLAY",
        "telegram_connected": bot_started,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/search')
async def api_search():
    """ENHANCED: Search with FULL text content"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 10))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        logger.info(f"🔍 API Search: '{query}' (page: {page}, limit: {limit})")
        
        search_result = await asyncio.wait_for(
            search_telegram_channels(query, limit, offset),
            timeout=40.0
        )
        
        return jsonify({
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
            "source": "REAL_TELEGRAM_FULL_TEXT",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Proper poster serving"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        # Validate file_id
        if not file_id or 'placeholder' in file_id:
            svg = '''<svg width="300" height="400" viewBox="0 0 300 400"><rect width="300" height="400" fill="#1a1a2e"/><text x="150" y="200" font-family="Arial" font-size="16" fill="#ffffff" text-anchor="middle">No Poster</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            svg = '''<svg width="300" height="400" viewBox="0 0 300 400"><rect width="300" height="400" fill="#ff6600"/><text x="150" y="200" font-family="Arial" font-size="14" fill="#ffffff" text-anchor="middle">Service Unavailable</text></svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        # Download poster
        file_data = await asyncio.wait_for(
            User.download_media(file_id, in_memory=True),
            timeout=25.0
        )
        
        return Response(
            file_data.getvalue(),
            mimetype='image/jpeg',
            headers={'Cache-Control': 'public, max-age=86400'}
        )
        
    except Exception as e:
        logger.error(f"❌ Poster error: {e}")
        svg = '''<svg width="300" height="400" viewBox="0 0 300 400"><rect width="300" height="400" fill="#dc3545"/><text x="150" y="200" font-family="Arial" font-size="14" fill="#ffffff" text-anchor="middle">Error Loading</text></svg>'''
        return Response(svg, mimetype='image/svg+xml')

# Cleanup and server code same as before...
async def cleanup():
    global User, bot_started
    logger.info("🔄 Shutting down...")
    bot_started = False
    if User:
        try:
            await asyncio.wait_for(User.stop(), timeout=3.0)
        except:
            pass
        User = None

def signal_handler(signum, frame):
    shutdown_event.set()

async def run_server():
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("🚀 Starting SK4FiLM Backend...")
        
        success = await initialize_telegram()
        if success:
            logger.info("✅ Full text search ACTIVE!")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        server_task = asyncio.create_task(serve(app, config))
        await shutdown_event.wait()
        
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        
    except Exception as e:
        logger.error(f"💥 Server error: {e}")
    finally:
        await cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)
