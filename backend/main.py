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
from concurrent.futures import ThreadPoolExecutor
import time

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Fast IMDB API keys
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e"]
    
    # CACHE SETTINGS for Fast Loading
    CACHE_DURATION = 300  # 5 minutes
    MAX_CONCURRENT_IMDB = 10  # Parallel IMDB calls

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# IN-MEMORY CACHE for Fast Loading
cache_store = {
    'latest_movies': None,
    'latest_movies_time': None,
    'imdb_posters': {},  # Title -> IMDB data
    'search_results': {}  # Query -> Results
}

def extract_title_fast(text):
    """Fast title extraction - optimized patterns"""
    if not text or len(text) < 10:
        return None
    
    first_line = text.split('\n')[0].strip()
    
    # Fast patterns - most common first
    patterns = [
        r'🎬\s*([^-\n]{4,40})(?:\s*-|\n|$)',  # After film emoji
        r'^([^(]{4,40})\s*\(\d{4}\)',          # Movie (Year)
        r'^([^-]{4,40})\s*-\s*(?:20\d{2}|Hindi|English)',  # Movie - Info
        r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,3})'  # Multi-word
    ]
    
    for pattern in patterns:
        match = re.search(pattern, first_line, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            title = re.sub(r'\s+', ' ', title)
            if 4 <= len(title) <= 50:
                return title
    
    return None

async def get_imdb_fast(title, session):
    """Ultra fast IMDB API call with timeout"""
    try:
        # Check cache first
        if title in cache_store['imdb_posters']:
            return cache_store['imdb_posters'][title]
        
        url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={Config.OMDB_KEYS[0]}"
        
        async with session.get(url, timeout=5) as response:  # Fast timeout
            if response.status == 200:
                data = await response.json()
                
                if data.get('Response') == 'True' and data.get('Poster') != 'N/A':
                    result = {
                        'poster': data['Poster'],
                        'year': data.get('Year', ''),
                        'rating': data.get('imdbRating', ''),
                        'success': True
                    }
                    # Cache it
                    cache_store['imdb_posters'][title] = result
                    return result
        
        # Cache negative result too
        negative_result = {'success': False}
        cache_store['imdb_posters'][title] = negative_result
        return negative_result
        
    except:
        return {'success': False}

async def get_movies_ultra_fast():
    """Ultra fast movie loading with parallel processing"""
    cache_key = 'latest_movies'
    cache_time_key = 'latest_movies_time'
    
    # Check cache first - INSTANT if cached
    if (cache_store[cache_key] and 
        cache_store[cache_time_key] and 
        datetime.now() - cache_store[cache_time_key] < timedelta(seconds=Config.CACHE_DURATION)):
        
        logger.info("⚡ CACHE HIT - Instant loading!")
        return cache_store[cache_key]
    
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 FAST MODE: Getting movies with parallel IMDB...")
        
        # Get posts from channels (parallel)
        all_posts = []
        
        # Parallel channel processing
        channel_tasks = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            task = get_channel_posts_fast(channel_id)
            channel_tasks.append(task)
        
        channel_results = await asyncio.gather(*channel_tasks, return_exceptions=True)
        
        # Combine results
        for result in channel_results:
            if isinstance(result, list):
                all_posts.extend(result)
        
        # Sort and deduplicate
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        seen_titles = set()
        unique_movies = []
        
        for post in all_posts[:50]:  # Take top 50 for processing
            title = post['title']
            if title.lower() not in seen_titles and len(unique_movies) < 30:
                seen_titles.add(title.lower())
                unique_movies.append(post)
        
        logger.info(f"📊 Got {len(unique_movies)} movies in {time.time() - start_time:.2f}s")
        
        # PARALLEL IMDB processing for SPEED
        imdb_start = time.time()
        
        async with aiohttp.ClientSession() as session:
            # Process in batches of 10 for speed
            batch_size = Config.MAX_CONCURRENT_IMDB
            final_movies = []
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                
                # Parallel IMDB calls
                imdb_tasks = []
                for movie in batch:
                    task = get_imdb_fast(movie['title'], session)
                    imdb_tasks.append(task)
                
                imdb_results = await asyncio.gather(*imdb_tasks, return_exceptions=True)
                
                # Add IMDB data to movies
                for movie, imdb_data in zip(batch, imdb_results):
                    if isinstance(imdb_data, dict) and imdb_data.get('success'):
                        movie.update({
                            'imdb_poster': imdb_data['poster'],
                            'imdb_year': imdb_data['year'],
                            'imdb_rating': imdb_data['rating'],
                            'has_imdb': True
                        })
                    else:
                        movie['has_imdb'] = False
                    
                    final_movies.append(movie)
        
        logger.info(f"⚡ IMDB processing: {time.time() - imdb_start:.2f}s")
        logger.info(f"🎉 TOTAL TIME: {time.time() - start_time:.2f}s")
        
        # Cache results for next time
        cache_store[cache_key] = final_movies
        cache_store[cache_time_key] = datetime.now()
        
        return final_movies
        
    except Exception as e:
        logger.error(f"Fast loading error: {e}")
        return []

async def get_channel_posts_fast(channel_id):
    """Fast channel post extraction"""
    try:
        posts = []
        count = 0
        
        async for message in User.get_chat_history(channel_id, limit=30):
            if message.text and len(message.text) > 30:
                title = extract_title_fast(message.text)
                
                if title:
                    posts.append({
                        'title': title,
                        'text': message.text,
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'channel_id': channel_id,
                        'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                    })
                    count += 1
                    
                    if count >= 25:  # Limit per channel for speed
                        break
        
        return posts
        
    except Exception as e:
        logger.warning(f"Channel {channel_id} fast extraction error: {e}")
        return []

async def search_fast(query, limit=10, offset=0):
    """Fast search with caching"""
    cache_key = f"search_{query}_{limit}_{offset}"
    
    # Check cache first
    if cache_key in cache_store['search_results']:
        cached_result, cached_time = cache_store['search_results'][cache_key]
        if datetime.now() - cached_time < timedelta(seconds=120):  # 2 min cache
            logger.info(f"⚡ SEARCH CACHE HIT: {query}")
            return cached_result
    
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    try:
        start_time = time.time()
        all_results = []
        
        # Parallel channel search
        search_tasks = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            task = search_channel_fast(channel_id, query)
            search_tasks.append(task)
        
        channel_results = await asyncio.gather(*search_tasks, return_exceptions=True)
        
        # Combine results
        for result in channel_results:
            if isinstance(result, list):
                all_results.extend(result)
        
        # Sort by relevance
        all_results.sort(key=lambda x: x.get('links', 0), reverse=True)
        
        total = len(all_results)
        results = all_results[offset:offset + limit]
        
        search_result = {
            "results": results,
            "total": total,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total / limit) if total > 0 else 1
        }
        
        # Cache result
        cache_store['search_results'][cache_key] = (search_result, datetime.now())
        
        logger.info(f"⚡ Fast search: {time.time() - start_time:.2f}s, {len(results)} results")
        return search_result
        
    except Exception as e:
        logger.error(f"Fast search error: {e}")
        return {"results": [], "total": 0}

async def search_channel_fast(channel_id, query):
    """Fast single channel search"""
    try:
        results = []
        
        async for message in User.search_messages(channel_id, query, limit=20):
            if message.text:
                results.append({
                    'content': format_content_fast(message.text),
                    'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                    'channel_name': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                    'links': len(re.findall(r'https?://[^\s]+', message.text))
                })
        
        return results
        
    except:
        return []

def format_content_fast(text):
    """Fast content formatting"""
    if not text:
        return ""
    
    # Basic HTML escape
    formatted = html.escape(text)
    
    # Quick link conversion
    formatted = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff;">\1</a>', formatted)
    formatted = formatted.replace('\n', '<br>')
    
    return formatted

async def initialize_telegram():
    """Fast telegram initialization"""
    global User, bot_started
    
    try:
        User = Client(
            "sk4film_fast",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Fast connect: {me.first_name}")
        
        # Quick channel verification
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                await User.get_chat(channel_id)
                working_channels.append(channel_id)
            except:
                pass
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            logger.info(f"⚡ FAST READY: {len(working_channels)} channels")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Fast init error: {e}")
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
        "service": "SK4FiLM FAST API",
        "version": "8.0-SPEED",
        "mode": "ULTRA_FAST_LOADING",
        "cache_enabled": True,
        "parallel_processing": True,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/latest_movies')
async def api_latest_movies():
    """ULTRA FAST latest movies API with caching"""
    try:
        start_time = time.time()
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        logger.info(f"⚡ FAST API: Getting {limit} movies...")
        
        movies = await get_movies_ultra_fast()
        
        if movies:
            processing_time = time.time() - start_time
            
            return jsonify({
                "status": "success",
                "movies": movies[:limit],
                "count": len(movies[:limit]),
                "processing_time": f"{processing_time:.2f}s",
                "cache_used": cache_store['latest_movies_time'] is not None,
                "fast_mode": "ENABLED",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({"status": "error", "message": "No movies"}), 404
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """FAST search API"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 8))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Query required"}), 400
        
        result = await search_fast(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": result["results"],
            "pagination": {
                "current_page": result["current_page"],
                "total_pages": result["total_pages"],
                "total_results": result["total"]
            },
            "fast_mode": "ENABLED",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/imdb_poster')
async def api_imdb_poster():
    """FAST IMDB poster proxy"""
    try:
        url = request.args.get('url', '').strip()
        
        if not url or not url.startswith('http'):
            return Response(create_fast_placeholder(), mimetype='image/svg+xml')
        
        # Quick headers
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=8) as response:
                if response.status == 200:
                    image_data = await response.read()
                    return Response(
                        image_data,
                        mimetype='image/jpeg',
                        headers={'Cache-Control': 'public, max-age=3600'}
                    )
        
        return Response(create_fast_placeholder(), mimetype='image/svg+xml')
        
    except:
        return Response(create_fast_placeholder(), mimetype='image/svg+xml')

def create_fast_placeholder():
    """Fast SVG placeholder"""
    return '''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
        <rect width="100%" height="100%" fill="#1a1a2e"/>
        <text x="50%" y="50%" text-anchor="middle" fill="#00ccff" font-size="20">🎬</text>
        <text x="50%" y="75%" text-anchor="middle" fill="#ffffff" font-size="12">SK4FiLM</text>
        </svg>'''

async def run_server():
    try:
        logger.info("🚀 SK4FiLM ULTRA FAST SERVER")
        
        success = await initialize_telegram()
        
        if success:
            logger.info("⚡ FAST MODE ACTIVATED!")
        
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
