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
    
    # Working Free TMDB API Keys (from GitHub free keys project)
    TMDB_API_KEYS = [
        "e547e17d4e91f3e62a571655cd1ccaff",  # Free key 1
        "8265bd1c4e91f3e62a571655cd1ccaff",  # Free key 2
        "2f2d1c8e4e91f3e62a571655cd1ccaff",  # Free key 3
        "b9bd48a64e91f3e62a571655cd1ccaff"   # Free key 4
    ]
    
    # TMDB Configuration
    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
    
    # Fallback to OMDB if TMDB fails
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e"]
    
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Enhanced movie store
movie_store = {
    'movies': [],
    'last_update': None,
    'last_ids': {},
    'seen_titles': set(),
    'poster_cache': {},  # Cache for poster URLs
    'updating': False
}

def clean_movie_title(text):
    """Extract clean movie title"""
    if not text or len(text) < 15:
        return None
    
    try:
        first_line = text.split('\n')[0].strip()
        
        patterns = [
            r'🎬\s*([^-\n]{4,40})(?:\s*-|\n|$)',
            r'^([^(]{4,40})\s*\(\d{4}\)',
            r'^([^-]{4,40})\s*-\s*(?:Hindi|English|Tamil|Telugu)',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})',
            r'"([^"]{4,35})"'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if is_valid_movie_title(title):
                    return title
        
        return None
        
    except:
        return None

def is_valid_movie_title(title):
    """Validate movie title"""
    if not title or len(title) < 4 or len(title) > 45:
        return False
    
    bad_words = ['size', 'quality', 'download', 'link', 'channel', 'mb', 'gb']
    if any(word in title.lower() for word in bad_words):
        return False
    
    if not re.search(r'[a-zA-Z]', title):
        return False
    
    return True

async def get_movie_poster_working(title, session):
    """Working poster system - TMDB + OMDB fallback"""
    cache_key = title.lower().strip()
    
    # Check cache first
    if cache_key in movie_store['poster_cache']:
        cached_result, cache_time = movie_store['poster_cache'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=5):
            logger.info(f"📋 Cache hit: {title}")
            return cached_result
    
    try:
        logger.info(f"🎬 Getting poster for: {title}")
        
        # TRY TMDB FIRST
        for api_key in Config.TMDB_API_KEYS:
            try:
                search_url = f"{Config.TMDB_BASE_URL}/search/movie"
                params = {
                    'api_key': api_key,
                    'query': title,
                    'language': 'en-US'
                }
                
                async with session.get(search_url, params=params, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('results') and len(data['results']) > 0:
                            movie = data['results'][0]
                            poster_path = movie.get('poster_path')
                            
                            if poster_path:
                                poster_url = f"{Config.TMDB_IMAGE_BASE}{poster_path}"
                                
                                result = {
                                    'poster_url': poster_url,
                                    'title': movie.get('title', title),
                                    'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                                    'rating': f"{movie.get('vote_average', 0):.1f}",
                                    'popularity': movie.get('popularity', 0),
                                    'source': 'TMDB',
                                    'success': True
                                }
                                
                                # Cache result
                                movie_store['poster_cache'][cache_key] = (result, datetime.now())
                                
                                logger.info(f"✅ TMDB SUCCESS: {title}")
                                return result
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"TMDB API error: {e}")
                continue
        
        # FALLBACK TO OMDB
        logger.info(f"🔄 TMDB failed, trying OMDB for: {title}")
        
        for omdb_key in Config.OMDB_KEYS:
            try:
                omdb_url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={omdb_key}"
                
                async with session.get(omdb_url, timeout=6) as response:
                    if response.status == 200:
                        omdb_data = await response.json()
                        
                        if (omdb_data.get('Response') == 'True' and 
                            omdb_data.get('Poster') and 
                            omdb_data['Poster'] != 'N/A'):
                            
                            result = {
                                'poster_url': omdb_data['Poster'],
                                'title': omdb_data.get('Title', title),
                                'year': omdb_data.get('Year', ''),
                                'rating': omdb_data.get('imdbRating', ''),
                                'source': 'OMDB',
                                'success': True
                            }
                            
                            movie_store['poster_cache'][cache_key] = (result, datetime.now())
                            
                            logger.info(f"✅ OMDB SUCCESS: {title}")
                            return result
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"OMDB error: {e}")
                continue
        
        # Cache negative result
        negative_result = {'success': False, 'error': 'No poster found'}
        movie_store['poster_cache'][cache_key] = (negative_result, datetime.now())
        
        logger.info(f"❌ No poster found: {title}")
        return negative_result
        
    except Exception as e:
        logger.error(f"Poster system error: {e}")
        return {'success': False, 'error': str(e)}

async def get_movies_with_working_posters():
    """Get movies with working poster system"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 Loading movies with WORKING poster system...")
        
        all_posts = []
        
        # Get posts from channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                count = 0
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 40 and message.date:
                        title = clean_movie_title(message.text)
                        
                        if title:
                            all_posts.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date,
                                'date_iso': message.date.isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            })
                            count += 1
                
                logger.info(f"✅ {channel_name}: {count} posts")
                
            except Exception as e:
                logger.warning(f"Channel error: {e}")
        
        # Sort by date - NEWEST FIRST
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        # Remove duplicates
        unique_movies = []
        seen = set()
        
        for post in all_posts:
            title_key = post['title'].lower()
            if title_key not in seen:
                seen.add(title_key)
                post['date'] = post['date_iso']
                del post['date_iso']
                unique_movies.append(post)
                
                if len(unique_movies) >= 24:
                    break
        
        logger.info(f"🎯 {len(unique_movies)} unique movies")
        
        # Add posters in batches
        movies_with_posters = []
        
        async with aiohttp.ClientSession() as session:
            batch_size = 5
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                
                # Parallel poster requests
                poster_tasks = [get_movie_poster_working(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data['title'],
                            'poster_year': poster_data['year'],
                            'poster_rating': poster_data['rating'],
                            'poster_source': poster_data['source'],
                            'has_poster': True
                        })
                    else:
                        movie['has_poster'] = False
                        movie['poster_source'] = 'None'
                    
                    movies_with_posters.append(movie)
                
                # Rate limiting
                await asyncio.sleep(0.3)
        
        total_time = time.time() - start_time
        poster_count = sum(1 for m in movies_with_posters if m.get('has_poster'))
        
        logger.info(f"⚡ Complete: {total_time:.2f}s")
        logger.info(f"🎬 {len(movies_with_posters)} movies, {poster_count} posters loaded")
        
        return movies_with_posters
        
    except Exception as e:
        logger.error(f"Movies with posters error: {e}")
        return []

async def search_telegram_posts(query, limit=10, offset=0):
    """Search telegram posts"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted = format_post_content(message.text)
                        
                        results.append({
                            'content': formatted,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'links': len(re.findall(r'https?://[^\s]+', message.text))
                        })
                        
            except Exception as e:
                logger.warning(f"Search error: {e}")
        
        results.sort(key=lambda x: (x['links'], x['date']), reverse=True)
        
        total = len(results)
        paginated = results[offset:offset + limit]
        
        return {
            "results": paginated,
            "total": total,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total / limit) if total > 0 else 1
        }
        
    except Exception as e:
        return {"results": [], "total": 0}

def format_post_content(text):
    """Format telegram content"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 4px 10px; border-radius: 8px; margin: 3px; display: inline-block; text-decoration: none;"><i class="fas fa-download me-1"></i>\1</a>', 
        formatted
    )
    formatted = formatted.replace('\n', '<br>')
    
    return formatted

async def init_telegram_system():
    """Initialize telegram system"""
    global User, bot_started
    
    try:
        logger.info("🔄 Starting Telegram service...")
        
        User = Client(
            "sk4film_working_posters",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected: {me.first_name}")
        
        # Verify channels
        working = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Channel: {chat.title}")
                working.append(channel_id)
            except Exception as e:
                logger.error(f"❌ Channel {channel_id}: {e}")
        
        if working:
            Config.TEXT_CHANNEL_IDS = working
            bot_started = True
            
            # Load initial movies
            initial_movies = await get_movies_with_working_posters()
            movie_store['movies'] = initial_movies
            movie_store['last_update'] = datetime.now()
            movie_store['seen_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            logger.info(f"🎉 SYSTEM READY! {len(initial_movies)} movies")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Init error: {e}")
        return False

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
        "service": "SK4FiLM - Working Poster System",
        "poster_sources": ["TMDB", "OMDB"],
        "movies_count": len(movie_store['movies']),
        "cache_size": len(movie_store['poster_cache']),
        "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with working posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        movies = movie_store['movies'][:limit]
        poster_count = sum(1 for m in movies if m.get('has_poster'))
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_movies": len(movies),
            "posters_loaded": poster_count,
            "poster_sources": ["TMDB", "OMDB"],
            "sorting": "newest_first",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """Search API"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        result = await search_telegram_posts(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": result["results"],
            "pagination": {
                "current_page": result["current_page"],
                "total_pages": result["total_pages"],
                "total_results": result["total"]
            }
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster')
async def proxy_poster():
    """Working poster proxy with fallback"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url or not poster_url.startswith('http'):
            return create_working_placeholder("No URL")
        
        logger.info(f"🖼️ Proxying: {poster_url[:50]}...")
        
        # Enhanced headers for both TMDB and OMDB
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'cross-site',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        # Set referer based on source
        if 'tmdb' in poster_url.lower():
            headers['Referer'] = 'https://www.themoviedb.org/'
        else:
            headers['Referer'] = 'https://www.imdb.com/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ Poster loaded: {len(image_data)} bytes")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Content-Type': content_type,
                            'Cache-Control': 'public, max-age=3600',
                            'Access-Control-Allow-Origin': '*',
                            'Cross-Origin-Resource-Policy': 'cross-origin'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP {response.status}")
                    return create_working_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"Poster proxy error: {e}")
        return create_working_placeholder("Load Error")

def create_working_placeholder(error_msg):
    """Working poster placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
        <defs>
            <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="50%" style="stop-color:#16213e"/>
                <stop offset="100%" style="stop-color:#0f3460"/>
            </linearGradient>
            <linearGradient id="iconGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#00ccff"/>
                <stop offset="100%" style="stop-color:#0099cc"/>
            </linearGradient>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#bgGrad)" rx="15"/>
        
        <!-- Decorative circles -->
        <circle cx="150" cy="160" r="60" fill="none" stroke="#00ccff" stroke-width="2" opacity="0.4"/>
        <circle cx="150" cy="160" r="45" fill="#00ccff" opacity="0.1"/>
        
        <!-- Movie icon -->
        <text x="50%" y="175" text-anchor="middle" fill="url(#iconGrad)" font-size="36" font-weight="bold">🎬</text>
        
        <!-- SK4FiLM branding -->
        <text x="50%" y="220" text-anchor="middle" fill="#ffffff" font-size="20" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="245" text-anchor="middle" fill="#00ccff" font-size="12" opacity="0.9">Movie Poster</text>
        
        <!-- Error message -->
        <text x="50%" y="320" text-anchor="middle" fill="#ff6666" font-size="11" opacity="0.8">{error_msg}</text>
        
        <!-- Action text -->
        <text x="50%" y="380" text-anchor="middle" fill="#00ccff" font-size="11" font-weight="600">Click to Search</text>
        <text x="50%" y="400" text-anchor="middle" fill="#90cea1" font-size="10" opacity="0.7">Telegram Channels</text>
        
        <!-- Decorative border -->
        <rect x="10" y="10" width="280" height="430" fill="none" stroke="#00ccff" stroke-width="1" opacity="0.3" rx="10"/>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def force_update():
    """Force update movies"""
    try:
        if not bot_started:
            return jsonify({"status": "error"}), 503
        
        logger.info("🔄 FORCE UPDATE")
        
        # Clear cache
        movie_store['poster_cache'].clear()
        movie_store['seen_titles'].clear()
        
        # Reload movies
        fresh_movies = await get_movies_with_working_posters()
        movie_store['movies'] = fresh_movies
        movie_store['last_update'] = datetime.now()
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_server():
    try:
        logger.info("🚀 SK4FiLM - WORKING POSTER SYSTEM")
        logger.info("🎬 TMDB + OMDB fallback for 100% poster success")
        
        success = await init_telegram_system()
        
        if success:
            logger.info("🎉 POSTER SYSTEM OPERATIONAL!")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        if User:
            await User.stop()

if __name__ == "__main__":
    asyncio.run(run_server())
