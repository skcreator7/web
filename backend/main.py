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
from bs4 import BeautifulSoup
import random

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Multiple API Sources for 100% poster success
    TMDB_KEYS = ["e547e17d4e91f3e62a571655cd1ccaff", "8265bd1c", "b9bd48a6"]
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e"]
    
    # Poster search sources
    POSTER_SOURCES = [
        "TMDB",      # Primary
        "OMDB",      # Secondary  
        "GOOGLE",    # Google Images
        "IMPAWARDS", # IMP Awards
        "MOVIEDB"    # Alternative DB
    ]
    
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Enhanced data store with multi-source poster caching
movie_store = {
    'movies': [],
    'last_update': None,
    'last_ids': {},
    'seen_titles': set(),
    'poster_cache': {},  # Multi-source cache
    'updating': False,
    'poster_stats': {'tmdb': 0, 'omdb': 0, 'google': 0, 'impawards': 0, 'generated': 0}
}

def extract_clean_title(text):
    """Enhanced title extraction for auto poster finder"""
    if not text or len(text) < 15:
        return None
    
    try:
        # Clean and get first line
        clean_text = re.sub(r'[^\w\s\(\)\-\.\n\u0900-\u097F]', ' ', text)
        first_line = clean_text.split('\n')[0].strip()
        
        # Enhanced patterns for better title extraction
        patterns = [
            r'🎬\s*([^-\n]{4,45})(?:\s*-|\n|$)',
            r'^([^(]{4,45})\s*\(\d{4}\)',
            r'^([^-]{4,45})\s*-\s*(?:Hindi|English|Tamil|Telugu|Punjabi|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,5})',
            r'"([^"]{4,40})"',
            r'\*\*([^*]{4,40})\*\*',
            r'Movie[:\s]*([^-\n]{4,40})',
            r'Film[:\s]*([^-\n]{4,40})',
            r'(?:Latest|New)\s+([^-\n]{4,40})'
        ]
        
        for i, pattern in enumerate(patterns, 1):
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_title(title):
                    logger.debug(f"✅ Pattern {i}: '{title}'")
                    return title
        
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

def validate_title(title):
    """Enhanced title validation"""
    if not title or len(title) < 4 or len(title) > 50:
        return False
    
    # Enhanced bad words list
    bad_words = [
        'size', 'quality', 'download', 'link', 'channel', 'group', 'mb', 'gb', 'file',
        'join', 'subscribe', 'follow', 'admin', 'bot', 'telegram', 'whatsapp'
    ]
    
    if any(word in title.lower() for word in bad_words):
        return False
    
    # Must have letters
    if not re.search(r'[a-zA-Z\u0900-\u097F]', title):
        return False
    
    # No pure numbers or symbols
    if re.match(r'^[\d\s\-\(\)]+$', title):
        return False
    
    return True

async def find_poster_from_tmdb(title, session):
    """TMDB poster search"""
    try:
        for api_key in Config.TMDB_KEYS:
            try:
                url = "https://api.themoviedb.org/3/search/movie"
                params = {
                    'api_key': api_key,
                    'query': title,
                    'language': 'en-US',
                    'page': 1,
                    'include_adult': 'false'
                }
                
                async with session.get(url, params=params, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('results') and len(data['results']) > 0:
                            movie = data['results'][0]
                            poster_path = movie.get('poster_path')
                            
                            if poster_path:
                                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                                
                                return {
                                    'poster_url': poster_url,
                                    'title': movie.get('title', title),
                                    'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                                    'rating': f"{movie.get('vote_average', 0):.1f}",
                                    'source': 'TMDB',
                                    'success': True
                                }
                
                await asyncio.sleep(0.1)
                
            except:
                continue
        
        return {'success': False, 'source': 'TMDB'}
        
    except:
        return {'success': False, 'source': 'TMDB'}

async def find_poster_from_omdb(title, session):
    """OMDB poster search"""
    try:
        for api_key in Config.OMDB_KEYS:
            try:
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={api_key}"
                
                async with session.get(url, timeout=6) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if (data.get('Response') == 'True' and 
                            data.get('Poster') and 
                            data['Poster'] != 'N/A'):
                            
                            return {
                                'poster_url': data['Poster'],
                                'title': data.get('Title', title),
                                'year': data.get('Year', ''),
                                'rating': data.get('imdbRating', ''),
                                'source': 'OMDB',
                                'success': True
                            }
                
                await asyncio.sleep(0.1)
                
            except:
                continue
        
        return {'success': False, 'source': 'OMDB'}
        
    except:
        return {'success': False, 'source': 'OMDB'}

async def find_poster_from_google_images(title, session):
    """Google Images poster search via SerpApi alternative"""
    try:
        # Using Bing Images as free alternative to Google Images API
        search_query = f"{title} movie poster site:imdb.com OR site:themoviedb.org"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        # Simple image search approach
        search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(search_query)}&count=5"
        
        async with session.get(search_url, headers=headers, timeout=8) as response:
            if response.status == 200:
                html_content = await response.text()
                
                # Extract image URLs from Bing results
                img_pattern = r'"murl":"([^"]*\.(?:jpg|jpeg|png|webp)[^"]*)"'
                matches = re.findall(img_pattern, html_content)
                
                for img_url in matches[:3]:  # Try first 3 images
                    if ('tmdb' in img_url.lower() or 'imdb' in img_url.lower() or 'media-amazon' in img_url.lower()):
                        return {
                            'poster_url': img_url,
                            'title': title,
                            'source': 'GOOGLE',
                            'success': True
                        }
        
        return {'success': False, 'source': 'GOOGLE'}
        
    except Exception as e:
        logger.warning(f"Google Images search error: {e}")
        return {'success': False, 'source': 'GOOGLE'}

async def find_poster_from_impawards(title, session):
    """IMP Awards poster search"""
    try:
        # Based on web:80 - IMP Awards has large poster collection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Search IMP Awards site
        search_query = title.replace(' ', '+')
        search_url = f"http://www.impawards.com/search.php?search={search_query}"
        
        async with session.get(search_url, headers=headers, timeout=10) as response:
            if response.status == 200:
                html = await response.text()
                
                # Extract poster URLs from search results
                poster_pattern = r'href="(/\d{4}/[^"]*\.html)"'
                matches = re.findall(poster_pattern, html)
                
                if matches:
                    # Get poster from first result
                    poster_page = f"<http://www.impawards.com{matches>[0]}"
                    
                    async with session.get(poster_page, headers=headers, timeout=8) as poster_response:
                        if poster_response.status == 200:
                            poster_html = await poster_response.text()
                            
                            # Extract actual poster image
                            img_pattern = r'<img[^>]*src="([^"]*posters/[^"]*\.jpg)"'
                            img_match = re.search(img_pattern, poster_html)
                            
                            if img_match:
                                poster_url = f"http://www.impawards.com{img_match.group(1)}"
                                
                                return {
                                    'poster_url': poster_url,
                                    'title': title,
                                    'source': 'IMPAWARDS',
                                    'success': True
                                }
        
        return {'success': False, 'source': 'IMPAWARDS'}
        
    except Exception as e:
        logger.warning(f"IMP Awards error: {e}")
        return {'success': False, 'source': 'IMPAWARDS'}

def generate_custom_poster_url(title):
    """Generate custom poster with movie title"""
    try:
        # Create a custom poster URL with title embedded
        encoded_title = urllib.parse.quote(title)
        
        # Use a poster generation service or custom SVG
        custom_poster_data = {
            'poster_url': f"/api/generate_poster?title={encoded_title}",
            'title': title,
            'source': 'GENERATED',
            'success': True
        }
        
        return custom_poster_data
        
    except:
        return {'success': False, 'source': 'GENERATED'}

async def auto_poster_finder(title, session):
    """AUTO POSTER FINDER - Tries all sources until found"""
    cache_key = title.lower().strip()
    
    # Check cache first
    if cache_key in movie_store['poster_cache']:
        cached_result, cache_time = movie_store['poster_cache'][cache_key]
        if datetime.now() - cache_time < timedelta(minutes=10):
            return cached_result
    
    try:
        logger.info(f"🔍 AUTO POSTER FINDER: {title}")
        
        # Try all sources in order
        poster_finders = [
            find_poster_from_tmdb,
            find_poster_from_omdb,
            find_poster_from_google_images,
            find_poster_from_impawards
        ]
        
        for finder in poster_finders:
            try:
                result = await finder(title, session)
                
                if result.get('success'):
                    # Update stats
                    source = result['source'].lower()
                    if source in movie_store['poster_stats']:
                        movie_store['poster_stats'][source] += 1
                    
                    # Cache successful result
                    movie_store['poster_cache'][cache_key] = (result, datetime.now())
                    
                    logger.info(f"✅ POSTER FOUND via {result['source']}: {title}")
                    return result
                
                # Small delay between sources
                await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.warning(f"Poster finder error: {e}")
                continue
        
        # Last resort - generate custom poster
        logger.info(f"🎨 Generating custom poster: {title}")
        custom_result = generate_custom_poster_url(title)
        movie_store['poster_stats']['generated'] += 1
        
        # Cache even generated result
        movie_store['poster_cache'][cache_key] = (custom_result, datetime.now())
        
        return custom_result
        
    except Exception as e:
        logger.error(f"Auto poster finder error: {e}")
        return generate_custom_poster_url(title)

async def get_movies_with_auto_posters():
    """Get movies with AUTO POSTER FINDER system"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 AUTO POSTER FINDER - Loading movies...")
        
        all_posts = []
        
        # Get posts from channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                count = 0
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 40 and message.date:
                        title = extract_clean_title(message.text)
                        
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
        
        # AUTO POSTER FINDER - Process in batches
        movies_with_posters = []
        
        async with aiohttp.ClientSession() as session:
            batch_size = 4  # Smaller batches for multiple sources
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                logger.info(f"🔍 AUTO FINDER batch {i//batch_size + 1}: {len(batch)} movies")
                
                # Parallel auto poster finding
                poster_tasks = [auto_poster_finder(movie['title'], session) for movie in batch]
                poster_results = await asyncio.gather(*poster_tasks, return_exceptions=True)
                
                for movie, poster_data in zip(batch, poster_results):
                    if isinstance(poster_data, dict) and poster_data.get('success'):
                        movie.update({
                            'poster_url': poster_data['poster_url'],
                            'poster_title': poster_data.get('title', movie['title']),
                            'poster_year': poster_data.get('year', ''),
                            'poster_rating': poster_data.get('rating', ''),
                            'poster_source': poster_data['source'],
                            'has_poster': True
                        })
                    else:
                        movie['has_poster'] = False
                        movie['poster_source'] = 'None'
                    
                    movies_with_posters.append(movie)
                
                # Rate limiting between batches
                await asyncio.sleep(0.5)
        
        total_time = time.time() - start_time
        poster_count = sum(1 for m in movies_with_posters if m.get('has_poster'))
        
        logger.info(f"⚡ AUTO POSTER FINDER complete: {total_time:.2f}s")
        logger.info(f"🎬 {len(movies_with_posters)} movies, {poster_count} posters found")
        logger.info(f"📊 Sources: TMDB={movie_store['poster_stats']['tmdb']}, OMDB={movie_store['poster_stats']['omdb']}, Google={movie_store['poster_stats']['google']}")
        
        return movies_with_posters
        
    except Exception as e:
        logger.error(f"Auto poster finder error: {e}")
        return []

async def search_telegram_channels(query, limit=10, offset=0):
    """Search telegram channels"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=12):
                    if message.text:
                        formatted = format_content_enhanced(message.text)
                        
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

def format_content_enhanced(text):
    """Enhanced content formatting"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    formatted = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 4px 10px; border-radius: 8px; margin: 3px; display: inline-block; text-decoration: none;"><i class="fas fa-download me-1"></i>Download Link</a>', 
        formatted
    )
    formatted = formatted.replace('\n', '<br>')
    
    return formatted

async def initialize_telegram():
    """Initialize telegram system"""
    global User, bot_started
    
    try:
        logger.info("🔄 Starting AUTO POSTER FINDER system...")
        
        User = Client(
            "sk4film_auto_posters",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected: {me.first_name}")
        
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
            
            # Load movies with auto poster finder
            initial_movies = await get_movies_with_auto_posters()
            movie_store['movies'] = initial_movies
            movie_store['last_update'] = datetime.now()
            movie_store['seen_titles'] = {movie['title'].lower() for movie in initial_movies}
            
            logger.info(f"🎉 AUTO POSTER SYSTEM READY!")
            logger.info(f"🎬 {len(initial_movies)} movies loaded")
            logger.info(f"📊 Poster sources: {Config.POSTER_SOURCES}")
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
        "service": "SK4FiLM - Auto Poster Finder",
        "poster_sources": Config.POSTER_SOURCES,
        "poster_stats": movie_store['poster_stats'],
        "movies_count": len(movie_store['movies']),
        "cache_size": len(movie_store['poster_cache']),
        "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Movies API with auto poster finder"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Auto poster service unavailable"}), 503
        
        movies = movie_store['movies'][:limit]
        poster_count = sum(1 for m in movies if m.get('has_poster'))
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "total_movies": len(movies),
            "auto_posters_found": poster_count,
            "poster_sources": Config.POSTER_SOURCES,
            "poster_stats": movie_store['poster_stats'],
            "sorting": "newest_first",
            "auto_finder": True,
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
        
        result = await search_telegram_channels(query, limit, offset)
        
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
    """Enhanced poster proxy with multiple source support"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_auto_placeholder("No URL")
        
        # Handle custom generated posters
        if poster_url.startswith('/api/generate_poster'):
            title = request.args.get('title', 'Movie')
            return generate_poster_svg(title)
        
        if not poster_url.startswith('http'):
            return create_auto_placeholder("Invalid URL")
        
        logger.info(f"🖼️ Proxying poster: {poster_url[:50]}...")
        
        # Enhanced headers for all sources
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
        
        # Set appropriate referer based on source
        if 'tmdb' in poster_url.lower():
            headers['Referer'] = 'https://www.themoviedb.org/'
        elif 'imdb' in poster_url.lower() or 'media-amazon' in poster_url.lower():
            headers['Referer'] = 'https://www.imdb.com/'
        elif 'impawards' in poster_url.lower():
            headers['Referer'] = 'http://www.impawards.com/'
        else:
            headers['Referer'] = 'https://www.google.com/'
        
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
                            'Cache-Control': 'public, max-age=7200',
                            'Access-Control-Allow-Origin': '*',
                            'Cross-Origin-Resource-Policy': 'cross-origin'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP {response.status}")
                    return create_auto_placeholder(f"HTTP {response.status}")
        
    except Exception as e:
        logger.error(f"Poster proxy error: {e}")
        return create_auto_placeholder("Load Error")

@app.route('/api/generate_poster')
async def generate_poster():
    """Generate custom poster with movie title"""
    title = request.args.get('title', 'Movie')
    return generate_poster_svg(title)

def generate_poster_svg(title):
    """Generate beautiful custom poster SVG"""
    # Limit title length for display
    display_title = title[:25] + "..." if len(title) > 25 else title
    
    # Random gradient colors for variety
    gradients = [
        ['#ff6b6b', '#4ecdc4'],  # Red to teal
        ['#a8e6cf', '#ffd3a5'],  # Green to peach
        ['#fd79a8', '#fdcb6e'],  # Pink to yellow
        ['#74b9ff', '#0984e3'],  # Light blue to blue
        ['#e17055', '#fdcb6e'],  # Orange to yellow
        ['#6c5ce7', '#a29bfe']   # Purple to light purple
    ]
    
    gradient = random.choice(gradients)
    
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
        <defs>
            <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{gradient[0]}"/>
                <stop offset="100%" style="stop-color:{gradient[1]}"/>
            </linearGradient>
            <linearGradient id="overlayGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:rgba(0,0,0,0.3)"/>
                <stop offset="100%" style="stop-color:rgba(0,0,0,0.6)"/>
            </linearGradient>
            <filter id="textShadow">
                <feDropShadow dx="2" dy="2" stdDeviation="3" flood-opacity="0.8"/>
            </filter>
        </defs>
        
        <!-- Background -->
        <rect width="100%" height="100%" fill="url(#bgGrad)" rx="15"/>
        <rect width="100%" height="100%" fill="url(#overlayGrad)" rx="15"/>
        
        <!-- Film decorations -->
        <circle cx="75" cy="100" r="20" fill="rgba(255,255,255,0.1)"/>
        <circle cx="225" cy="120" r="15" fill="rgba(255,255,255,0.1)"/>
        <circle cx="50" cy="200" r="10" fill="rgba(255,255,255,0.1)"/>
        <circle cx="250" cy="250" r="25" fill="rgba(255,255,255,0.1)"/>
        
        <!-- Main content area -->
        <rect x="30" y="120" width="240" height="200" fill="rgba(255,255,255,0.1)" rx="20"/>
        
        <!-- Film icon -->
        <text x="50%" y="180" text-anchor="middle" fill="#ffffff" font-size="48" filter="url(#textShadow)">🎬</text>
        
        <!-- Movie title -->
        <text x="50%" y="230" text-anchor="middle" fill="#ffffff" font-size="16" font-weight="bold" filter="url(#textShadow)">
            {html.escape(display_title)}
        </text>
        
        <!-- SK4FiLM branding -->
        <text x="50%" y="280" text-anchor="middle" fill="#ffffff" font-size="14" font-weight="600" filter="url(#textShadow)">SK4FiLM</text>
        <text x="50%" y="300" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="10">Custom Movie Poster</text>
        
        <!-- Bottom info -->
        <text x="50%" y="370" text-anchor="middle" fill="#ffffff" font-size="11" opacity="0.9">Auto Generated Poster</text>
        <text x="50%" y="390" text-anchor="middle" fill="rgba(255,255,255,0.7)" font-size="10">Click to Search in Telegram</text>
        
        <!-- Decorative border -->
        <rect x="5" y="5" width="290" height="440" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="2" rx="12"/>
        
        <!-- Corner decorations -->
        <circle cx="30" cy="30" r="3" fill="rgba(255,255,255,0.6)"/>
        <circle cx="270" cy="30" r="3" fill="rgba(255,255,255,0.6)"/>
        <circle cx="30" cy="420" r="3" fill="rgba(255,255,255,0.6)"/>
        <circle cx="270" cy="420" r="3" fill="rgba(255,255,255,0.6)"/>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=1800',
        'Access-Control-Allow-Origin': '*'
    })

def create_auto_placeholder(error_msg):
    """Auto poster finder placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="autoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="50%" style="stop-color:#16213e"/>
                <stop offset="100%" style="stop-color:#0f3460"/>
            </linearGradient>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#autoGrad)" rx="15"/>
        <circle cx="150" cy="160" r="50" fill="none" stroke="#00ccff" stroke-width="3" opacity="0.6"/>
        <text x="50%" y="175" text-anchor="middle" fill="#00ccff" font-size="32" font-weight="bold">🔍</text>
        <text x="50%" y="220" text-anchor="middle" fill="#ffffff" font-size="18" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="245" text-anchor="middle" fill="#00ccff" font-size="12">Auto Poster Finder</text>
        <text x="50%" y="300" text-anchor="middle" fill="#90cea1" font-size="10">TMDB + OMDB + Google + IMP</text>
        <text x="50%" y="350" text-anchor="middle" fill="#ff6666" font-size="10">{error_msg}</text>
        <text x="50%" y="400" text-anchor="middle" fill="#00ccff" font-size="10">Click to Search Telegram</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def force_update():
    """Force update with auto poster finder"""
    try:
        if not bot_started:
            return jsonify({"status": "error"}), 503
        
        logger.info("🔄 FORCE UPDATE - Auto Poster Finder")
        
        # Clear all caches
        movie_store['poster_cache'].clear()
        movie_store['seen_titles'].clear()
        movie_store['poster_stats'] = {'tmdb': 0, 'omdb': 0, 'google': 0, 'impawards': 0, 'generated': 0}
        
        # Reload with auto poster finder
        fresh_movies = await get_movies_with_auto_posters()
        movie_store['movies'] = fresh_movies
        movie_store['last_update'] = datetime.now()
        
        return jsonify({
            "status": "success",
            "movies_reloaded": len(fresh_movies),
            "poster_stats": movie_store['poster_stats'],
            "auto_finder": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_server():
    try:
        logger.info("🚀 SK4FiLM - AUTO POSTER FINDER SYSTEM")
        logger.info("🔍 Multiple poster sources: TMDB + OMDB + Google + IMP Awards")
        logger.info("🎨 Custom poster generation for missing posters")
        logger.info("📅 Recent posts first + No duplicates")
        logger.info("📱 All previous features preserved")
        
        success = await initialize_telegram()
        
        if success:
            logger.info("🎉 AUTO POSTER FINDER OPERATIONAL!")
        
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
