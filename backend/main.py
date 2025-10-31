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
    
    # HIGH QUALITY poster sources
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4"]
    TMDB_KEYS = ["e547e17d4e91f3e62a571655cd1ccaff", "a1b2c3d4e5f6g7h8"]
    
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
    'home_movies': [],      # For home display (no pagination)
    'last_update': None,
    'poster_cache': {},
    'updating': False,
    'stats': {'omdb': 0, 'tmdb_hq': 0, 'justwatch_hq': 0, 'letterboxd_hq': 0, 'imdb_hq': 0, 'custom': 0}
}

def extract_title_smart(text):
    """Smart title extraction"""
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
            r'"([^"]{4,35})"'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_title_smart(title):
                    return title
        
        return None
        
    except:
        return None

def validate_title_smart(title):
    """Enhanced title validation"""
    if not title or len(title) < 4 or len(title) > 45:
        return False
    
    bad_words = ['size', 'quality', 'download', 'link', 'channel', 'mb', 'gb', 'file']
    if any(word in title.lower() for word in bad_words):
        return False
    
    return bool(re.search(r'[a-zA-Z]', title))

async def get_high_quality_poster(title, session):
    """HIGH QUALITY poster sources - Better quality control"""
    cache_key = title.lower().strip()
    
    if cache_key in movie_db['poster_cache']:
        cached, cache_time = movie_db['poster_cache'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=12):
            return cached
    
    try:
        logger.info(f"🔍 HIGH QUALITY POSTER: {title}")
        
        # SOURCE 1: OMDB (Primary - Best Quality)
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
                                'source': 'OMDB',
                                'quality': 'HIGH',
                                'success': True
                            }
                            
                            movie_db['poster_cache'][cache_key] = (result, datetime.now())
                            movie_db['stats']['omdb'] += 1
                            
                            logger.info(f"✅ OMDB HIGH QUALITY: {title}")
                            return result
                
                await asyncio.sleep(0.1)
                
            except:
                continue
        
        logger.info(f"🔄 OMDB failed, trying TMDB HIGH QUALITY for: {title}")
        
        # SOURCE 2: TMDB HIGH QUALITY (w780 instead of w500)
        for tmdb_key in Config.TMDB_KEYS:
            try:
                tmdb_search_url = "https://api.themoviedb.org/3/search/movie"
                tmdb_params = {
                    'api_key': tmdb_key,
                    'query': title,
                    'language': 'en-US',
                    'include_adult': 'false'
                }
                
                async with session.get(tmdb_search_url, params=tmdb_params, timeout=8) as response:
                    if response.status == 200:
                        tmdb_data = await response.json()
                        
                        if tmdb_data.get('results') and len(tmdb_data['results']) > 0:
                            movie = tmdb_data['results'][0]
                            poster_path = movie.get('poster_path')
                            
                            if poster_path:
                                # HIGH QUALITY TMDB poster (w780 instead of w500)
                                hq_poster_url = f"https://image.tmdb.org/t/p/w780{poster_path}"
                                
                                result = {
                                    'poster_url': hq_poster_url,
                                    'title': movie.get('title', title),
                                    'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                                    'rating': f"{movie.get('vote_average', 0):.1f}",
                                    'source': 'TMDB',
                                    'quality': 'HIGH',
                                    'success': True
                                }
                                
                                movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                movie_db['stats']['tmdb_hq'] += 1
                                
                                logger.info(f"✅ TMDB HIGH QUALITY: {title}")
                                return result
                
            except Exception as e:
                logger.warning(f"TMDB HQ error: {e}")
        
        logger.info(f"🔄 TMDB failed, trying JustWatch HIGH QUALITY for: {title}")
        
        # SOURCE 3: JustWatch HIGH QUALITY (Better image extraction)
        try:
            # Enhanced title cleaning for JustWatch URLs
            clean_title = re.sub(r'[^\w\s]', '', title.lower())
            clean_title = re.sub(r'\b(the|a|an)\b', '', clean_title).strip()  # Remove articles
            url_title = '-'.join(clean_title.split())
            
            justwatch_urls = [
                f"https://www.justwatch.com/in/movie/{url_title}",
                f"https://www.justwatch.com/us/movie/{url_title}"  # Try US too
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Cache-Control': 'no-cache'
            }
            
            for justwatch_url in justwatch_urls:
                try:
                    async with session.get(justwatch_url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            html_content = await response.text()
                            
                            # Enhanced poster extraction patterns
                            hq_poster_patterns = [
                                r'"poster_url":"([^"]*)"',
                                r'"posterUrl":"([^"]*)"',
                                r'"image":"([^"]*justwatch[^"]*\.jpg[^"]*)"',
                                r'<img[^>]+src="([^"]*s\d{3,4}\.justwatch[^"]*\.jpg)"',
                                r'data-src="([^"]*justwatch[^"]*\.webp)"'
                            ]
                            
                            for pattern in hq_poster_patterns:
                                match = re.search(pattern, html_content, re.IGNORECASE)
                                if match:
                                    poster_url = match.group(1)
                                    
                                    # Fix URL format
                                    if poster_url.startswith('//'):
                                        poster_url = 'https:' + poster_url
                                    elif poster_url.startswith('/'):
                                        poster_url = 'https://www.justwatch.com' + poster_url
                                    
                                    # Get highest quality version
                                    if 's166' in poster_url:
                                        poster_url = poster_url.replace('s166', 's592')
                                    elif 's276' in poster_url:
                                        poster_url = poster_url.replace('s276', 's592')
                                    
                                    if poster_url.startswith('http') and ('justwatch' in poster_url or any(ext in poster_url.lower() for ext in ['.jpg', '.jpeg', '.webp'])):
                                        result = {
                                            'poster_url': poster_url,
                                            'title': title,
                                            'source': 'JUSTWATCH',
                                            'quality': 'HIGH',
                                            'success': True
                                        }
                                        
                                        movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                        movie_db['stats']['justwatch_hq'] += 1
                                        
                                        logger.info(f"✅ JUSTWATCH HIGH QUALITY: {title}")
                                        return result
                    
                    await asyncio.sleep(0.2)
                    
                except:
                    continue
                    
        except Exception as e:
            logger.warning(f"JustWatch HQ error: {e}")
        
        logger.info(f"🔄 JustWatch failed, trying Letterboxd HIGH QUALITY for: {title}")
        
        # SOURCE 4: Letterboxd HIGH QUALITY (Better resolution)
        try:
            clean_title = re.sub(r'[^\w\s]', '', title.lower())
            clean_title = re.sub(r'\b(the|a|an)\b', '', clean_title).strip()
            url_title = '-'.join(clean_title.split())
            letterboxd_url = f"https://letterboxd.com/film/{url_title}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://letterboxd.com/'
            }
            
            async with session.get(letterboxd_url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    html_content = await response.text()
                    
                    # Enhanced Letterboxd poster patterns
                    hq_poster_patterns = [
                        r'<img[^>]+src="([^"]*0-[0-9]+-[0-9]+-crop[^"]*\.jpg)"',  # Crop versions
                        r'<img[^>]+src="([^"]*0-[0-9]+-[0-9]+-[^"]*\.jpg)"',      # Standard
                        r'"image":"([^"]*letterboxd[^"]*\.jpg)"',
                        r'data-film-poster="([^"]*)"',
                        r'data-target-link="([^"]*\.jpg)"'
                    ]
                    
                    for pattern in hq_poster_patterns:
                        match = re.search(pattern, html_content)
                        if match:
                            poster_url = match.group(1)
                            
                            if poster_url.startswith('//'):
                                poster_url = 'https:' + poster_url
                            elif poster_url.startswith('/'):
                                poster_url = 'https://letterboxd.com' + poster_url
                            
                            # Get HIGHEST quality version
                            if '-150-' in poster_url:
                                poster_url = poster_url.replace('-150-', '-500-')
                            elif '-230-' in poster_url:
                                poster_url = poster_url.replace('-230-', '-500-')
                            elif '-345-' in poster_url:
                                poster_url = poster_url.replace('-345-', '-500-')
                            
                            if poster_url.startswith('http'):
                                result = {
                                    'poster_url': poster_url,
                                    'title': title,
                                    'source': 'LETTERBOXD',
                                    'quality': 'HIGH',
                                    'success': True
                                }
                                
                                movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                movie_db['stats']['letterboxd_hq'] += 1
                                
                                logger.info(f"✅ LETTERBOXD HIGH QUALITY: {title}")
                                return result
                                
        except Exception as e:
            logger.warning(f"Letterboxd HQ error: {e}")
        
        logger.info(f"🔄 Letterboxd failed, trying IMDB HIGH QUALITY for: {title}")
        
        # SOURCE 5: IMDB HIGH QUALITY (Direct poster search)
        try:
            # Enhanced IMDB search
            search_variations = [
                title,
                title.replace(' ', '+'),
                re.sub(r'\([^)]*\)', '', title).strip()  # Remove year/brackets
            ]
            
            for search_title in search_variations:
                try:
                    imdb_search = f"https://www.imdb.com/find/?q={urllib.parse.quote(search_title)}&s=tt&ref_=fn_al_tt_mr"
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Referer': 'https://www.imdb.com/'
                    }
                    
                    async with session.get(imdb_search, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            html_content = await response.text()
                            
                            # HIGH QUALITY IMDB poster patterns
                            hq_poster_patterns = [
                                r'<img[^>]+src="([^"]*media-amazon[^"]*\.jpg)"',
                                r'<img[^>]+loadlate="([^"]*media-amazon[^"]*\.jpg)"',
                                r'"image":"([^"]*amazonaws[^"]*\.jpg)"',
                                r'data-src="([^"]*imdb[^"]*\.jpg)"'
                            ]
                            
                            for pattern in hq_poster_patterns:
                                match = re.search(pattern, html_content)
                                if match:
                                    poster_url = match.group(1)
                                    
                                    # Enhance to highest quality
                                    if 'UX' in poster_url and 'CR' in poster_url:
                                        # Try to get larger version
                                        poster_url = re.sub(r'UX\d+', 'UX500', poster_url)
                                        poster_url = re.sub(r'CR\d+,\d+,\d+,\d+', 'CR0,0,500,750', poster_url)
                                    
                                    if poster_url.startswith('http') and 'amazon' in poster_url:
                                        result = {
                                            'poster_url': poster_url,
                                            'title': title,
                                            'source': 'IMDB',
                                            'quality': 'HIGH',
                                            'success': True
                                        }
                                        
                                        movie_db['poster_cache'][cache_key] = (result, datetime.now())
                                        movie_db['stats']['imdb_hq'] += 1
                                        
                                        logger.info(f"✅ IMDB HIGH QUALITY: {title}")
                                        return result
                    
                    await asyncio.sleep(0.2)
                    
                except:
                    continue
                    
        except Exception as e:
            logger.warning(f"IMDB HQ error: {e}")
        
        # Final fallback - Enhanced custom poster
        logger.info(f"❌ All HQ sources failed, generating enhanced custom: {title}")
        custom_result = {
            'poster_url': f"/api/enhanced_poster?title={urllib.parse.quote(title)}",
            'title': title,
            'source': 'CUSTOM',
            'quality': 'CUSTOM',
            'success': True
        }
        
        movie_db['poster_cache'][cache_key] = (custom_result, datetime.now())
        movie_db['stats']['custom'] += 1
        
        return custom_result
        
    except:
        return {
            'poster_url': f"/api/enhanced_poster?title={urllib.parse.quote(title)}",
            'title': title,
            'source': 'CUSTOM',
            'quality': 'CUSTOM',
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

async def background_update_hq():
    """Background update with HIGH QUALITY posters"""
    if not User or not bot_started or movie_db['updating']:
        return
    
    try:
        movie_db['updating'] = True
        logger.info("🔄 BACKGROUND HIGH QUALITY UPDATE")
        
        all_posts = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                count = 0
                async for message in User.get_chat_history(channel_id, limit=30):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_title_smart(message.text)
                        
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
                logger.warning(f"Background channel error: {e}")
        
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
        
        # Add HIGH QUALITY posters
        async with aiohttp.ClientSession() as session:
            batch_size = 4  # Smaller batches for better quality control
            
            for i in range(0, min(len(unique_movies), 60), batch_size):
                batch = unique_movies[i:i + batch_size]
                
                poster_tasks = [get_high_quality_poster(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data['title'],
                            'poster_year': poster_data.get('year', ''),
                            'poster_rating': poster_data.get('rating', ''),
                            'poster_source': poster_data['source'],
                            'poster_quality': poster_data.get('quality', 'STANDARD'),
                            'has_poster': True
                        })
                
                await asyncio.sleep(0.3)  # Longer delay for quality
        
        # Update database
        movie_db['all_movies'] = unique_movies
        movie_db['home_movies'] = unique_movies[:24]  # First 24 for home (no pagination)
        movie_db['last_update'] = datetime.now()
        
        logger.info(f"✅ BACKGROUND HQ UPDATE: {len(unique_movies)} movies")
        logger.info(f"🏠 Home movies: {len(movie_db['home_movies'])} (no pagination)")
        logger.info(f"📊 HQ Source stats: {movie_db['stats']}")
        
    except Exception as e:
        logger.error(f"Background HQ update error: {e}")
    finally:
        movie_db['updating'] = False

async def start_hidden_hq_update():
    """Start hidden high quality update"""
    global auto_update_task
    
    async def hq_update_loop():
        while bot_started:
            try:
                await asyncio.sleep(Config.AUTO_UPDATE_INTERVAL)
                logger.info("🔄 Starting HIGH QUALITY background update...")
                await background_update_hq()
            except Exception as e:
                logger.error(f"HQ auto update error: {e}")
    
    auto_update_task = asyncio.create_task(hq_update_loop())
    logger.info(f"✅ HIGH QUALITY background updates started (every {Config.AUTO_UPDATE_INTERVAL//60} minutes)")

async def search_with_pagination(query, limit=8, page=1):
    """Search with pagination - Only for results page"""
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
        return {"results": [], "pagination": {"current_page": 1, "total_pages": 1, "total_results": 0}}

def format_original_post(text):
    """Original post format"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; text-decoration: underline;">\1</a>', 
        formatted
    )
    formatted = formatted.replace('\n', '<br>')
    return formatted

async def init_telegram_hq():
    """Initialize with high quality system"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing HIGH QUALITY POSTER system...")
        
        session_name = f"sk4film_hq_{uuid.uuid4().hex[:8]}_{int(time.time())}"
        
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
            
            # Initial HIGH QUALITY load
            await background_update_hq()
            
            # Start hidden HIGH QUALITY auto updates
            await start_hidden_hq_update()
            
            logger.info(f"🎉 HIGH QUALITY POSTER SYSTEM READY!")
            logger.info(f"🏠 Home: {len(movie_db['home_movies'])} movies (no pagination)")
            logger.info(f"📊 Total: {len(movie_db['all_movies'])} movies (pagination in results)")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"HQ init error: {e}")
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
        "service": "SK4FiLM - High Quality Poster System",
        "home_pagination": False,
        "results_pagination": True,
        "poster_sources": ["OMDB", "TMDB_HQ", "JustWatch_HQ", "Letterboxd_HQ", "IMDB_HQ", "Custom"],
        "stats": movie_db['stats'],
        "home_movies": len(movie_db['home_movies']),
        "total_movies": len(movie_db['all_movies']),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API - Home (no pagination) or Results (with pagination)"""
    try:
        # Check if request wants pagination (for results page)
        page = request.args.get('page')
        
        if not bot_started:
            return jsonify({"status": "starting"}), 503
        
        if page:
            # Results page - WITH pagination
            page = int(page)
            limit = int(request.args.get('limit', 8))
            
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
                    "has_previous": page > 1
                },
                "page_type": "results_with_pagination",
                "timestamp": datetime.now().isoformat()
            })
        else:
            # Home page - NO pagination, fixed 24 movies
            return jsonify({
                "status": "success",
                "movies": movie_db['home_movies'],
                "total_movies": len(movie_db['home_movies']),
                "page_type": "home_no_pagination",
                "high_quality_sources": True,
                "timestamp": datetime.now().isoformat()
            })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """Search API with pagination - Only for results page"""
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
            "results_page_only": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster')
async def proxy_hq_poster():
    """HIGH QUALITY poster proxy"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_enhanced_placeholder("No URL")
        
        if poster_url.startswith('/api/enhanced_poster'):
            title = request.args.get('title', 'Movie')
            return create_enhanced_poster_svg(title)
        
        if not poster_url.startswith('http'):
            return create_enhanced_placeholder("Invalid URL")
        
        # Enhanced headers for HIGH QUALITY
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Cache-Control': 'max-age=0'
        }
        
        # Source-specific optimizations
        if 'tmdb' in poster_url.lower():
            headers['Referer'] = 'https://www.themoviedb.org/'
        elif 'justwatch' in poster_url.lower():
            headers['Referer'] = 'https://www.justwatch.com/'
        elif 'letterboxd' in poster_url.lower():
            headers['Referer'] = 'https://letterboxd.com/'
        elif 'amazon' in poster_url.lower() or 'imdb' in poster_url.lower():
            headers['Referer'] = 'https://www.imdb.com/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ HIGH QUALITY poster: {len(image_data)} bytes")
                    
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
                    return create_enhanced_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"HQ poster proxy error: {e}")
        return create_enhanced_placeholder("Load Error")

@app.route('/api/enhanced_poster')
async def enhanced_poster_api():
    """Enhanced custom poster"""
    title = request.args.get('title', 'Movie')
    return create_enhanced_poster_svg(title)

def create_enhanced_poster_svg(title):
    """ENHANCED custom poster - Better quality design"""
    display_title = title[:20] + "..." if len(title) > 20 else title
    
    # Enhanced color themes
    themes = [
        {'bg': ['#667eea', '#764ba2'], 'text': '#ffffff', 'accent': '#f093fb'},
        {'bg': ['#f093fb', '#f5576c'], 'text': '#ffffff', 'accent': '#4facfe'},
        {'bg': ['#43e97b', '#38f9d7'], 'text': '#2c3e50', 'accent': '#667eea'},
        {'bg': ['#fa709a', '#fee140'], 'text': '#2c3e50', 'accent': '#667eea'},
        {'bg': ['#a8edea', '#fed6e3'], 'text': '#2c3e50', 'accent': '#d299c2'}
    ]
    
    theme = themes[hash(title) % len(themes)]
    
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
        <defs>
            <linearGradient id="enhancedBg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{theme['bg'][0]}"/>
                <stop offset="100%" style="stop-color:{theme['bg'][1]}"/>
            </linearGradient>
            <linearGradient id="frameGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:rgba(255,255,255,0.2)"/>
                <stop offset="100%" style="stop-color:rgba(255,255,255,0.05)"/>
            </linearGradient>
            <filter id="shadowEffect">
                <feDropShadow dx="3" dy="3" stdDeviation="6" flood-opacity="0.6"/>
            </filter>
        </defs>
        
        <!-- Enhanced background -->
        <rect width="100%" height="100%" fill="url(#enhancedBg)" rx="18"/>
        
        <!-- Quality frame -->
        <rect x="25" y="60" width="250" height="320" fill="url(#frameGrad)" rx="20" stroke="rgba(255,255,255,0.3)" stroke-width="1"/>
        
        <!-- Enhanced movie icon with shadow -->
        <circle cx="150" cy="180" r="45" fill="rgba(255,255,255,0.15)" stroke="rgba(255,255,255,0.3)" stroke-width="2"/>
        <text x="50%" y="195" text-anchor="middle" fill="{theme['text']}" font-size="44" font-weight="bold" filter="url(#shadowEffect)">🎬</text>
        
        <!-- Enhanced title -->
        <text x="50%" y="250" text-anchor="middle" fill="{theme['text']}" font-size="16" font-weight="bold" filter="url(#shadowEffect)">
            {html.escape(display_title)}
        </text>
        
        <!-- Quality indicator -->
        <text x="50%" y="280" text-anchor="middle" fill="{theme['accent']}" font-size="11" font-weight="600" opacity="0.9">HIGH QUALITY</text>
        
        <!-- Enhanced brand -->
        <text x="50%" y="410" text-anchor="middle" fill="{theme['text']}" font-size="16" font-weight="700" filter="url(#shadowEffect)">SK4FiLM</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=1800',
        'Access-Control-Allow-Origin': '*'
    })

def create_enhanced_placeholder(error_msg):
    """Enhanced error placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="errorGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#2c3e50"/>
                <stop offset="100%" style="stop-color:#34495e"/>
            </linearGradient>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#errorGrad)" rx="15"/>
        <circle cx="150" cy="180" r="40" fill="none" stroke="#3498db" stroke-width="2" opacity="0.7"/>
        <text x="50%" y="195" text-anchor="middle" fill="#3498db" font-size="32">🎬</text>
        <text x="50%" y="240" text-anchor="middle" fill="#ffffff" font-size="14">SK4FiLM</text>
        <text x="50%" y="280" text-anchor="middle" fill="#e74c3c" font-size="10">{error_msg}</text>
        <text x="50%" y="350" text-anchor="middle" fill="#95a5a6" font-size="9">High Quality System</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

async def run_hq_server():
    try:
        logger.info("🚀 SK4FiLM - HIGH QUALITY POSTER SYSTEM")
        logger.info("🏠 Home page: 24 movies, NO pagination")
        logger.info("📄 Results page: All movies, WITH pagination")  
        logger.info("🎬 High quality sources: OMDB → TMDB_HQ → JustWatch_HQ → Letterboxd_HQ → IMDB_HQ → Enhanced_Custom")
        logger.info("👻 Hidden auto updates every 3 minutes")
        
        success = await init_telegram_hq()
        
        if success:
            logger.info("🎉 HIGH QUALITY SYSTEM OPERATIONAL!")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"HQ server error: {e}")
    finally:
        if auto_update_task:
            auto_update_task.cancel()
        if User:
            try:
                await User.stop()
            except:
                pass

if __name__ == "__main__":
    asyncio.run(run_hq_server())
