import asyncio
import os
import logging
from pyrogram import Client, errors
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import html
import re
from datetime import datetime
import math
import aiohttp
import urllib.parse

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # IMDB API Keys for reliability
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e", "3e2b5f9d"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
User = None
bot_started = False

def extract_movie_title_smart(telegram_text):
    """Smart movie title extraction from Telegram posts"""
    if not telegram_text or len(telegram_text) < 10:
        return None
    
    try:
        # Clean text for processing
        text = telegram_text.replace('\u0000', '').strip()
        
        # Get first meaningful line
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if not lines:
            return None
        
        first_line = lines[0]
        logger.info(f"🎯 Extracting from: '{first_line[:50]}...'")
        
        # Enhanced movie title patterns
        title_patterns = [
            # Pattern 1: Movie Name (Year)
            r'🎬?\s*([^(]{4,45}?)\s*\(\d{4}\)',
            
            # Pattern 2: Movie Name - Year/Info
            r'🎬?\s*([^-]{4,45}?)\s*-\s*(?:20\d{2}|Hindi|English|Action|Drama|Comedy)',
            
            # Pattern 3: After film emoji
            r'🎬\s*([^-\n]{4,45}?)(?:\s*-|\s*\n|$)',
            
            # Pattern 4: Quoted titles
            r'"([^"]{4,40})"',
            
            # Pattern 5: Bold/emphasized titles
            r'\*\*([^*]{4,40})\*\*',
            
            # Pattern 6: Clean title before separator
            r'^([A-Z][^-|\n]{4,35}?)(?:\s*[-|]|\s*\n)',
            
            # Pattern 7: Multiple word titles
            r'^([A-Z][a-z]+(?:\s+[A-Za-z]+){1,4})',
            
            # Pattern 8: Numeric titles (like "3 Idiots")
            r'^(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        ]
        
        for i, pattern in enumerate(title_patterns, 1):
            try:
                match = re.search(pattern, first_line, re.IGNORECASE)
                if match:
                    raw_title = match.group(1).strip()
                    
                    # Clean and validate title
                    clean_title = clean_movie_title(raw_title)
                    
                    if validate_movie_title(clean_title):
                        logger.info(f"✅ Pattern {i} success: '{clean_title}'")
                        return clean_title
                        
            except Exception as e:
                logger.warning(f"Pattern {i} error: {e}")
                continue
        
        logger.warning(f"⚠️ No title patterns matched for: '{first_line[:50]}...'")
        return None
        
    except Exception as e:
        logger.error(f"Smart title extraction error: {e}")
        return None

def clean_movie_title(title):
    """Clean and normalize movie title"""
    if not title:
        return ""
    
    # Remove extra words
    title = title.replace('Movie', '').replace('Film', '').replace('Full', '').strip()
    
    # Normalize spaces
    title = re.sub(r'\s+', ' ', title)
    
    # Remove leading/trailing punctuation
    title = re.sub(r'^[^\w]+|[^\w]+$', '', title)
    
    return title.strip()

def validate_movie_title(title):
    """Validate if extracted title is a valid movie name"""
    if not title or len(title) < 3 or len(title) > 60:
        return False
    
    # Check for invalid patterns
    invalid_words = ['size', 'quality', 'rating', 'download', 'link', 'channel', 'group', 'file', 'mb', 'gb']
    if any(word in title.lower() for word in invalid_words):
        return False
    
    # Check if it's just numbers
    if re.match(r'^\d+$', title):
        return False
    
    # Must contain at least one letter
    if not re.search(r'[a-zA-Z]', title):
        return False
    
    return True

async def get_imdb_poster_enhanced(movie_title):
    """Enhanced IMDB poster fetching with multiple API keys"""
    if not movie_title:
        return {'success': False, 'error': 'No title provided'}
    
    for i, api_key in enumerate(Config.OMDB_KEYS):
        try:
            logger.info(f"🎬 IMDB API {i+1}/{len(Config.OMDB_KEYS)}: '{movie_title}'")
            
            async with aiohttp.ClientSession() as session:
                # Primary search
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(movie_title)}&apikey={api_key}&plot=short"
                
                async with session.get(url, timeout=12) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('Response') == 'True':
                            poster_url = data.get('Poster', '')
                            
                            if poster_url and poster_url != 'N/A' and poster_url.startswith('http'):
                                imdb_info = {
                                    'poster_url': poster_url,
                                    'imdb_title': data.get('Title', movie_title),
                                    'year': data.get('Year', 'Unknown'),
                                    'rating': data.get('imdbRating', 'N/A'),
                                    'genre': data.get('Genre', 'N/A'),
                                    'plot': data.get('Plot', 'No plot available')[:150],
                                    'director': data.get('Director', 'N/A'),
                                    'runtime': data.get('Runtime', 'N/A'),
                                    'success': True,
                                    'api_key_index': i + 1
                                }
                                
                                logger.info(f"✅ IMDB SUCCESS (API {i+1}): {poster_url[:50]}...")
                                return imdb_info
                            else:
                                logger.info(f"⚠️ No poster URL (API {i+1})")
                        else:
                            logger.info(f"⚠️ Movie not found (API {i+1}): {data.get('Error', 'Unknown')}")
                    else:
                        logger.warning(f"❌ HTTP {response.status} (API {i+1})")
            
            # Small delay between API attempts
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.warning(f"⚠️ API {i+1} failed: {e}")
            continue
    
    logger.error(f"❌ All IMDB APIs failed for: '{movie_title}'")
    return {'success': False, 'error': 'All API keys exhausted'}

async def get_recent_movies_with_posters(limit=30):
    """Get recent movies from Telegram with IMDB posters"""
    if not User or not bot_started:
        logger.error("❌ Telegram not connected")
        return []
    
    try:
        logger.info("📋 Getting recent movie posts from Telegram channels...")
        
        all_movie_posts = []
        
        # Get posts from all text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                logger.info(f"📝 Processing {channel_name} ({channel_id})...")
                
                posts_found = 0
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=60  # Get more to ensure variety
                ):
                    if message.text and len(message.text) > 40:
                        # Extract movie title
                        movie_title = extract_movie_title_smart(message.text)
                        
                        if movie_title:
                            movie_post = {
                                'extracted_title': movie_title,
                                'original_post': message.text,
                                'preview_text': message.text[:100] + ('...' if len(message.text) > 100 else ''),
                                'post_date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': channel_name,
                                'has_download_links': bool(re.search(r'https?://', message.text)),
                                'download_count': len(re.findall(r'https?://[^\s]+', message.text)),
                                'post_length': len(message.text)
                            }
                            
                            all_movie_posts.append(movie_post)
                            posts_found += 1
                            
                            logger.info(f"📄 Movie {posts_found}: '{movie_title}' from {channel_name}")
                
                logger.info(f"✅ {channel_name}: {posts_found} movie posts extracted")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} processing error: {e}")
                continue
        
        if not all_movie_posts:
            logger.warning("⚠️ No movie posts found in any channel")
            return []
        
        # Sort by date (newest first) and remove duplicates
        all_movie_posts.sort(key=lambda x: x['post_date'], reverse=True)
        
        # Remove duplicate movie titles
        seen_titles = set()
        unique_movies = []
        
        for post in all_movie_posts:
            title_key = post['extracted_title'].lower().strip()
            if title_key not in seen_titles and len(unique_movies) < limit:
                seen_titles.add(title_key)
                unique_movies.append(post)
        
        logger.info(f"📊 Found {len(unique_movies)} unique movies for IMDB processing")
        
        # Add IMDB posters to each movie
        movies_with_imdb = []
        
        for i, movie in enumerate(unique_movies):
            try:
                logger.info(f"🎬 IMDB processing {i+1}/{len(unique_movies)}: '{movie['extracted_title']}'")
                
                # Get IMDB data
                imdb_result = await get_imdb_poster_enhanced(movie['extracted_title'])
                
                if imdb_result.get('success'):
                    # Successfully got IMDB data
                    movie.update({
                        'imdb_poster_url': imdb_result['poster_url'],
                        'imdb_title': imdb_result['imdb_title'],
                        'imdb_year': imdb_result['year'],
                        'imdb_rating': imdb_result['rating'],
                        'imdb_genre': imdb_result['genre'],
                        'imdb_plot': imdb_result['plot'],
                        'has_imdb_data': True,
                        'api_used': imdb_result['api_key_index']
                    })
                    logger.info(f"✅ IMDB added: '{movie['extracted_title']}'")
                else:
                    # No IMDB data available
                    movie.update({
                        'imdb_poster_url': None,
                        'has_imdb_data': False,
                        'imdb_error': imdb_result.get('error', 'Not found in IMDB')
                    })
                    logger.info(f"⚠️ No IMDB: '{movie['extracted_title']}'")
                
                movies_with_imdb.append(movie)
                
                # Rate limiting delay
                await asyncio.sleep(0.4)
                
            except Exception as e:
                logger.error(f"Movie IMDB processing error: {e}")
                continue
        
        logger.info(f"✅ COMPLETE: {len(movies_with_imdb)} movies ready with IMDB integration")
        return movies_with_imdb
        
    except Exception as e:
        logger.error(f"❌ Recent movies processing error: {e}")
        return []

async def search_telegram_full(query, limit=20, offset=0):
    """Complete telegram search with enhanced formatting"""
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    try:
        logger.info(f"🔍 Full Telegram search: '{query}'")
        
        search_results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                logger.info(f"📝 Searching {channel_name}...")
                
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=50
                ):
                    if message.text and len(message.text) > 30:
                        formatted_content = format_telegram_post(message.text)
                        
                        result = {
                            'content': formatted_content,
                            'raw_text': message.text,
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'channel_name': channel_name,
                            'channel_id': channel_id,
                            'message_id': message.id,
                            'telegram_link': f"https://t.me/c/{str(channel_id).replace('-100', '')}/{message.id}",
                            'download_links': len(re.findall(r'https?://[^\s]+', message.text)),
                            'has_downloads': bool(re.search(r'https?://', message.text))
                        }
                        
                        search_results.append(result)
                        
            except Exception as e:
                logger.warning(f"Search error in {channel_id}: {e}")
                continue
        
        # Sort by relevance and date
        search_results.sort(key=lambda x: (x['download_links'], x['date']), reverse=True)
        
        total_results = len(search_results)
        paginated_results = search_results[offset:offset + limit]
        
        logger.info(f"✅ Search complete: {len(paginated_results)}/{total_results} results")
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1
        }
        
    except Exception as e:
        logger.error(f"Telegram search error: {e}")
        return {"results": [], "total": 0}

def format_telegram_post(text):
    """Format telegram post for display"""
    if not text:
        return ""
    
    try:
        # HTML escape
        formatted = html.escape(text)
        
        # Enhanced download links
        formatted = re.sub(
            r'(https?://[^\s]+)', 
            r'<a href="\1" target="_blank" class="download-link"><i class="fas fa-external-link-alt me-1"></i>\1</a>', 
            formatted
        )
        
        # Convert newlines
        formatted = formatted.replace('\n', '<br>')
        
        # Movie info tags
        formatted = re.sub(r'📁\s*Size[:\s]*([^<br>|]+)', r'<span class="info-tag size-tag"><i class="fas fa-hdd me-1"></i>\1</span>', formatted)
        formatted = re.sub(r'📹\s*Quality[:\s]*([^<br>|]+)', r'<span class="info-tag quality-tag"><i class="fas fa-video me-1"></i>\1</span>', formatted)
        formatted = re.sub(r'⭐\s*Rating[:\s]*([^<br>|]+)', r'<span class="info-tag rating-tag"><i class="fas fa-star me-1"></i>\1</span>', formatted)
        
        # Movie title highlighting
        formatted = re.sub(r'🎬\s*([^<br>-]+)', r'<h5 class="movie-highlight"><i class="fas fa-film me-2"></i>\1</h5>', formatted)
        
        return formatted
        
    except Exception as e:
        logger.warning(f"Post formatting error: {e}")
        return html.escape(str(text))

async def initialize_telegram():
    """Initialize Telegram connection"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram...")
        
        User = Client(
            "sk4film_main",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected: {me.first_name} (@{me.username or 'no_username'})")
        
        # Verify channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Channel OK: {chat.title}")
                working_channels.append(channel_id)
            except Exception as e:
                logger.error(f"❌ Channel {channel_id} error: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            logger.info(f"🎉 SYSTEM READY with {len(working_channels)} channels")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"❌ Telegram init error: {e}")
        return False

# CORS
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
        "service": "SK4FiLM API - Recent Movies with IMDB Posters",
        "telegram_connected": bot_started,
        "channels": Config.TEXT_CHANNEL_IDS,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/latest_movies')
async def api_latest_movies():
    """MAIN API: Get recent movies with IMDB posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available"
            }), 503
        
        logger.info(f"🎬 API: Getting {limit} recent movies with IMDB posters...")
        
        movies = await get_recent_movies_with_posters(limit)
        
        if movies:
            imdb_count = sum(1 for m in movies if m.get('has_imdb_data'))
            logger.info(f"✅ API SUCCESS: {len(movies)} movies, {imdb_count} with IMDB posters")
            
            return jsonify({
                "status": "success",
                "movies": movies,
                "total_movies": len(movies),
                "movies_with_imdb": imdb_count,
                "source": "RECENT_TELEGRAM_POSTS_WITH_IMDB",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "message": "No recent movies found"
            }), 404
            
    except Exception as e:
        logger.error(f"❌ Latest movies API error: {e}")
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
        
        result = await search_telegram_full(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": result["results"],
            "pagination": {
                "current_page": result["current_page"],
                "total_pages": result["total_pages"],
                "total_results": result["total"],
                "results_per_page": limit
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/imdb_poster')
async def api_imdb_poster():
    """Enhanced IMDB poster proxy with better error handling"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url or not poster_url.startswith('http'):
            return create_poster_placeholder("Invalid URL")
        
        logger.info(f"🖼️ Proxying IMDB poster: {poster_url[:60]}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/jpeg,image/png,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Referer': 'https://www.imdb.com/'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ IMDB poster loaded: {len(image_data)} bytes")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Cache-Control': 'public, max-age=86400',  # 24 hours
                            'Content-Type': content_type,
                            'Access-Control-Allow-Origin': '*',
                            'Access-Control-Allow-Methods': 'GET',
                            'Access-Control-Allow-Headers': 'Content-Type'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster HTTP error: {response.status}")
                    return create_poster_placeholder(f"HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        logger.error("⏰ IMDB poster timeout")
        return create_poster_placeholder("Timeout")
    except Exception as e:
        logger.error(f"❌ Poster proxy error: {e}")
        return create_poster_placeholder("Load Error")

def create_poster_placeholder(error_text):
    """Create professional poster placeholder"""
    svg = f'''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="posterGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="50%" style="stop-color:#16213e"/>
                <stop offset="100%" style="stop-color:#0f172a"/>
            </linearGradient>
            <linearGradient id="iconGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#00ccff"/>
                <stop offset="100%" style="stop-color:#0066ff"/>
            </linearGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#posterGrad)"/>
        <circle cx="150" cy="150" r="45" fill="none" stroke="url(#iconGrad)" stroke-width="3" opacity="0.6"/>
        <circle cx="150" cy="150" r="35" fill="url(#iconGrad)" opacity="0.3"/>
        <text x="50%" y="160" text-anchor="middle" fill="url(#iconGrad)" font-size="24" font-family="Arial, sans-serif" font-weight="bold">🎬</text>
        <text x="50%" y="220" text-anchor="middle" fill="#00ccff" font-size="16" font-family="Arial, sans-serif" font-weight="600">SK4FiLM</text>
        <text x="50%" y="250" text-anchor="middle" fill="#ffffff" font-size="12" font-family="Arial, sans-serif" opacity="0.8">{error_text}</text>
        <text x="50%" y="320" text-anchor="middle" fill="#00ccff" font-size="10" font-family="Arial, sans-serif" opacity="0.6">Click to Search Telegram</text>
        </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={'Cache-Control': 'public, max-age=300'})

# Server
async def run_server():
    try:
        logger.info("🚀 SK4FiLM - Recent Movies + IMDB Posters System")
        
        success = await initialize_telegram()
        
        if success:
            logger.info("✅ SYSTEM FULLY OPERATIONAL!")
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"💥 Server error: {e}")
    finally:
        if User:
            await User.stop()

if __name__ == "__main__":
    asyncio.run(run_server())
