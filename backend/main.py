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
from bs4 import BeautifulSoup
import random

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Multi-source poster system configuration
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4"]
    
    # JustWatch configuration (based on web:90, web:104)
    JUSTWATCH_BASE = "https://www.justwatch.com/in/movie"
    
    # Letterboxd configuration (based on web:100, web:103)
    LETTERBOXD_BASE = "https://letterboxd.com/film"
    
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Enhanced movie store with multi-source tracking
movie_store = {
    'movies': [],
    'last_update': None,
    'last_ids': {},
    'seen_titles': set(),
    'multi_poster_cache': {},
    'updating': False,
    'source_stats': {
        'omdb_success': 0,
        'justwatch_success': 0, 
        'letterboxd_success': 0,
        'custom_generated': 0,
        'total_attempts': 0
    }
}

def clean_movie_title_advanced(text):
    """Advanced movie title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        # Enhanced cleaning
        clean_text = re.sub(r'[^\w\s\(\)\-\.\n\u0900-\u097F]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        # Multiple extraction patterns
        title_patterns = [
            r'🎬\s*([^-\n]{4,45})(?:\s*-|\n|$)',
            r'^([^(]{4,45})\s*\(\d{4}\)',
            r'^([^-]{4,45})\s*-\s*(?:Hindi|English|Tamil|Telugu|Punjabi|Bengali|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,5})',
            r'"([^"]{4,40})"',
            r'\*\*([^*]{4,40})\*\*',
            r'Movie[:\s]*([^-\n]{4,40})',
            r'Film[:\s]*([^-\n]{4,40})',
            r'(?:Watch|Download)\s+([^-\n]{4,40})',
            r'(?:Latest|New)\s+([^-\n]{4,40})'
        ]
        
        for i, pattern in enumerate(title_patterns, 1):
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_title_advanced(title):
                    logger.debug(f"✅ Pattern {i} extracted: '{title}'")
                    return title
        
        return None
        
    except Exception as e:
        logger.warning(f"Advanced title extraction error: {e}")
        return None

def validate_title_advanced(title):
    """Advanced title validation"""
    if not title or len(title) < 4 or len(title) > 50:
        return False
    
    # Enhanced bad words filtering
    invalid_words = [
        'size', 'quality', 'download', 'link', 'channel', 'group', 'mb', 'gb', 'file',
        'join', 'subscribe', 'follow', 'admin', 'bot', 'telegram', 'whatsapp', 'youtube'
    ]
    
    if any(word in title.lower() for word in invalid_words):
        return False
    
    # Must contain meaningful letters
    if not re.search(r'[a-zA-Z\u0900-\u097F]', title):
        return False
    
    # No pure numbers or basic symbols
    if re.match(r'^[\d\s\-\(\)\.]+$', title):
        return False
    
    return True

async def get_poster_from_omdb(title, session):
    """OMDB poster search - Primary source"""
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
                                'movie_title': data.get('Title', title),
                                'release_year': data.get('Year', ''),
                                'imdb_rating': data.get('imdbRating', ''),
                                'genre': data.get('Genre', ''),
                                'director': data.get('Director', ''),
                                'plot': data.get('Plot', ''),
                                'source': 'OMDB',
                                'success': True
                            }
                            
                            movie_store['source_stats']['omdb_success'] += 1
                            logger.info(f"✅ OMDB SUCCESS: {title}")
                            return result
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"OMDB API error: {e}")
        
        return {'success': False, 'source': 'OMDB'}
        
    except Exception as e:
        logger.error(f"OMDB search error: {e}")
        return {'success': False, 'source': 'OMDB'}

async def get_poster_from_justwatch(title, session):
    """JustWatch poster scraping - Based on web:104"""
    try:
        logger.info(f"🔍 JustWatch search: {title}")
        
        # Convert title to JustWatch URL format
        clean_title = re.sub(r'[^\w\s]', '', title.lower())
        url_title = '-'.join(clean_title.split())
        justwatch_url = f"{Config.JUSTWATCH_BASE}/{url_title}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        async with session.get(justwatch_url, headers=headers, timeout=10) as response:
            if response.status == 200:
                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Extract poster from JustWatch page structure
                poster_img = soup.select_one('picture img, .poster img, [data-testid="poster"] img')
                
                if poster_img and poster_img.get('src'):
                    poster_url = poster_img['src']
                    
                    # Make URL absolute if needed
                    if poster_url.startswith('//'):
                        poster_url = 'https:' + poster_url
                    elif poster_url.startswith('/'):
                        poster_url = 'https://www.justwatch.com' + poster_url
                    
                    # Extract additional info using regex (from web:104)
                    imdb_match = re.search(r'"imdbId":\s*"([^"]+)"', html_content)
                    rating_match = re.search(r'"imdbRating":\s*([0-9.]+)', html_content)
                    
                    result = {
                        'poster_url': poster_url,
                        'movie_title': title,
                        'imdb_id': imdb_match.group(1) if imdb_match else '',
                        'imdb_rating': rating_match.group(1) if rating_match else '',
                        'source': 'JUSTWATCH',
                        'success': True
                    }
                    
                    movie_store['source_stats']['justwatch_success'] += 1
                    logger.info(f"✅ JUSTWATCH SUCCESS: {title}")
                    return result
        
        return {'success': False, 'source': 'JUSTWATCH'}
        
    except Exception as e:
        logger.warning(f"JustWatch search error: {e}")
        return {'success': False, 'source': 'JUSTWATCH'}

async def get_poster_from_letterboxd(title, session):
    """Letterboxd poster scraping - Based on web:100, web:103"""
    try:
        logger.info(f"📚 Letterboxd search: {title}")
        
        # Convert title to Letterboxd URL format
        clean_title = re.sub(r'[^\w\s]', '', title.lower())
        url_title = '-'.join(clean_title.split())
        letterboxd_url = f"{Config.LETTERBOXD_BASE}/{url_title}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive'
        }
        
        async with session.get(letterboxd_url, headers=headers, timeout=10) as response:
            if response.status == 200:
                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Extract poster using BeautifulSoup (from web:100 solution)
                poster_img = soup.select_one('img.image, .poster img, .film-poster img')
                
                if poster_img:
                    poster_src = poster_img.get('src') or poster_img.get('data-src')
                    
                    if poster_src:
                        # Handle Letterboxd's image URLs
                        if poster_src.startswith('//'):
                            poster_url = 'https:' + poster_src
                        elif poster_src.startswith('/'):
                            poster_url = 'https://letterboxd.com' + poster_src
                        else:
                            poster_url = poster_src
                        
                        # Get higher quality version if available
                        if '-230-' in poster_url:
                            poster_url = poster_url.replace('-230-', '-500-')
                        elif '-345-' in poster_url:
                            poster_url = poster_url.replace('-345-', '-500-')
                        
                        # Extract rating from Letterboxd
                        rating_element = soup.select_one('.rating, .average-rating, [class*="rating"]')
                        rating = ''
                        if rating_element:
                            rating_text = rating_element.get_text(strip=True)
                            rating_match = re.search(r'([0-9.]+)', rating_text)
                            if rating_match:
                                rating = rating_match.group(1)
                        
                        result = {
                            'poster_url': poster_url,
                            'movie_title': title,
                            'letterboxd_rating': rating,
                            'source': 'LETTERBOXD',
                            'success': True
                        }
                        
                        movie_store['source_stats']['letterboxd_success'] += 1
                        logger.info(f"✅ LETTERBOXD SUCCESS: {title}")
                        return result
        
        return {'success': False, 'source': 'LETTERBOXD'}
        
    except Exception as e:
        logger.warning(f"Letterboxd search error: {e}")
        return {'success': False, 'source': 'LETTERBOXD'}

async def multi_source_poster_finder(title, session):
    """Complete multi-source poster finder: OMDB + JustWatch + Letterboxd + Custom"""
    cache_key = title.lower().strip()
    
    # Check cache first
    if cache_key in movie_store['multi_poster_cache']:
        cached_result, cache_time = movie_store['multi_poster_cache'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=12):
            return cached_result
    
    try:
        logger.info(f"🔍 MULTI-SOURCE POSTER FINDER: {title}")
        movie_store['source_stats']['total_attempts'] += 1
        
        # Source priority order
        poster_sources = [
            ('OMDB', get_poster_from_omdb),
            ('JUSTWATCH', get_poster_from_justwatch),
            ('LETTERBOXD', get_poster_from_letterboxd)
        ]
        
        # Try each source sequentially
        for source_name, finder_func in poster_sources:
            try:
                logger.info(f"🔄 Trying {source_name} for: {title}")
                result = await finder_func(title, session)
                
                if result.get('success') and result.get('poster_url'):
                    # Cache successful result
                    movie_store['multi_poster_cache'][cache_key] = (result, datetime.now())
                    
                    logger.info(f"✅ MULTI-SOURCE SUCCESS via {source_name}: {title}")
                    return result
                
                # Small delay between sources
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.warning(f"{source_name} finder error: {e}")
                continue
        
        # Final fallback - Custom generation
        logger.info(f"🎨 All sources failed, generating custom poster: {title}")
        custom_result = {
            'poster_url': f"/api/generate_poster?title={urllib.parse.quote(title)}",
            'movie_title': title,
            'source': 'CUSTOM',
            'success': True
        }
        
        movie_store['source_stats']['custom_generated'] += 1
        movie_store['multi_poster_cache'][cache_key] = (custom_result, datetime.now())
        
        return custom_result
        
    except Exception as e:
        logger.error(f"Multi-source poster finder error: {e}")
        return {
            'poster_url': f"/api/generate_poster?title={urllib.parse.quote(title)}",
            'movie_title': title,
            'source': 'CUSTOM',
            'success': True
        }

async def get_movies_with_multi_source_posters():
    """Get movies with multi-source poster system"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 MULTI-SOURCE POSTER SYSTEM: Loading movies...")
        
        all_movie_posts = []
        
        # Get posts from telegram channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                posts_found = 0
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 40 and message.date:
                        title = clean_movie_title_advanced(message.text)
                        
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
        logger.info(f"📊 Sorted {len(all_movie_posts)} posts by date (newest first)")
        
        # Remove duplicates - keep newest version
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
        
        # Multi-source poster finding in batches
        movies_with_posters = []
        
        async with aiohttp.ClientSession() as session:
            batch_size = 3  # Smaller batches for multiple sources
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                logger.info(f"🔍 Multi-source batch {i//batch_size + 1}: {len(batch)} movies")
                
                # Parallel multi-source poster finding
                poster_tasks = [multi_source_poster_finder(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data.get('movie_title', movie['title']),
                            'poster_year': poster_data.get('release_year', ''),
                            'poster_rating': poster_data.get('imdb_rating', poster_data.get('letterboxd_rating', '')),
                            'poster_genre': poster_data.get('genre', ''),
                            'poster_director': poster_data.get('director', ''),
                            'poster_plot': poster_data.get('plot', ''),
                            'poster_source': poster_data['source'],
                            'has_poster': True
                        })
                        logger.info(f"🎬 {poster_data['source']}: {movie['title']}")
                    else:
                        # Fallback to custom
                        movie.update({
                            'poster_url': f"/api/generate_poster?title={urllib.parse.quote(movie['title'])}",
                            'poster_source': 'CUSTOM',
                            'has_poster': True
                        })
                    
                    movies_with_posters.append(movie)
                
                # Rate limiting between batches
                await asyncio.sleep(0.6)
        
        total_time = time.time() - start_time
        poster_count = sum(1 for m in movies_with_posters if m.get('has_poster'))
        
        logger.info(f"⚡ MULTI-SOURCE COMPLETE: {total_time:.2f}s")
        logger.info(f"🎬 {len(movies_with_posters)} movies, {poster_count} posters found")
        logger.info(f"📊 Source stats: OMDB={movie_store['source_stats']['omdb_success']}, JustWatch={movie_store['source_stats']['justwatch_success']}, Letterboxd={movie_store['source_stats']['letterboxd_success']}")
        
        return movies_with_posters
        
    except Exception as e:
        logger.error(f"Multi-source movies error: {e}")
        return []

async def search_telegram_enhanced(query, limit=10, offset=0):
    """Enhanced telegram search"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted = format_telegram_content_enhanced(message.text)
                        
                        results.append({
                            'content': formatted,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': channel_name,
                            'download_links': len(re.findall(r'https?://[^\s]+', message.text)),
                            'quality_score': calculate_quality_score(message.text)
                        })
                        
            except Exception as e:
                logger.warning(f"Enhanced search error: {e}")
        
        # Sort by quality score and date
        results.sort(key=lambda x: (x['quality_score'], x['download_links'], x['date']), reverse=True)
        
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

def calculate_quality_score(text):
    """Calculate content quality score"""
    score = 0
    if 'download' in text.lower(): score += 2
    if re.search(r'\d+p', text.lower()): score += 3  # Quality indicators
    if 'size' in text.lower(): score += 1
    if len(re.findall(r'https?://[^\s]+', text)) > 1: score += 2
    return score

def format_telegram_content_enhanced(text):
    """Enhanced telegram content formatting"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    
    # Enhanced download links with icons
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 5px 12px; border-radius: 10px; margin: 4px; display: inline-block; text-decoration: none; border: 1px solid rgba(0,204,255,0.3);"><i class="fas fa-download me-2"></i>Download Link</a>', 
        formatted
    )
    
    formatted = formatted.replace('\n', '<br>')
    
    # Enhanced quality and size highlighting
    formatted = re.sub(r'📁\s*Size[:\s]*([^<br>|]+)', r'<span style="background: rgba(40,167,69,0.2); color: #28a745; padding: 6px 14px; border-radius: 15px; font-size: 0.85rem; margin: 5px; display: inline-block; border: 1px solid rgba(40,167,69,0.3);"><i class="fas fa-hdd me-2"></i>Size: \1</span>', formatted)
    formatted = re.sub(r'📹\s*Quality[:\s]*([^<br>|]+)', r'<span style="background: rgba(0,123,255,0.2); color: #007bff; padding: 6px 14px; border-radius: 15px; font-size: 0.85rem; margin: 5px; display: inline-block; border: 1px solid rgba(0,123,255,0.3);"><i class="fas fa-video me-2"></i>Quality: \1</span>', formatted)
    
    return formatted

async def initialize_telegram_multi_source():
    """Initialize telegram with multi-source poster system"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing MULTI-SOURCE POSTER SYSTEM...")
        
        # Unique session to avoid conflicts
        session_name = f"sk4film_multi_{uuid.uuid4().hex[:8]}_{int(time.time())}"
        
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
            
            # Load initial movies with multi-source posters
            logger.info("📋 Loading movies with OMDB + JustWatch + Letterboxd posters...")
            initial_movies = await get_movies_with_multi_source_posters()
            
            movie_store['movies'] = initial_movies
            movie_store['last_update'] = datetime.now()
            movie_store['seen_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            logger.info(f"🎉 MULTI-SOURCE SYSTEM READY!")
            logger.info(f"🎬 {len(initial_movies)} movies loaded")
            logger.info(f"📊 Poster sources: OMDB + JustWatch + Letterboxd + Custom")
            logger.info(f"📈 Success stats: {movie_store['source_stats']}")
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Multi-source init error: {e}")
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
        "service": "SK4FiLM - Multi-Source Poster System",
        "poster_sources": ["OMDB", "JustWatch", "Letterboxd", "Custom"],
        "source_stats": movie_store['source_stats'],
        "movies_count": len(movie_store['movies']),
        "cache_size": len(movie_store['multi_poster_cache']),
        "features": [
            "omdb_primary_source",
            "justwatch_integration", 
            "letterboxd_scraping",
            "custom_poster_generation",
            "recent_posts_first",
            "no_duplicates",
            "auto_update_system",
            "all_social_links",
            "tutorial_videos",
            "features_section",
            "disclaimer_section",
            "adsense_optimization"
        ],
        "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with multi-source posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "starting",
                "message": "Multi-source poster system initializing..."
            }), 503
        
        movies = movie_store['movies'][:limit]
        poster_count = sum(1 for m in movies if m.get('has_poster'))
        
        logger.info(f"📱 API: Serving {len(movies)} movies with multi-source posters")
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_movies": len(movies),
            "posters_found": poster_count,
            "success_rate": f"{(poster_count/len(movies)*100):.1f}%" if movies else "0%",
            "poster_sources": ["OMDB", "JustWatch", "Letterboxd", "Custom"],
            "source_stats": movie_store['source_stats'],
            "sorting": "newest_first",
            "no_duplicates": True,
            "multi_source_active": True,
            "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Movies API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """Enhanced search API"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Search query required"}), 400
        
        result = await search_telegram_enhanced(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": result["results"],
            "pagination": {
                "current_page": result["current_page"],
                "total_pages": result["total_pages"],
                "total_results": result["total"]
            },
            "enhanced_search": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster')
async def proxy_multi_source_poster():
    """Multi-source poster proxy"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_multi_source_placeholder("No URL provided")
        
        # Handle custom poster generation
        if poster_url.startswith('/api/generate_poster'):
            title_param = request.args.get('title', 'Movie')
            return create_custom_multi_poster(title_param)
        
        if not poster_url.startswith('http'):
            return create_multi_source_placeholder("Invalid URL format")
        
        logger.info(f"🖼️ Multi-source proxying: {poster_url[:60]}...")
        
        # Enhanced headers for different sources
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Cache-Control': 'no-cache'
        }
        
        # Set proper referer based on source
        if 'justwatch' in poster_url.lower():
            headers['Referer'] = 'https://www.justwatch.com/'
        elif 'letterboxd' in poster_url.lower():
            headers['Referer'] = 'https://letterboxd.com/'
        elif 'amazon' in poster_url.lower() or 'media-amazon' in poster_url.lower():
            headers['Referer'] = 'https://www.imdb.com/'
        else:
            headers['Referer'] = 'https://www.google.com/'
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ Multi-source poster loaded: {len(image_data)} bytes")
                    
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
                    logger.warning(f"❌ Multi-source poster HTTP {response.status}")
                    return create_multi_source_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"Multi-source poster proxy error: {e}")
        return create_multi_source_placeholder("Loading Error")

@app.route('/api/generate_poster')
async def generate_custom_poster():
    """Generate custom poster endpoint"""
    title = request.args.get('title', 'Movie')
    return create_custom_multi_poster(title)

def create_custom_multi_poster(title):
    """Create beautiful custom multi-source poster"""
    display_title = title[:32] + "..." if len(title) > 32 else title
    
    # Multi-source color schemes
    color_themes = [
        {'bg': ['#ff6b6b', '#4ecdc4'], 'text': '#ffffff', 'accent': '#ffee58', 'theme': 'Sunset'},
        {'bg': ['#a8e6cf', '#ffd3a5'], 'text': '#2c3e50', 'accent': '#e74c3c', 'theme': 'Nature'},
        {'bg': ['#74b9ff', '#0984e3'], 'text': '#ffffff', 'accent': '#fdcb6e', 'theme': 'Ocean'},
        {'bg': ['#6c5ce7', '#a29bfe'], 'text': '#ffffff', 'accent': '#fd79a8', 'theme': 'Purple'},
        {'bg': ['#00b894', '#00cec9'], 'text': '#ffffff', 'accent': '#fdcb6e', 'theme': 'Mint'},
        {'bg': ['#e17055', '#fdcb6e'], 'text': '#ffffff', 'accent': '#74b9ff', 'theme': 'Warm'}
    ]
    
    theme = color_themes[hash(title) % len(color_themes)]
    
    svg_content = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
        <defs>
            <linearGradient id="mainGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{theme['bg'][0]}"/>
                <stop offset="100%" style="stop-color:{theme['bg'][1]}"/>
            </linearGradient>
            <linearGradient id="overlayGradient" x1="0%" y1="60%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:rgba(0,0,0,0.2)"/>
                <stop offset="100%" style="stop-color:rgba(0,0,0,0.8)"/>
            </linearGradient>
            <filter id="glowEffect">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge> 
                    <feMergeNode in="coloredBlur"/>
                    <feMergeNode in="SourceGraphic"/> 
                </feMerge>
            </filter>
            <pattern id="sourcePattern" patternUnits="userSpaceOnUse" width="40" height="40">
                <rect width="40" height="40" fill="rgba(255,255,255,0.05)"/>
                <circle cx="20" cy="20" r="2" fill="rgba(255,255,255,0.2)"/>
            </pattern>
        </defs>
        
        <!-- Main background -->
        <rect width="100%" height="100%" fill="url(#mainGradient)" rx="20"/>
        
        <!-- Pattern overlay -->
        <rect width="100%" height="100%" fill="url(#sourcePattern)" opacity="0.4"/>
        
        <!-- Content frame -->
        <rect x="25" y="50" width="250" height="320" fill="rgba(255,255,255,0.12)" rx="30" stroke="rgba(255,255,255,0.25)" stroke-width="2"/>
        
        <!-- Multi-source indicators -->
        <circle cx="60" cy="80" r="12" fill="rgba(245,197,24,0.6)"/>
        <text x="60" y="85" text-anchor="middle" fill="white" font-size="10" font-weight="bold">O</text>
        
        <circle cx="90" cy="80" r="12" fill="rgba(255,107,53,0.6)"/>
        <text x="90" y="85" text-anchor="middle" fill="white" font-size="10" font-weight="bold">J</text>
        
        <circle cx="120" cy="80" r="12" fill="rgba(0,204,136,0.6)"/>
        <text x="120" y="85" text-anchor="middle" fill="white" font-size="10" font-weight="bold">L</text>
        
        <!-- Central movie icon -->
        <circle cx="150" cy="180" r="45" fill="rgba(255,255,255,0.2)" stroke="rgba(255,255,255,0.3)" stroke-width="2"/>
        <text x="50%" y="195" text-anchor="middle" fill="{theme['text']}" font-size="42" font-weight="bold" filter="url(#glowEffect)">🎬</text>
        
        <!-- Movie title -->
        <text x="50%" y="240" text-anchor="middle" fill="{theme['text']}" font-size="15" font-weight="bold" filter="url(#glowEffect)">
            {html.escape(display_title)}
        </text>
        
        <!-- SK4FiLM branding -->
        <text x="50%" y="280" text-anchor="middle" fill="{theme['accent']}" font-size="20" font-weight="900" filter="url(#glowEffect)">SK4FiLM</text>
        <text x="50%" y="300" text-anchor="middle" fill="rgba(255,255,255,0.9)" font-size="11" font-weight="600">Multi-Source Poster System</text>
        
        <!-- Source labels -->
        <text x="50%" y="330" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="9" font-weight="600">OMDB + JustWatch + Letterboxd</text>
        
        <!-- Bottom overlay -->
        <rect x="0" y="350" width="100%" height="100" fill="url(#overlayGradient)" rx="0 0 20 20"/>
        
        <!-- Action text -->
        <text x="50%" y="390" text-anchor="middle" fill="#ffffff" font-size="13" font-weight="700" filter="url(#glowEffect)">Click to Search in Telegram</text>
        <text x="50%" y="410" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="10">Multi-Source Auto Poster</text>
        
        <!-- Corner decorations -->
        <text x="30" y="35" text-anchor="middle" fill="{theme['accent']}" font-size="16" opacity="0.8">🎭</text>
        <text x="270" y="35" text-anchor="middle" fill="{theme['accent']}" font-size="16" opacity="0.8">🎪</text>
        <text x="30" y="430" text-anchor="middle" fill="{theme['accent']}" font-size="16" opacity="0.8">🎨</text>
        <text x="270" y="430" text-anchor="middle" fill="{theme['accent']}" font-size="16" opacity="0.8">⭐</text>
    </svg>'''
    
    return Response(svg_content, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=1800',
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'image/svg+xml'
    })

def create_multi_source_placeholder(error_msg):
    """Multi-source system placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="errorGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="100%" style="stop-color:#16213e"/>
            </linearGradient>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#errorGrad)" rx="18"/>
        <circle cx="150" cy="160" r="55" fill="none" stroke="#00ccff" stroke-width="3" opacity="0.5"/>
        
        <!-- Multi-source icons -->
        <text x="120" y="140" text-anchor="middle" fill="#f5c518" font-size="12" font-weight="bold">O</text>
        <text x="150" y="135" text-anchor="middle" fill="#ff6b35" font-size="12" font-weight="bold">J</text>
        <text x="180" y="140" text-anchor="middle" fill="#00cc88" font-size="12" font-weight="bold">L</text>
        
        <text x="50%" y="175" text-anchor="middle" fill="#00ccff" font-size="32" font-weight="bold">🔍</text>
        <text x="50%" y="220" text-anchor="middle" fill="#ffffff" font-size="18" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="245" text-anchor="middle" fill="#00ccff" font-size="12">Multi-Source Finder</text>
        <text x="50%" y="290" text-anchor="middle" fill="#90cea1" font-size="10">OMDB + JustWatch + Letterboxd</text>
        <text x="50%" y="350" text-anchor="middle" fill="#ff6666" font-size="10">{error_msg}</text>
        <text x="50%" y="400" text-anchor="middle" fill="#00ccff" font-size="10">Click to Search</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def force_update():
    """Force update with multi-source system"""
    try:
        if not bot_started:
            return jsonify({"status": "error", "message": "Multi-source system not ready"}), 503
        
        logger.info("🔄 FORCE UPDATE - Multi-source poster reload")
        
        # Clear all caches
        movie_store['multi_poster_cache'].clear()
        movie_store['seen_titles'].clear()
        movie_store['source_stats'] = {
            'omdb_success': 0,
            'justwatch_success': 0,
            'letterboxd_success': 0,
            'custom_generated': 0,
            'total_attempts': 0
        }
        
        # Reload with multi-source system
        fresh_movies = await get_movies_with_multi_source_posters()
        
        movie_store['movies'] = fresh_movies
        movie_store['last_update'] = datetime.now()
        movie_store['seen_titles'] = {movie['title'].lower() for movie in fresh_movies}
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "poster_sources": ["OMDB", "JustWatch", "Letterboxd", "Custom"],
            "source_stats": movie_store['source_stats'],
            "multi_source_active": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Force update error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/stats')
async def api_stats():
    """Multi-source poster system statistics"""
    try:
        return jsonify({
            "status": "success",
            "system": "Multi-Source Poster Finder",
            "sources": {
                "primary": "OMDB (Open Movie Database)",
                "secondary": "JustWatch (Streaming Database)", 
                "tertiary": "Letterboxd (Film Social Network)",
                "fallback": "Custom SVG Generation"
            },
            "success_stats": movie_store['source_stats'],
            "cache_info": {
                "cached_posters": len(movie_store['multi_poster_cache']),
                "cache_duration": "12 minutes"
            },
            "performance": {
                "batch_size": 3,
                "rate_limiting": "0.6s between batches",
                "timeout": "15s per source"
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_multi_source_server():
    """Run server with multi-source poster system"""
    try:
        logger.info("🚀 SK4FiLM - MULTI-SOURCE POSTER SYSTEM")
        logger.info("🎬 Primary: OMDB (High success rate from log)")
        logger.info("🔍 Secondary: JustWatch (Streaming database)")
        logger.info("📚 Tertiary: Letterboxd (Film social network)")
        logger.info("🎨 Fallback: Custom poster generation")
        logger.info("📅 Recent posts first + No duplicates")
        logger.info("📱 All previous features 100% preserved")
        
        success = await initialize_telegram_multi_source()
        
        if success:
            logger.info("🎉 MULTI-SOURCE SYSTEM OPERATIONAL!")
            logger.info("📊 All poster sources active")
        else:
            logger.error("❌ Multi-source system failed to start")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.graceful_timeout = 30
        
        await serve(app, config)
        
    except KeyboardInterrupt:
        logger.info("🛑 Multi-source server shutdown")
    except Exception as e:
        logger.error(f"Multi-source server error: {e}")
    finally:
        # Proper cleanup
        if User and bot_started:
            try:
                logger.info("🔄 Stopping Telegram client properly...")
                await User.stop()
                logger.info("✅ Telegram client stopped cleanly")
            except Exception as e:
                logger.warning(f"Telegram cleanup warning: {e}")

if __name__ == "__main__":
    asyncio.run(run_multi_source_server())
