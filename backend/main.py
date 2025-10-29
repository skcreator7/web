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

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", ""))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    # Channel IDs - CORRECT FORMAT
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    POSTER_CHANNEL_ID = -1002708802395
    
    # Server Config
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-key-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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

async def initialize_telegram():
    """Initialize Telegram client and verify channel access"""
    global User, bot_started
    
    try:
        if not Config.USER_SESSION_STRING:
            logger.error("❌ USER_SESSION_STRING is required for real search!")
            return False
            
        logger.info("🔄 Initializing Telegram User Client...")
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING
        )
        
        await User.start()
        logger.info("✅ Telegram User Client started successfully!")
        
        # Test connection by getting own info
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username})")
        
        # Verify channel access
        await verify_channel_access()
        
        bot_started = True
        return True
        
    except errors.SessionPasswordNeeded:
        logger.error("❌ 2FA Password required! Please check your session string.")
        return False
    except errors.ApiIdInvalid:
        logger.error("❌ Invalid API_ID or API_HASH!")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to initialize Telegram client: {e}")
        return False

async def verify_channel_access():
    """Verify access to all channels"""
    logger.info("🔍 Verifying channel access...")
    
    channels_to_check = Config.TEXT_CHANNEL_IDS + [Config.POSTER_CHANNEL_ID]
    
    for channel_id in channels_to_check:
        try:
            chat = await User.get_chat(channel_id)
            logger.info(f"✅ Access to channel {channel_id}: {chat.title}")
        except errors.ChannelInvalid:
            logger.error(f"❌ Invalid channel ID: {channel_id}")
        except errors.ChannelPrivate:
            logger.error(f"❌ Private channel: {channel_id} - Need to join first")
        except errors.ChatWriteForbidden:
            logger.error(f"❌ No read permission for channel: {channel_id}")
        except Exception as e:
            logger.error(f"❌ Error accessing channel {channel_id}: {e}")

async def search_text_channels(query, limit=20):
    """Search in text channels with proper error handling"""
    results = []
    
    for channel_id in Config.TEXT_CHANNEL_IDS:
        try:
            logger.info(f"🔍 Searching in text channel: {channel_id}")
            
            async for message in User.search_messages(
                chat_id=channel_id,
                query=query,
                limit=limit
            ):
                if message.text:
                    results.append({
                        'type': 'text',
                        'content': format_result(message.text),
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id,
                        'channel_id': channel_id
                    })
                    
            logger.info(f"✅ Found {len(results)} results in channel {channel_id}")
            
        except errors.ChatWriteForbidden:
            logger.error(f"❌ No permission to read channel: {channel_id}")
        except errors.ChannelInvalid:
            logger.error(f"❌ Invalid channel: {channel_id}")
        except errors.ChannelPrivate:
            logger.error(f"❌ Private channel: {channel_id} - Join required")
        except Exception as e:
            logger.error(f"❌ Error searching channel {channel_id}: {e}")
    
    return results

async def search_poster_channel(query, limit=20):
    """Search in poster channel with proper error handling"""
    results = []
    
    try:
        logger.info(f"🖼️ Searching in poster channel: {Config.POSTER_CHANNEL_ID}")
        
        async for message in User.search_messages(
            chat_id=Config.POSTER_CHANNEL_ID,
            query=query,
            limit=limit
        ):
            if message.caption:
                result = {
                    'type': 'poster',
                    'content': format_result(message.caption),
                    'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                    'message_id': message.id,
                    'channel_id': Config.POSTER_CHANNEL_ID
                }
                
                # Add photo if available
                if message.photo:
                    result['photo'] = message.photo.file_id
                    result['has_poster'] = True
                else:
                    result['has_poster'] = False
                    result['photo'] = f"text_result_{message.id}"
                
                results.append(result)
                
        logger.info(f"✅ Found {len(results)} poster results")
        
    except errors.ChatWriteForbidden:
        logger.error(f"❌ No permission to read poster channel: {Config.POSTER_CHANNEL_ID}")
    except errors.ChannelInvalid:
        logger.error(f"❌ Invalid poster channel: {Config.POSTER_CHANNEL_ID}")
    except errors.ChannelPrivate:
        logger.error(f"❌ Private poster channel: {Config.POSTER_CHANNEL_ID} - Join required")
    except Exception as e:
        logger.error(f"❌ Error searching poster channel: {e}")
    
    return results

async def web_search(query, limit=50):
    """Real search across all Telegram channels"""
    if not User or not bot_started:
        raise Exception("Telegram client not initialized. Please check USER_SESSION_STRING.")
    
    logger.info(f"🎬 Starting REAL search for: '{query}'")
    
    # Search in both text and poster channels
    text_results = await search_text_channels(query, limit//2)
    poster_results = await search_poster_channel(query, limit//2)
    
    # Combine results
    all_results = text_results + poster_results
    
    # Sort by date (newest first)
    all_results.sort(key=lambda x: x['date'], reverse=True)
    
    logger.info(f"📊 Total results found: {len(all_results)}")
    
    return all_results[:limit]

async def get_latest_posters(limit=12):
    """Get real latest posters from Telegram channel with error handling"""
    if not User or not bot_started:
        raise Exception("Telegram client not initialized.")
    
    posters = []
    
    try:
        logger.info(f"🖼️ Fetching {limit} latest posters...")
        
        async for message in User.get_chat_history(
            chat_id=Config.POSTER_CHANNEL_ID,
            limit=limit
        ):
            if message.caption:
                poster = {
                    'caption': message.caption,
                    'search_query': message.caption.split('\n')[0] if message.caption else "Movie",
                    'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                    'message_id': message.id
                }
                
                # Add photo if available
                if message.photo:
                    poster['photo'] = message.photo.file_id
                    poster['has_poster'] = True
                else:
                    poster['has_poster'] = False
                    poster['photo'] = f"text_poster_{message.id}"
                
                posters.append(poster)
                
        logger.info(f"✅ Found {len(posters)} real posters")
        
    except errors.ChannelPrivate:
        logger.error(f"❌ Private channel: {Config.POSTER_CHANNEL_ID} - Join required")
        raise Exception(f"Please join the channel first: {Config.POSTER_CHANNEL_ID}")
    except errors.ChatWriteForbidden:
        logger.error(f"❌ No read permission for channel: {Config.POSTER_CHANNEL_ID}")
        raise Exception(f"No permission to read channel: {Config.POSTER_CHANNEL_ID}")
    except Exception as e:
        logger.error(f"❌ Error fetching posters: {e}")
        raise
    
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
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM Real Search API",
        "version": "3.1.0",
        "timestamp": datetime.now().isoformat(),
        "telegram_status": "connected" if bot_started else "disconnected",
        "search_mode": "REAL_DATA",
        "channels_configured": {
            "text_channels": Config.TEXT_CHANNEL_IDS,
            "poster_channel": Config.POSTER_CHANNEL_ID
        }
    }
    return jsonify(status)

@app.route('/health')
async def health():
    """Health check for load balancers"""
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "service": "SK4FiLM Backend",
        "telegram_connected": bot_started,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/health')
async def api_health():
    """API health check"""
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "api_version": "3.1.0",
        "telegram_connected": bot_started,
        "search_mode": "REAL_DATA_ONLY",
        "timestamp": datetime.now().isoformat()
    })

# Main API endpoints
@app.route('/api/search')
async def api_search():
    """Real search endpoint - NO MOCK DATA"""
    try:
        query = request.args.get('query', '').strip()
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        
        if not query:
            return jsonify({
                "status": "error",
                "message": "Query parameter is required",
                "example": "/api/search?query=animal&page=1&limit=20"
            }), 400
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram client not connected. Please check USER_SESSION_STRING.",
                "solution": "Ensure USER_SESSION_STRING is set correctly in environment variables"
            }), 503
        
        logger.info(f"🔍 API Search Request: '{query}' | Page: {page} | Limit: {limit}")
        
        # Perform real search
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
            "search_info": {
                "mode": "REAL_TELEGRAM_DATA",
                "channels_searched": len(Config.TEXT_CHANNEL_IDS) + 1,
                "query_time": datetime.now().isoformat()
            }
        }
        
        logger.info(f"✅ Search completed: {len(page_results)} results on page {page}")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"❌ API Search Error: {e}")
        return jsonify({
            "status": "error",
            "message": "Search failed",
            "error": str(e),
            "solution": "Check Telegram client connection and channel permissions"
        }), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """Get real latest posters - NO MOCK DATA"""
    try:
        limit = int(request.args.get('limit', 12))
        limit = min(limit, 20)  # Max 20 posters
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram client not connected"
            }), 503
        
        logger.info(f"🖼️ Fetching {limit} real latest posters")
        
        posters = await get_latest_posters(limit)
        
        return jsonify({
            "status": "success",
            "posters": posters,
            "count": len(posters),
            "source": "REAL_TELEGRAM_CHANNEL",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Latest Posters Error: {e}")
        return jsonify({
            "status": "error",
            "message": "Failed to fetch posters",
            "error": str(e)
        }), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve real poster images from Telegram"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id:
            return jsonify({
                "status": "error",
                "message": "File ID parameter is required"
            }), 400
        
        # Handle text-only results (no actual poster)
        if file_id.startswith('text_'):
            # Return a simple placeholder for text results
            placeholder_svg = f'''
            <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
                <rect width="100%" height="100%" fill="#1a1a2e"/>
                <text x="50%" y="50%" text-anchor="middle" dy="0" fill="white" font-family="Arial" font-size="16">
                    Text Result
                </text>
                <text x="50%" y="60%" text-anchor="middle" dy="0" fill="#666" font-family="Arial" font-size="12">
                    No Poster Available
                </text>
            </svg>
            '''
            return Response(placeholder_svg, mimetype='image/svg+xml')
        
        if not User or not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram client not available"
            }), 503
        
        logger.info(f"📸 Downloading poster: {file_id}")
        
        # Download from Telegram
        file_data = await User.download_media(file_id, in_memory=True)
        
        if not file_data:
            raise Exception("Failed to download file from Telegram")
        
        logger.info(f"✅ Poster downloaded successfully: {len(file_data.getvalue())} bytes")
        
        return Response(
            file_data.getvalue(),
            mimetype='image/jpeg',
            headers={
                'Cache-Control': 'public, max-age=86400',
                'Content-Disposition': f'inline; filename="sk4film_poster.jpg"'
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Get Poster Error: {e}")
        # Return error placeholder
        error_svg = '''
        <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#1a1a2e"/>
            <text x="50%" y="50%" text-anchor="middle" dy="0" fill="white" font-family="Arial" font-size="14">
                Error Loading Image
            </text>
        </svg>
        '''
        return Response(error_svg, mimetype='image/svg+xml')

@app.route('/api/test_channels')
async def api_test_channels():
    """Test channel accessibility"""
    if not bot_started:
        return jsonify({"status": "error", "message": "Telegram not connected"}), 503
    
    channel_status = {}
    
    # Test all channels
    all_channels = Config.TEXT_CHANNEL_IDS + [Config.POSTER_CHANNEL_ID]
    
    for channel_id in all_channels:
        try:
            chat = await User.get_chat(channel_id)
            channel_status[str(channel_id)] = {
                "accessible": True,
                "title": chat.title,
                "type": str(chat.type),
                "username": getattr(chat, 'username', 'Private')
            }
        except errors.ChannelPrivate:
            channel_status[str(channel_id)] = {
                "accessible": False,
                "error": "Private channel - Join required",
                "solution": f"Join the channel first: {channel_id}"
            }
        except errors.ChatWriteForbidden:
            channel_status[str(channel_id)] = {
                "accessible": False,
                "error": "No read permission",
                "solution": "Ensure bot/user has read permissions"
            }
        except errors.ChannelInvalid:
            channel_status[str(channel_id)] = {
                "accessible": False,
                "error": "Invalid channel ID",
                "solution": "Check channel ID format"
            }
        except Exception as e:
            channel_status[str(channel_id)] = {
                "accessible": False,
                "error": str(e)
            }
    
    return jsonify({
        "status": "success",
        "channel_status": channel_status,
        "bot_user": {
            "first_name": (await User.get_me()).first_name,
            "username": (await User.get_me()).username
        }
    })

async def startup():
    """Initialize services on startup"""
    logger.info("🚀 Starting SK4FiLM Real Search Backend...")
    logger.info("📝 Mode: REAL DATA ONLY (No Mock Data)")
    
    # Initialize Telegram client
    success = await initialize_telegram()
    
    if success:
        logger.info("✅ All services initialized successfully!")
        logger.info("🎯 Ready for REAL Telegram search!")
    else:
        logger.error("❌ Failed to initialize Telegram client!")
        logger.error("💡 Please check your USER_SESSION_STRING environment variable")
        raise Exception("Telegram client initialization failed")

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
        
        logger.info(f"🎯 Server starting on http://0.0.0.0:{Config.WEB_SERVER_PORT}")
        
        # Start the server
        asyncio.run(serve(app, config))
        
    except KeyboardInterrupt:
        logger.info("⏹️ Server stopped by user")
    except Exception as e:
        logger.error(f"💥 Server failed to start: {e}")
    finally:
        asyncio.run(shutdown())
