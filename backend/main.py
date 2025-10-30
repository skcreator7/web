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
import json

class Config:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Working text channels
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))
    
    # Multiple OMDB API keys for better reliability
    OMDB_KEYS = ["8265bd1c", "b9bd48a6", "2f2d1c8e"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

User = None
bot_started = False

def extract_movie_title_enhanced(telegram_text):
    """Enhanced movie title extraction from telegram posts"""
    if not telegram_text:
        return None
    
    try:
        # Remove excess emojis but keep structure
        text = re.sub(r'[🔥💥⚡🎯🎪🎭⭐✨🌟💫🎊🎉]', '', telegram_text)
        
        # Get first meaningful line
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if not lines:
            return None
        
        first_line = lines[0]
        logger.info(f"🔍 Processing line: '{first_line[:60]}...'")
        
        # Enhanced patterns for Bollywood/Hollywood movies
        patterns = [
            # Pattern 1: Movie Name (Year)
            r'🎬?\s*([^(]{4,50}?)\s*\(\d{4}\)',
            
            # Pattern 2: Movie Name - Year/Quality
            r'🎬?\s*([^-]{4,50}?)\s*-\s*(?:20\d{2}|Hindi|English|Action|Drama)',
            
            # Pattern 3: After film emoji
            r'🎬\s*([^-\n]{4,50}?)(?:\s*-|\s*\n|$)',
            
            # Pattern 4: Clean title before dash
            r'^([A-Z][^-\n]{4,45}?)\s*-',
            
            # Pattern 5: Multi-word titles
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})',
            
            # Pattern 6: Numbers in title (like "3 Idiots", "2 States")
            r'^(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        ]
        
        for i, pattern in enumerate(patterns, 1):
            match = re.search(pattern, first_line, re.IGNORECASE)
            if match:
                raw_title = match.group(1).strip()
                
                # Clean up the title
                clean_title = re.sub(r'\s+', ' ', raw_title)  # Normalize spaces
                clean_title = clean_title.replace('Movie', '').replace('Film', '').strip()
                
                # Validate title
                if (4 <= len(clean_title) <= 60 and 
                    not re.match(r'^\d+$', clean_title) and
                    not clean_title.lower() in ['size', 'quality', 'rating', 'download', 'link']):
                    
                    logger.info(f"✅ Pattern {i} matched: '{clean_title}'")
                    return clean_title
        
        # Fallback: Look for quoted titles
        quoted_match = re.search(r'"([^"]{4,40})"', first_line)
        if quoted_match:
            quoted_title = quoted_match.group(1).strip()
            logger.info(f"💬 Quoted title found: '{quoted_title}'")
            return quoted_title
        
        logger.warning(f"⚠️ No title pattern matched for: '{first_line[:50]}...'")
        return None
        
    except Exception as e:
        logger.error(f"Title extraction error: {e}")
        return None

async def get_imdb_data_with_fallback(movie_title):
    """Get IMDB data with multiple API keys as fallback"""
    for i, api_key in enumerate(Config.OMDB_KEYS):
        try:
            logger.info(f"🎬 IMDB attempt {i+1}/3 for: '{movie_title}' (Key: {api_key[:4]}...)")
            
            async with aiohttp.ClientSession() as session:
                # Try exact title first
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(movie_title)}&apikey={api_key}&plot=short"
                
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if data.get('Response') == 'True':
                            poster_url = data.get('Poster', '')
                            
                            if poster_url and poster_url != 'N/A' and poster_url.startswith('http'):
                                imdb_result = {
                                    'poster_url': poster_url,
                                    'imdb_title': data.get('Title', movie_title),
                                    'year': data.get('Year', 'Unknown'),
                                    'rating': data.get('imdbRating', 'N/A'),
                                    'genre': data.get('Genre', 'N/A'),
                                    'plot': data.get('Plot', 'No plot available')[:200],
                                    'director': data.get('Director', 'N/A'),
                                    'actors': data.get('Actors', 'N/A')[:100],
                                    'runtime': data.get('Runtime', 'N/A'),
                                    'imdb_id': data.get('imdbID', ''),
                                    'success': True,
                                    'api_key_used': i + 1
                                }
                                
                                logger.info(f"✅ IMDB SUCCESS (Key {i+1}): {poster_url}")
                                return imdb_result
                            else:
                                logger.info(f"⚠️ No poster in response (Key {i+1})")
                        else:
                            error_msg = data.get('Error', 'Unknown error')
                            logger.info(f"⚠️ OMDB Error (Key {i+1}): {error_msg}")
                    else:
                        logger.warning(f"❌ HTTP Error (Key {i+1}): {response.status}")
        
        except Exception as e:
            logger.warning(f"⚠️ API Key {i+1} failed: {e}")
            continue
    
    logger.warning(f"❌ All IMDB API keys failed for: '{movie_title}'")
    return {'success': False, 'error': 'All API keys exhausted'}

async def get_30_latest_posts_with_titles_and_posters():
    """Get 30 latest posts with extracted titles and IMDB posters"""
    if not User or not bot_started:
        logger.error("❌ Telegram not connected")
        return []
    
    try:
        logger.info("📋 Getting latest posts from text channels for title extraction...")
        
        all_posts = []
        
        # Get posts from both text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                logger.info(f"📝 Processing channel: {channel_name} ({channel_id})")
                
                post_count = 0
                async for message in User.get_chat_history(
                    chat_id=channel_id,
                    limit=50  # Get more messages for better title variety
                ):
                    if message.text and len(message.text) > 40:  # Substantial posts only
                        # Extract movie title
                        movie_title = extract_movie_title_enhanced(message.text)
                        
                        if movie_title:
                            post_data = {
                                'extracted_title': movie_title,
                                'original_text': message.text,
                                'short_preview': message.text[:100] + ('...' if len(message.text) > 100 else ''),
                                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                                'message_id': message.id,
                                'channel_id': channel_id,
                                'channel_name': channel_name,
                                'has_download_links': bool(re.search(r'https?://', message.text)),
                                'download_link_count': len(re.findall(r'https?://[^\s]+', message.text)),
                                'telegram_link': f"https://t.me/c/{str(channel_id).replace('-100', '')}/{message.id}"
                            }
                            
                            all_posts.append(post_data)
                            post_count += 1
                            
                            logger.info(f"📄 Post {post_count}: '{movie_title}' from {channel_name}")
                
                logger.info(f"✅ Channel {channel_name}: {post_count} posts with extractable titles")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} processing error: {e}")
                continue
        
        if not all_posts:
            logger.error("❌ No posts with extractable titles found!")
            return []
        
        # Sort by date (newest first) and remove duplicates
        all_posts.sort(key=lambda x: x['date'], reverse=True)
        
        # Remove duplicate titles (case-insensitive)
        seen_titles = set()
        unique_posts = []
        
        for post in all_posts:
            title_key = post['extracted_title'].lower().strip()
            if title_key not in seen_titles and len(unique_posts) < 30:
                seen_titles.add(title_key)
                unique_posts.append(post)
        
        logger.info(f"📊 Found {len(unique_posts)} unique movie titles for IMDB lookup")
        
        # Add IMDB posters to each unique post
        final_posts_with_imdb = []
        
        for i, post in enumerate(unique_posts):
            try:
                logger.info(f"🎬 IMDB lookup {i+1}/{len(unique_posts)}: '{post['extracted_title']}'")
                
                # Get IMDB data
                imdb_data = await get_imdb_data_with_fallback(post['extracted_title'])
                
                if imdb_data.get('success'):
                    # Add IMDB data to post
                    post.update({
                        'imdb_poster_url': imdb_data['poster_url'],
                        'imdb_title': imdb_data['imdb_title'],
                        'imdb_year': imdb_data['year'],
                        'imdb_rating': imdb_data['rating'],
                        'imdb_genre': imdb_data['genre'],
                        'imdb_plot': imdb_data['plot'],
                        'imdb_director': imdb_data['director'],
                        'imdb_actors': imdb_data['actors'],
                        'has_imdb_poster': True,
                        'api_key_used': imdb_data['api_key_used']
                    })
                    logger.info(f"✅ IMDB added for: '{post['extracted_title']}'")
                else:
                    # No IMDB data available
                    post.update({
                        'imdb_poster_url': None,
                        'has_imdb_poster': False,
                        'imdb_error': imdb_data.get('error', 'Not found')
                    })
                    logger.info(f"⚠️ No IMDB data for: '{post['extracted_title']}'")
                
                final_posts_with_imdb.append(post)
                
                # Rate limiting - small delay between API calls
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.warning(f"Post IMDB integration error: {e}")
                continue
        
        logger.info(f"✅ COMPLETE: {len(final_posts_with_imdb)} posts ready with IMDB integration")
        return final_posts_with_imdb
        
    except Exception as e:
        logger.error(f"❌ Latest posts with IMDB error: {e}")
        return []

async def search_telegram_channels_enhanced(query, limit=20, offset=0):
    """Enhanced telegram search with better formatting"""
    if not User or not bot_started:
        return {"results": [], "total": 0}
    
    try:
        logger.info(f"🔍 Enhanced Telegram search for: '{query}'")
        
        all_results = []
        
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                channel_name = 'Movies Link' if channel_id == -1001891090100 else 'DISKWALA MOVIES'
                logger.info(f"📝 Searching {channel_name}...")
                
                result_count = 0
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=50
                ):
                    if message.text and len(message.text) > 30:
                        # Enhanced formatting
                        formatted_content = format_telegram_content_enhanced(message.text)
                        
                        result = {
                            'type': 'telegram_result',
                            'content': formatted_content,
                            'raw_text': message.text,
                            'extracted_title': extract_movie_title_enhanced(message.text),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id,
                            'channel_name': channel_name,
                            'telegram_link': f"https://t.me/c/{str(channel_id).replace('-100', '')}/{message.id}",
                            'download_links': extract_download_links(message.text),
                            'has_download_links': bool(re.search(r'https?://', message.text)),
                            'link_count': len(re.findall(r'https?://[^\s]+', message.text)),
                            'text_length': len(message.text),
                            'relevance_score': calculate_relevance_score(query, message.text)
                        }
                        
                        all_results.append(result)
                        result_count += 1
                
                logger.info(f"✅ {channel_name}: {result_count} results")
                
            except Exception as e:
                logger.warning(f"Channel {channel_id} search error: {e}")
                continue
        
        # Sort by relevance and date
        all_results.sort(key=lambda x: (x['relevance_score'], x['date']), reverse=True)
        
        total_results = len(all_results)
        paginated_results = all_results[offset:offset + limit]
        
        logger.info(f"✅ Enhanced search completed: {len(paginated_results)}/{total_results} results")
        
        return {
            "results": paginated_results,
            "total": total_results,
            "current_page": (offset // limit) + 1,
            "total_pages": math.ceil(total_results / limit) if total_results > 0 else 1,
            "search_query": query,
            "channels_searched": Config.TEXT_CHANNEL_IDS
        }
        
    except Exception as e:
        logger.error(f"Enhanced search error: {e}")
        return {"results": [], "total": 0}

def format_telegram_content_enhanced(text):
    """Enhanced formatting for telegram content"""
    if not text:
        return ""
    
    try:
        # HTML escape
        formatted = html.escape(text)
        
        # Enhanced download links formatting
        formatted = re.sub(
            r'(https?://[^\s]+)', 
            r'<a href="\1" target="_blank" class="download-link"><i class="fas fa-download me-2"></i>\1</a>', 
            formatted
        )
        
        # Convert newlines
        formatted = formatted.replace('\n', '<br>')
        
        # Enhanced movie metadata tags
        formatted = re.sub(r'📁\s*Size[:\s]*([^<br>|]+)', r'<span class="info-tag size-tag"><i class="fas fa-hdd me-1"></i>Size: \1</span>', formatted)
        formatted = re.sub(r'📹\s*Quality[:\s]*([^<br>|]+)', r'<span class="info-tag quality-tag"><i class="fas fa-video me-1"></i>Quality: \1</span>', formatted)
        formatted = re.sub(r'⭐\s*Rating[:\s]*([^<br>|]+)', r'<span class="info-tag rating-tag"><i class="fas fa-star me-1"></i>Rating: \1</span>', formatted)
        formatted = re.sub(r'🎭\s*Genre[:\s]*([^<br>|]+)', r'<span class="info-tag genre-tag"><i class="fas fa-masks-theater me-1"></i>Genre: \1</span>', formatted)
        formatted = re.sub(r'🎵\s*Audio[:\s]*([^<br>|]+)', r'<span class="info-tag audio-tag"><i class="fas fa-volume-up me-1"></i>Audio: \1</span>', formatted)
        
        # Movie title highlighting
        formatted = re.sub(r'🎬\s*([^<br>-]+)', r'<h6 class="movie-title-highlight"><i class="fas fa-film me-2"></i>\1</h6>', formatted)
        
        return formatted
        
    except Exception as e:
        logger.warning(f"Content formatting error: {e}")
        return html.escape(str(text))

def extract_download_links(text):
    """Extract and categorize download links"""
    if not text:
        return []
    
    links = re.findall(r'https?://[^\s]+', text)
    categorized_links = []
    
    for link in links:
        link_type = 'unknown'
        if 'drive.google' in link:
            link_type = 'google_drive'
        elif 'mega.nz' in link or 'mega.io' in link:
            link_type = 'mega'
        elif 'dropbox.com' in link:
            link_type = 'dropbox'
        elif 'telegram' in link or 't.me' in link:
            link_type = 'telegram'
        elif any(x in link.lower() for x in ['stream', 'watch', 'play']):
            link_type = 'streaming'
        elif any(x in link.lower() for x in ['download', 'dl', 'file']):
            link_type = 'download'
        
        categorized_links.append({
            'url': link,
            'type': link_type,
            'domain': urllib.parse.urlparse(link).netloc
        })
    
    return categorized_links

def calculate_relevance_score(query, text):
    """Calculate relevance score for search results"""
    if not query or not text:
        return 0
    
    query_lower = query.lower()
    text_lower = text.lower()
    
    score = 0
    
    # Exact match bonus
    if query_lower in text_lower:
        score += 10
    
    # Word matches
    query_words = query_lower.split()
    for word in query_words:
        if word in text_lower:
            score += 5
    
    # Download links bonus
    if re.search(r'https?://', text):
        score += 3
    
    # Length bonus for substantial content
    if len(text) > 200:
        score += 2
    
    return score

async def initialize_telegram():
    """Initialize telegram connection"""
    global User, bot_started
    
    try:
        logger.info("🔄 Initializing Telegram connection...")
        
        User = Client(
            "sk4film_latest",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING,
            workdir="/tmp"
        )
        
        await User.start()
        me = await User.get_me()
        logger.info(f"✅ Connected as: {me.first_name} (@{me.username or 'no_username'})")
        
        # Verify text channels
        working_channels = []
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                chat = await User.get_chat(channel_id)
                logger.info(f"✅ Channel verified: {chat.title} ({channel_id})")
                working_channels.append(channel_id)
            except Exception as e:
                logger.error(f"❌ Channel {channel_id} access error: {e}")
        
        if working_channels:
            Config.TEXT_CHANNEL_IDS = working_channels
            bot_started = True
            logger.info(f"🎉 SYSTEM READY! Working channels: {working_channels}")
            return True
        else:
            logger.error("❌ No accessible channels found!")
            return False
        
    except Exception as e:
        logger.error(f"❌ Telegram initialization failed: {e}")
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
        "service": "SK4FiLM API - Latest Posts + IMDB + Enhanced Search",
        "version": "7.0",
        "mode": "TITLE_EXTRACTION_IMDB_INTEGRATION",
        "telegram_connected": bot_started,
        "text_channels": Config.TEXT_CHANNEL_IDS,
        "imdb_keys_available": len(Config.OMDB_KEYS),
        "features": ["title_extraction", "imdb_posters", "enhanced_search", "click_to_search"],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/latest_posts')
async def api_latest_posts():
    """Get latest posts with titles and IMDB posters"""
    try:
        limit = int(request.args.get('limit', 30))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram service not available - please check connection"
            }), 503
        
        logger.info(f"🎬 API: Getting {limit} latest posts with IMDB integration...")
        
        posts_with_imdb = await get_30_latest_posts_with_titles_and_posters()
        
        if posts_with_imdb:
            success_count = sum(1 for post in posts_with_imdb if post.get('has_imdb_poster'))
            logger.info(f"✅ API SUCCESS: {len(posts_with_imdb)} posts, {success_count} with IMDB posters")
            
            return jsonify({
                "status": "success",
                "posts": posts_with_imdb[:limit],
                "total_posts": len(posts_with_imdb),
                "posts_with_imdb": success_count,
                "source": "TEXT_CHANNELS_TITLE_EXTRACTION_IMDB",
                "channels_used": Config.TEXT_CHANNEL_IDS,
                "timestamp": datetime.now().isoformat()
            })
        else:
            logger.warning("⚠️ No posts with extractable titles found")
            return jsonify({
                "status": "error",
                "message": "No posts with extractable movie titles found"
            }), 404
            
    except Exception as e:
        logger.error(f"❌ Latest posts API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/search')
async def api_search():
    """Enhanced search API"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 10))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        
        if not query:
            return jsonify({"status": "error", "message": "Search query is required"}), 400
        
        if not bot_started:
            return jsonify({"status": "error", "message": "Telegram service unavailable"}), 503
        
        logger.info(f"🔍 Enhanced Search API: '{query}' (page: {page}, limit: {limit})")
        
        search_results = await search_telegram_channels_enhanced(query, limit, offset)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": search_results["results"],
            "pagination": {
                "current_page": search_results["current_page"],
                "total_pages": search_results["total_pages"],
                "total_results": search_results["total"],
                "results_per_page": limit,
                "showing_start": offset + 1,
                "showing_end": min(offset + limit, search_results["total"]),
                "has_next_page": search_results["current_page"] < search_results["total_pages"]
            },
            "search_source": "TELEGRAM_CHANNELS_ENHANCED",
            "channels_searched": search_results.get("channels_searched", []),
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/proxy_poster')
async def api_proxy_poster():
    """FIXED: Proxy IMDB posters with better error handling"""
    try:
        poster_url = request.args.get('url', '').strip()
        
        if not poster_url:
            return create_error_placeholder("No URL provided")
        
        if not poster_url.startswith('http'):
            return create_error_placeholder("Invalid URL")
        
        logger.info(f"🖼️ Proxying IMDB poster: {poster_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Referer': 'https://www.imdb.com/'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    image_data = await response.read()
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    
                    logger.info(f"✅ IMDB poster proxied: {len(image_data)} bytes")
                    
                    return Response(
                        image_data,
                        mimetype=content_type,
                        headers={
                            'Cache-Control': 'public, max-age=7200',
                            'Content-Type': content_type,
                            'Access-Control-Allow-Origin': '*'
                        }
                    )
                else:
                    logger.warning(f"❌ Poster response error: {response.status}")
                    return create_error_placeholder(f"HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        logger.error("⏰ Poster download timeout")
        return create_error_placeholder("Timeout")
    except Exception as e:
        logger.error(f"❌ Poster proxy error: {e}")
        return create_error_placeholder("Proxy Error")

def create_error_placeholder(error_msg):
    """Create error placeholder SVG"""
    svg = f'''<svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="errorGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#1a1a2e"/>
                <stop offset="100%" style="stop-color:#16213e"/>
            </linearGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#errorGrad)"/>
        <circle cx="150" cy="150" r="50" fill="none" stroke="#00ccff" stroke-width="2" opacity="0.5"/>
        <text x="50%" y="160" text-anchor="middle" fill="#00ccff" font-size="18" font-family="Arial, sans-serif" font-weight="bold">
            <tspan x="50%" dy="0">🎬</tspan>
            <tspan x="50%" dy="30" font-size="14">SK4FiLM</tspan>
        </text>
        <text x="50%" y="250" text-anchor="middle" fill="#ffffff" font-size="12" font-family="Arial, sans-serif" opacity="0.8">{error_msg}</text>
        </svg>'''
    
    return Response(svg, mimetype='image/svg+xml', headers={'Cache-Control': 'public, max-age=300'})

# Server startup
async def run_server():
    try:
        logger.info("🚀 SK4FiLM Server - ENHANCED TITLE + IMDB + SEARCH SYSTEM")
        
        # Initialize telegram
        telegram_success = await initialize_telegram()
        
        if telegram_success:
            logger.info("✅ COMPLETE SYSTEM ONLINE!")
            logger.info("📋 Latest posts with title extraction")
            logger.info("🎬 IMDB posters with multiple API keys")
            logger.info("🔍 Enhanced telegram search")
            logger.info("🖱️ Click-to-search functionality")
        else:
            logger.warning("⚠️ System running in limited mode")
        
        # Start web server
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        logger.info(f"🌐 Starting web server on port {Config.WEB_SERVER_PORT}")
        await serve(app, config)
        
    except Exception as e:
        logger.error(f"💥 Server startup error: {e}")
    finally:
        if User:
            try:
                await User.stop()
                logger.info("🔌 Telegram client stopped")
            except:
                pass

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal server error: {e}")
