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
    
    # Channel IDs
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
    
    text = html.escape(text)
    text = re.sub(
        r'(https?://[^\s]+)', 
        r'<a href="\1" target="_blank" style="color: #00ccff;">\1</a>', 
        text
    )
    text = text.replace('\n', '<br>')
    
    return text

async def initialize_telegram():
    """Initialize Telegram client"""
    global User, bot_started
    
    try:
        if not Config.USER_SESSION_STRING:
            logger.error("❌ USER_SESSION_STRING is required!")
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
        
        me = await User.get_me()
        logger.info(f"✅ Logged in as: {me.first_name}")
        
        bot_started = True
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Telegram: {e}")
        return False

async def search_telegram_channels(query, limit=50):
    """Search in all Telegram channels - REAL DATA ONLY"""
    if not User or not bot_started:
        return []
    
    results = []
    
    try:
        # Search in text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for message in User.search_messages(
                    chat_id=channel_id,
                    query=query,
                    limit=20
                ):
                    if message.text:
                        results.append({
                            'type': 'text',
                            'content': format_result(message.text),
                            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                            'message_id': message.id
                        })
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
                continue
        
        # Search in poster channel
        try:
            async for message in User.search_messages(
                chat_id=Config.POSTER_CHANNEL_ID,
                query=query,
                limit=20
            ):
                if message.caption:
                    result = {
                        'type': 'poster',
                        'content': format_result(message.caption),
                        'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                        'message_id': message.id
                    }
                    
                    if message.photo:
                        result['photo'] = message.photo.file_id
                    else:
                        result['photo'] = None
                    
                    results.append(result)
        except Exception as e:
            logger.warning(f"Poster channel error: {e}")
    
    except Exception as e:
        logger.error(f"Search error: {e}")
    
    # Sort by date (newest first)
    results.sort(key=lambda x: x['date'], reverse=True)
    
    return results[:limit]

async def get_real_posters(limit=12):
    """Get real posters from Telegram - NO MOCK DATA"""
    if not User or not bot_started:
        return []
    
    posters = []
    
    try:
        async for message in User.get_chat_history(
            chat_id=Config.POSTER_CHANNEL_ID,
            limit=limit
        ):
            if message.caption and message.photo:
                posters.append({
                    'photo': message.photo.file_id,
                    'caption': message.caption[:100] + "..." if len(message.caption) > 100 else message.caption,
                    'search_query': message.caption.split('\n')[0] if message.caption else "Movie",
                    'date': message.date.isoformat() if message.date else datetime.now().isoformat()
                })
                
                if len(posters) >= limit:
                    break
                    
    except Exception as e:
        logger.error(f"Error getting posters: {e}")
    
    return posters

# CORS setup
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# API endpoints
@app.route('/')
async def home():
    return jsonify({
        "status": "healthy" if bot_started else "error",
        "service": "SK4FiLM API",
        "mode": "REAL_DATA_ONLY",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
async def health():
    return jsonify({"status": "healthy" if bot_started else "unhealthy"})

@app.route('/api/health')
async def api_health():
    return jsonify({
        "status": "healthy" if bot_started else "unhealthy",
        "telegram_connected": bot_started
    })

@app.route('/api/search')
async def api_search():
    """Real search - NO MOCK DATA"""
    try:
        query = request.args.get('query', '').strip()
        limit = int(request.args.get('limit', 20))
        
        if not query:
            return jsonify({
                "status": "error",
                "message": "Query parameter required"
            }), 400
        
        if not bot_started:
            return jsonify({
                "status": "error", 
                "message": "Telegram not connected"
            }), 503
        
        logger.info(f"🔍 Real search: {query}")
        
        results = await search_telegram_channels(query, limit)
        
        return jsonify({
            "status": "success",
            "query": query,
            "results": results,
            "count": len(results),
            "source": "REAL_TELEGRAM_DATA"
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({
            "status": "error",
            "message": "Search failed"
        }), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """Real posters - NO MOCK DATA"""
    try:
        limit = int(request.args.get('limit', 8))
        
        if not bot_started:
            return jsonify({
                "status": "error",
                "message": "Telegram not connected"
            }), 503
        
        posters = await get_real_posters(limit)
        
        return jsonify({
            "status": "success",
            "posters": posters,
            "count": len(posters),
            "source": "REAL_TELEGRAM_CHANNEL"
        })
        
    except Exception as e:
        logger.error(f"Posters error: {e}")
        return jsonify({
            "status": "error", 
            "message": "Failed to get posters"
        }), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve real poster images"""
    try:
        file_id = request.args.get('file_id', '').strip()
        
        if not file_id or file_id == 'null':
            # Return placeholder for missing posters
            svg = '''
            <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
                <rect width="100%" height="100%" fill="#1a1a2e"/>
                <text x="50%" y="50%" text-anchor="middle" fill="white" font-family="Arial">No Poster</text>
            </svg>
            '''
            return Response(svg, mimetype='image/svg+xml')
        
        if not User:
            return jsonify({"status": "error"}), 503
        
        # Download from Telegram
        file_data = await User.download_media(file_id, in_memory=True)
        
        return Response(
            file_data.getvalue(),
            mimetype='image/jpeg',
            headers={'Cache-Control': 'public, max-age=3600'}
        )
        
    except Exception as e:
        logger.error(f"Poster error: {e}")
        svg = '''
        <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#1a1a2e"/>
            <text x="50%" y="50%" text-anchor="middle" fill="white" font-family="Arial">Error</text>
        </svg>
        '''
        return Response(svg, mimetype='image/svg+xml')

async def startup():
    """Initialize services"""
    logger.info("🚀 Starting SK4FiLM Backend...")
    await initialize_telegram()
    
    if bot_started:
        logger.info("✅ Ready for REAL Telegram search!")
    else:
        logger.error("❌ Telegram initialization failed!")

async def shutdown():
    """Cleanup"""
    if User:
        await User.stop()

if __name__ == "__main__":
    try:
        asyncio.run(startup())
        
        config = HyperConfig()
        config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
        
        logger.info(f"🌐 Server starting on port {Config.WEB_SERVER_PORT}")
        asyncio.run(serve(app, config))
        
    except Exception as e:
        logger.error(f"💥 Server failed: {e}")
    finally:
        asyncio.run(shutdown())
