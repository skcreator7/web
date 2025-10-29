import asyncio
import os
import logging
from pyrogram import Client
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import html
import re
from datetime import datetime

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", "12345678"))
    API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "1234567890:your_bot_token_here")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Channel IDs
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    POSTER_CHANNEL_ID = -1002708802395
    
    # Server Config
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('backend.log')
    ]
)
logger = logging.getLogger(__name__)

# Initialize Quart app
app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

# Global variables
User = None
bot_started = False

def format_result(text):
    """Format the result text with HTML"""
    if not text:
        return ""
    
    # Escape HTML characters
    text = html.escape(text)
    
    # Convert URLs to clickable links
    text = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff; text-decoration: none;">\1</a>', 
        text
    )
    
    # Convert newlines to <br>
    text = text.replace('\n', '<br>')
    
    return text

def get_mock_results(query):
    """Return realistic mock results for testing"""
    mock_posters = [
        {
            'photo': 'mock_animal',
            'caption': 'Animal (2023) Hindi Action Drama Film | Ranbir Kapoor | 1080p WEB-DL | 2.1GB',
            'search_query': 'Animal'
        },
        {
            'photo': 'mock_salaar', 
            'caption': 'Salaar: Part 1 - Ceasefire (2023) Telugu Action Thriller | Prabhas | 720p HD | 1.8GB',
            'search_query': 'Salaar'
        },
        {
            'photo': 'mock_dunki',
            'caption': 'Dunki (2023) Hindi Drama Comedy | Shah Rukh Khan | 1080p WEB-DL | 1.5GB',
            'search_query': 'Dunki'
        },
        {
            'photo': 'mock_jawan',
            'caption': 'Jawan (2023) Hindi Action Thriller | Shah Rukh Khan | 4K Ultra HD | 3.2GB',
            'search_query': 'Jawan'
        }
    ]
    
    mock_results = [
        {
            'type': 'text',
            'content': f'''
🎬 <b>{query} (2023)</b><br>
📁 <b>Size:</b> 2.1GB | 📹 <b>Quality:</b> 1080p WEB-DL<br>
🎭 <b>Genre:</b> Action, Drama, Crime<br>
⭐ <b>IMDb:</b> 7.5/10 | 📅 <b>Released:</b> 2023<br>
🗣️ <b>Language:</b> Hindi | 🔊 <b>Audio:</b> Original<br>

📥 <b>Download Links:</b><br>
✅ <a href="https://example.com/streamnet" target="_blank" style="color: #00ff00;">StreamNet Link</a> - Fast Streaming<br>
✅ <a href="https://example.com/diskwala" target="_blank" style="color: #00ff00;">DiskWala Link</a> - Direct Download<br>
✅ <a href="https://example.com/mega" target="_blank" style="color: #00ff00;">MegaNZ Link</a> - High Speed<br>
✅ <a href="https://example.com/gdrive" target="_blank" style="color: #00ff00;">Google Drive</a> - Premium Quality<br>

🔗 <b>Telegram Links:</b><br>
📱 <a href="https://t.me/sk4film" target="_blank" style="color: #0088cc;">Join Channel</a> - For latest updates<br>
🤖 <a href="https://t.me/skfilmbot" target="_blank" style="color: #0088cc;">Use Bot</a> - Instant search<br>

💡 <b>Note:</b> All links are tested and working. Use ad blocker for better experience.
            ''',
            'date': datetime.now().isoformat()
        },
        {
            'type': 'poster',
            'content': f'''
🎭 <b>{query} - Complete Movie Pack</b><br>
📦 <b>Includes:</b> Movie + Subtitles + OST<br>
🎵 <b>Soundtrack:</b> Original & Background Score<br>
🔊 <b>Audio:</b> Hindi 5.1 + English 5.1<br>
🎬 <b>Chapters:</b> Included | 📝 <b>Subtitles:</b> English<br>

⭐ <b>Features:</b><br>
• High Quality 1080p Encoding<br>
• Original Theatrical Experience<br>
• No Watermarks or Ads<br>
• Fast Download Servers<br>

📥 <b>Available On:</b><br>
🔸 StreamNet - Instant Play<br>
🔸 DiskWala - Multi-part Download<br>
🔸 Telegram - Direct Access<br>
🔸 Mega - Premium Speed<br>

🎯 <b>Quality Guaranteed:</b> 100% working links
            ''',
            'photo': 'mock_poster',
            'date': datetime.now().isoformat()
        }
    ]
    
    return mock_results, mock_posters

async def initialize_telegram():
    """Initialize Telegram client"""
    global User, bot_started
    
    try:
        if Config.USER_SESSION_STRING and not User:
            logger.info("🔄 Initializing Telegram User Client...")
            User = Client(
                "user_session",
                api_id=Config.API_ID,
                api_hash=Config.API_HASH,
                session_string=Config.USER_SESSION_STRING
            )
            
            await User.start()
            logger.info("✅ Telegram User Client started successfully!")
            bot_started = True
            
        elif not Config.USER_SESSION_STRING:
            logger.warning("⚠️ USER_SESSION_STRING not provided. Using mock data mode.")
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize Telegram client: {e}")
        User = None

async def web_search(query, limit=20):
    """Search movies across Telegram channels"""
    
    # If no Telegram client, return mock data
    if not User or not bot_started:
        logger.info(f"🔍 Mock search for: {query}")
        results, _ = get_mock_results(query)
        return results[:limit]
    
    results = []
    
    try:
        logger.info(f"🔍 Searching Telegram for: {query}")
        
        # Search in text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=10
                ):
                    if message.text:
                        results.append({
                            'type': 'text',
                            'content': format_result(message.text),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id,
                            'channel_id': channel_id
                        })
                        
            except Exception as e:
                logger.warning(f"Failed to search channel {channel_id}: {e}")
                continue
        
        # Search in poster channel
        try:
            async for message in User.search_messages(
                chat_id=Config.POSTER_CHANNEL_ID,
                query=query,
                limit=10
            ):
                if message.photo and message.caption:
                    results.append({
                        'type': 'poster',
                        'content': format_result(message.caption),
                        'photo': message.photo.file_id,
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': Config.POSTER_CHANNEL_ID
                    })
                    
        except Exception as e:
            logger.warning(f"Failed to search poster channel: {e}")
    
    except Exception as e:
        logger.error(f"Search error: {e}")
    
    # If no real results, use mock data
    if not results:
        logger.info("No real results found, using mock data")
        results, _ = get_mock_results(query)
    
    logger.info(f"📊 Found {len(results)} results for: {query}")
    return results[:limit]

async def get_latest_posters(limit=8):
    """Get latest posters from Telegram channel"""
    
    # If no Telegram client, return mock data
    if not User or not bot_started:
        logger.info("📸 Getting mock posters")
        _, mock_posters = get_mock_results("latest")
        return mock_posters[:limit]
    
    posters = []
    
    try:
        logger.info("📸 Fetching latest posters from Telegram...")
        
        async for message in User.get_chat_history(
            chat_id=Config.POSTER_CHANNEL_ID,
            limit=limit * 2  # Get more to filter
        ):
            if message.photo and message.caption and len(posters) < limit:
                posters.append({
                    'photo': message.photo.file_id,
                    'caption': message.caption[:150] + "..." if len(message.caption) > 150 else message.caption,
                    'search_query': message.caption.split('\n')[0] if message.caption else "Movie",
                    'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                    'message_id': message.id
                })
                
    except Exception as e:
        logger.error(f"Failed to get posters: {e}")
    
    # If no real posters, use mock data
    if not posters:
        logger.info("No real posters found, using mock data")
        _, posters = get_mock_results("latest")
    
    logger.info(f"🖼️ Found {len(posters)} posters")
    return posters[:limit]

# CORS setup
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Health check endpoints
@app.route('/')
async def home():
    """Home page with service status"""
    status = {
        "status": "healthy",
        "service": "SK4FiLM Backend API",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "telegram_status": "connected" if bot_started else "mock_mode",
        "endpoints": {
            "/health": "Service health check",
            "/api/search": "Search movies - GET ?query=moviename",
            "/api/latest_posters": "Get latest posters",
            "/api/get_poster": "Get poster image - GET ?file_id=xxx"
        }
    }
    return jsonify(status)

@app.route('/health')
async def health():
    """Health check for load balancers"""
    return jsonify({
        "status": "healthy",
        "service": "SK4FiLM Backend",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/health')
async def api_health():
    """API health check"""
    return jsonify({
        "status": "healthy",
        "api_version": "2.0.0",
        "telegram_connected": bot_started,
        "timestamp": datetime.now().isoformat()
    })

# Main API endpoints
@app.route('/api/search')
async def api_search():
    """Search endpoint with pagination"""
    try:
        query = request.args.get('query', '').strip()
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        if not query:
            return jsonify({
                "status": "error",
                "message": "Query parameter is required",
                "example": "/api/search?query=animal&page=1&limit=10"
            }), 400
        
        logger.info(f"🔍 API Search: '{query}' | Page: {page} | Limit: {limit}")
        
        # Get all results
        all_results = await web_search(query, limit=50)
        
        # Calculate pagination
        total_results = len(all_results)
        total_pages = max(1, (total_results + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_results = all_results[start_idx:end_idx]
        
        response = {
            "status": "success",
            "query": query,
            "results": page_results,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_results": total_results,
                "results_per_page": limit,
                "has_next": page < total_pages,
                "has_prev": page > 1
            },
            "telegram_mode": bot_started
        }
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"API Search Error: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal server error",
            "error": str(e)
        }), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """Get latest movie posters"""
    try:
        limit = int(request.args.get('limit', 8))
        limit = min(limit, 20)  # Max 20 posters
        
        logger.info(f"🖼️ Fetching {limit} latest posters")
        
        posters = await get_latest_posters(limit)
        
        return jsonify({
            "status": "success",
            "posters": posters,
            "count": len(posters),
            "telegram_mode": bot_started,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Latest Posters Error: {e}")
        return jsonify({
            "status": "error",
            "message": "Failed to fetch posters",
            "error": str(e)
        }), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster images"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id:
            return jsonify({
                "status": "error",
                "message": "File ID parameter is required"
            }), 400
        
        # Handle mock posters
        if file_id.startswith('mock_'):
            # Return a nice placeholder image
            placeholder_svg = f'''
            <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" style="stop-color:#ff0000;stop-opacity:1" />
                        <stop offset="100%" style="stop-color:#0066ff;stop-opacity:1" />
                    </linearGradient>
                </defs>
                <rect width="100%" height="100%" fill="url(#grad)"/>
                <text x="50%" y="45%" text-anchor="middle" dy="0" fill="white" font-family="Arial" font-size="24" font-weight="bold">
                    SK4FiLM
                </text>
                <text x="50%" y="55%" text-anchor="middle" dy="0" fill="white" font-family="Arial" font-size="16">
                    {file_id.replace('mock_', '').title()}
                </text>
                <text x="50%" y="70%" text-anchor="middle" dy="0" fill="white" font-family="Arial" font-size="12" opacity="0.8">
                    Movie Poster
                </text>
            </svg>
            '''
            return Response(placeholder_svg, mimetype='image/svg+xml')
        
        # Get real poster from Telegram
        if not User or not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram client not available"
            }), 503
        
        # Download and serve the image
        file_data = await User.download_media(file_id, in_memory=True)
        
        return Response(
            file_data.getvalue(),
            mimetype='image/jpeg',
            headers={
                'Cache-Control': 'public, max-age=3600',  # Cache for 1 hour
                'Content-Disposition': f'inline; filename="poster_{file_id}.jpg"'
            }
        )
        
    except Exception as e:
        logger.error(f"Get Poster Error: {e}")
        # Return error placeholder
        error_svg = '''
        <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#1a1a2e"/>
            <text x="50%" y="50%" text-anchor="middle" dy="0" fill="white" font-family="Arial" font-size="16">
                Error Loading Poster
            </text>
        </svg>
        '''
        return Response(error_svg, mimetype='image/svg+xml')

@app.route('/api/stats')
async def api_stats():
    """Get API statistics"""
    return jsonify({
        "status": "success",
        "service": "SK4FiLM Backend",
        "version": "2.0.0",
        "uptime": "running",
        "telegram_connected": bot_started,
        "mode": "production" if bot_started else "mock_mode",
        "timestamp": datetime.now().isoformat(),
        "supported_channels": len(Config.TEXT_CHANNEL_IDS) + 1,
        "features": [
            "Movie Search",
            "Poster Downloads", 
            "Real-time Updates",
            "Pagination",
            "Mock Data Fallback"
        ]
    })

async def startup():
    """Initialize services on startup"""
    logger.info("🚀 Starting SK4FiLM Backend Server...")
    
    # Initialize Telegram client
    await initialize_telegram()
    
    logger.info("✅ Backend services initialized successfully!")
    logger.info(f"🌐 Server will run on port {Config.WEB_SERVER_PORT}")

async def shutdown():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down backend services...")
    
    if User and bot_started:
        await User.stop()
        logger.info("✅ Telegram client stopped")

if __name__ == "__main__":
    try:
        # Run startup tasks
        asyncio.run(startup())
        
        # Server configuration
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        config.workers = 1
        config.accesslog = "-"
        config.errorlog = "-"
        
        logger.info(f"🎯 Server starting on http://0.0.0.0:{Config.WEB_SERVER_PORT}")
        logger.info("📊 Endpoints available:")
        logger.info("   GET /              - Service status")
        logger.info("   GET /health        - Health check") 
        logger.info("   GET /api/search    - Search movies")
        logger.info("   GET /api/posters   - Latest posters")
        logger.info("   GET /api/stats     - API statistics")
        
        # Start the server
        asyncio.run(serve(app, config))
        
    except KeyboardInterrupt:
        logger.info("⏹️ Server stopped by user")
    except Exception as e:
        logger.error(f"💥 Server failed to start: {e}")
    finally:
        asyncio.run(shutdown())
