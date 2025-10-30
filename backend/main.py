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
from io import BytesIO

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Working Text Channels
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # IMDB API Keys
    OMDB_API_KEY = "8265bd1c"  # Free OMDB API
    BACKUP_API_KEY = "b9bd48a6"  # Backup OMDB key

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

User = None
bot_started = False

def extract_movie_title_from_post(post_text):
    """Enhanced movie title extraction from telegram posts"""
    if not post_text:
        return None
    
    try:
        # Remove emojis and special characters
        clean_text = re.sub(r'[^\w\s\(\)\-\.\:\!\?\'\"]', ' ', post_text)
        
        # Get first meaningful line
        lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
        if not lines:
            return None
        
        first_line = lines[0]
        
        # Enhanced movie title patterns
        patterns = [
            r'^([^(]{3,50}?)\s*\(\d{4}\)',  # "Movie Name (2023)"
            r'^([^-]{5,50}?)\s*-\s*(?:\d{4}|Hindi|English|Action)',  # "Movie Name - 2023/Hindi/etc"
            r'^([^|]{5,50}?)\s*\|',  # "Movie Name | other info"
            r'^🎬\s*([^-\n]{5,50}?)(?:\s*-|\s*\n)',  # "🎬 Movie Name -"
            r'^([A-Za-z][^-\n]{4,40}?)(?:\s*-|\s*\n)',  # General pattern
            r'^(\w+(?:\s+\w+){1,5})',  # First 2-6 words
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                
                # Clean up title
                title = re.sub(r'\s+', ' ', title)  # Normalize spaces
                title = title.replace('Movie', '').replace('Film', '').strip()
                
                # Validate title
                if (3 <= len(title) <= 60 and 
                    not re.match(r'^\d+$', title) and 
                    not title.lower() in ['size', 'quality', 'rating', 'genre', 'audio']):
                    
                    logger.info(f"🎬 Extracted title: '{title}' from: '{first_line[:50]}...'")
                    return title
        
        # Fallback: Look for movie-like words
        movie_words = re.findall(r'\b[A-Z][a-z]{2,}\b', first_line)
        if len(movie_words) >= 2:
            potential_title = ' '.join(movie_words[:3])
            if 5 <= len(potential_title) <= 50:
                logger.info(f"🎯 Fallback title: '{potential_title}'")
                return potential_title
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

async def get_imdb_poster_data(movie_title, api_key):
    """Get IMDB poster and metadata"""
    try:
        logger.info(f"🎬 Getting IMDB data for: '{movie_title}'")
        
        async with aiohttp.ClientSession() as session:
            # Try exact match first
            url = f"http://www.omdbapi.com/?t={urllib.parse.quote(movie_title)}&apikey={api_key}&plot=short"
            
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('Response') == 'True':
                        poster_url = data.get('Poster')
                        
                        if poster_url and poster_url != 'N/A' and poster_url.startswith('http'):
                            imdb_data = {
                                'poster_url': poster_url,
                                'title': data.get('Title', movie_title),
                                'year': data.get('Year', 'Unknown'),
                                'rating': data.get('imdbRating', 'N/A'),
                                'genre': data.get('Genre', 'N/A'),
                                'plot': data.get('Plot', 'N/A'),
                                'director': data.get('Director', 'N/A'),
                                'actors': data.get('Actors', 'N/A'),
                                'runtime': data.get('Runtime', 'N/A'),
                                'imdb_id': data.get('imdbID', 'N/A'),
                                'success': True
                            }
                            
                            logger.info(f"✅ IMDB success: {poster_url}")
                            return imdb_data
                        else:
                            logger.info(f"⚠️ No poster available for: {movie_title}")
                    else:
                        logger.info(f"⚠️ Movie not found in IMDB: {movie_title}")
                else:
                    logger.warning(f"❌ OMDB API error: {response.status}")
        
        return {'success': False, 'error': 'No IMDB data found'}
        
    except Exception as e:
        logger.warning(f"IMDB API error: {e}")
        return {'success': False, 'error': str(e)}

async def get_latest_posts_with_imdb_posters(limit=30):
    """Get latest posts from text channels and add IMDB posters"""
    if not User or not bot_started:
        logger.warning("❌ Telegram not connected")
        return []
    
    try:
        logger.info("📝 Getting latest posts from text channels...")
        
        all_posts = []
        
        # Get recent posts from text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"📋 Channel {channel_id}: Getting recent posts...")
                
                post_count = 0
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=60  # Get extra for variety
                ):
                    if message.text and len(message.text) > 30:  # Meaningful posts only
                        # Extract movie title
                        movie_title = extract_movie_title_from_post(message.text)
                        
                        if movie_title:
                            post_item = {
                                'extracted_title': movie_title,
                                'original_text': message.text,
                                'display_text': message.text[:100] + ('...' if len(message.text) > 100 else ''),
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'has_links': bool(re.search(r'https?://', message.text)),
                                'link_count': len(re.findall(r'https?://[^\s]+', message.text))
                            }
                            
                            all_posts.append(post_item)
                            post_count += 1
                            
                            logger.info(f"📄 Post {post_count}: '{movie_title}' from {channel_id}")
                
                logger.info(f"✅ Channel {channel_id}: {post_count} posts extracted")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
                continue
        
        if not all_posts:
            logger.warning("⚠️ No posts found in any text channel")
            return []
        
        # Sort by date (newest first) and get unique titles
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        # Remove duplicates based on title
        seen_titles = set()
        unique_posts = []
        
        for post in all_posts:
            title_key = post['extracted_title'].lower().strip()
            if title_key not in seen_titles and len(unique_posts) < limit:
                seen_titles.add(title_key)
                unique_posts.append(post)
        
        logger.info(f"📊 Got {len(unique_posts)} unique movie titles")
        
        # Add IMDB posters to each post
        enhanced_posts = []
        
        for i, post in enumerate(unique_posts):
            try:
                logger.info(f"🎬 IMDB lookup {i+1}/{len(unique_posts)}: {post['extracted_title']}")
                
                # Try primary API key first
                imdb_data = await get_imdb_poster_data(post['extracted_title'], Config.OMDB_API_KEY)
                
                # Try backup key if primary fails
                if not imdb_data.get('success'):
                    logger.info("🔄 Trying backup API key...")
                    imdb_data = await get_imdb_poster_data(post['extracted_title'], Config.BACKUP_API_KEY)
                
                # Add IMDB data to post
                if imdb_data.get('success'):
                    post.update({
                        'imdb_poster': imdb_data['poster_url'],
                        'imdb_title': imdb_data['title'],
                        'imdb_year': imdb_data['year'],
                        'imdb_rating': imdb_data['rating'],
                        'imdb_genre': imdb_data['genre'],
                        'imdb_plot': imdb_data['plot'],
                        'has_imdb_poster': True
                    })
                    logger.info(f"✅ IMDB added: {post['extracted_title']}")
                else:
                    post.update({
                        'imdb_poster': None,
                        'has_imdb_poster': False,
                        'imdb_error': imdb_data.get('error', 'Unknown error')
                    })
                    logger.info(f"⚠️ No IMDB data: {post['extracted_title']}")
                
                enhanced_posts.append(post)
                
                # Small delay to avoid API rate limits
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.warning(f"Post enhancement error: {e}")
                continue
        
        logger.info(f"✅ Enhanced {len(enhanced_posts)} posts with IMDB data")
        return enhanced_posts
        
    except Exception as e:
        logger.error(f"❌ Latest posts error: {e}")
        return []

async def search_telegram_for_movie(query, limit=20, offset=0):
    """Search telegram channels for specific movie"""
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    all_results = []
    
    try:
        logger.info(f"🔍 Telegram search for movie: '{query}'")
        
        # Search all text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                logger.info(f"📝 Searching channel {channel_id}...")
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=50
                ):
                    if message.text and len(message.text) > 20:
                        result = {
                            'type': 'telegram_post',
                            'content': format_telegram_content(message.text),
                            'raw_text': message.text,
                            'title': extract_movie_title_from_post(message.text) or query,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'telegram_link': f"https://t.me/c/{str(channel_id).replace('-100', '')}/{message.id}",
                            'has_download_links': bool(re.search(r'https?://[^\s]+', message.text)),
                            'download_links': re.findall(r'https?://[^\s]+', message.text),
                            'link_count': len(re.findall(r'https?://[^\s]+', message.text))
                        }
                        
                        all_results.append(result)
                        
            except Exception as e:
                logger.warning(f"Channel {channel_id} search error: {e}")
                continue
        
        # Sort by relevance and date
        all_results.sort(key=lambda x: (x['link_count'], x['date']), reverse=True)
        
        total_results = len(all_results)
        paginated_results = all_results[offset:offset + limit]
        
        logger.info(f"✅ Telegram search completed: {len(paginated_results)}/{total_results} results")
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1,
            "query": query,
            "channels_searched": Config.TEXT_CHANNEL_IDS
        }
        
    except Exception as e:
        logger.error(f"Telegram search error: {e}")
        return {"results": [], "total": 0}

def format_telegram_content(text):
    """Enhanced telegram content formatting"""
    if not text:
        return ""
    
    try:
        # HTML escape
        formatted = html.escape(text)
        
        # Convert URLs to clickable links
        formatted = re.sub(
            r'(https?://[^\s]+)', 
            r'<a href="\1" target="_blank" class="download-link"><i class="fas fa-download me-1"></i>\1</a>', 
            formatted
        )
        
        # Convert newlines
        formatted = formatted.replace('\n', '<br>')
        
        # Enhanced movie info tags
        formatted = re.sub(r'📁\s*Size[:\s]*([^<br>|]+)', r'<span class="info-tag size-tag">📁 Size: \1</span>', formatted)
        formatted = re.sub(r'📹\s*Quality[:\s]*([^<br>|]+)', r'<span class="info-tag quality-tag">📹 Quality: \1</span>', formatted)
        formatted = re.sub(r'⭐\s*Rating[:\s]*([^<br>|]+)', r'<span class="info-tag rating-tag">⭐ Rating: \1</span>', formatted)
        formatted = re.sub(r'🎭\s*Genre[:\s]*([^<br>|]+)', r'<span class="info-tag genre-tag">🎭 Genre: \1</span>', formatted)
        formatted = re.sub(r'🎵\s*Audio[:\s]*([^<br>|]+)', r'<span class="info-tag audio-tag">🎵 Audio: \1</span>', formatted)
        
        # Movie title highlighting
        formatted = re.sub(r'🎬\s*([^<br>-]+)', r'<h6 class="movie-title-highlight">🎬 \1</h6>', formatted)
        
        return formatted
        
    except Exception as e:
        logger.warning(f"Content formatting error: {e}")
        return html.escape(str(text))

async def initialize_telegram():
    """Initialize telegram - text channels only"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram (Text Channels Only)...")
        
        User = Client(
            "sk4film_user",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected: {me.first_name} (@{me.username or 'no_username'})")
        
        # Verify text channels only
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Channel access OK: {chat.title} ({channel_id})")
                working_channels.append(channel_id)
            except Exception as e:
                logger.warning(f"⚠️ Channel {channel_id} access error: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            logger.info(f"🎉 TEXT CHANNELS READY: {working_channels}")
            return True
        else:
            logger.error("❌ No working channels found!")
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization error: {e}")
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
        "service": "SK4FiLM API - Latest Posts → IMDB Posters → Telegram Search",
        "version": "6.0",
        "mode": "TITLE_TO_IMDB_TO_SEARCH",
        "telegram_connected": bot_started,
        "text_channels": Config.TEXT_CHANNEL_IDS,
        "features": ["latest_posts", "imdb_posters", "telegram_search", "real_data_only"],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/latest_posts')
async def api_latest_posts():
    """MAIN API: Get latest posts with IMDB posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not connected"
            }), 503
        
        logger.info(f"🎬 API: Getting {limit} latest posts with IMDB posters...")
        
        # Get posts with IMDB integration
        posts_with_imdb = await get_latest_posts_with_imdb_posters(limit)
        
        if posts_with_imdb:
            logger.info(f"✅ API Success: {len(posts_with_imdb)} posts with IMDB data")
            
            return jsonify({
                "status": "success",
                "posts": posts_with_imdb,
                "count": len(posts_with_imdb),
                "source": "TEXT_CHANNELS_WITH_IMDB_INTEGRATION",
                "channels": Config.TEXT_CHANNEL_IDS,
                "api_mode": "LATEST_POSTS_IMDB_POSTERS",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "message": "No recent posts found with extractable movie titles"
            }), 404
            
    except Exception as e:
        logger.error(f"❌ Latest posts API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """Search API for telegram channels"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Search query required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Telegram service unavailable"}), 503
        
        logger.info(f"🔍 Search API: '{query}' (page: {page}, limit: {limit})")
        
        search_result = await search_telegram_for_movie(query, limit, offset)
        
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
            "source": "TELEGRAM_CHANNELS_SEARCH",
            "channels_searched": search_result.get("channels_searched", []),
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/proxy_poster')
async def proxy_poster():
    """Proxy IMDB posters to avoid CORS"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url or not poster_url.startswith('http'):
            return create_placeholder_image("Invalid URL")
        
        logger.info(f"🖼️ Proxying IMDB poster: {poster_url[:50]}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info("✅ IMDB poster proxied successfully")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Cache-Control': 'public, max-age=7200',
                            'Content-Type': content_type
                        }
                    )
                else:
                    logger.warning(f"❌ Poster response error: {response.status}")
                    return create_placeholder_image("Load Error")
                    
    except Exception as e:
        logger.error(f"❌ Poster proxy error: {e}")
        return create_placeholder_image("Proxy Error")

def create_placeholder_image(text):
    """Create placeholder image"""
    svg = f'''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="100%" style="stop-color:#16213e"/>
            </linearGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#bg)"/>
        <circle cx="150" cy="150" r="40" fill="#00ccff" opacity="0.3"/>
        <text x="50%" y="200" text-anchor="middle" fill="#00ccff" font-size="16" font-family="Arial, sans-serif">{text}</text>
        <text x="50%" y="230" text-anchor="middle" fill="#ffffff" font-size="12" font-family="Arial, sans-serif" opacity="0.7">SK4FiLM</text>
        </svg>'''
    return Response(svg, mimetype='image/svg+xml')

# Server
async def run_server():
    try:
        logger.info("🚀 SK4FiLM Server - LATEST POSTS → IMDB → TELEGRAM SEARCH")
        
        # Initialize telegram
        success = await initialize_telegram()
        
        if success:
            logger.info("✅ COMPLETE SYSTEM READY!")
            logger.info("📝 Latest posts from text channels")
            logger.info("🎬 IMDB posters for movie titles")
            logger.info("🔍 Telegram search for full content")
        else:
            logger.warning("⚠️ System running in limited mode")
        
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
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
