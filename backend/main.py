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

# Enhanced Configuration with Fallback
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # WORKING: Text channels (confirmed working)
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    # POSTER CHANNELS: Multiple options (fallback system)
    POSTER_CHANNEL_OPTIONS = [
        -1002708802395,  # Primary poster channel (if accessible)
        -1001891090100,  # Fallback: Use text channel for posters too
        -1002024811395   # Another fallback option
    ]
    
    # Will be set dynamically based on what's accessible
    ACTIVE_POSTER_CHANNEL = None
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

User = None
bot_started = False

def safe_format_text(text):
    """Enhanced text formatting"""
    if not text:
        return ""
    
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')
        
        # Clean text
        text = text.replace('\u0000', '').replace('\ufffd', '')
        text = html.escape(text)
        
        # Convert URLs to links
        text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; text-decoration: underline;">\1</a>', text)
        
        # Convert newlines
        text = text.replace('\n', '<br>')
        
        # Enhanced formatting for movie details
        text = re.sub(r'📁\s*(Size[^|<br>]*)', r'<div class="movie-tag">📁 \1</div>', text)
        text = re.sub(r'📹\s*(Quality[^|<br>]*)', r'<div class="movie-tag">📹 \1</div>', text)
        text = re.sub(r'⭐\s*(Rating[^|<br>]*)', r'<div class="movie-tag">⭐ \1</div>', text)
        
        return text
        
    except Exception as e:
        logger.warning(f"Text formatting error: {e}")
        return str(text)

def extract_movie_name_for_search(caption):
    """Extract clean movie name from any caption"""
    if not caption:
        return "movie"
    
    try:
        # Remove emojis and special chars
        clean = re.sub(r'[^\w\s\(\)\-\.]', ' ', caption)
        
        # Get first meaningful part
        first_line = clean.split('\n')[0].strip()
        
        # Extract movie name (before year, quality, etc)
        patterns = [
            r'^([^(]+?)(?:\s*\(|\s*-|\s*20\d{2}|\s*hindi|\s*english|\s*\d+p)',  # Before year/quality
            r'^([^-]+?)(?:\s*-)',  # Before dash
            r'^(\w+(?:\s+\w+){0,2})'  # First 1-3 words
        ]
        
        for pattern in patterns:
            match = re.match(pattern, first_line, re.IGNORECASE)
            if match:
                movie_name = match.group(1).strip()
                if movie_name and len(movie_name) > 2:
                    return ' '.join(movie_name.split())[:40]
        
        # Ultimate fallback
        words = first_line.split()[:2]
        return ' '.join(words) if words else "movie"
        
    except Exception as e:
        logger.warning(f"Movie name extraction error: {e}")
        return "movie"

async def get_30_posters_with_fallback():
    """Get 30 posters using fallback channel system"""
    posters = []
    
    if not User or not bot_started:
        return generate_mock_posters()
    
    # Try to get posters from active channel
    if Config.ACTIVE_POSTER_CHANNEL:
        try:
            logger.info(f"🖼️ Getting 30 posters from active channel: {Config.ACTIVE_POSTER_CHANNEL}")
            
            async for message in User.get_chat_history(
                chat_id=Config.ACTIVE_POSTER_CHANNEL,
                limit=50  # Get extra to ensure 30 valid ones
            ):
                if len(posters) >= 30:
                    break
                
                # Check if message has poster OR caption (flexible)
                if message.photo or (message.caption and len(message.caption) > 20):
                    try:
                        caption = message.caption or f"Movie {len(posters) + 1}"
                        search_name = extract_movie_name_for_search(caption)
                        
                        poster_item = {
                            'photo': message.photo.file_id if message.photo else None,
                            'caption': caption[:85] + ('...' if len(caption) > 85 else ''),
                            'full_caption': caption,
                            'search_query': search_name,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': Config.ACTIVE_POSTER_CHANNEL,
                            'channel_name': get_channel_name(Config.ACTIVE_POSTER_CHANNEL),
                            'has_poster': bool(message.photo),
                            'telegram_link': f"https://t.me/c/{str(Config.ACTIVE_POSTER_CHANNEL).replace('-100', '')}/{message.id}"
                        }
                        
                        posters.append(poster_item)
                        
                    except Exception as e:
                        logger.warning(f"Message processing error: {e}")
                        continue
            
            logger.info(f"✅ Got {len(posters)} items from active channel")
            return posters[:30]
            
        except Exception as e:
            logger.error(f"❌ Active channel error: {e}")
    
    # Fallback to mock posters
    logger.info("📦 Using mock posters as fallback")
    return generate_mock_posters()

def generate_mock_posters():
    """Generate 30 mock posters for fallback"""
    logger.info("🎭 Generating 30 mock posters")
    
    mock_movies = [
        "Animal (2023)", "Salaar (2023)", "Pushpa 2 The Rule (2024)", "Dunki (2023)", 
        "Tiger 3 (2023)", "Jawan (2023)", "Pathaan (2023)", "KGF Chapter 2 (2022)",
        "RRR (2022)", "Brahmastra (2022)", "Vikram (2022)", "Beast (2022)",
        "Avengers Endgame (2019)", "Spider-Man No Way Home", "The Batman (2022)",
        "Doctor Strange 2 (2022)", "Thor Love Thunder", "Fast X (2023)",
        "John Wick 4 (2023)", "Scream VI (2023)", "Avatar Way of Water",
        "Black Panther 2 (2022)", "Top Gun Maverick", "Dune (2021)",
        "No Time To Die (2021)", "Matrix Resurrections", "Venom 2 (2021)",
        "Eternals (2021)", "Shang-Chi (2021)", "F9 Fast Saga (2021)"
    ]
    
    mock_posters = []
    for i, movie in enumerate(mock_movies):
        mock_posters.append({
            'photo': None,
            'caption': f"{movie} - Action Drama",
            'full_caption': f"{movie} - High Quality Action Drama Movie",
            'search_query': movie.split('(')[0].strip(),
            'date': datetime.now().isoformat(),
            'message_id': 1000 + i,
            'channel_id': -1001891090100,
            'channel_name': 'SK4FiLM Mock',
            'has_poster': False,
            'is_mock': True
        })
    
    return mock_posters

def get_channel_name(channel_id):
    """Get user-friendly channel name"""
    names = {
        -1001891090100: "Movies Link",
        -1002024811395: "DISKWALA MOVIES", 
        -1002708802395: "SK4FiLM Posters"
    }
    return names.get(channel_id, "Unknown Channel")

async def search_text_channels(query, limit=20, offset=0):
    """Search in text channels for full movie content"""
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    all_results = []
    
    try:
        logger.info(f"🔍 Searching text channels for: '{query}'")
        
        # Search both text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"🔍 Searching channel: {channel_id}")
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=50
                ):
                    if message.text:
                        result = {
                            'type': 'text',
                            'content': safe_format_text(message.text),
                            'raw_text': message.text,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': get_channel_name(channel_id),
                            'has_links': bool(re.search(r'https?://', message.text or '')),
                            'link_count': len(re.findall(r'https?://[^\s]+', message.text or ''))
                        }
                        all_results.append(result)
                        
            except Exception as e:
                logger.warning(f"Channel {channel_id} search error: {e}")
                continue
        
        # Sort by date (newest first)
        all_results.sort(key=lambda x: x['date'], reverse=True)
        
        total_results = len(all_results)
        paginated_results = all_results[offset:offset + limit]
        
        logger.info(f"✅ Search completed: {len(paginated_results)} results")
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"results": [], "total": 0}

async def initialize_telegram_with_fallback():
    """Initialize Telegram with smart channel detection"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram with channel detection...")
        
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
        
        # Check text channels first (essential)
        working_text_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Text channel OK: {chat.title}")
                working_text_channels.append(channel_id)
            except Exception as e:
                logger.warning(f"⚠️ Text channel {channel_id} error: {e}")
        
        if not working_text_channels:
            logger.error("❌ No working text channels found!")
            return False
        
        Config.TEXT_CHANNEL_IDS = working_text_channels
        
        # Try poster channels with fallback
        logger.info("🖼️ Testing poster channel options...")
        
        for poster_channel_id in Config.POSTER_CHANNEL_OPTIONS:
            try:
                chat = await User.get_chat(poster_channel_id)
                logger.info(f"✅ POSTER CHANNEL FOUND: {chat.title} ({poster_channel_id})")
                Config.ACTIVE_POSTER_CHANNEL = poster_channel_id
                break
                
            except Exception as e:
                logger.warning(f"⚠️ Poster channel {poster_channel_id} not accessible: {e}")
                continue
        
        if not Config.ACTIVE_POSTER_CHANNEL:
            # Use first text channel as poster source
            Config.ACTIVE_POSTER_CHANNEL = working_text_channels[0]
            logger.info(f"📋 Using text channel {Config.ACTIVE_POSTER_CHANNEL} as poster source")
        
        bot_started = True
        logger.info(f"🎉 TELEGRAM READY! Text: {working_text_channels}, Poster: {Config.ACTIVE_POSTER_CHANNEL}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization failed: {e}")
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
        "service": "SK4FiLM API v4.0 - SMART CHANNEL DETECTION",
        "telegram_connected": bot_started,
        "active_poster_channel": Config.ACTIVE_POSTER_CHANNEL,
        "text_channels": Config.TEXT_CHANNEL_IDS,
        "mode": "FALLBACK_SYSTEM_ACTIVE",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/search')
async def api_search():
    """Search API with full text content"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        logger.info(f"🔍 API Search: '{query}' (page: {page}, limit: {limit})")
        
        search_result = await search_text_channels(query, limit, offset)
        
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
                "showing_end": min(offset + limit, search_result["total"]),
                "has_more": search_result["current_page"] < search_result["total_pages"]
            },
            "source": "TEXT_CHANNELS_FULL_CONTENT",
            "channels_used": Config.TEXT_CHANNEL_IDS,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """Get 30 latest posters from working channel"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            # Return mock data immediately if service unavailable
            mock_posters = generate_mock_posters()
            return jsonify({
                "status": "success",
                "posters": mock_posters[:limit],
                "count": len(mock_posters[:limit]),
                "source": "MOCK_FALLBACK_DATA",
                "message": "Service offline - using fallback data",
                "timestamp": datetime.now().isoformat()
            })
        
        logger.info(f"🖼️ Getting {limit} posters from active channel: {Config.ACTIVE_POSTER_CHANNEL}")
        
        channel_posters = await get_30_posters_with_fallback()
        
        return jsonify({
            "status": "success",
            "posters": channel_posters[:limit],
            "count": len(channel_posters[:limit]),
            "source": f"CHANNEL_{Config.ACTIVE_POSTER_CHANNEL}",
            "channel_name": get_channel_name(Config.ACTIVE_POSTER_CHANNEL),
            "mode": "SMART_FALLBACK_ACTIVE",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Latest posters API error: {e}")
        
        # Always return something
        mock_posters = generate_mock_posters()
        return jsonify({
            "status": "success",
            "posters": mock_posters[:30],
            "count": 30,
            "source": "EMERGENCY_FALLBACK",
            "message": f"Error: {str(e)}",
            "timestamp": datetime.now().isoformat()
        })

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster with better error handling"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        # Handle placeholder requests
        if not file_id or file_id == 'null' or 'placeholder' in file_id.lower():
            return create_placeholder_svg("No Poster")
        
        if not User or not bot_started:
            return create_placeholder_svg("Service Offline")
        
        logger.info(f"📥 Downloading poster: {file_id[:30]}...")
        
        # Download with timeout
        file_data = await asyncio.wait_for(
            User.download_media(file_id, in_memory=True),
            timeout=25.0
        )
        
        logger.info("✅ Poster downloaded")
        
        return Response(
            file_data.getvalue(),
            mimetype='image/jpeg',
            headers={
                'Cache-Control': 'public, max-age=3600',
                'Content-Type': 'image/jpeg'
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Poster error: {e}")
        return create_placeholder_svg("Load Failed")

def create_placeholder_svg(text):
    """Create SVG placeholder"""
    svg = f'''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#1a1a2e"/>
        <text x="50%" y="50%" text-anchor="middle" fill="#00ccff" font-size="14" font-family="Arial">{text}</text>
        </svg>'''
    return Response(svg, mimetype='image/svg+xml')

# Server startup
async def run_server():
    try:
        logger.info("🚀 SK4FiLM Server - SMART CHANNEL DETECTION")
        
        # Initialize with fallback detection
        telegram_success = await initialize_telegram_with_fallback()
        
        if telegram_success:
            logger.info("✅ TELEGRAM READY WITH SMART FALLBACK")
            logger.info(f"🖼️ Active poster source: {Config.ACTIVE_POSTER_CHANNEL}")
            logger.info(f"📝 Text channels: {Config.TEXT_CHANNEL_IDS}")
        else:
            logger.warning("⚠️ Telegram connection failed - API will use mock data")
        
        # Start web server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"💥 Server error: {e}")
    finally:
        if User:
            try:
                await User.stop()
            except:
                pass

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
