import asyncio
import os
from pyrogram import Client
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import logging

# Configuration
class Config:
    API_ID = int(os.environ.get("API_ID", ""))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    USER_SESSION_STRING = os.environ.get("USER_SESSION_STRING", "")
    
    TEXT_CHANNEL_IDS = [-1001891090100, -1002024811395]
    POSTER_CHANNEL_ID = -1002708802395
    SECRET_KEY = os.environ.get("SECRET_KEY", "sk4film-secret-2024")
    WEB_SERVER_PORT = int(os.environ.get("PORT", 8000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

# CORS setup
@app.after_request
async def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Telegram client
User = Client(
    "user_session",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    session_string=Config.USER_SESSION_STRING
) if Config.USER_SESSION_STRING else None

async def web_search(query, limit=20):
    """Search movies"""
    if not User:
        return []
    
    if not User.is_connected:
        try:
            await User.start()
        except Exception as e:
            logger.error(f"User client error: {e}")
            return []

    results = []
    
    try:
        # Search text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for msg in User.search_messages(channel_id, query=query, limit=10):
                    if msg.text:
                        results.append({
                            'type': 'text',
                            'content': msg.text[:500] + "..." if len(msg.text) > 500 else msg.text,
                            'date': msg.date.isoformat() if msg.date else None
                        })
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # Search poster channel
        async for msg in User.search_messages(Config.POSTER_CHANNEL_ID, query=query, limit=10):
            if msg.caption and msg.photo:
                results.append({
                    'type': 'poster',
                    'content': msg.caption[:500] + "..." if len(msg.caption) > 500 else msg.caption,
                    'photo': msg.photo.file_id,
                    'date': msg.date.isoformat() if msg.date else None
                })
    except Exception as e:
        logger.error(f"Search error: {e}")
    
    return results[:limit]

async def get_latest_posters(limit=12):
    """Get latest posters"""
    if not User:
        return []
    
    if not User.is_connected:
        try:
            await User.start()
        except Exception:
            return []

    posters = []
    try:
        async for msg in User.get_chat_history(Config.POSTER_CHANNEL_ID, limit=limit):
            if msg.photo and msg.caption:
                posters.append({
                    'photo': msg.photo.file_id,
                    'caption': msg.caption[:100] + "..." if len(msg.caption) > 100 else msg.caption,
                    'search_query': msg.caption.split('\n')[0] if msg.caption else "Movie"
                })
    except Exception as e:
        logger.error(f"Posters error: {e}")
    
    return posters

# API Routes
@app.route('/api/search')
async def api_search():
    """Search endpoint"""
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({'error': 'Query required'}), 400
    
    try:
        results = await web_search(query)
        return jsonify({
            'status': 'success',
            'query': query,
            'results': results,
            'count': len(results)
        })
    except Exception as e:
        logger.error(f"API search error: {e}")
        return jsonify({'error': 'Search failed'}), 500

@app.route('/api/latest_posters')
async def api_latest_posters():
    """Latest posters endpoint"""
    try:
        posters = await get_latest_posters()
        return jsonify({
            'status': 'success',
            'posters': posters,
            'count': len(posters)
        })
    except Exception as e:
        logger.error(f"Posters API error: {e}")
        return jsonify({'error': 'Failed to load posters'}), 500

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster images"""
    file_id = request.args.get('file_id')
    if not file_id:
        return "File ID required", 400
    
    try:
        if not User.is_connected:
            await User.start()
        
        file = await User.download_media(file_id, in_memory=True)
        return Response(file.getvalue(), mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Poster download error: {e}")
        return "Error loading image", 500

@app.route('/api/health')
async def health():
    """Health check"""
    return jsonify({"status": "healthy", "service": "SK4FiLM API"})

async def start_server():
    """Start the API server"""
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except Exception as e:
        logger.error(f"Server error: {e}")
