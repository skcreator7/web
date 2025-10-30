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

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Working OMDB API keys
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "a1b2c3d4"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Cache for performance
movie_cache = {}
poster_cache = {}

def extract_movie_title_clean(text):
    """Clean movie title extraction"""
    if not text:
        return None
    
    try:
        first_line = text.split('\n')[0].strip()
        
        patterns = [
            r'🎬\s*([^-\n]{4,35})(?:\s*-|\n|$)',
            r'^([^(]{4,35})\s*\(\d{4}\)',
            r'^([^-]{4,35})\s*-\s*(?:Hindi|English|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,3})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if 4 <= len(title) <= 40:
                    return title
        
        return None
        
    except:
        return None

async def get_imdb_poster_working(title):
    """WORKING IMDB poster fetching"""
    if title in poster_cache:
        return poster_cache[title]
    
    try:
        logger.info(f"🎬 Getting IMDB poster: {title}")
        
        # Use multiple user agents for better success
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]
        
        for i, api_key in enumerate(Config.OMDB_KEYS[:2]):  # Use first 2 keys for speed
            try:
                headers = {
                    'User-Agent': user_agents[i % len(user_agents)],
                    'Accept': 'application/json',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'DNT': '1',
                    'Connection': 'keep-alive'
                }
                
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={api_key}&type=movie"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=8) as response:
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
                                    'success': True
                                }
                                
                                poster_cache[title] = result
                                logger.info(f"✅ IMDB SUCCESS: {title}")
                                return result
                
                await asyncio.sleep(0.1)  # Small delay between keys
                
            except Exception as e:
                logger.warning(f"API key {i+1} failed: {e}")
                continue
        
        # Cache negative result
        negative = {'success': False, 'error': 'Not found'}
        poster_cache[title] = negative
        return negative
        
    except Exception as e:
        logger.error(f"IMDB error for {title}: {e}")
        return {'success': False, 'error': str(e)}

async def get_latest_movies_with_working_posters():
    """Get movies with WORKING poster system"""
    cache_key = 'latest_movies_cache'
    
    # Check cache first (1 minute for development)
    if cache_key in movie_cache:
        cached_data, cached_time = movie_cache[cache_key]
        if datetime.now() - cached_time < timedelta(minutes=1):
            logger.info("⚡ Using cached movies")
            return cached_data
    
    if not User or not bot_started:
        return []
    
    try:
        logger.info("📝 Getting latest movies...")
        
        all_posts = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                count = 0
                async for message in User.get_chat_history(channel_id, limit=30):
                    if message.text and len(message.text) > 40:
                        title = extract_movie_title_clean(message.text)
                        
                        if title:
                            all_posts.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'channel': channel_name
                            })
                            count += 1
                            
                            if count >= 20:  # Limit for speed
                                break
                
                logger.info(f"✅ {channel_name}: {count} movies")
                
            except Exception as e:
                logger.warning(f"Channel error: {e}")
        
        # Sort and deduplicate
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        unique_movies = []
        seen = set()
        
        for post in all_posts:
            if post['title'].lower() not in seen and len(unique_movies) < 25:
                seen.add(post['title'].lower())
                unique_movies.append(post)
        
        logger.info(f"📊 Processing {len(unique_movies)} unique movies")
        
        # Add IMDB posters - PARALLEL for speed
        movies_with_posters = []
        
        # Process in smaller batches for better success rate
        batch_size = 5
        for i in range(0, len(unique_movies), batch_size):
            batch = unique_movies[i:i + batch_size]
            
            # Parallel IMDB calls
            imdb_tasks = [get_imdb_poster_working(movie['title']) for movie in batch]
            imdb_results = await asyncio.gather(*imdb_tasks, return_exceptions=True)
            
            for movie, imdb_data in zip(batch, imdb_results):
                if isinstance(imdb_data, dict) and imdb_data.get('success'):
                    movie.update({
                        'imdb_poster': imdb_data['poster_url'],
                        'imdb_year': imdb_data['year'],
                        'imdb_rating': imdb_data['rating'],
                        'has_poster': True
                    })
                else:
                    movie['has_poster'] = False
                
                movies_with_posters.append(movie)
            
            # Small delay between batches
            await asyncio.sleep(0.2)
        
        # Cache results
        movie_cache[cache_key] = (movies_with_posters, datetime.now())
        
        logger.info(f"✅ {len(movies_with_posters)} movies ready")
        return movies_with_posters
        
    except Exception as e:
        logger.error(f"Latest movies error: {e}")
        return []

async def search_telegram(query, limit=10, offset=0):
    """Fast telegram search"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=15):
                    if message.text:
                        formatted = html.escape(message.text)
                        formatted = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600;">\1</a>', formatted)
                        formatted = formatted.replace('\n', '<br>')
                        
                        results.append({
                            'content': formatted,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'links': len(re.findall(r'https?://[^\s]+', message.text))
                        })
                        
            except Exception as e:
                logger.warning(f"Search error: {e}")
        
        results.sort(key=lambda x: x['date'], reverse=True)
        
        total = len(results)
        paginated = results[offset:offset + limit]
        
        return {
            "results": paginated,
            "total": total,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total / limit) if total > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"results": [], "total": 0}

async def initialize_telegram():
    global User, bot_started
    
    try:
        User = Client(
            "sk4film_poster",
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
                await User.get_chat(channel_id)
                working.append(channel_id)
            except:
                pass
        
        if working:
            bot_started = True
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
        "service": "SK4FiLM - Fixed Posters + AdSense Optimized",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/latest_movies')
async def api_latest_movies():
    """Fixed latest movies API"""
    try:
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        movies = await get_latest_movies_with_working_posters()
        
        return jsonify({
            "status": "success",
            "movies": movies[:30],
            "count": len(movies[:30]),
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
        
        result = await search_telegram(query, limit, offset)
        
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

@app.route('/api/poster/<path:poster_url>')
async def proxy_poster(poster_url):
    """FIXED poster proxy with better headers"""
    try:
        if not poster_url.startswith('http'):
            poster_url = urllib.parse.unquote(poster_url)
        
        logger.info(f"🖼️ Proxying poster: {poster_url[:50]}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
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
                            'Cache-Control': 'public, max-age=86400',
                            'Access-Control-Allow-Origin': '*',
                            'Access-Control-Allow-Methods': 'GET',
                            'Access-Control-Allow-Headers': 'Content-Type',
                            'Cross-Origin-Resource-Policy': 'cross-origin'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP {response.status}")
        
        return create_working_placeholder()
        
    except Exception as e:
        logger.error(f"Poster error: {e}")
        return create_working_placeholder()

def create_working_placeholder():
    """Working poster placeholder"""
    svg = '''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="100%" style="stop-color:#16213e"/>
            </linearGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#bg)"/>
        <circle cx="150" cy="180" r="40" fill="#00ccff" opacity="0.3"/>
        <text x="50%" y="190" text-anchor="middle" fill="#00ccff" font-size="30" font-weight="bold">🎬</text>
        <text x="50%" y="250" text-anchor="middle" fill="#ffffff" font-size="16" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="280" text-anchor="middle" fill="#00ccff" font-size="12">Movie Poster</text>
        </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

async def run_server():
    try:
        logger.info("🚀 SK4FiLM - Fixed Posters + AdSense Optimized")
        
        success = await initialize_telegram()
        if success:
            logger.info("✅ System ready!")
        
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
