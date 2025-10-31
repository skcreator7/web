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
    
    # Multiple poster sources - OMDB + alternatives
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4"]
    TMDB_KEYS = ["e547e17d4e91f3e62a571655cd1ccaff", "a1b2c3d4e5f6g7h8"]
    
    # Hidden auto update - 3 minutes
    AUTO_UPDATE_INTERVAL = 180

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False
auto_update_task = None

# Movie database
movie_db = {
    'all_movies': [],
    'last_update': None,
    'poster_cache': {},
    'updating': False,
    'stats': {'omdb': 0, 'tmdb': 0, 'justwatch': 0, 'letterboxd': 0, 'imdb': 0, 'custom': 0, 'auto_updates': 0}
}

def extract_title_enhanced(text):
    """Enhanced title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        clean_text = re.sub(r'[^\w\s\(\)\-\.\n\u0900-\u097F]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        patterns = [
            r'🎬\s*([^-\n]{4,45})(?:\s*-|\n|$)',
            r'^([^(]{4,45})\s*\(\d{4}\)',
            r'^([^-]{4,45})\s*-\s*(?:Hindi|English|Tamil|Telugu|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})',
            r'"([^"]{4,35})"',
            r'Movie[:\s]*([^-\n]{4,40})',
            r'Film[:\s]*([^-\n]{4,40})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_title_enhanced(title):
                    return title
        
        return None
        
    except:
        return None

def validate_title_enhanced(title):
    """Enhanced title validation"""
    if not title or len(title) < 4 or len(title) > 45:
        return False
    
    bad_words = ['size', 'quality', 'download', 'link', 'channel', 'mb', 'gb', 'file', 'join']
    if any(word in title.lower() for word in bad_words):
        return False
    
    return bool(re.search(r'[a-zA-Z]', title))

async def get_poster_multiple_sources(title, session):
    """Multiple poster sources - OMDB + TMDB + JustWatch + Letterboxd + IMDB + Custom"""
    cache_key = title.lower().strip()
    
    if cache_key in movie_db['poster_cache']:
        cached, cache_time = movie_db['poster_cache'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=10):
            return cached
    
    try:
        logger.info(f"🔍 MULTIPLE SOURCES: {title}")
        
        # SOURCE 1: OMDB (Primary)
        for api_key in Config.OMDB_KEYS:
            try:
                omdb_url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={api_key}"
                
                async with session.get(omdb_url, timeout=6) as response:
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
                                'source': 'OMDB',
                                'success': True
                            }
                            
                            movie_db['poster_cache'][cache_key] = (result, datetime.now())
                            movie_db['stats']['omdb'] += 1
                            
                            logger.info(f"✅ OMDB SUCCESS: {title}")
                            return result
                
                await asyncio.sleep(0.1)
                
            except:
                continue
        
        logger.info(f"🔄 OMDB failed, trying TMDB for: {title}")
        
        # SOURCE 2: TMDB (Fallback 1)
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
                                    'title': movie.get('title', title),
                                    'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                                    'rating': f"{movie.get('vote_average', 0):.1f}",
                                    'source': 'TMDB',
                                    'success': True
                                }
                                
                                movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                movie_db['stats']['tmdb'] += 1
                                
                                logger.info(f"✅ TMDB SUCCESS: {title}")
                                return result
                
            except Exception as e:
                logger.warning(f"TMDB error: {e}")
        
        logger.info(f"🔄 TMDB failed, trying JustWatch for: {title}")
        
        # SOURCE 3: JustWatch (Fallback 2)
        try:
            clean_title = re.sub(r'[^\w\s]', '', title.lower())
            url_title = '-'.join(clean_title.split())
            justwatch_url = f"https://www.justwatch.com/in/movie/{url_title}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(justwatch_url, headers=headers, timeout=8) as response:
                if response.status == 200:
                    html_content = await response.text()
                    
                    poster_patterns = [
                        r'"poster":"([^"]*)"',
                        r'<img[^>]+src="([^"]*)"[^>]*poster'
                    ]
                    
                    for pattern in poster_patterns:
                        match = re.search(pattern, html_content)
                        if match:
                            poster_url = match.group(1)
                            
                            if poster_url.startswith('//'):
                                poster_url = 'https:' + poster_url
                            
                            if poster_url.startswith('http') and any(ext in poster_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                                result = {
                                    'poster_url': poster_url,
                                    'title': title,
                                    'source': 'JUSTWATCH',
                                    'success': True
                                }
                                
                                movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                movie_db['stats']['justwatch'] += 1
                                
                                logger.info(f"✅ JUSTWATCH SUCCESS: {title}")
                                return result
        except:
            pass
        
        logger.info(f"🔄 JustWatch failed, trying Letterboxd for: {title}")
        
        # SOURCE 4: Letterboxd (Fallback 3)
        try:
            clean_title = re.sub(r'[^\w\s]', '', title.lower())
            url_title = '-'.join(clean_title.split())
            letterboxd_url = f"https://letterboxd.com/film/{url_title}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(letterboxd_url, headers=headers, timeout=8) as response:
                if response.status == 200:
                    html_content = await response.text()
                    
                    poster_patterns = [
                        r'<img[^>]+src="([^"]*0-[0-9]+-[0-9]+-[^"]*\.jpg)"',
                        r'"image":"([^"]*letterboxd[^"]*\.jpg)"'
                    ]
                    
                    for pattern in poster_patterns:
                        match = re.search(pattern, html_content)
                        if match:
                            poster_url = match.group(1)
                            
                            if poster_url.startswith('//'):
                                poster_url = 'https:' + poster_url
                            
                            if '-230-' in poster_url:
                                poster_url = poster_url.replace('-230-', '-500-')
                            
                            if poster_url.startswith('http'):
                                result = {
                                    'poster_url': poster_url,
                                    'title': title,
                                    'source': 'LETTERBOXD',
                                    'success': True
                                }
                                
                                movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                movie_db['stats']['letterboxd'] += 1
                                
                                logger.info(f"✅ LETTERBOXD SUCCESS: {title}")
                                return result
        except:
            pass
        
        logger.info(f"🔄 Letterboxd failed, trying IMDB search for: {title}")
        
        # SOURCE 5: IMDB Search (Fallback 4)
        try:
            imdb_search = f"https://www.imdb.com/find/?q={urllib.parse.quote(title)}&ref_=nv_sr_sm"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(imdb_search, headers=headers, timeout=8) as response:
                if response.status == 200:
                    html_content = await response.text()
                    
                    # Look for poster images in IMDB search results
                    poster_patterns = [
                        r'<img[^>]+src="([^"]*amazon[^"]*\.jpg)"',
                        r'<img[^>]+loadlate="([^"]*amazon[^"]*\.jpg)"'
                    ]
                    
                    for pattern in poster_patterns:
                        match = re.search(pattern, html_content)
                        if match:
                            poster_url = match.group(1)
                            
                            if poster_url.startswith('http') and 'amazon' in poster_url:
                                result = {
                                    'poster_url': poster_url,
                                    'title': title,
                                    'source': 'IMDB',
                                    'success': True
                                }
                                
                                movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                movie_db['stats']['imdb'] += 1
                                
                                logger.info(f"✅ IMDB SUCCESS: {title}")
                                return result
        except:
            pass
        
        # Final fallback - Custom poster
        logger.info(f"❌ All sources failed, generating custom: {title}")
        custom_result = {
            'poster_url': f"/api/clean_poster?title={urllib.parse.quote(title)}",
            'title': title,
            'source': 'CUSTOM',
            'success': True
        }
        
        movie_db['poster_cache'][cache_key] = (custom_result, datetime.now())
        movie_db['stats']['custom'] += 1
        
        return custom_result
        
    except:
        return {
            'poster_url': f"/api/clean_poster?title={urllib.parse.quote(title)}",
            'title': title,
            'source': 'CUSTOM',
            'success': True
        }

def is_new_post(post_date):
    """Check if post is within 24 hours"""
    try:
        if isinstance(post_date, str):
            post_date = datetime.fromisoformat(post_date.replace('Z', '+00:00'))
        
        hours_ago = (datetime.now() - post_date.replace(tzinfo=None)).total_seconds() / 3600
        return hours_ago <= 24
    except:
        return False

async def silent_background_update():
    """SILENT background update - no visible indicators"""
    if not User or not bot_started or movie_db['updating']:
        return
    
    try:
        movie_db['updating'] = True
        logger.info("🔄 SILENT AUTO UPDATE - Hidden from users")
        
        all_posts = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                count = 0
                async for message in User.get_chat_history(channel_id, limit=30):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_title_enhanced(message.text)
                        
                        if title:
                            all_posts.append({
                                'title': title,
                                'original_text': message.text,
                                'date': message.date,
                                'date_iso': message.date.isoformat(),
                                'channel': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'message_id': message.id,
                                'is_new': is_new_post(message.date)
                            })
                            count += 1
                
            except Exception as e:
                logger.warning(f"Silent update channel error: {e}")
        
        # Sort newest first
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
        
        # Add posters from multiple sources
        async with aiohttp.ClientSession() as session:
            batch_size = 5
            
            for i in range(0, min(len(unique_movies), 50), batch_size):
                batch = unique_movies[i:i + batch_size]
                
                poster_tasks = [get_poster_multiple_sources(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data['title'],
                            'poster_year': poster_data.get('year', ''),
                            'poster_rating': poster_data.get('rating', ''),
                            'poster_source': poster_data['source'],
                            'has_poster': True
                        })
                
                await asyncio.sleep(0.2)
        
        # Silent update
        movie_db['all_movies'] = unique_movies
        movie_db['last_update'] = datetime.now()
        movie_db['stats']['auto_updates'] += 1
        
        logger.info(f"✅ SILENT UPDATE: {len(unique_movies)} movies updated in background")
        logger.info(f"📊 Source stats: {movie_db['stats']}")
        
    except Exception as e:
        logger.error(f"Silent background update error: {e}")
    finally:
        movie_db['updating'] = False

async def start_hidden_auto_update():
    """Start HIDDEN auto update - no visible indicators"""
    global auto_update_task
    
    async def hidden_update_loop():
        while bot_started:
            try:
                await asyncio.sleep(Config.AUTO_UPDATE_INTERVAL)
                logger.info("🔄 HIDDEN AUTO UPDATE starting...")
                await silent_background_update()
            except Exception as e:
                logger.error(f"Hidden auto update error: {e}")
    
    auto_update_task = asyncio.create_task(hidden_update_loop())
    logger.info(f"✅ HIDDEN auto update started (every {Config.AUTO_UPDATE_INTERVAL//60} minutes - SILENT)")

async def search_with_pagination(query, limit=8, page=1):
    """Search with pagination"""
    try:
        offset = (page - 1) * limit
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=50):
                    if message.text:
                        original_content = format_original_post(message.text)
                        
                        results.append({
                            'content': original_content,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'links': len(re.findall(r'https?://[^\s]+', message.text)),
                            'is_new': is_new_post(message.date) if message.date else False
                        })
                        
            except Exception as e:
                logger.warning(f"Search error: {e}")
        
        results.sort(key=lambda x: (x['links'], x['date']), reverse=True)
        
        total_results = len(results)
        paginated = results[offset:offset + limit]
        total_pages = math.ceil(total_results / limit) if total_results > 0 else 1
        
        return {
            "results": paginated,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_results": total_results,
                "per_page": limit,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }
        
    except:
        return {
            "results": [],
            "pagination": {"current_page": 1, "total_pages": 1, "total_results": 0, "per_page": limit}
        }

def format_original_post(text):
    """Original post format - no download buttons"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    
    # Original links - plain format
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; text-decoration: underline;">\1</a>', 
        formatted
    )
    
    formatted = formatted.replace('\n', '<br>')
    return formatted

async def init_telegram_hidden():
    """Initialize with hidden auto update"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing HIDDEN AUTO UPDATE system...")
        
        session_name = f"sk4film_hidden_{uuid.uuid4().hex[:8]}_{int(time.time())}"
        
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
        logger.info(f"✅ Connected: {me.first_name}")
        
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
            
            # Initial load
            await silent_background_update()
            
            # Start HIDDEN auto update
            await start_hidden_auto_update()
            
            logger.info(f"🎉 HIDDEN AUTO UPDATE SYSTEM READY!")
            logger.info(f"🔄 SILENT background updates every {Config.AUTO_UPDATE_INTERVAL//60} minutes")
            logger.info(f"👤 Users won't see auto update indicators")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Hidden init error: {e}")
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
        "service": "SK4FiLM - Hidden Auto Update",
        "poster_sources": ["OMDB", "TMDB", "JustWatch", "Letterboxd", "IMDB", "Custom"],
        "features": ["hidden_auto_update", "multiple_poster_sources", "pagination"],
        "stats": movie_db['stats'],
        "total_movies": len(movie_db['all_movies']),
        "last_update": movie_db['last_update'].isoformat() if movie_db['last_update'] else None,
        "user_visible_auto_update": False,  # Hidden from users
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with pagination - no auto update indicators"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 12))
        
        if not bot_started:
            return jsonify({"status": "starting"}), 503
        
        total_movies = len(movie_db['all_movies'])
        offset = (page - 1) * limit
        paginated_movies = movie_db['all_movies'][offset:offset + limit]
        total_pages = math.ceil(total_movies / limit) if total_movies > 0 else 1
        
        return jsonify({
            "status": "success",
            "movies": paginated_movies,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_movies": total_movies,
                "per_page": limit,
                "has_next": page < total_pages,
                "has_previous": page > 1,
                "showing_from": offset + 1,
                "showing_to": min(offset + limit, total_movies)
            },
            "multiple_sources": True,
            "hidden_auto_update": True,  # Users don't see this
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """Search API with pagination"""
    try:
        query = request.args.get('query', '').strip()
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 8))
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        result = await search_with_pagination(query, limit, page)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": result["results"],
            "pagination": result["pagination"],
            "original_format": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster')
async def proxy_poster():
    """Multiple source poster proxy"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_clean_placeholder("No URL")
        
        if poster_url.startswith('/api/clean_poster'):
            title = request.args.get('title', 'Movie')
            return create_clean_poster_svg(title)
        
        if not poster_url.startswith('http'):
            return create_clean_placeholder("Invalid URL")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/*',
            'Referer': get_referer_for_source(poster_url)
        }
        
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
                            'Access-Control-Allow-Origin': '*'
                        }
                    )
                else:
                    return create_clean_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        return create_clean_placeholder("Load Error")

def get_referer_for_source(poster_url):
    """Get appropriate referer based on poster source"""
    if 'tmdb' in poster_url.lower():
        return 'https://www.themoviedb.org/'
    elif 'justwatch' in poster_url.lower():
        return 'https://www.justwatch.com/'
    elif 'letterboxd' in poster_url.lower():
        return 'https://letterboxd.com/'
    elif 'amazon' in poster_url.lower():
        return 'https://www.imdb.com/'
    else:
        return 'https://www.google.com/'

@app.route('/api/clean_poster')
async def clean_poster_api():
    """Clean custom poster"""
    title = request.args.get('title', 'Movie')
    return create_clean_poster_svg(title)

def create_clean_poster_svg(title):
    """CLEAN custom poster - Only essentials"""
    display_title = title[:20] + "..." if len(title) > 20 else title
    
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <!-- Clean background -->
        <rect width="100%" height="100%" fill="#2c3e50" rx="12"/>
        
        <!-- Poster frame -->
        <rect x="30" y="80" width="240" height="290" fill="rgba(255,255,255,0.05)" rx="12"/>
        
        <!-- Movie icon -->
        <text x="50%" y="200" text-anchor="middle" fill="#ffffff" font-size="40">🎬</text>
        
        <!-- TITLE ONLY -->
        <text x="50%" y="250" text-anchor="middle" fill="#ffffff" font-size="14" font-weight="bold">
            {html.escape(display_title)}
        </text>
        
        <!-- Minimal brand -->
        <text x="50%" y="390" text-anchor="middle" fill="#3498db" font-size="12">SK4FiLM</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=1800',
        'Access-Control-Allow-Origin': '*'
    })

def create_clean_placeholder(error_msg):
    """Clean error placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#34495e" rx="12"/>
        <text x="50%" y="200" text-anchor="middle" fill="#3498db" font-size="28">🎬</text>
        <text x="50%" y="240" text-anchor="middle" fill="#ffffff" font-size="12">SK4FiLM</text>
        <text x="50%" y="280" text-anchor="middle" fill="#e74c3c" font-size="9">{error_msg}</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

async def run_hidden_server():
    try:
        logger.info("🚀 SK4FiLM - HIDDEN AUTO UPDATE SYSTEM")
        logger.info("🔄 Silent background updates every 3 minutes")
        logger.info("👤 Users won't see auto update indicators")
        logger.info("🎬 Multiple poster sources: OMDB → TMDB → JustWatch → Letterboxd → IMDB → Custom")
        logger.info("📄 Pagination system active")
        logger.info("🏠 Search only from home page")
        
        success = await init_telegram_hidden()
        
        if success:
            logger.info("🎉 HIDDEN AUTO UPDATE OPERATIONAL!")
            logger.info("👻 All updates happen silently in background")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"Hidden server error: {e}")
    finally:
        if auto_update_task:
            auto_update_task.cancel()
        if User:
            try:
                await User.stop()
            except:
                pass

if __name__ == "__main__":
    asyncio.run(run_hidden_server())
