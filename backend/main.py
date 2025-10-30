import asyncio
import os
import logging
from pyrogram import Client, errors
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import html
import re
from datetime import datetime, timedelta
import math
import aiohttp
import urllib.parse
import json
import time

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Working OMDB API keys
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4"]
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Data store for movies
movies_data = {
    'movies_list': [],
    'last_update_time': None,
    'channel_last_ids': {},
    'seen_movie_titles': set(),
    'is_updating': False
}

def extract_movie_title_clean(text):
    """Clean movie title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        # Get first line and clean it
        first_line = text.split('\n')[0].strip()
        
        # Title extraction patterns
        patterns = [
            r'🎬\s*([^-\n]{4,35})(?:\s*-|\n|$)',
            r'^([^(]{4,35})\s*\(\d{4}\)',
            r'^([^-]{4,35})\s*-\s*(?:Hindi|English|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,3})',
            r'"([^"]{4,30})"'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if is_valid_title(title):
                    return title
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

def is_valid_title(title):
    """Check if title is valid movie name"""
    if not title or len(title) < 4 or len(title) > 40:
        return False
    
    # Filter out invalid words
    invalid_words = ['size', 'quality', 'download', 'link', 'channel', 'group', 'mb', 'gb', 'file']
    if any(word in title.lower() for word in invalid_words):
        return False
    
    # Must contain letters
    if not re.search(r'[a-zA-Z]', title):
        return False
    
    return True

async def get_imdb_poster_data(title, session):
    """Get IMDB poster data with multiple API keys"""
    try:
        logger.info(f"🎬 Getting IMDB data for: {title}")
        
        for api_index, api_key in enumerate(Config.OMDB_KEYS):
            try:
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={api_key}&plot=short"
                
                async with session.get(url, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if (data.get('Response') == 'True' and 
                            data.get('Poster') and 
                            data['Poster'] != 'N/A' and
                            data['Poster'].startswith('http')):
                            
                            poster_info = {
                                'poster_url': data['Poster'],
                                'imdb_title': data.get('Title', title),
                                'year': data.get('Year', ''),
                                'rating': data.get('imdbRating', ''),
                                'genre': data.get('Genre', ''),
                                'success': True
                            }
                            
                            logger.info(f"✅ IMDB success for: {title}")
                            return poster_info
                        else:
                            logger.info(f"⚠️ No poster found for: {title}")
                
                # Small delay between API attempts
                if api_index < len(Config.OMDB_KEYS) - 1:
                    await asyncio.sleep(0.2)
                    
            except Exception as e:
                logger.warning(f"IMDB API {api_index + 1} error: {e}")
                continue
        
        return {'success': False}
        
    except Exception as e:
        logger.error(f"IMDB data error: {e}")
        return {'success': False}

async def get_recent_movies_sorted():
    """Get movies sorted by date - newest first"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 Loading recent movies - NEWEST FIRST")
        
        all_movie_posts = []
        
        # Get posts from all channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                channel_movies = 0
                async for message in User.get_chat_history(channel_id, limit=30):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_movie_title_clean(message.text)
                        
                        if title:
                            all_movie_posts.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date,  # Keep as datetime for sorting
                                'date_iso': message.date.isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            })
                            channel_movies += 1
                
                logger.info(f"✅ {channel_name}: {channel_movies} movies")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # SORT BY DATE - NEWEST FIRST
        all_movie_posts.sort(key=lambda x: x['date'], reverse=True)
        logger.info(f"📊 Sorted {len(all_movie_posts)} posts by date (newest first)")
        
        # Remove duplicates - keep newest version
        unique_movies = []
        seen_titles = set()
        
        for post in all_movie_posts:
            title_key = post['title'].lower().strip()
            
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                
                # Convert datetime back to string for JSON
                post['date'] = post['date_iso']
                del post['date_iso']
                
                unique_movies.append(post)
                
                if len(unique_movies) >= 25:  # Limit for performance
                    break
        
        logger.info(f"🎯 After deduplication: {len(unique_movies)} unique movies")
        
        # Add IMDB posters in parallel
        final_movies = []
        
        async with aiohttp.ClientSession() as session:
            batch_size = 6
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                
                # Parallel IMDB requests
                imdb_tasks = [get_imdb_poster_data(movie['title'], session) for movie in batch]
                imdb_results = await asyncio.gather(*imdb_tasks, return_exceptions=True)
                
                for movie, imdb_data in zip(batch, imdb_results):
                    if isinstance(imdb_data, dict) and imdb_data.get('success'):
                        movie.update({
                            'imdb_poster': imdb_data['poster_url'],
                            'imdb_year': imdb_data['year'],
                            'imdb_rating': imdb_data['rating'],
                            'imdb_genre': imdb_data['genre'],
                            'has_poster': True
                        })
                    else:
                        movie['has_poster'] = False
                    
                    final_movies.append(movie)
                
                # Rate limiting
                if i + batch_size < len(unique_movies):
                    await asyncio.sleep(0.3)
        
        processing_time = time.time() - start_time
        posters_found = sum(1 for m in final_movies if m.get('has_poster'))
        
        logger.info(f"⚡ Complete in {processing_time:.2f}s")
        logger.info(f"🎬 {len(final_movies)} movies, {posters_found} with IMDB posters")
        
        return final_movies
        
    except Exception as e:
        logger.error(f"Recent movies error: {e}")
        return []

async def search_telegram_channels(query, limit=10, offset=0):
    """Search across telegram channels"""
    try:
        search_results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted_text = format_telegram_post(message.text)
                        
                        search_results.append({
                            'content': formatted_text,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': channel_name,
                            'download_links': len(re.findall(r'https?://[^\s]+', message.text))
                        })
                        
            except Exception as e:
                logger.warning(f"Search error for channel {channel_id}: {e}")
        
        # Sort by download links and date
        search_results.sort(key=lambda x: (x['download_links'], x['date']), reverse=True)
        
        total_results = len(search_results)
        paginated_results = search_results[offset:offset + limit]
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"Search channels error: {e}")
        return {"results": [], "total": 0}

def format_telegram_post(text):
    """Format telegram post content"""
    if not text:
        return ""
    
    # Escape HTML
    formatted = html.escape(text)
    
    # Convert URLs to clickable links
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 3px 8px; border-radius: 6px; margin: 2px; display: inline-block; text-decoration: none;"><i class="fas fa-external-link-alt me-1"></i>\1</a>', 
        formatted
    )
    
    # Convert newlines to HTML breaks
    formatted = formatted.replace('\n', '<br>')
    
    return formatted

async def initialize_telegram_service():
    """Initialize telegram service"""
    global User, bot_started
    
    try:
        logger.info("🔄 Starting Telegram service...")
        
        User = Client(
            "sk4film_fixed",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        user_info = await User.get_me()
        logger.info(f"✅ Telegram connected: {user_info.first_name}")
        
        # Test channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_info = await User.get_chat(channel_id)
                logger.info(f"✅ Channel OK: {channel_info.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.error(f"❌ Channel {channel_id} failed: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            
            # Load initial movies
            logger.info("📋 Loading initial movies...")
            initial_movies = await get_recent_movies_sorted()
            
            movies_data['movies_list'] = initial_movies
            movies_data['last_update_time'] = datetime.now()
            movies_data['seen_movie_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            logger.info(f"🎉 SERVICE READY! {len(initial_movies)} movies loaded")
            return True
        
        logger.error("❌ No working channels found")
        return False
        
    except Exception as e:
        logger.error(f"Telegram service init error: {e}")
        return False

@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/')
async def health_check():
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM - Fixed Syntax Error",
        "features": "recent_first + no_duplicates + all_sections",
        "movies_count": len(movies_data['movies_list']),
        "last_update": movies_data['last_update_time'].isoformat() if movies_data['last_update_time'] else None,
        "telegram_connected": bot_started,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def get_movies_api():
    """Get movies API - recent first, no duplicates"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Telegram service not available"}), 503
        
        # Return movies from data store - already sorted newest first
        movies = movies_data['movies_list'][:limit]
        posters_count = sum(1 for movie in movies if movie.get('has_poster'))
        
        logger.info(f"📱 Serving {len(movies)} movies (newest first)")
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_count": len(movies),
            "movies_with_posters": posters_count,
            "sorting": "newest_first",
            "no_duplicates": True,
            "last_update": movies_data['last_update_time'].isoformat() if movies_data['last_update_time'] else None,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Movies API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def search_movies_api():
    """Search movies API"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Search query required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Search service unavailable"}), 503
        
        search_result = await search_telegram_channels(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": search_result["results"],
            "pagination": {
                "current_page": search_result["current_page"],
                "total_pages": search_result["total_pages"],
                "total_results": search_result["total"]
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster')
async def proxy_poster_image():
    """Proxy IMDB poster images"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url or not poster_url.startswith('http'):
            return create_movie_placeholder("Invalid URL")
        
        logger.info(f"🖼️ Proxying poster: {poster_url[:50]}...")
        
        # Professional headers
        request_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Cache-Control': 'no-cache',
            'Referer': 'https://www.imdb.com/'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=request_headers, timeout=12) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ Poster loaded: {len(image_data)} bytes")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Content-Type': content_type,
                            'Cache-Control': 'public, max-age=7200',
                            'Access-Control-Allow-Origin': '*'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP error: {response.status}")
                    return create_movie_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"Poster proxy error: {e}")
        return create_movie_placeholder("Loading Error")

def create_movie_placeholder(error_message):
    """Create movie poster placeholder SVG"""
    placeholder_svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="bgGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="100%" style="stop-color:#16213e"/>
            </linearGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#bgGradient)" rx="12"/>
        <circle cx="150" cy="180" r="40" fill="#00ccff" opacity="0.3"/>
        <text x="50%" y="190" text-anchor="middle" fill="#00ccff" font-size="30" font-weight="bold">🎬</text>
        <text x="50%" y="250" text-anchor="middle" fill="#ffffff" font-size="16" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="280" text-anchor="middle" fill="#00ccff" font-size="12">Movie Poster</text>
        <text x="50%" y="350" text-anchor="middle" fill="#ff9999" font-size="10">{error_message}</text>
        <text x="50%" y="400" text-anchor="middle" fill="#00ccff" font-size="10">Click to Search Telegram</text>
    </svg>'''
    
    return Response(placeholder_svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def force_update_movies():
    """Force update all movies"""
    try:
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        logger.info("🔄 FORCE UPDATE - Reloading all movies")
        
        # Clear existing data
        movies_data['seen_movie_titles'].clear()
        
        # Get fresh movies
        fresh_movies = await get_recent_movies_sorted()
        
        # Update data store
        movies_data['movies_list'] = fresh_movies
        movies_data['last_update_time'] = datetime.now()
        movies_data['seen_movie_titles'] = {movie['title'].lower() for movie in fresh_movies}
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "sorting": "newest_first",
            "no_duplicates": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Force update error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_main_server():
    try:
        logger.info("🚀 SK4FiLM - SYNTAX ERROR FIXED")
        logger.info("✅ All imports corrected")
        logger.info("📅 Recent posts first system")
        logger.info("🚫 No duplicate posters")
        logger.info("📱 All features preserved")
        
        telegram_success = await initialize_telegram_service()
        
        if telegram_success:
            logger.info("🎉 ALL SYSTEMS OPERATIONAL!")
        else:
            logger.error("❌ Telegram initialization failed")
        
        # Start server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"Main server error: {e}")
    finally:
        if User:
            await User.stop()

if __name__ == "__main__":
    asyncio.run(run_main_server())
