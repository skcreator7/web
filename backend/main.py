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
import math

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Channel Configuration
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]  # For search results
    POSTER_CHANNEL_ID = -1002708802395  # MAIN: Direct poster source
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

User = None
bot_started = False

def safe_format_text(text):
    """Simple text formatting"""
    if not text:
        return ""
    
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')
        
        # Clean and format
        text = html.escape(text)
        text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600;">\1</a>', text)
        text = text.replace('\n', '<br>')
        
        return text
        
    except Exception as e:
        logger.warning(f"Text formatting error: {e}")
        return str(text)

def extract_movie_name_from_caption(caption):
    """Extract clean movie name from telegram caption"""
    if not caption:
        return "movie"
    
    try:
        # Remove all emojis
        clean = re.sub(r'[^\w\s\(\)\-\.]', ' ', caption)
        
        # Get first line or sentence
        first_line = clean.split('\n')[0].strip()
        
        # Extract movie name (before year or quality indicators)
        movie_match = re.match(r'^([^(]+?)(?:\s*\(|\s*-|\s*20\d{2}|\s*hindi|\s*english|\s*\d+p)', first_line, re.IGNORECASE)
        
        if movie_match:
            movie_name = movie_match.group(1).strip()
            # Clean extra spaces
            movie_name = ' '.join(movie_name.split())
            return movie_name[:40] if movie_name else "movie"
        
        # Fallback: first 3 words
        words = first_line.split()[:3]
        return ' '.join(words) if words else "movie"
        
    except Exception as e:
        logger.warning(f"Movie name extraction error: {e}")
        return "movie"

async def get_exact_channel_posters(limit=30):
    """DIRECT: Get exactly what's posted in channel -1002708802395"""
    posters = []
    
    if not User or not bot_started:
        logger.warning("❌ Telegram not connected")
        return posters
    
    try:
        logger.info(f"🖼️ DIRECT SYNC: Getting exact uploads from {Config.POSTER_CHANNEL_ID}")
        
        message_count = 0
        async for message in User.get_chat_history(
            chat_id=Config.POSTER_CHANNEL_ID,
            limit=limit + 10  # Get a few extra to ensure we have enough valid ones
        ):
            # ONLY process messages that have BOTH poster AND caption
            if message.photo and message.caption:
                try:
                    original_caption = message.caption
                    movie_search_name = extract_movie_name_from_caption(original_caption)
                    
                    poster_item = {
                        'photo': message.photo.file_id,
                        'original_caption': original_caption,
                        'display_caption': original_caption[:90] + ('...' if len(original_caption) > 90 else ''),
                        'search_query': movie_search_name,
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': Config.POSTER_CHANNEL_ID,
                        'telegram_link': f"https://t.me/c/{str(Config.POSTER_CHANNEL_ID).replace('-100', '')}/{message.id}",
                        'is_valid': True
                    }
                    
                    posters.append(poster_item)
                    message_count += 1
                    
                    logger.info(f"📄 Added poster {message_count}: {movie_search_name}")
                    
                    # Stop when we have enough
                    if len(posters) >= limit:
                        break
                        
                except Exception as e:
                    logger.warning(f"⚠️ Poster processing error: {e}")
                    continue
            else:
                # Log what type of message was skipped
                if message.photo and not message.caption:
                    logger.debug("⏭️ Skipped: Photo without caption")
                elif message.caption and not message.photo:
                    logger.debug("⏭️ Skipped: Caption without photo")
        
        logger.info(f"✅ DIRECT SYNC COMPLETE: {len(posters)} valid posters from channel")
        return posters[:limit]  # Ensure exact limit
        
    except Exception as e:
        logger.error(f"❌ Direct channel sync error: {e}")
        return posters

async def search_telegram_channels(query, limit=20, offset=0):
    """Search in text channels for full content"""
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    all_results = []
    logger.info(f"🔍 Searching text channels for: '{query}'")
    
    try:
        # Search text channels for detailed content
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=50
                ):
                    if message.text:
                        result = {
                            'type': 'text',
                            'content': safe_format_text(message.text),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'link_count': len(re.findall(r'https?://[^\s]+', message.text or ''))
                        }
                        all_results.append(result)
                        
            except Exception as e:
                logger.warning(f"Text channel {channel_id} error: {e}")
                continue
        
        # Also search poster channel for matching content
        try:
            async for message in User.search_messages(
                chat_id=Config.POSTER_CHANNEL_ID,
                query=query,
                limit=30
            ):
                if message.caption and message.photo:
                    result = {
                        'type': 'poster',
                        'content': safe_format_text(message.caption),
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': Config.POSTER_CHANNEL_ID,
                        'channel_name': 'SK4FiLM Posters',
                        'photo': message.photo.file_id,
                        'link_count': len(re.findall(r'https?://[^\s]+', message.caption or ''))
                    }
                    all_results.append(result)
        except Exception as e:
            logger.warning(f"Poster channel search error: {e}")
        
        # Sort by date (newest first)
        all_results.sort(key=lambda x: x['date'], reverse=True)
        
        total_results = len(all_results)
        paginated_results = all_results[offset:offset + limit]
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"results": [], "total": 0}

async def initialize_telegram():
    """Initialize Telegram connection"""
    global User, bot_started
    
    try:
        logger.info("🔄 Connecting to Telegram...")
        
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected as: {me.first_name}")
        
        # Verify poster channel access
        try:
            poster_chat = await User.get_chat(Config.POSTER_CHANNEL_ID)
            logger.info(f"✅ Poster channel confirmed: {poster_chat.title}")
            bot_started = True
            return True
        except Exception as e:
            logger.error(f"❌ Cannot access poster channel {Config.POSTER_CHANNEL_ID}: {e}")
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram connection failed: {e}")
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
        "service": "SK4FiLM API - DIRECT CHANNEL SYNC",
        "poster_channel": Config.POSTER_CHANNEL_ID,
        "telegram_connected": bot_started,
        "mode": "EXACT_CHANNEL_UPLOADS",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/search')
async def api_search():
    """Search API for text channel content"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 10))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        logger.info(f"🔍 Search API: '{query}' (page: {page})")
        
        search_result = await search_telegram_channels(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": search_result["results"],
            "pagination": {
                "current_page": search_result["current_page"],
                "total_pages": search_result["total_pages"],
                "total_results": search_result["total"],
                "results_per_page": limit,
                "showing_start": offset + 1,
                "showing_end": min(offset + limit, search_result["total"])
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """MAIN: Get exactly what's uploaded in poster channel"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "error", 
                "message": "Telegram service not available"
            }), 503
        
        logger.info(f"🖼️ API: Getting {limit} exact uploads from channel {Config.POSTER_CHANNEL_ID}")
        
        # Get DIRECT channel uploads
        channel_posters = await get_exact_channel_posters(limit)
        
        if channel_posters:
            logger.info(f"✅ API SUCCESS: {len(channel_posters)} exact channel uploads")
            
            return jsonify({
                "status": "success",
                "posters": channel_posters,
                "count": len(channel_posters),
                "source": f"DIRECT_CHANNEL_{Config.POSTER_CHANNEL_ID}",
                "channel_name": "SK4FiLM Posters",
                "sync_mode": "EXACT_UPLOADS_ONLY",
                "timestamp": datetime.now().isoformat()
            })
        else:
            logger.warning("⚠️ No posters found in channel")
            
            return jsonify({
                "status": "error",
                "message": "No posters found in channel",
                "channel_id": Config.POSTER_CHANNEL_ID
            }), 404
            
    except Exception as e:
        logger.error(f"❌ Latest posters API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster images"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id or 'placeholder' in file_id.lower():
            # Return placeholder
            svg = '''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
                <rect width="100%" height="100%" fill="#1a1a2e"/>
                <text x="50%" y="50%" text-anchor="middle" fill="#00ccff" font-size="16">Loading...</text>
                </svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            svg = '''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
                <rect width="100%" height="100%" fill="#dc3545"/>
                <text x="50%" y="50%" text-anchor="middle" fill="white" font-size="14">Service Offline</text>
                </svg>'''
            return Response(svg, mimetype='image/svg+xml')
        
        logger.info(f"📥 Downloading poster: {file_id[:20]}...")
        
        # Download from Telegram
        file_data = await asyncio.wait_for(
            User.download_media(file_id, in_memory=True),
            timeout=20.0
        )
        
        logger.info("✅ Poster downloaded successfully")
        
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
        svg = '''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#6c757d"/>
            <text x="50%" y="50%" text-anchor="middle" fill="white" font-size="14">Failed to Load</text>
            </svg>'''
        return Response(svg, mimetype='image/svg+xml')

# Server startup
async def run_server():
    try:
        logger.info("🚀 Starting SK4FiLM Server - DIRECT CHANNEL SYNC MODE")
        
        # Initialize Telegram
        telegram_success = await initialize_telegram()
        
        if telegram_success:
            logger.info("✅ DIRECT SYNC MODE ACTIVE")
            logger.info(f"🖼️ Poster Source: Channel {Config.POSTER_CHANNEL_ID}")
            logger.info("📋 Will show EXACTLY what's uploaded in channel")
        else:
            logger.error("❌ Telegram connection failed - using fallback mode")
        
        # Start web server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"💥 Server startup error: {e}")
    finally:
        if User:
            await User.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
