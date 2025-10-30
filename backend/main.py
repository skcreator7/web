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
    
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e"]
    
    # AUTO UPDATE SETTINGS
    AUTO_UPDATE_INTERVAL = 30  # 30 seconds check for new posts
    CACHE_DURATION = 60  # 1 minute cache

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

# REAL-TIME DATA STORE
movie_data_store = {
    'latest_movies': [],
    'last_update': None,
    'last_message_ids': {},  # Track last message ID per channel
    'auto_update_running': False
}

def extract_movie_title_from_post(text):
    """Extract movie title from telegram post"""
    if not text or len(text) < 15:
        return None
    
    try:
        first_line = text.split('\n')[0].strip()
        
        patterns = [
            r'🎬\s*([^-\n]{4,40})(?:\s*-|\n|$)',
            r'^([^(]{4,40})\s*\(\d{4}\)',
            r'^([^-]{4,40})\s*-\s*(?:Hindi|English|20\d{2})',
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                title = re.sub(r'\s+', ' ', title)
                if 4 <= len(title) <= 45:
                    return title
        
        return None
        
    except:
        return None

async def get_imdb_data_fast(title):
    """Fast IMDB data fetching"""
    try:
        url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&apikey={Config.OMDB_KEYS[0]}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('Response') == 'True' and data.get('Poster') != 'N/A':
                        return {
                            'poster': data['Poster'],
                            'year': data.get('Year', ''),
                            'rating': data.get('imdbRating', ''),
                            'success': True
                        }
        
        return {'success': False}
        
    except:
        return {'success': False}

async def check_for_new_posts():
    """Check for new posts in channels - AUTO UPDATE CORE"""
    if not User or not bot_started:
        return False
    
    try:
        logger.info("🔄 AUTO UPDATE: Checking for new posts...")
        
        new_posts_found = False
        current_time = datetime.now()
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                # Get last known message ID for this channel
                last_known_id = movie_data_store['last_message_ids'].get(channel_id, 0)
                
                # Check recent messages
                new_messages = []
                async for message in User.get_chat_history(channel_id, limit=10):
                    if message.id > last_known_id and message.text and len(message.text) > 30:
                        title = extract_movie_title_from_post(message.text)
                        
                        if title:
                            new_messages.append({
                                'title': title,
                                'text': message.text,
                                'date': message.date.isoformat() if message.date else current_time.isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            })
                
                if new_messages:
                    logger.info(f"🆕 NEW POSTS: {len(new_messages)} from {channel_name}")
                    
                    # Update last message ID
                    movie_data_store['last_message_ids'][channel_id] = max(msg['message_id'] for msg in new_messages)
                    
                    # Add IMDB data to new posts
                    for movie in new_messages:
                        imdb_data = await get_imdb_data_fast(movie['title'])
                        if imdb_data['success']:
                            movie.update({
                                'imdb_poster': imdb_data['poster'],
                                'imdb_year': imdb_data['year'],
                                'imdb_rating': imdb_data['rating'],
                                'has_poster': True
                            })
                        else:
                            movie['has_poster'] = False
                    
                    # Add new movies to front of list
                    movie_data_store['latest_movies'] = new_messages + movie_data_store['latest_movies']
                    
                    # Keep only latest 50 movies
                    movie_data_store['latest_movies'] = movie_data_store['latest_movies'][:50]
                    
                    new_posts_found = True
                    
            except Exception as e:
                logger.warning(f"New posts check error for {channel_id}: {e}")
                continue
        
        if new_posts_found:
            movie_data_store['last_update'] = current_time
            logger.info("✅ AUTO UPDATE: New movies added to feed")
        else:
            logger.info("ℹ️ AUTO UPDATE: No new posts found")
        
        return new_posts_found
        
    except Exception as e:
        logger.error(f"❌ Auto update check error: {e}")
        return False

async def auto_update_loop():
    """Background auto update loop - runs continuously"""
    logger.info("🔄 AUTO UPDATE LOOP STARTED")
    
    while bot_started:
        try:
            if not movie_data_store['auto_update_running']:
                movie_data_store['auto_update_running'] = True
                
                # Check for new posts
                await check_for_new_posts()
                
                movie_data_store['auto_update_running'] = False
            
            # Wait before next check
            await asyncio.sleep(Config.AUTO_UPDATE_INTERVAL)
            
        except Exception as e:
            logger.error(f"Auto update loop error: {e}")
            movie_data_store['auto_update_running'] = False
            await asyncio.sleep(60)  # Wait longer on error

async def get_initial_movies():
    """Get initial movies on startup"""
    if not User or not bot_started:
        return []
    
    try:
        logger.info("📋 Getting initial movies...")
        
        all_movies = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                
                latest_message_id = 0
                movies_from_channel = []
                
                async for message in User.get_chat_history(channel_id, limit=25):
                    if message.text and len(message.text) > 30:
                        title = extract_movie_title_from_post(message.text)
                        
                        if title:
                            movie = {
                                'title': title,
                                'text': message.text,
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'channel': channel_name,
                                'message_id': message.id,
                                'channel_id': channel_id
                            }
                            
                            movies_from_channel.append(movie)
                            latest_message_id = max(latest_message_id, message.id)
                
                # Store last message ID for auto updates
                movie_data_store['last_message_ids'][channel_id] = latest_message_id
                all_movies.extend(movies_from_channel)
                
                logger.info(f"✅ {channel_name}: {len(movies_from_channel)} movies (Last ID: {latest_message_id})")
                
            except Exception as e:
                logger.warning(f"Initial load error for {channel_id}: {e}")
        
        # Sort by date, remove duplicates
        all_movies.sort(key=lambda x: x['date'], reverse=True)
        
        unique_movies = []
        seen_titles = set()
        
        for movie in all_movies:
            if movie['title'].lower() not in seen_titles and len(unique_movies) < 30:
                seen_titles.add(movie['title'].lower())
                unique_movies.append(movie)
        
        # Add IMDB data in batches
        for i in range(0, len(unique_movies), 5):
            batch = unique_movies[i:i+5]
            
            imdb_tasks = [get_imdb_data_fast(movie['title']) for movie in batch]
            imdb_results = await asyncio.gather(*imdb_tasks, return_exceptions=True)
            
            for movie, imdb_data in zip(batch, imdb_results):
                if isinstance(imdb_data, dict) and imdb_data.get('success'):
                    movie.update({
                        'imdb_poster': imdb_data['poster'],
                        'imdb_year': imdb_data['year'],
                        'imdb_rating': imdb_data['rating'],
                        'has_poster': True
                    })
                else:
                    movie['has_poster'] = False
            
            await asyncio.sleep(0.2)
        
        movie_data_store['latest_movies'] = unique_movies
        movie_data_store['last_update'] = datetime.now()
        
        logger.info(f"✅ Initial load: {len(unique_movies)} movies ready")
        return unique_movies
        
    except Exception as e:
        logger.error(f"Initial movies error: {e}")
        return []

async def search_telegram_channels(query, limit=10, offset=0):
    """Search telegram channels"""
    try:
        results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(channel_id, query, limit=15):
                    if message.text:
                        formatted = html.escape(message.text)
                        formatted = re.sub(r'(https?://[^\s]+)', r'<a href="\1" target="_blank" style="color: #00ccff;">\1</a>', formatted)
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
    """Initialize telegram and start auto update"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram with AUTO UPDATE...")
        
        User = Client(
            "sk4film_auto_update",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected: {me.first_name}")
        
        # Verify channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Channel verified: {chat.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.error(f"❌ Channel {channel_id} error: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            
            # Load initial movies
            await get_initial_movies()
            
            # START AUTO UPDATE BACKGROUND TASK
            asyncio.create_task(auto_update_loop())
            
            logger.info(f"🎉 SYSTEM READY with AUTO UPDATE! Channels: {working_channels}")
            logger.info(f"⏰ Auto update every {Config.AUTO_UPDATE_INTERVAL} seconds")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"❌ Telegram init error: {e}")
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
        "service": "SK4FiLM - Real-time Auto Update System",
        "auto_update_enabled": True,
        "update_interval": f"{Config.AUTO_UPDATE_INTERVAL}s",
        "last_update": movie_data_store['last_update'].isoformat() if movie_data_store['last_update'] else None,
        "movies_count": len(movie_data_store['latest_movies']),
        "telegram_connected": bot_started,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/latest_movies')
async def api_latest_movies():
    """Get latest movies - ALWAYS FRESH DATA"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        # Always return fresh data from store
        movies = movie_data_store['latest_movies'][:limit]
        
        logger.info(f"📱 API: Serving {len(movies)} movies (Last update: {movie_data_store['last_update']})")
        
        return jsonify({
            "status": "success",
            "movies": movies,
            "count": len(movies),
            "auto_update_active": True,
            "last_update": movie_data_store['last_update'].isoformat() if movie_data_store['last_update'] else None,
            "next_update_in": f"{Config.AUTO_UPDATE_INTERVAL}s",
            "real_time": True,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_status')
async def api_update_status():
    """Get real-time update status"""
    try:
        return jsonify({
            "auto_update_running": movie_data_store['auto_update_running'],
            "last_update": movie_data_store['last_update'].isoformat() if movie_data_store['last_update'] else None,
            "movies_count": len(movie_data_store['latest_movies']),
            "update_interval": Config.AUTO_UPDATE_INTERVAL,
            "last_message_ids": movie_data_store['last_message_ids'],
            "channels_monitored": Config.TEXT_CHANNEL_IDS,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/force_update')
async def api_force_update():
    """Force manual update check"""
    try:
        if not bot_started:
            return jsonify({"status": "error", "message": "Service unavailable"}), 503
        
        logger.info("🔄 FORCE UPDATE triggered by user")
        
        # Force check for new posts
        new_posts = await check_for_new_posts()
        
        return jsonify({
            "status": "success",
            "new_posts_found": new_posts,
            "movies_count": len(movie_data_store['latest_movies']),
            "last_update": movie_data_store['last_update'].isoformat() if movie_data_store['last_update'] else None,
            "message": "Update check completed",
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
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/poster/<path:poster_url>')
async def proxy_poster(poster_url):
    """Poster proxy"""
    try:
        if not poster_url.startswith('http'):
            poster_url = urllib.parse.unquote(poster_url)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/*',
            'Referer': 'https://www.imdb.com/'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    image_data = await response.read()
                    return Response(
                        image_data,
                        mimetype='image/jpeg',
                        headers={'Cache-Control': 'public, max-age=3600'}
                    )
        
        # Fallback SVG
        svg = '''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#1a1a2e"/>
            <text x="50%" y="50%" text-anchor="middle" fill="#00ccff" font-size="20">🎬</text>
            <text x="50%" y="75%" text-anchor="middle" fill="#ffffff" font-size="14">SK4FiLM</text>
            </svg>'''
        return Response(svg, mimetype='image/svg+xml')
        
    except:
        svg = '''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#dc3545"/>
            <text x="50%" y="50%" text-anchor="middle" fill="white" font-size="16">Error</text>
            </svg>'''
        return Response(svg, mimetype='image/svg+xml')

async def run_server():
    try:
        logger.info("🚀 SK4FiLM - REAL-TIME AUTO UPDATE SYSTEM")
        
        success = await initialize_telegram()
        
        if success:
            logger.info("✅ AUTO UPDATE SYSTEM ACTIVE!")
            logger.info(f"⏰ New posts check every {Config.AUTO_UPDATE_INTERVAL} seconds")
            logger.info("🔄 Website will show new movies automatically")
        
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
