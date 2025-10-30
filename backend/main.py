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
    
    # Working OMDB API Keys
    OMDB_KEYS = [
        "8265bd1c",  # Primary
        "b9bd48a6",  # Backup 1  
        "2f2d1c8e",  # Backup 2
        "a1b2c3d4"   # Backup 3
    ]
    
    AUTO_UPDATE_INTERVAL = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# Data store with auto update
movie_store = {
    'movies': [],
    'last_update': None,
    'last_ids': {},
    'updating': False
}

def extract_title_enhanced(text):
    """Enhanced title extraction"""
    if not text or len(text) < 15:
        return None
    
    try:
        # Clean text first
        text = re.sub(r'[^\w\s\(\)\-\.\n]', ' ', text)
        first_line = text.split('\n')[0].strip()
        
        logger.debug(f"🎯 Processing: '{first_line[:40]}...'")
        
        patterns = [
            r'🎬\s*([^-\n]{4,40})(?:\s*-|\n|$)',
            r'^([^(]{4,40})\s*\(\d{4}\)',
            r'^([^-]{4,40})\s*-\s*(?:Hindi|English|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})',
            r'"([^"]{4,35})"',
            r'\*\*([^*]{4,35})\*\*'
        ]
        
        for i, pattern in enumerate(patterns, 1):
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                
                if validate_title(title):
                    logger.info(f"✅ Pattern {i}: '{title}'")
                    return title
        
        logger.debug(f"⚠️ No pattern matched")
        return None
        
    except Exception as e:
        logger.warning(f"Title extraction error: {e}")
        return None

def validate_title(title):
    """Validate movie title"""
    if not title or len(title) < 4 or len(title) > 45:
        return False
    
    bad_words = ['size', 'quality', 'download', 'link', 'channel', 'mb', 'gb']
    if any(word in title.lower() for word in bad_words):
        return False
    
    if re.match(r'^\d+$', title):
        return False
    
    return True

async def get_imdb_poster_fast(title, session):
    """Fast IMDB poster with working headers"""
    try:
        logger.info(f"🎬 IMDB: {title}")
        
        # Try multiple API keys quickly
        for i, api_key in enumerate(Config.OMDB_KEYS[:3]):
            try:
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={api_key}&plot=short"
                
                async with session.get(url, timeout=6) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if (data.get('Response') == 'True' and 
                            data.get('Poster') and 
                            data['Poster'] != 'N/A' and
                            data['Poster'].startswith('http')):
                            
                            result = {
                                'poster_url': data['Poster'],
                                'imdb_title': data.get('Title', title),
                                'year': data.get('Year', 'Unknown'),
                                'rating': data.get('imdbRating', 'N/A'),
                                'genre': data.get('Genre', 'N/A')[:50],
                                'success': True,
                                'api_used': i + 1
                            }
                            
                            logger.info(f"✅ IMDB OK (API {i+1}): {title}")
                            return result
                        else:
                            logger.debug(f"⚠️ No poster (API {i+1})")
                
                # Quick delay between API attempts
                if i < len(Config.OMDB_KEYS) - 1:
                    await asyncio.sleep(0.2)
                    
            except Exception as e:
                logger.warning(f"API {i+1} error: {e}")
                continue
        
        logger.info(f"❌ No IMDB: {title}")
        return {'success': False, 'error': 'No poster found'}
        
    except Exception as e:
        logger.error(f"IMDB error: {e}")
        return {'success': False, 'error': str(e)}

async def get_movies_with_fast_posters():
    """Get movies with FAST IMDB poster loading"""
    if not User or not bot_started:
        return []
    
    try:
        start_time = time.time()
        logger.info("🚀 Getting movies with fast IMDB posters...")
        
        all_posts = []
        
        # Get posts from channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                posts_count = 0
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 40:
                        title = extract_title_enhanced(message.text)
                        
                        if title:
                            all_posts.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            })
                            posts_count += 1
                
                logger.info(f"✅ {channel_name}: {posts_count} movies")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # Remove duplicates and sort
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        unique_movies = []
        seen_titles = set()
        
        for post in all_posts:
            if post['title'].lower() not in seen_titles and len(unique_movies) < 30:
                seen_titles.add(post['title'].lower())
                unique_movies.append(post)
        
        logger.info(f"📊 Processing {len(unique_movies)} movies")
        
        # FAST parallel IMDB processing
        imdb_start = time.time()
        
        async with aiohttp.ClientSession() as session:
            # Process in batches for reliability
            batch_size = 8
            final_movies = []
            
            for i in range(0, len(unique_movies), batch_size):
                batch = unique_movies[i:i + batch_size]
                
                # Parallel IMDB calls
                imdb_tasks = [get_imdb_poster_fast(movie['title'], session) for movie in batch]
                imdb_results = await asyncio.gather(*imdb_tasks, return_exceptions=True)
                
                for movie, imdb_data in zip(batch, imdb_results):
                    if isinstance(imdb_data, dict) and imdb_data.get('success'):
                        movie.update({
                            'imdb_poster': imdb_data['poster_url'],
                            'imdb_year': imdb_data['year'],
                            'imdb_rating': imdb_data['rating'],
                            'imdb_genre': imdb_data['genre'],
                            'has_poster': True
                        })
                    else:
                        movie['has_poster'] = False
                    
                    final_movies.append(movie)
                
                # Rate limiting between batches
                if i + batch_size < len(unique_movies):
                    await asyncio.sleep(0.3)
        
        imdb_time = time.time() - imdb_start
        total_time = time.time() - start_time
        
        poster_count = sum(1 for m in final_movies if m.get('has_poster'))
        
        logger.info(f"⚡ IMDB: {imdb_time:.2f}s, Total: {total_time:.2f}s")
        logger.info(f"🎬 {len(final_movies)} movies, {poster_count} with posters")
        
        return final_movies
        
    except Exception as e:
        logger.error(f"Movies with posters error: {e}")
        return []

async def check_new_posts():
    """Check for new posts - auto update"""
    if not User or not bot_started:
        return False
    
    try:
        logger.info("🔄 Checking for new posts...")
        
        new_found = False
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                last_id = movie_store['last_ids'].get(channel_id, 0)
                
                async for message in User.get_chat_history(channel_id, limit=5):
                    if message.id > last_id and message.text and len(message.text) > 40:
                        title = extract_title_enhanced(message.text)
                        
                        if title:
                            logger.info(f"🆕 NEW: {title}")
                            
                            # Add to front of list
                            new_movie = {
                                'title': title,
                                'text': message.text,
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'channel': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                                'is_new': True
                            }
                            
                            # Get IMDB poster quickly
                            async with aiohttp.ClientSession() as session:
                                imdb_data = await get_imdb_poster_fast(title, session)
                                
                                if imdb_data.get('success'):
                                    new_movie.update({
                                        'imdb_poster': imdb_data['poster_url'],
                                        'imdb_year': imdb_data['year'],
                                        'imdb_rating': imdb_data['rating'],
                                        'has_poster': True
                                    })
                                else:
                                    new_movie['has_poster'] = False
                            
                            movie_store['movies'].insert(0, new_movie)
                            movie_store['movies'] = movie_store['movies'][:40]  # Keep latest 40
                            
                            new_found = True
                
                # Update last message ID
                if movie_store['movies']:
                    movie_store['last_ids'][channel_id] = max(
                        movie_store['last_ids'].get(channel_id, 0),
                        max(msg.get('message_id', 0) for msg in movie_store['movies'] if 'message_id' in msg)
                    )
                
            except Exception as e:
                logger.warning(f"New posts check error: {e}")
        
        if new_found:
            movie_store['last_update'] = datetime.now()
            logger.info("✅ NEW MOVIES ADDED!")
        
        return new_found
        
    except Exception as e:
        logger.error(f"New posts error: {e}")
        return False

async def auto_update_background():
    """Background auto update loop"""
    logger.info("🔄 AUTO UPDATE LOOP STARTED")
    
    while bot_started:
        try:
            if not movie_store['updating']:
                movie_store['updating'] = True
                await check_new_posts()
                movie_store['updating'] = False
            
            await asyncio.sleep(Config.AUTO_UPDATE_INTERVAL)
            
        except Exception as e:
            logger.error(f"Auto update error: {e}")
            movie_store['updating'] = False
            await asyncio.sleep(60)

async def search_channels(query, limit=10, offset=0):
    """Search telegram channels"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=15):
                    if message.text:
                        formatted = format_content(message.text)
                        
                        results.append({
                            'content': formatted,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel': 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES',
                            'links': len(re.findall(r'https?://[^\s]+', message.text))
                        })
                        
            except Exception as e:
                logger.warning(f"Search error: {e}")
        
        results.sort(key=lambda x: x['links'], reverse=True)
        
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

def format_content(text):
    """Format telegram content"""
    if not text:
        return ""
    
    formatted = html.escape(text)
    formatted = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff; font-weight: 600; background: rgba(0,204,255,0.1); padding: 2px 6px; border-radius: 4px; margin: 2px; display: inline-block;"><i class="fas fa-external-link-alt me-1"></i>\1</a>', formatted)
    formatted = formatted.replace('\n', '<br>')
    
    # Enhanced formatting
    formatted = re.sub(r'📁\s*Size[:\s]*([^<br>|]+)', r'<span style="background: rgba(40,167,69,0.2); color: #28a745; padding: 4px 8px; border-radius: 8px; font-size: 0.8rem; margin: 2px; display: inline-block;"><i class="fas fa-hdd me-1"></i>Size: \1</span>', formatted)
    formatted = re.sub(r'📹\s*Quality[:\s]*([^<br>|]+)', r'<span style="background: rgba(0,123,255,0.2); color: #007bff; padding: 4px 8px; border-radius: 8px; font-size: 0.8rem; margin: 2px; display: inline-block;"><i class="fas fa-video me-1"></i>Quality: \1</span>', formatted)
    formatted = re.sub(r'⭐\s*Rating[:\s]*([^<br>|]+)', r'<span style="background: rgba(255,193,7,0.2); color: #ffc107; padding: 4px 8px; border-radius: 8px; font-size: 0.8rem; margin: 2px; display: inline-block;"><i class="fas fa-star me-1"></i>Rating: \1</span>', formatted)
    
    return formatted

async def initialize_telegram():
    """Initialize telegram with auto update"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram...")
        
        User = Client(
            "sk4film_complete",
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
            initial_movies = await get_movies_with_fast_posters()
            movie_store['movies'] = initial_movies
            movie_store['last_update'] = datetime.now()
            
            # Start auto update background task
            asyncio.create_task(auto_update_background())
            
            logger.info(f"🎉 COMPLETE SYSTEM READY!")
            logger.info(f"🎬 {len(initial_movies)} movies loaded")
            logger.info(f"🔄 Auto update every {Config.AUTO_UPDATE_INTERVAL}s")
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
        "service": "SK4FiLM Complete System",
        "features": [
            "fast_imdb_posters",
            "auto_update_system", 
            "social_media_menu",
            "tutorial_videos",
            "features_section",
            "disclaimer",
            "adsense_optimization"
        ],
        "auto_update": movie_store['updating'],
        "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
        "movies_count": len(movie_store['movies']),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/movies')
async def api_movies():
    """Main movies API with auto update data"""
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
            "movies_with_posters": poster_count,
            "auto_update_active": True,
            "last_update": movie_store['last_update'].isoformat() if movie_store['last_update'] else None,
            "update_interval": f"{Config.AUTO_UPDATE_INTERVAL}s",
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
        
        result = await search_channels(query, limit, offset)
        
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
async def api_poster():
    """WORKING poster proxy with enhanced headers"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url or not poster_url.startswith('http'):
            return create_placeholder_svg("No URL")
        
        logger.info(f"🖼️ Proxying: {poster_url[:60]}...")
        
        # Enhanced headers for IMDB
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
            'Sec-CH-UA': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Referer': 'https://www.imdb.com/'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ Poster OK: {len(image_data)} bytes")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Content-Type': content_type,
                            'Cache-Control': 'public, max-age=7200',
                            'Access-Control-Allow-Origin': '*',
                            'Access-Control-Allow-Methods': 'GET',
                            'Access-Control-Allow-Headers': 'Content-Type',
                            'Cross-Origin-Resource-Policy': 'cross-origin',
                            'X-Content-Type-Options': 'nosniff'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP {response.status}")
                    return create_placeholder_svg(f"HTTP {response.status}")
        
    except asyncio.TimeoutError:
        logger.warning("⏰ Poster timeout")
        return create_placeholder_svg("Timeout")
    except Exception as e:
        logger.error(f"❌ Poster error: {e}")
        return create_placeholder_svg("Error")

def create_placeholder_svg(error_msg):
    """Professional poster placeholder"""
    svg = f'''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="posterGrad" x1="0%" y1="0%" x2="100%" y2="100%">
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
        <rect width="100%" height="100%" fill="url(#posterGrad)" rx="10"/>
        <circle cx="150" cy="180" r="50" fill="none" stroke="#00ccff" stroke-width="3" opacity="0.6"/>
        <circle cx="150" cy="180" r="35" fill="#00ccff" opacity="0.2"/>
        <text x="50%" y="190" text-anchor="middle" fill="#00ccff" font-size="32" font-weight="bold" filter="url(#glow)">🎬</text>
        <text x="50%" y="250" text-anchor="middle" fill="#ffffff" font-size="18" font-weight="bold">SK4FiLM</text>
        <text x="50%" y="280" text-anchor="middle" fill="#00ccff" font-size="14" opacity="0.9">Movie Poster</text>
        <text x="50%" y="350" text-anchor="middle" fill="#ff6666" font-size="11" opacity="0.8">{error_msg}</text>
        <text x="50%" y="400" text-anchor="middle" fill="#00ccff" font-size="10" opacity="0.7">Click to Search</text>
    </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={
        'Cache-Control': 'public, max-age=300',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/api/force_update')
async def api_force_update():
    """Force manual update"""
    try:
        if not bot_started:
            return jsonify({"status": "error"}), 503
        
        logger.info("🔄 FORCE UPDATE requested")
        
        # Reload all movies
        new_movies = await get_movies_with_fast_posters()
        movie_store['movies'] = new_movies
        movie_store['last_update'] = datetime.now()
        
        return jsonify({
            "status": "success",
            "movies_loaded": len(new_movies),
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

async def run_server():
    try:
        logger.info("🚀 SK4FiLM COMPLETE SYSTEM")
        
        success = await initialize_telegram()
        
        if success:
            logger.info("🎉 ALL SYSTEMS OPERATIONAL!")
        
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
