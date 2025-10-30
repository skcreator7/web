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
import math
import aiohttp
import urllib.parse

# Configuration - Text Channels Only
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # ONLY Working Text Channels
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # IMDB API Configuration
    OMDB_API_KEY = "8265bd1c"  # Free OMDB API key
    TMDB_API_KEY = "8265bd1c"  # Fallback API

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

User = None
bot_started = False

def safe_format_text(text):
    """Clean text formatting for display"""
    if not text:
        return ""
    
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')
        
        # Basic cleaning
        text = html.escape(text)
        
        # Convert URLs to clickable links
        text = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; text-decoration: underline;">\1</a>', text)
        
        # Convert newlines
        text = text.replace('\n', '<br>')
        
        # Movie info formatting
        text = re.sub(r'📁\s*(Size[^|<br>]*)', r'<div class="movie-tag">📁 \1</div>', text)
        text = re.sub(r'📹\s*(Quality[^|<br>]*)', r'<div class="movie-tag">📹 \1</div>', text)
        text = re.sub(r'⭐\s*(Rating[^|<br>]*)', r'<div class="movie-tag">⭐ \1</div>', text)
        
        return text
        
    except Exception as e:
        logger.warning(f"Text formatting error: {e}")
        return str(text)

def extract_movie_title_from_text(text):
    """Extract clean movie title from telegram post"""
    if not text:
        return None
    
    try:
        # Remove emojis and get first meaningful line
        clean_text = re.sub(r'[^\w\s\(\)\-\.\:]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        # Common patterns for movie titles
        patterns = [
            r'^([^(]+?)\s*\(\d{4}\)',  # "Movie Name (2023)"
            r'^([^-]+?)\s*-\s*\d{4}',  # "Movie Name - 2023"
            r'^([^-]{10,50})\s*-',     # "Movie Name - other info"
            r'^(\w+(?:\s+\w+){1,4})',  # First 2-5 words
        ]
        
        for pattern in patterns:
            match = re.match(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if len(title) > 3 and not re.match(r'^\d+$', title):
                    return ' '.join(title.split())[:50]
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

async def get_imdb_poster(movie_title):
    """Get poster from OMDB API (IMDB data)"""
    if not movie_title:
        return None
    
    try:
        logger.info(f"🎬 Getting IMDB poster for: {movie_title}")
        
        async with aiohttp.ClientSession() as session:
            # OMDB API call
            url = f"http://www.omdbapi.com/?t={urllib.parse.quote(movie_title)}&apikey={Config.OMDB_API_KEY}"
            
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('Response') == 'True' and data.get('Poster') and data['Poster'] != 'N/A':
                        poster_url = data['Poster']
                        logger.info(f"✅ IMDB poster found: {poster_url}")
                        
                        return {
                            'poster_url': poster_url,
                            'imdb_title': data.get('Title', movie_title),
                            'year': data.get('Year', 'N/A'),
                            'rating': data.get('imdbRating', 'N/A'),
                            'genre': data.get('Genre', 'N/A'),
                            'plot': data.get('Plot', 'N/A')
                        }
                    else:
                        logger.info(f"⚠️ No IMDB poster for: {movie_title}")
                        return None
                else:
                    logger.warning(f"❌ OMDB API error: {response.status}")
                    return None
                    
    except Exception as e:
        logger.warning(f"⚠️ IMDB API error: {e}")
        return None

async def get_30_recent_posts_with_imdb():
    """Get 30 recent posts from text channels with IMDB posters"""
    if not User or not bot_started:
        return []
    
    try:
        logger.info("📝 Getting 30 recent posts from text channels...")
        
        all_posts = []
        
        # Get recent posts from both text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"📋 Getting recent posts from: {channel_id}")
                
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=50  # Get more to ensure variety
                ):
                    if message.text and len(message.text) > 50:
                        # Extract movie title
                        movie_title = extract_movie_title_from_text(message.text)
                        
                        if movie_title:
                            post_item = {
                                'title': movie_title,
                                'full_text': message.text,
                                'display_text': message.text[:120] + ('...' if len(message.text) > 120 else ''),
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'has_links': bool(re.search(r'https?://', message.text)),
                                'link_count': len(re.findall(r'https?://[^\s]+', message.text))
                            }
                            
                            all_posts.append(post_item)
                            
                            if len(all_posts) >= 40:  # Get extra for variety
                                break
                            
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
                continue
        
        if not all_posts:
            logger.warning("⚠️ No recent posts found")
            return []
        
        # Sort by date (newest first)
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        # Get unique movies (avoid duplicates)
        seen_titles = set()
        unique_posts = []
        
        for post in all_posts[:30]:  # Take top 30
            title_key = post['title'].lower().strip()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_posts.append(post)
        
        logger.info(f"✅ Got {len(unique_posts)} unique recent posts")
        
        # Add IMDB posters to each post
        enhanced_posts = []
        for i, post in enumerate(unique_posts):
            try:
                logger.info(f"🎬 Getting IMDB data {i+1}/{len(unique_posts)}: {post['title']}")
                
                imdb_data = await get_imdb_poster(post['title'])
                
                if imdb_data:
                    post.update({
                        'imdb_poster': imdb_data['poster_url'],
                        'imdb_year': imdb_data['year'],
                        'imdb_rating': imdb_data['rating'],
                        'imdb_genre': imdb_data['genre'],
                        'has_imdb_data': True
                    })
                else:
                    # Create title-based placeholder
                    post.update({
                        'imdb_poster': None,
                        'has_imdb_data': False,
                        'placeholder_text': post['title']
                    })
                
                enhanced_posts.append(post)
                
                # Small delay to avoid API rate limits
                await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.warning(f"Post enhancement error: {e}")
                continue
        
        logger.info(f"✅ Enhanced {len(enhanced_posts)} posts with IMDB data")
        return enhanced_posts
        
    except Exception as e:
        logger.error(f"❌ Recent posts error: {e}")
        return []

async def search_text_channels_only(query, limit=20, offset=0):
    """Search ONLY in text channels - no poster channels"""
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    all_results = []
    
    try:
        logger.info(f"🔍 Searching ONLY text channels for: '{query}'")
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"📝 Searching text channel: {channel_id}")
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=100  # Get more for better results
                ):
                    if message.text and len(message.text) > 20:
                        result = {
                            'type': 'text',
                            'content': safe_format_text(message.text),
                            'raw_text': message.text,
                            'title': extract_movie_title_from_text(message.text),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'has_links': bool(re.search(r'https?://', message.text)),
                            'link_count': len(re.findall(r'https?://[^\s]+', message.text)),
                            'text_length': len(message.text)
                        }
                        all_results.append(result)
                        
            except Exception as e:
                logger.warning(f"Text channel {channel_id} search error: {e}")
                continue
        
        # Sort by date (newest first)
        all_results.sort(key=lambda x: x['date'], reverse=True)
        
        total_results = len(all_results)
        paginated_results = all_results[offset:offset + limit]
        
        logger.info(f"✅ Text-only search completed: {len(paginated_results)}/{total_results} results")
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"Text search error: {e}")
        return {"results": [], "total": 0}

async def initialize_telegram_text_only():
    """Initialize ONLY text channels"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram - TEXT CHANNELS ONLY...")
        
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
        
        # Verify ONLY text channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Text channel OK: {chat.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} error: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            logger.info(f"🎉 TEXT-ONLY MODE ACTIVE! Channels: {working_channels}")
            return True
        else:
            logger.error("❌ No working text channels!")
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
        "service": "SK4FiLM API v5.0 - REAL DATA + IMDB",
        "mode": "TEXT_CHANNELS_ONLY_WITH_IMDB_POSTERS",
        "telegram_connected": bot_started,
        "text_channels": Config.TEXT_CHANNEL_IDS,
        "features": ["real_data_only", "imdb_posters", "title_based_display"],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/search')
async def api_search():
    """Search API - text channels only"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Telegram service unavailable"}), 503
        
        logger.info(f"🔍 TEXT-ONLY Search: '{query}' (page: {page})")
        
        search_result = await search_text_channels_only(query, limit, offset)
        
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
            "source": "TEXT_CHANNELS_ONLY_REAL_DATA",
            "channels": Config.TEXT_CHANNEL_IDS,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/latest_posts')
async def api_latest_posts():
    """NEW: Get recent posts with IMDB posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available"
            }), 503
        
        logger.info(f"📋 Getting {limit} recent posts with IMDB posters...")
        
        recent_posts = await get_30_recent_posts_with_imdb()
        
        if recent_posts:
            return jsonify({
                "status": "success",
                "posts": recent_posts[:limit],
                "count": len(recent_posts[:limit]),
                "source": "TEXT_CHANNELS_WITH_IMDB_POSTERS",
                "mode": "REAL_DATA_ONLY",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "message": "No recent posts available"
            }), 404
            
    except Exception as e:
        logger.error(f"Latest posts API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/proxy_image')
async def proxy_image():
    """Proxy IMDB images to avoid CORS issues"""
    try:
        image_url = request.args.get('url', '').strip()
        
        if not image_url or not image_url.startswith('http'):
            return Response("Invalid URL", status=400)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={'Cache-Control': 'public, max-age=3600'}
                    )
                else:
                    return Response("Image not found", status=404)
                    
    except Exception as e:
        logger.error(f"Image proxy error: {e}")
        return Response("Proxy error", status=500)

# Server startup
async def run_server():
    try:
        logger.info("🚀 SK4FiLM Server - REAL DATA + IMDB MODE")
        
        # Initialize text channels only
        success = await initialize_telegram_text_only()
        
        if success:
            logger.info("✅ TEXT-ONLY MODE ACTIVE!")
            logger.info("📝 Real data from text channels only")
            logger.info("🎬 IMDB posters for movie titles")
        else:
            logger.warning("⚠️ Telegram connection failed")
        
        # Start server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"💥 Server error: {e}")
    finally:
        if User:
            await User.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped")
