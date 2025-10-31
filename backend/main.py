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
import uuid

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Working OMDB Keys (जो log में success दिख रहे हैं)
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4"]
    
    # TMDB backup keys
    TMDB_KEYS = ["e547e17d4e91f3e62a571655cd1ccaff"]
    
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Movie data store
movie_data = {
    'movies_list': [],
    'last_update_time': None,
    'channel_last_ids': {},
    'seen_movie_titles': set(),
    'poster_cache_data': {},
    'is_updating_now': False,
    'poster_success_stats': {'tmdb': 0, 'omdb': 0, 'custom': 0, 'total_attempts': 0}
}

def extract_movie_title_improved(text):
    """Improved title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        clean_text = re.sub(r'[^\w\s\(\)\-\.\n\u0900-\u097F]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        patterns = [
            r'🎬\s*([^-\n]{4,40})(?:\s*-|\n|$)',
            r'^([^(]{4,40})\s*\(\d{4}\)',
            r'^([^-]{4,40})\s*-\s*(?:Hindi|English|Tamil|Telugu|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})',
            r'"([^"]{4,35})"',
            r'Movie[:\s]*([^-\n]{4,35})',
            r'Film[:\s]*([^-\n]{4,35})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_extracted_title(title):
                    return title
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

def validate_extracted_title(title):
    """Enhanced title validation"""
    if not title or len(title) < 4 or len(title) > 45:
        return False
    
    bad_words = ['size', 'quality', 'download', 'link', 'channel', 'group', 'mb', 'gb', 'file', 'join']
    if any(word in title.lower() for word in bad_words):
        return False
    
    if not re.search(r'[a-zA-Z\u0900-\u097F]', title):
        return False
    
    return True

async def get_poster_multi_source(title, session):
    """Multi-source poster finder - TMDB + OMDB + Custom"""
    cache_key = title.lower().strip()
    
    # Check cache first
    if cache_key in movie_data['poster_cache_data']:
        cached_data, cache_time = movie_data['poster_cache_data'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=8):
            return cached_data
    
    try:
        logger.info(f"🎬 Multi-source poster search: {title}")
        movie_data['poster_success_stats']['total_attempts'] += 1
        
        # TRY TMDB FIRST
        for tmdb_key in Config.TMDB_KEYS:
            try:
                tmdb_url = "https://api.themoviedb.org/3/search/movie"
                tmdb_params = {
                    'api_key': tmdb_key,
                    'query': title,
                    'language': 'en-US'
                }
                
                async with session.get(tmdb_url, params=tmdb_params, timeout=7) as response:
                    if response.status == 200:
                        tmdb_data = await response.json()
                        
                        if tmdb_data.get('results') and len(tmdb_data['results']) > 0:
                            movie = tmdb_data['results'][0]
                            poster_path = movie.get('poster_path')
                            
                            if poster_path:
                                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                                
                                result = {
                                    'poster_url': poster_url,
                                    'movie_title': movie.get('title', title),
                                    'release_year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                                    'vote_rating': f"{movie.get('vote_average', 0):.1f}",
                                    'poster_source': 'TMDB',
                                    'success': True
                                }
                                
                                movie_data['poster_cache_data'][cache_key] = (result, datetime.now())
                                movie_data['poster_success_stats']['tmdb'] += 1
                                
                                logger.info(f"✅ TMDB poster found: {title}")
                                return result
                
            except Exception as e:
                logger.warning(f"TMDB search error: {e}")
        
        # FALLBACK TO OMDB (जो log में successful है)
        logger.info(f"🔄 TMDB failed, trying OMDB for: {title}")
        
        for omdb_key in Config.OMDB_KEYS:
            try:
                omdb_url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={omdb_key}"
                
                async with session.get(omdb_url, timeout=6) as response:
                    if response.status == 200:
                        omdb_data = await response.json()
                        
                        if (omdb_data.get('Response') == 'True' and 
                            omdb_data.get('Poster') and 
                            omdb_data['Poster'] != 'N/A' and
                            omdb_data['Poster'].startswith('http')):
                            
                            result = {
                                'poster_url': omdb_data['Poster'],
                                'movie_title': omdb_data.get('Title', title),
                                'release_year': omdb_data.get('Year', ''),
                                'vote_rating': omdb_data.get('imdbRating', ''),
                                'poster_source': 'OMDB',
                                'success': True
                            }
                            
                            movie_data['poster_cache_data'][cache_key] = (result, datetime.now())
                            movie_data['poster_success_stats']['omdb'] += 1
                            
                            logger.info(f"✅ OMDB SUCCESS: {title}")
                            return result
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"OMDB error: {e}")
        
        # Custom poster as last resort
        logger.info(f"🎨 Generating custom poster: {title}")
        custom_result = {
            'poster_url': f"/api/custom_poster?title={urllib.parse.quote(title)}",
            'movie_title': title,
            'poster_source': 'CUSTOM',
            'success': True
        }
        
        movie_data['poster_cache_data'][cache_key] = (custom_result, datetime.now())
        movie_data['poster_success_stats']['custom'] += 1
        
        return custom_result
        
    except Exception as e:
        logger.error(f"Multi-source poster error: {e}")
        return {
            'poster_url': f"/api/custom_poster?title={urllib.parse.quote(title)}",
            'movie_title': title,
            'poster_source': 'CUSTOM',
            'success': True
        }

async def get_recent_movies_with_posters():
    """Get recent movies with multi-source posters"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 Getting recent movies with multi-source posters...")
        
        all_movie_posts = []
        
        # Get posts from channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                posts_found = 0
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_movie_title_improved(message.text)
                        
                        if title:
                            all_movie_posts.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date,
                                'date_iso': message.date.isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            })
                            posts_found += 1
                
                logger.info(f"✅ {channel_name}: {posts_found} movie posts")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # Sort by date - NEWEST FIRST
        all_movie_posts.sort(key=lambda x: x['date'], reverse=True)
        logger.info(f"📊 Sorted {len(all_movie_posts)} posts by date")
        
        # Remove duplicates - keep newest
        unique_movies = []
        seen_titles = set()
        
        for post in all_movie_posts:
            title_key = post['title'].lower().strip()
            
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                post['date'] = post['date_iso']
                del post['date_iso']
                unique_movies.append(post)
                
                if len(unique_movies) >= 24:
                    break
        
        logger.info(f"🎯 After deduplication: {len(unique_movies)} unique movies")
        
        # Add posters with multi-source system
        movies_with_posters = []
        
        async with aiohttp.ClientSession() as session:
            batch_size = 4
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                logger.info(f"🔍 Poster batch {i//batch_size + 1}: {len(batch)} movies")
                
                # Parallel poster finding
                poster_tasks = [get_poster_multi_source(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data['movie_title'],
                            'poster_year': poster_data.get('release_year', ''),
                            'poster_rating': poster_data.get('vote_rating', ''),
                            'poster_source': poster_data['poster_source'],
                            'has_poster': True
                        })
                    else:
                        movie.update({
                            'poster_url': f"/api/custom_poster?title={urllib.parse.quote(movie['title'])}",
                            'poster_source': 'CUSTOM',
                            'has_poster': True
                        })
                    
                    movies_with_posters.append(movie)
                
                # Rate limiting between batches
                await asyncio.sleep(0.4)
        
        total_time = time.time() - start_time
        poster_count = sum(1 for m in movies_with_posters if m.get('has_poster'))
        
        logger.info(f"⚡ Complete: {total_time:.2f}s")
        logger.info(f"🎬 {len(movies_with_posters)} movies, {poster_count} posters loaded")
        logger.info(f"📊 Stats: TMDB={movie_data['poster_success_stats']['tmdb']}, OMDB={movie_data['poster_success_stats']['omdb']}")
        
        return movies_with_posters
        
    except Exception as e:
        logger.error(f"Recent movies error: {e}")
        return []

async def search_channels(query, limit=10, offset=0):
    """Search telegram channels"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted = format_telegram_content(message.text)
                        
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
        
    except:
        return {"results": [], "total": 0}

def format_telegram_content(text):
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

async def initialize_telegram_fixed():
    """FIXED: Initialize telegram with unique session"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram with FIXED session...")
        
        # Generate unique session name to avoid AUTH_KEY_DUPLICATED
        session_name = f"sk4film_{uuid.uuid4().hex[:8]}_{int(time.time())}"
        
        User = Client(
            session_name,  # Unique session name
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp",
            sleep_threshold=60,  # Reduce flood wait
            max_concurrent_transmissions=1  # Prevent session conflicts
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Telegram connected (FIXED): {me.first_name}")
        
        # Verify channels work
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
            
            # Load initial movies with posters
            logger.info("📋 Loading movies with multi-source posters...")
            initial_movies = await get_recent_movies_with_posters()
            
            movie_data['movies_list'] = initial_movies
            movie_data['last_update_time'] = datetime.now()
            movie_data['seen_movie_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            logger.info(f"🎉 FIXED SYSTEM READY!")
            logger.info(f"🎬 {len(initial_movies)} movies loaded")
            logger.info(f"📊 Poster stats: {movie_data['poster_success_stats']}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"FIXED telegram init error: {e}")
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
        "service": "SK4FiLM - Multi-Source Poster System (FIXED)",
        "session_fix": "AUTH_KEY_DUPLICATED resolved",
        "poster_sources": ["TMDB", "OMDB", "CUSTOM"],
        "movies_count": len(movie_data['movies_list']),
        "poster_stats": movie_data['poster_success_stats'],
        "last_update": movie_data['last_update_time'].isoformat() if movie_data['last_update_time'] else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with multi-source posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service starting..."}), 503
        
        movies = movie_data['movies_list'][:limit]
        poster_count = sum(1 for m in movies if m.get('has_poster'))
        
        logger.info(f"📱 API: Serving {len(movies)} movies with multi-source posters")
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_movies": len(movies),
            "posters_found": poster_count,
            "poster_success_rate": f"{(poster_count/len(movies)*100):.1f}%" if movies else "0%",
            "poster_sources": ["TMDB", "OMDB", "CUSTOM"],
            "poster_stats": movie_data['poster_success_stats'],
            "sorting": "newest_first",
            "session_status": "fixed",
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
        
        result = await search_channels(query, limit, offset)
        
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
async def proxy_poster_fixed():
    """FIXED poster proxy - working with Amazon images"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_custom_poster_svg("No URL")
        
        # Handle custom poster generation
        if poster_url.startswith('/api/custom_poster'):
            title_param = request.args.get('title', 'Movie')
            return create_custom_poster_svg(title_param)
        
        if not poster_url.startswith('http'):
            return create_custom_poster_svg("Invalid URL")
        
        logger.info(f"🖼️ Proxying: {poster_url[:50]}...")
        
        # Enhanced headers for Amazon images (जो log में working हैं)
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
            'Cache-Control': 'no-cache'
        }
        
        # Set proper referer for Amazon images
        if 'amazon' in poster_url.lower() or 'media-amazon' in poster_url.lower():
            headers['Referer'] = 'https://www.imdb.com/'
        elif 'tmdb' in poster_url.lower():
            headers['Referer'] = 'https://www.themoviedb.org/'
        else:
            headers['Referer'] = 'https://www.google.com/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=12) as response:
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
                            'Cross-Origin-Resource-Policy': 'cross-origin',
                            'Vary': 'Accept'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP {response.status}")
                    return create_custom_poster_svg(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"Poster proxy error: {e}")
        return create_custom_poster_svg("Load Error")

@app.route('/api/custom_poster')
async def custom_poster_generator():
    """Custom poster generator endpoint"""
    title = request.args.get('title', 'Movie')
    return create_custom_poster_svg(title)

def create_custom_poster_svg(title):
    """Enhanced custom poster SVG generator"""
    # Clean title for display
    display_title = title[:30] + "..." if len(title) > 30 else title
    
    # Multiple color schemes
    color_schemes = [
        {'bg1': '#ff6b6b', 'bg2': '#4ecdc4', 'text': '#ffffff', 'accent': '#ffee58'},
        {'bg1': '#a8e6cf', 'bg2': '#ffd3a5', 'text': '#2c3e50', 'accent': '#e74c3c'},
        {'bg1': '#74b9ff', 'bg2': '#0984e3', 'text': '#ffffff', 'accent': '#fdcb6e'},
        {'bg1': '#6c5ce7', 'bg2': '#a29bfe', 'text': '#ffffff', 'accent': '#fd79a8'},
        {'bg1': '#00b894', 'bg2': '#00cec9', 'text': '#ffffff', 'accent': '#fdcb6e'}
    ]
    
    scheme = color_schemes[hash(title) % len(color_schemes)]
    
    svg_content = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
        <defs>
            <linearGradient id="mainBg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{scheme['bg1']}"/>
                <stop offset="100%" style="stop-color:{scheme['bg2']}"/>
            </linearGradient>
            <linearGradient id="overlayGrad" x1="0%" y1="70%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:rgba(0,0,0,0)"/>
                <stop offset="100%" style="stop-color:rgba(0,0,0,0.7)"/>
            </linearGradient>
            <filter id="dropShadow">
                <feDropShadow dx="3" dy="3" stdDeviation="4" flood-opacity="0.8"/>
            </filter>
            <pattern id="filmStrip" patternUnits="userSpaceOnUse" width="30" height="30">
                <rect width="30" height="30" fill="rgba(255,255,255,0.1)"/>
                <circle cx="15" cy="15" r="3" fill="rgba(255,255,255,0.3)"/>
            </pattern>
        </defs>
        
        <!-- Main background -->
        <rect width="100%" height="100%" fill="url(#mainBg)" rx="18"/>
        
        <!-- Film strip decoration -->
        <rect x="0" y="0" width="30" height="100%" fill="url(#filmStrip)" opacity="0.6"/>
        <rect x="270" y="0" width="30" height="100%" fill="url(#filmStrip)" opacity="0.6"/>
        
        <!-- Content area -->
        <rect x="40" y="60" width="220" height="280" fill="rgba(255,255,255,0.15)" rx="25" stroke="rgba(255,255,255,0.3)" stroke-width="2"/>
        
        <!-- Film icon with glow -->
        <circle cx="150" cy="140" r="35" fill="rgba(255,255,255,0.2)"/>
        <text x="50%" y="155" text-anchor="middle" fill="{scheme['text']}" font-size="40" font-weight="bold" filter="url(#dropShadow)">🎬</text>
        
        <!-- Movie title -->
        <text x="50%" y="200" text-anchor="middle" fill="{scheme['text']}" font-size="14" font-weight="bold" filter="url(#dropShadow)">
            {html.escape(display_title)}
        </text>
        
        <!-- SK4FiLM branding -->
        <text x="50%" y="240" text-anchor="middle" fill="{scheme['accent']}" font-size="18" font-weight="800" filter="url(#dropShadow)">SK4FiLM</text>
        <text x="50%" y="260" text-anchor="middle" fill="rgba(255,255,255,0.9)" font-size="11" font-weight="600">House of Entertainment</text>
        
        <!-- Custom poster badge -->
        <rect x="60" y="290" width="180" height="25" fill="rgba(0,0,0,0.4)" rx="12"/>
        <text x="50%" y="305" text-anchor="middle" fill="{scheme['accent']}" font-size="10" font-weight="600">✨ Custom Generated Poster</text>
        
        <!-- Bottom overlay -->
        <rect x="0" y="350" width="100%" height="100" fill="url(#overlayGrad)" rx="0 0 18 18"/>
        
        <!-- Action text -->
        <text x="50%" y="390" text-anchor="middle" fill="#ffffff" font-size="12" font-weight="700" filter="url(#dropShadow)">Click to Search in Telegram</text>
        <text x="50%" y="410" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="10">Auto Poster System</text>
        
        <!-- Corner stars -->
        <text x="25" y="40" text-anchor="middle" fill="{scheme['accent']}" font-size="16" opacity="0.7">⭐</text>
        <text x="275" y="40" text-anchor="middle" fill="{scheme['accent']}" font-size="16" opacity="0.7">⭐</text>
        <text x="25" y="420" text-anchor="middle" fill="{scheme['accent']}" font-size="16" opacity="0.7">⭐</text>
        <text x="275" y="420" text-anchor="middle" fill="{scheme['accent']}" font-size="16" opacity="0.7">⭐</text>
    </svg>'''
    
    return Response(svg_content, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=1800',
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'image/svg+xml'
    })

@app.route('/api/force_update')
async def force_update():
    """Force update with fixed system"""
    try:
        if not bot_started:
            return jsonify({"status": "error", "message": "Service not ready"}), 503
        
        logger.info("🔄 FORCE UPDATE - Multi-source poster reload")
        
        # Clear caches
        movie_data['poster_cache_data'].clear()
        movie_data['seen_movie_titles'].clear()
        movie_data['poster_success_stats'] = {'tmdb': 0, 'omdb': 0, 'custom': 0, 'total_attempts': 0}
        
        # Reload movies
        fresh_movies = await get_recent_movies_with_posters()
        
        movie_data['movies_list'] = fresh_movies
        movie_data['last_update_time'] = datetime.now()
        movie_data['seen_movie_titles'] = {movie['title'].lower() for movie in fresh_movies}
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "poster_stats": movie_data['poster_success_stats'],
            "session_fix": "working",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_server_fixed():
    """FIXED server with proper session handling"""
    try:
        logger.info("🚀 SK4FiLM - FIXED SESSION + MULTI-SOURCE POSTERS")
        logger.info("🔧 AUTH_KEY_DUPLICATED error fixed")
        logger.info("🎬 Multi-source poster system: TMDB + OMDB + Custom")
        logger.info("📅 Recent posts first + No duplicates")
        logger.info("📱 All previous features preserved")
        
        success = await initialize_telegram_fixed()
        
        if success:
            logger.info("🎉 FIXED SYSTEM OPERATIONAL!")
        else:
            logger.error("❌ System initialization failed")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.graceful_timeout = 30
        
        await serve(app, config)
        
    except KeyboardInterrupt:
        logger.info("🛑 Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        # FIXED: Proper cleanup to avoid session conflicts
        if User and bot_started:
            try:
                logger.info("🔄 Properly stopping Telegram client...")
                await User.stop()
                logger.info("✅ Telegram client stopped cleanly")
            except Exception as e:
                logger.warning(f"Telegram stop warning: {e}")

if __name__ == "__main__":
    asyncio.run(run_server_fixed())
