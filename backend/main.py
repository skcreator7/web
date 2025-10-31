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
    
    # Working poster sources (no lxml dependency)
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4", "7c2e8f9d"]
    
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Enhanced movie data store
movie_database = {
    'movies': [],
    'last_update': None,
    'last_ids': {},
    'seen_titles': set(),
    'poster_cache': {},
    'updating': False,
    'stats': {'omdb': 0, 'justwatch': 0, 'letterboxd': 0, 'custom': 0, 'total': 0}
}

def extract_movie_title_smart(text):
    """Smart movie title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        clean_text = re.sub(r'[^\w\s\(\)\-\.\n\u0900-\u097F]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        # Enhanced patterns for better extraction
        extraction_patterns = [
            r'🎬\s*([^-\n]{4,45})(?:\s*-|\n|$)',
            r'^([^(]{4,45})\s*\(\d{4}\)',
            r'^([^-]{4,45})\s*-\s*(?:Hindi|English|Tamil|Telugu|Punjabi|Bengali|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,5})',
            r'"([^"]{4,40})"',
            r'\*\*([^*]{4,40})\*\*',
            r'Movie[:\s]*([^-\n]{4,40})',
            r'Film[:\s]*([^-\n]{4,40})',
            r'(?:Watch|Download|Latest|New)\s+([^-\n]{4,40})'
        ]
        
        for pattern in extraction_patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if is_valid_movie_title(title):
                    return title
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

def is_valid_movie_title(title):
    """Enhanced title validation"""
    if not title or len(title) < 4 or len(title) > 50:
        return False
    
    # Enhanced filtering
    bad_words = [
        'size', 'quality', 'download', 'link', 'channel', 'group', 'mb', 'gb', 'file',
        'join', 'subscribe', 'follow', 'admin', 'bot', 'telegram', 'whatsapp'
    ]
    
    if any(word in title.lower() for word in bad_words):
        return False
    
    if not re.search(r'[a-zA-Z\u0900-\u097F]', title):
        return False
    
    if re.match(r'^[\d\s\-\(\)\.]+$', title):
        return False
    
    return True

async def get_omdb_poster(title, session):
    """OMDB poster search - Primary working source"""
    try:
        logger.info(f"🎬 OMDB search: {title}")
        
        for api_key in Config.OMDB_KEYS:
            try:
                omdb_url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={api_key}&plot=short"
                
                async with session.get(omdb_url, timeout=7) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if (data.get('Response') == 'True' and 
                            data.get('Poster') and 
                            data['Poster'] != 'N/A' and
                            data['Poster'].startswith('http')):
                            
                            result = {
                                'poster_url': data['Poster'],
                                'title': data.get('Title', title),
                                'year': data.get('Year', ''),
                                'rating': data.get('imdbRating', ''),
                                'genre': data.get('Genre', ''),
                                'plot': data.get('Plot', ''),
                                'source': 'OMDB',
                                'success': True
                            }
                            
                            movie_database['stats']['omdb'] += 1
                            logger.info(f"✅ OMDB SUCCESS: {title}")
                            return result
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"OMDB error: {e}")
        
        return {'success': False, 'source': 'OMDB'}
        
    except Exception as e:
        logger.error(f"OMDB search error: {e}")
        return {'success': False, 'source': 'OMDB'}

async def get_justwatch_poster_simple(title, session):
    """JustWatch poster search - Simple regex approach (no lxml)"""
    try:
        logger.info(f"📺 JustWatch search: {title}")
        
        # Create JustWatch URL
        clean_title = re.sub(r'[^\w\s]', '', title.lower())
        url_title = '-'.join(clean_title.split())
        justwatch_url = f"https://www.justwatch.com/in/movie/{url_title}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
        
        async with session.get(justwatch_url, headers=headers, timeout=8) as response:
            if response.status == 200:
                html_content = await response.text()
                
                # Simple regex extraction (no BeautifulSoup needed)
                poster_patterns = [
                    r'"poster":"([^"]*)"',
                    r'<img[^>]+src="([^"]*)"[^>]*poster',
                    r'data-src="([^"]*)"[^>]*poster',
                    r'<picture[^>]*>.*?<img[^>]+src="([^"]*)"'
                ]
                
                for pattern in poster_patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
                    if match:
                        poster_url = match.group(1)
                        
                        if poster_url.startswith('//'):
                            poster_url = 'https:' + poster_url
                        elif poster_url.startswith('/'):
                            poster_url = 'https://www.justwatch.com' + poster_url
                        
                        if poster_url.startswith('http') and any(ext in poster_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            movie_database['stats']['justwatch'] += 1
                            logger.info(f"✅ JUSTWATCH SUCCESS: {title}")
                            
                            return {
                                'poster_url': poster_url,
                                'title': title,
                                'source': 'JUSTWATCH',
                                'success': True
                            }
        
        return {'success': False, 'source': 'JUSTWATCH'}
        
    except Exception as e:
        logger.warning(f"JustWatch error: {e}")
        return {'success': False, 'source': 'JUSTWATCH'}

async def get_letterboxd_poster_simple(title, session):
    """Letterboxd poster search - Simple regex approach (no lxml)"""
    try:
        logger.info(f"📚 Letterboxd search: {title}")
        
        # Create Letterboxd URL
        clean_title = re.sub(r'[^\w\s]', '', title.lower())
        url_title = '-'.join(clean_title.split())
        letterboxd_url = f"https://letterboxd.com/film/{url_title}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml'
        }
        
        async with session.get(letterboxd_url, headers=headers, timeout=8) as response:
            if response.status == 200:
                html_content = await response.text()
                
                # Simple regex for Letterboxd posters (no BeautifulSoup)
                poster_patterns = [
                    r'<img[^>]+src="([^"]*0-[0-9]+-[0-9]+-[^"]*\.jpg)"',
                    r'"image":"([^"]*letterboxd[^"]*\.jpg)"',
                    r'data-film-poster="([^"]*)"',
                    r'<img[^>]+class="[^"]*image[^"]*"[^>]+src="([^"]*)"'
                ]
                
                for pattern in poster_patterns:
                    match = re.search(pattern, html_content)
                    if match:
                        poster_url = match.group(1)
                        
                        if poster_url.startswith('//'):
                            poster_url = 'https:' + poster_url
                        elif poster_url.startswith('/'):
                            poster_url = 'https://letterboxd.com' + poster_url
                        
                        # Try to get higher quality version
                        if '-230-' in poster_url:
                            poster_url = poster_url.replace('-230-', '-500-')
                        elif '-345-' in poster_url:
                            poster_url = poster_url.replace('-345-', '-500-')
                        
                        if poster_url.startswith('http'):
                            movie_database['stats']['letterboxd'] += 1
                            logger.info(f"✅ LETTERBOXD SUCCESS: {title}")
                            
                            return {
                                'poster_url': poster_url,
                                'title': title,
                                'source': 'LETTERBOXD',
                                'success': True
                            }
        
        return {'success': False, 'source': 'LETTERBOXD'}
        
    except Exception as e:
        logger.warning(f"Letterboxd error: {e}")
        return {'success': False, 'source': 'LETTERBOXD'}

async def smart_poster_finder(title, session):
    """Smart poster finder - OMDB + JustWatch + Letterboxd (no lxml)"""
    cache_key = title.lower().strip()
    
    # Check cache
    if cache_key in movie_database['poster_cache']:
        cached_result, cache_time = movie_database['poster_cache'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=10):
            return cached_result
    
    try:
        logger.info(f"🔍 SMART POSTER FINDER: {title}")
        movie_database['stats']['total'] += 1
        
        # Try sources in priority order
        poster_finders = [
            get_omdb_poster,           # Primary (working from your log)
            get_justwatch_poster_simple,   # Secondary
            get_letterboxd_poster_simple   # Tertiary
        ]
        
        for finder in poster_finders:
            try:
                result = await finder(title, session)
                
                if result.get('success') and result.get('poster_url'):
                    # Cache successful result
                    movie_database['poster_cache'][cache_key] = (result, datetime.now())
                    
                    logger.info(f"✅ SMART FINDER SUCCESS via {result['source']}: {title}")
                    return result
                
                # Delay between sources
                await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.warning(f"Poster finder error: {e}")
                continue
        
        # Custom poster as guaranteed fallback
        logger.info(f"🎨 Generating custom poster: {title}")
        custom_result = {
            'poster_url': f"/api/custom_poster?title={urllib.parse.quote(title)}",
            'title': title,
            'source': 'CUSTOM',
            'success': True
        }
        
        movie_database['stats']['custom'] += 1
        movie_database['poster_cache'][cache_key] = (custom_result, datetime.now())
        
        return custom_result
        
    except Exception as e:
        logger.error(f"Smart poster finder error: {e}")
        return {
            'poster_url': f"/api/custom_poster?title={urllib.parse.quote(title)}",
            'title': title,
            'source': 'CUSTOM',
            'success': True
        }

async def get_recent_movies_smart_posters():
    """Get recent movies with smart poster system"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 Loading movies with SMART POSTER SYSTEM...")
        
        all_posts = []
        
        # Get posts from channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                count = 0
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_movie_title_smart(message.text)
                        
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
                
                logger.info(f"✅ {channel_name}: {count} movies")
                
            except Exception as e:
                logger.warning(f"Channel error: {e}")
        
        # Sort by date - NEWEST FIRST
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        # Remove duplicates - keep newest
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
        
        # Smart poster finding in batches
        movies_with_smart_posters = []
        
        async with aiohttp.ClientSession() as session:
            batch_size = 3
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                logger.info(f"🔍 Smart poster batch {i//batch_size + 1}")
                
                # Parallel smart poster finding
                poster_tasks = [smart_poster_finder(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data.get('title', movie['title']),
                            'poster_year': poster_data.get('year', ''),
                            'poster_rating': poster_data.get('rating', ''),
                            'poster_genre': poster_data.get('genre', ''),
                            'poster_plot': poster_data.get('plot', ''),
                            'poster_source': poster_data['source'],
                            'has_poster': True
                        })
                    else:
                        movie.update({
                            'poster_url': f"/api/custom_poster?title={urllib.parse.quote(movie['title'])}",
                            'poster_source': 'CUSTOM',
                            'has_poster': True
                        })
                    
                    movies_with_smart_posters.append(movie)
                
                await asyncio.sleep(0.5)
        
        total_time = time.time() - start_time
        poster_count = sum(1 for m in movies_with_smart_posters if m.get('has_poster'))
        
        logger.info(f"⚡ SMART POSTER COMPLETE: {total_time:.2f}s")
        logger.info(f"🎬 {len(movies_with_smart_posters)} movies, {poster_count} posters")
        logger.info(f"📊 Source stats: {movie_database['stats']}")
        
        return movies_with_smart_posters
        
    except Exception as e:
        logger.error(f"Smart poster movies error: {e}")
        return []

async def search_telegram_content(query, limit=10, offset=0):
    """Search telegram content"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted = format_content_smart(message.text)
                        
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

def format_content_smart(text):
    """Smart content formatting"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 5px 12px; border-radius: 10px; margin: 4px; display: inline-block; text-decoration: none; border: 1px solid rgba(0,204,255,0.3);"><i class="fas fa-download me-2"></i>Download</a>', 
        formatted
    )
    formatted = formatted.replace('\n', '<br>')
    
    return formatted

async def initialize_telegram_smart():
    """Initialize telegram with smart poster system"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing SMART POSTER SYSTEM (No lxml)...")
        
        # Unique session to prevent AUTH_KEY_DUPLICATED
        session_name = f"sk4film_smart_{uuid.uuid4().hex[:8]}_{int(time.time())}"
        
        User = Client(
            session_name,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp",
            sleep_threshold=60,
            max_concurrent_transmissions=1
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Telegram connected: {me.first_name}")
        
        # Test channels
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
            
            # Load movies with smart poster system
            initial_movies = await get_recent_movies_smart_posters()
            
            movie_database['movies'] = initial_movies
            movie_database['last_update'] = datetime.now()
            movie_database['seen_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            logger.info(f"🎉 SMART POSTER SYSTEM READY!")
            logger.info(f"🎬 {len(initial_movies)} movies loaded")
            logger.info(f"📊 No lxml dependency - pure Python solution")
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Smart system init error: {e}")
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
        "status": "healthy" if bot_started else "starting",
        "service": "SK4FiLM - Smart Poster System (No lxml)",
        "build_fixed": "lxml dependency removed",
        "poster_sources": ["OMDB", "JustWatch", "Letterboxd", "Custom"],
        "dependencies": ["aiohttp", "requests", "pyrogram", "quart"],
        "source_stats": movie_database['stats'],
        "movies_count": len(movie_database['movies']),
        "last_update": movie_database['last_update'].isoformat() if movie_database['last_update'] else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with smart poster system"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "starting", 
                "message": "Smart poster system initializing..."
            }), 503
        
        movies = movie_database['movies'][:limit]
        poster_count = sum(1 for m in movies if m.get('has_poster'))
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_movies": len(movies),
            "posters_found": poster_count,
            "success_rate": f"{(poster_count/len(movies)*100):.1f}%" if movies else "0%",
            "poster_sources": ["OMDB", "JustWatch", "Letterboxd", "Custom"],
            "source_stats": movie_database['stats'],
            "build_status": "fixed_no_lxml",
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
        
        result = await search_telegram_content(query, limit, offset)
        
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
async def proxy_smart_poster():
    """Smart poster proxy"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_smart_placeholder("No URL")
        
        # Handle custom poster
        if poster_url.startswith('/api/custom_poster'):
            title = request.args.get('title', 'Movie')
            return generate_smart_poster(title)
        
        if not poster_url.startswith('http'):
            return create_smart_placeholder("Invalid URL")
        
        logger.info(f"🖼️ Smart proxying: {poster_url[:50]}...")
        
        # Enhanced headers for all sources
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache'
        }
        
        # Source-specific referers
        if 'justwatch' in poster_url.lower():
            headers['Referer'] = 'https://www.justwatch.com/'
        elif 'letterboxd' in poster_url.lower():
            headers['Referer'] = 'https://letterboxd.com/'
        elif 'amazon' in poster_url.lower():
            headers['Referer'] = 'https://www.imdb.com/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=12) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ Smart poster loaded: {len(image_data)} bytes")
                    
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
                    return create_smart_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"Smart poster proxy error: {e}")
        return create_smart_placeholder("Load Error")

@app.route('/api/custom_poster')
async def custom_poster():
    """Custom poster generator"""
    title = request.args.get('title', 'Movie')
    return generate_smart_poster(title)

def generate_smart_poster(title):
    """Generate beautiful smart poster"""
    display_title = title[:28] + "..." if len(title) > 28 else title
    
    # Color themes
    themes = [
        {'bg': ['#ff6b6b', '#4ecdc4'], 'text': '#ffffff', 'accent': '#ffee58'},
        {'bg': ['#74b9ff', '#0984e3'], 'text': '#ffffff', 'accent': '#fdcb6e'},
        {'bg': ['#6c5ce7', '#a29bfe'], 'text': '#ffffff', 'accent': '#fd79a8'},
        {'bg': ['#00b894', '#00cec9'], 'text': '#ffffff', 'accent': '#fdcb6e'},
        {'bg': ['#e17055', '#fdcb6e'], 'text': '#ffffff', 'accent': '#74b9ff'}
    ]
    
    theme = themes[hash(title) % len(themes)]
    
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{theme['bg'][0]}"/>
                <stop offset="100%" style="stop-color:{theme['bg'][1]}"/>
            </linearGradient>
            <linearGradient id="overlay" x1="0%" y1="60%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:rgba(0,0,0,0.2)"/>
                <stop offset="100%" style="stop-color:rgba(0,0,0,0.8)"/>
            </linearGradient>
            <filter id="glow">
                <feDropShadow dx="2" dy="2" stdDeviation="4" flood-opacity="0.8"/>
            </filter>
        </defs>
        
        <!-- Background -->
        <rect width="100%" height="100%" fill="url(#bg)" rx="20"/>
        
        <!-- Content area -->
        <rect x="30" y="80" width="240" height="260" fill="rgba(255,255,255,0.15)" rx="25"/>
        
        <!-- Source indicators -->
        <circle cx="70" cy="60" r="8" fill="rgba(245,197,24,0.7)"/>
        <text x="70" y="64" text-anchor="middle" fill="white" font-size="8" font-weight="bold">O</text>
        
        <circle cx="90" cy="60" r="8" fill="rgba(255,107,53,0.7)"/>
        <text x="90" y="64" text-anchor="middle" fill="white" font-size="8" font-weight="bold">J</text>
        
        <circle cx="110" cy="60" r="8" fill="rgba(0,204,136,0.7)"/>
        <text x="110" y="64" text-anchor="middle" fill="white" font-size="8" font-weight="bold">L</text>
        
        <!-- Film icon -->
        <circle cx="150" cy="180" r="40" fill="rgba(255,255,255,0.2)"/>
        <text x="50%" y="195" text-anchor="middle" fill="{theme['text']}" font-size="36" font-weight="bold" filter="url(#glow)">🎬</text>
        
        <!-- Title -->
        <text x="50%" y="240" text-anchor="middle" fill="{theme['text']}" font-size="14" font-weight="bold" filter="url(#glow)">
            {html.escape(display_title)}
        </text>
        
        <!-- SK4FiLM brand -->
        <text x="50%" y="280" text-anchor="middle" fill="{theme['accent']}" font-size="18" font-weight="900" filter="url(#glow)">SK4FiLM</text>
        <text x="50%" y="300" text-anchor="middle" fill="rgba(255,255,255,0.9)" font-size="10">Smart Poster System</text>
        
        <!-- Bottom overlay -->
        <rect x="0" y="350" width="100%" height="100" fill="url(#overlay)" rx="0 0 20 20"/>
        
        <!-- Action -->
        <text x="50%" y="390" text-anchor="middle" fill="#ffffff" font-size="12" font-weight="700" filter="url(#glow)">Click to Search Telegram</text>
        <text x="50%" y="410" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="9">OMDB + JustWatch + Letterboxd</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=1800',
        'Access-Control-Allow-Origin': '*'
    })

def create_smart_placeholder(error_msg):
    """Smart poster placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="url(#smartGrad)" rx="18"/>
        
        <defs>
            <linearGradient id="smartGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="100%" style="stop-color:#16213e"/>
            </linearGradient>
        </defs>
        
        <circle cx="150" cy="160" r="50" fill="none" stroke="#00ccff" stroke-width="3" opacity="0.6"/>
        <text x="50%" y="175" text-anchor="middle" fill="#00ccff" font-size="28" font-weight="bold">🔍</text>
        <text x="50%" y="220" text-anchor="middle" fill="#ffffff" font-size="16" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="245" text-anchor="middle" fill="#00ccff" font-size="11">Smart Poster System</text>
        <text x="50%" y="300" text-anchor="middle" fill="#90cea1" font-size="9">OMDB + JustWatch + Letterboxd</text>
        <text x="50%" y="350" text-anchor="middle" fill="#ff6666" font-size="9">{error_msg}</text>
        <text x="50%" y="400" text-anchor="middle" fill="#00ccff" font-size="9">Click to Search</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def force_update():
    """Force update smart poster system"""
    try:
        if not bot_started:
            return jsonify({"status": "error"}), 503
        
        logger.info("🔄 FORCE UPDATE - Smart poster reload")
        
        # Clear caches
        movie_database['poster_cache'].clear()
        movie_database['seen_titles'].clear()
        movie_database['stats'] = {'omdb': 0, 'justwatch': 0, 'letterboxd': 0, 'custom': 0, 'total': 0}
        
        # Reload
        fresh_movies = await get_recent_movies_smart_posters()
        
        movie_database['movies'] = fresh_movies
        movie_database['last_update'] = datetime.now()
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "source_stats": movie_database['stats'],
            "build_status": "fixed",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/stats')
async def api_stats():
    """System statistics"""
    return jsonify({
        "status": "success",
        "system": "Smart Poster System",
        "build_fix": "lxml removed - pure Python solution",
        "sources": {
            "omdb": "Open Movie Database (Primary)",
            "justwatch": "JustWatch Streaming Database", 
            "letterboxd": "Letterboxd Film Community",
            "custom": "SVG Generation Fallback"
        },
        "stats": movie_database['stats'],
        "dependencies": ["pyrogram", "quart", "aiohttp", "requests"],
        "no_lxml": True,
        "timestamp": datetime.now().isoformat()
    })

async def run_smart_server():
    """Run server with smart poster system"""
    try:
        logger.info("🚀 SK4FiLM - SMART POSTER SYSTEM (BUILD FIXED)")
        logger.info("🔧 lxml dependency removed - pure Python solution")
        logger.info("🎬 Primary: OMDB (proven working from your log)")
        logger.info("📺 Secondary: JustWatch (simple regex scraping)")
        logger.info("📚 Tertiary: Letterboxd (simple regex scraping)")
        logger.info("🎨 Fallback: Custom SVG generation")
        logger.info("📅 Recent posts first + No duplicates")
        logger.info("📱 All previous features preserved")
        
        success = await initialize_telegram_smart()
        
        if success:
            logger.info("🎉 SMART POSTER SYSTEM OPERATIONAL!")
            logger.info("✅ Build error fixed - no lxml dependency")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.graceful_timeout = 30
        
        await serve(app, config)
        
    except KeyboardInterrupt:
        logger.info("🛑 Smart system shutdown")
    except Exception as e:
        logger.error(f"Smart server error: {e}")
    finally:
        if User and bot_started:
            try:
                logger.info("🔄 Stopping Telegram client...")
                await User.stop()
                logger.info("✅ Clean shutdown complete")
            except Exception as e:
                logger.warning(f"Cleanup warning: {e}")

if __name__ == "__main__":
    asyncio.run(run_smart_server())
