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
    
    # TMDB API Configuration - Better than IMDB
    TMDB_API_KEYS = [
        "8265bd1c",  # Primary TMDB key
        "b9bd48a6",  # Backup 1
        "2f2d1c8e",  # Backup 2
        "a1b2c3d4"   # Backup 3
    ]
    
    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"  # High quality posters
    
    AUTO_UPDATE_INTERVAL = 30
    CACHE_DURATION = 300  # 5 minutes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Enhanced data store with TMDB caching
movie_store = {
    'movies': [],
    'last_update': None,
    'last_ids': {},
    'seen_titles': set(),
    'tmdb_cache': {},  # Cache TMDB results
    'updating': False
}

def extract_movie_title_enhanced(text):
    """Enhanced movie title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        # Clean text and get first line
        clean_text = re.sub(r'[^\w\s\(\)\-\.\n\u0900-\u097F]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        # Multiple extraction patterns
        patterns = [
            r'🎬\s*([^-\n]{4,40})(?:\s*-|\n|$)',
            r'^([^(]{4,40})\s*\(\d{4}\)',
            r'^([^-]{4,40})\s*-\s*(?:Hindi|English|Tamil|Telugu|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})',
            r'"([^"]{4,35})"',
            r'\*\*([^*]{4,35})\*\*',
            r'Movie[:\s]*([^-\n]{4,35})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_movie_title(title):
                    logger.debug(f"✅ Title extracted: '{title}'")
                    return title
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

def validate_movie_title(title):
    """Validate extracted movie title"""
    if not title or len(title) < 4 or len(title) > 45:
        return False
    
    # Filter invalid content
    bad_words = ['size', 'quality', 'download', 'link', 'channel', 'group', 'mb', 'gb', 'file', 'join', 'subscribe']
    if any(word in title.lower() for word in bad_words):
        return False
    
    # Must contain letters
    if not re.search(r'[a-zA-Z\u0900-\u097F]', title):
        return False
    
    # No pure numbers
    if re.match(r'^\d+$', title):
        return False
    
    return True

async def get_tmdb_movie_data(title, session):
    """Get movie data from TMDB - Better quality than IMDB"""
    cache_key = title.lower().strip()
    
    # Check cache first
    if cache_key in movie_store['tmdb_cache']:
        cached_data, cached_time = movie_store['tmdb_cache'][cache_key]
        if datetime.now() - cached_time < timedelta(seconds=Config.CACHE_DURATION):
            logger.info(f"📋 TMDB cache hit: {title}")
            return cached_data
    
    try:
        logger.info(f"🎬 TMDB: Searching for '{title}'")
        
        for api_key in Config.TMDB_API_KEYS:
            try:
                # Search for movie
                search_url = f"{Config.TMDB_BASE_URL}/search/movie"
                search_params = {
                    'api_key': api_key,
                    'query': title,
                    'language': 'en-US',
                    'page': 1,
                    'include_adult': 'false'
                }
                
                async with session.get(search_url, params=search_params, timeout=10) as response:
                    if response.status == 200:
                        search_data = await response.json()
                        
                        if search_data.get('results') and len(search_data['results']) > 0:
                            # Get first result (best match)
                            movie = search_data['results'][0]
                            
                            # Build poster URL
                            poster_path = movie.get('poster_path')
                            if poster_path:
                                poster_url = f"{Config.TMDB_IMAGE_BASE}{poster_path}"
                                
                                tmdb_result = {
                                    'poster_url': poster_url,
                                    'tmdb_title': movie.get('title', title),
                                    'original_title': movie.get('original_title', ''),
                                    'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                                    'rating': f"{movie.get('vote_average', 0):.1f}" if movie.get('vote_average') else '',
                                    'popularity': movie.get('popularity', 0),
                                    'overview': movie.get('overview', '')[:200],
                                    'genre_ids': movie.get('genre_ids', []),
                                    'tmdb_id': movie.get('id'),
                                    'success': True
                                }
                                
                                # Cache result
                                movie_store['tmdb_cache'][cache_key] = (tmdb_result, datetime.now())
                                
                                logger.info(f"✅ TMDB SUCCESS: {title} → {movie['title']} ({tmdb_result['year']})")
                                return tmdb_result
                        else:
                            logger.info(f"⚠️ TMDB: No results for '{title}'")
                
                # Small delay between API attempts
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"TMDB API error: {e}")
                continue
        
        # Cache negative result
        negative_result = {'success': False, 'error': 'Not found in TMDB'}
        movie_store['tmdb_cache'][cache_key] = (negative_result, datetime.now())
        
        logger.info(f"❌ TMDB: No data for '{title}'")
        return negative_result
        
    except Exception as e:
        logger.error(f"TMDB error for '{title}': {e}")
        return {'success': False, 'error': str(e)}

async def get_recent_movies_with_tmdb():
    """Get recent movies with TMDB posters - newest first"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 Loading recent movies with TMDB posters...")
        
        all_posts = []
        
        # Get posts from channels with timestamps
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                posts_count = 0
                async for message in User.get_chat_history(channel_id, limit=30):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_movie_title_enhanced(message.text)
                        
                        if title:
                            all_posts.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date,  # Keep datetime for sorting
                                'date_iso': message.date.isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            })
                            posts_count += 1
                
                logger.info(f"✅ {channel_name}: {posts_count} posts")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # SORT BY DATE - NEWEST FIRST
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        logger.info(f"📊 Sorted {len(all_posts)} posts by date (newest first)")
        
        # Remove duplicates - keep newest
        unique_movies = []
        seen_titles = set()
        
        for post in all_posts:
            title_key = post['title'].lower().strip()
            
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                
                # Convert datetime to string for JSON
                post['date'] = post['date_iso']
                del post['date_iso']
                
                unique_movies.append(post)
                
                if len(unique_movies) >= 25:
                    break
        
        logger.info(f"🎯 After deduplication: {len(unique_movies)} unique movies")
        
        # Add TMDB posters in parallel
        tmdb_start = time.time()
        movies_with_tmdb = []
        
        async with aiohttp.ClientSession() as session:
            # Process in batches for better reliability
            batch_size = 5
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                logger.info(f"🎬 TMDB batch {i//batch_size + 1}: Processing {len(batch)} movies")
                
                # Parallel TMDB requests
                tmdb_tasks = [get_tmdb_movie_data(movie['title'], session) for movie in batch]
                tmdb_results = await asyncio.gather(*tmdb_tasks, return_exceptions=True)
                
                for movie, tmdb_data in zip(batch, tmdb_results):
                    if isinstance(tmdb_data, dict) and tmdb_data.get('success'):
                        movie.update({
                            'tmdb_poster': tmdb_data['poster_url'],
                            'tmdb_title': tmdb_data['tmdb_title'],
                            'tmdb_year': tmdb_data['year'],
                            'tmdb_rating': tmdb_data['rating'],
                            'tmdb_overview': tmdb_data['overview'],
                            'tmdb_popularity': tmdb_data['popularity'],
                            'has_poster': True,
                            'poster_source': 'TMDB'
                        })
                        logger.info(f"✅ TMDB added: {movie['title']}")
                    else:
                        movie['has_poster'] = False
                        movie['poster_source'] = 'None'
                        logger.info(f"⚠️ No TMDB: {movie['title']}")
                    
                    movies_with_tmdb.append(movie)
                
                # Rate limiting between batches
                if i + batch_size < len(unique_movies):
                    await asyncio.sleep(0.4)
        
        tmdb_time = time.time() - tmdb_start
        total_time = time.time() - start_time
        poster_count = sum(1 for m in movies_with_tmdb if m.get('has_poster'))
        
        logger.info(f"⚡ TMDB processing: {tmdb_time:.2f}s")
        logger.info(f"⚡ Total time: {total_time:.2f}s")
        logger.info(f"🎬 Final result: {len(movies_with_tmdb)} movies, {poster_count} with TMDB posters")
        
        return movies_with_tmdb
        
    except Exception as e:
        logger.error(f"Recent movies with TMDB error: {e}")
        return []

async def check_new_posts_tmdb():
    """Check for new posts and add TMDB data"""
    if not User or not bot_started or movie_store['updating']:
        return False
    
    try:
        movie_store['updating'] = True
        logger.info("🔄 Checking for new posts...")
        
        new_posts_found = False
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                last_known_id = movie_store['last_ids'].get(channel_id, 0)
                
                new_movies = []
                async for message in User.get_chat_history(channel_id, limit=8):
                    if (message.id > last_known_id and 
                        message.text and 
                        len(message.text) > 40 and 
                        message.date):
                        
                        title = extract_movie_title_enhanced(message.text)
                        
                        if title:
                            title_key = title.lower().strip()
                            
                            # Only add if not seen before
                            if title_key not in movie_store['seen_titles']:
                                movie_store['seen_titles'].add(title_key)
                                
                                new_movie = {
                                    'title': title,
                                    'text': message.text,
                                    'date': message.date.isoformat(),
                                    'channel': channel_name,
                                    'message_id': message.id,
                                    'channel_id': channel_id,
                                    'is_new': True
                                }
                                
                                new_movies.append(new_movie)
                                logger.info(f"🆕 NEW: {title} from {channel_name}")
                
                if new_movies:
                    # Get TMDB data for new movies
                    async with aiohttp.ClientSession() as session:
                        for movie in new_movies:
                            tmdb_data = await get_tmdb_movie_data(movie['title'], session)
                            if tmdb_data.get('success'):
                                movie.update({
                                    'tmdb_poster': tmdb_data['poster_url'],
                                    'tmdb_title': tmdb_data['tmdb_title'],
                                    'tmdb_year': tmdb_data['year'],
                                    'tmdb_rating': tmdb_data['rating'],
                                    'has_poster': True,
                                    'poster_source': 'TMDB'
                                })
                            else:
                                movie['has_poster'] = False
                                movie['poster_source'] = 'None'
                    
                    # Add NEW movies to FRONT (newest first)
                    movie_store['movies'] = new_movies + movie_store['movies']
                    movie_store['movies'] = movie_store['movies'][:35]  # Keep latest 35
                    
                    # Update last message ID
                    movie_store['last_ids'][channel_id] = max(movie['message_id'] for movie in new_movies)
                    
                    new_posts_found = True
                    
            except Exception as e:
                logger.warning(f"New posts check error for {channel_id}: {e}")
        
        if new_posts_found:
            movie_store['last_update'] = datetime.now()
            logger.info("✅ NEW MOVIES ADDED WITH TMDB!")
        
        movie_store['updating'] = False
        return new_posts_found
        
    except Exception as e:
        logger.error(f"New posts check error: {e}")
        movie_store['updating'] = False
        return False

async def auto_update_background_loop():
    """Background auto update loop"""
    logger.info("🔄 TMDB AUTO UPDATE LOOP STARTED")
    
    while bot_started:
        try:
            await check_new_posts_tmdb()
            await asyncio.sleep(Config.AUTO_UPDATE_INTERVAL)
            
        except Exception as e:
            logger.error(f"Auto update loop error: {e}")
            await asyncio.sleep(60)

async def search_telegram_content(query, limit=10, offset=0):
    """Search telegram channels"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted = format_post_content(message.text)
                        
                        results.append({
                            'content': formatted,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': channel_name,
                            'links': len(re.findall(r'https?://[^\s]+', message.text))
                        })
                        
            except Exception as e:
                logger.warning(f"Search error: {e}")
        
        # Sort by relevance (links count and date)
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
    """Format telegram post content"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    
    # Enhanced link formatting
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 4px 10px; border-radius: 8px; margin: 3px; display: inline-block; text-decoration: none;"><i class="fas fa-download me-1"></i>\1</a>', 
        formatted
    )
    
    formatted = formatted.replace('\n', '<br>')
    
    # Highlight movie info
    formatted = re.sub(r'📁\s*Size[:\s]*([^<br>|]+)', r'<span style="background: rgba(40,167,69,0.2); color: #28a745; padding: 5px 12px; border-radius: 12px; font-size: 0.85rem; margin: 4px; display: inline-block; border: 1px solid rgba(40,167,69,0.3);"><i class="fas fa-hdd me-1"></i>Size: \1</span>', formatted)
    formatted = re.sub(r'📹\s*Quality[:\s]*([^<br>|]+)', r'<span style="background: rgba(0,123,255,0.2); color: #007bff; padding: 5px 12px; border-radius: 12px; font-size: 0.85rem; margin: 4px; display: inline-block; border: 1px solid rgba(0,123,255,0.3);"><i class="fas fa-video me-1"></i>Quality: \1</span>', formatted)
    
    return formatted

async def initialize_telegram_with_tmdb():
    """Initialize telegram service with TMDB integration"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram with TMDB integration...")
        
        User = Client(
            "sk4film_tmdb",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        user_info = await User.get_me()
        logger.info(f"✅ Telegram connected: {user_info.first_name}")
        
        # Verify channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_info = await User.get_chat(channel_id)
                logger.info(f"✅ Channel verified: {channel_info.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.error(f"❌ Channel {channel_id} error: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            
            # Load initial movies with TMDB
            logger.info("📋 Loading initial movies with TMDB posters...")
            initial_movies = await get_recent_movies_with_tmdb()
            
            # Initialize data store
            movie_store['movies'] = initial_movies
            movie_store['last_update'] = datetime.now()
            movie_store['seen_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            # Set initial last message IDs
            for movie in initial_movies:
                channel_id = movie.get('channel_id')
                if channel_id:
                    current_max = movie_store['last_ids'].get(channel_id, 0)
                    movie_store['last_ids'][channel_id] = max(current_max, movie.get('message_id', 0))
            
            # Start background auto update
            asyncio.create_task(auto_update_background_loop())
            
            logger.info(f"🎉 TMDB SYSTEM READY!")
            logger.info(f"🎬 {len(initial_movies)} movies loaded with TMDB posters")
            logger.info(f"🔄 Auto update every {Config.AUTO_UPDATE_INTERVAL}s")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"TMDB system init error: {e}")
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
        "service": "SK4FiLM - TMDB Integration",
        "poster_source": "TMDB (The Movie Database)",
        "features": [
            "tmdb_high_quality_posters",
            "recent_posts_first",
            "no_duplicate_display",
            "auto_update_system",
            "social_media_menu",
            "tutorial_videos", 
            "features_section",
            "disclaimer_section",
            "adsense_optimization"
        ],
        "movies_count": len(movie_store['movies']),
        "tmdb_cache_size": len(movie_store['tmdb_cache']),
        "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with TMDB posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "TMDB service unavailable"}), 503
        
        movies = movie_store['movies'][:limit]
        tmdb_posters = sum(1 for m in movies if m.get('has_poster'))
        
        logger.info(f"📱 API: Serving {len(movies)} movies with TMDB posters")
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_movies": len(movies),
            "tmdb_posters_count": tmdb_posters,
            "poster_source": "TMDB",
            "sorting": "newest_first",
            "no_duplicates": True,
            "auto_update_active": True,
            "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Movies API error: {e}")
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
        
        result = await search_telegram_content(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": result["results"],
            "pagination": {
                "current_page": result["current_page"],
                "total_pages": result["total_pages"],
                "total_results": result["total"]
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster')
async def proxy_tmdb_poster():
    """Proxy TMDB poster images - better quality than IMDB"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url or not poster_url.startswith('http'):
            return create_tmdb_placeholder("No URL provided")
        
        logger.info(f"🖼️ Proxying TMDB poster: {poster_url[:60]}...")
        
        # TMDB-optimized headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'cross-site',
            'Cache-Control': 'no-cache',
            'Referer': 'https://www.themoviedb.org/'  # TMDB referer
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ TMDB poster loaded: {len(image_data)} bytes")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Content-Type': content_type,
                            'Cache-Control': 'public, max-age=7200',
                            'Access-Control-Allow-Origin': '*',
                            'Cross-Origin-Resource-Policy': 'cross-origin'
                        }
                    )
                else:
                    logger.warning(f"❌ TMDB poster HTTP {response.status}")
                    return create_tmdb_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"TMDB poster error: {e}")
        return create_tmdb_placeholder("Loading Error")

def create_tmdb_placeholder(error_msg):
    """Professional TMDB-branded placeholder"""
    tmdb_svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="tmdbGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="50%" style="stop-color:#16213e"/>
                <stop offset="100%" style="stop-color:#0f172a"/>
            </linearGradient>
            <filter id="glow">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge> 
                    <feMergeNode in="coloredBlur"/>
                    <feMergeNode in="SourceGraphic"/> 
                </feMerge>
            </filter>
        </defs>
        <rect width="100%" height="100%" fill="url(#tmdbGrad)" rx="12"/>
        
        <!-- TMDB Brand Colors -->
        <circle cx="150" cy="160" r="50" fill="none" stroke="#01d277" stroke-width="4" opacity="0.6"/>
        <circle cx="150" cy="160" r="35" fill="#01d277" opacity="0.2"/>
        
        <text x="50%" y="170" text-anchor="middle" fill="#01d277" font-size="32" font-weight="bold" filter="url(#glow)">🎬</text>
        <text x="50%" y="220" text-anchor="middle" fill="#ffffff" font-size="18" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="250" text-anchor="middle" fill="#01d277" font-size="14">TMDB Poster</text>
        <text x="50%" y="320" text-anchor="middle" fill="#0d253f" font-size="12" font-weight="bold">TMDB</text>
        <text x="50%" y="340" text-anchor="middle" fill="#90cea1" font-size="11">The Movie Database</text>
        <text x="50%" y="380" text-anchor="middle" fill="#ff6666" font-size="10">{error_msg}</text>
        <text x="50%" y="420" text-anchor="middle" fill="#01d277" font-size="10">Click to Search Telegram</text>
    </svg>'''
    
    return Response(tmdb_svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def api_force_update():
    """Force update with TMDB"""
    try:
        if not bot_started:
            return jsonify({"status": "error"}), 503
        
        logger.info("🔄 FORCE UPDATE - Reloading with TMDB")
        
        # Clear cache and seen titles
        movie_store['seen_titles'].clear()
        movie_store['tmdb_cache'].clear()
        
        # Get fresh movies
        fresh_movies = await get_recent_movies_with_tmdb()
        
        movie_store['movies'] = fresh_movies
        movie_store['last_update'] = datetime.now()
        movie_store['seen_titles'] = {movie['title'].lower() for movie in fresh_movies}
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "poster_source": "TMDB",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_server():
    try:
        logger.info("🚀 SK4FiLM - TMDB INTEGRATION")
        logger.info("🎬 Using TMDB instead of IMDB for better poster quality")
        logger.info("📅 Recent posts first system")
        logger.info("🚫 No duplicate poster display")
        logger.info("📱 All previous features preserved")
        
        success = await initialize_telegram_with_tmdb()
        
        if success:
            logger.info("🎉 TMDB SYSTEM OPERATIONAL!")
        else:
            logger.error("❌ TMDB system failed to start")
        
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
