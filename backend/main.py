import asyncio
import os
from pyrogram import Client
from quart import Quart, jsonify, request, Response
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
import logging
import html
import re

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

def format_result(text):
    """Format the result text"""
    if not text:
        return ""
    text = html.escape(text)
    text = re.sub(r'(https?://\S+)', r'<a href="\1">\1</a>', text)
    return text

# Telegram client
User = None
try:
    if Config.USER_SESSION_STRING:
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING
        )
        logger.info("User client initialized successfully")
    else:
        logger.warning("USER_SESSION_STRING not provided")
except Exception as e:
    logger.error(f"Failed to initialize Telegram client: {e}")

async def web_search(query, limit=20):
    """Search across channels"""
    if not User:
        return get_mock_results(query)
    
    try:
        if not User.is_connected:
            await User.start()
    except Exception as e:
        logger.error(f"Telegram client error: {e}")
        return get_mock_results(query)
    
    results = []
    
    try:
        # Search text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for msg in User.search_messages(channel_id, query=query, limit=10):
                    if msg.text:
                        results.append({
                            'type': 'text',
                            'content': format_result(msg.text),
                            'date': msg.date.isoformat() if msg.date else None
                        })
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # Search poster channel
        try:
            async for msg in User.search_messages(Config.POSTER_CHANNEL_ID, query=query, limit=10):
                if msg.caption and msg.photo:
                    results.append({
                        'type': 'poster',
                        'content': format_result(msg.caption),
                        'photo': msg.photo.file_id,
                        'date': msg.date.isoformat() if msg.date else None
                    })
        except Exception as e:
            logger.warning(f"Poster channel error: {e}")
            
    except Exception as e:
        logger.error(f"Search error: {e}")
    
    if not results:
        return get_mock_results(query)
    
    return results[:limit]

def get_mock_results(query):
    """Return mock results for testing"""
    return [
        {
            'type': 'text',
            'content': f'🎬 <b>{query} (2023)</b><br>📁 Size: 2.1GB | 📹 Quality: 1080p<br>🎭 Genre: Action, Drama<br>⭐ Rating: 8.5/10<br><br>📥 <b>Download Links:</b><br>✅ <a href="#">StreamNet Link</a><br>✅ <a href="#">DiskWala Link</a><br>✅ <a href="#">Direct Download</a>',
            'date': '2024-01-01T00:00:00'
        }
    ]

async def get_latest_posters(limit=8):
    """Get latest posters"""
    if not User:
        return get_mock_posters()
    
    try:
        if not User.is_connected:
            await User.start()
    except Exception:
        return get_mock_posters()
    
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
    
    if not posters:
        return get_mock_posters()
    
    return posters[:limit]

def get_mock_posters():
    """Return mock posters for testing"""
    return [
        {
            'photo': 'mock1',
            'caption': 'Animal (2023) - Hindi Action Drama Film',
            'search_query': 'Animal movie'
        },
        {
            'photo': 'mock2',
            'caption': 'Salaar (2023) - Prabhas Action Thriller',
            'search_query': 'Salaar movie'
        },
        {
            'photo': 'mock3',
            'caption': 'Dunki (2023) - Shah Rukh Khan Drama',
            'search_query': 'Dunki movie'
        },
        {
            'photo': 'mock4',
            'caption': 'Hi Nanna (2023) - Telugu Family Drama',
            'search_query': 'Hi Nanna movie'
        }
    ]

# API Routes
@app.route('/')
async def home():
    return jsonify({
        "status": "healthy", 
        "service": "SK4FiLM API",
        "message": "Backend server is running successfully"
    })

@app.route('/health')
async def health():
    return jsonify({"status": "healthy"})

@app.route('/api/health')
async def api_health():
    return jsonify({"status": "healthy"})

@app.route('/api/search')
async def api_search():
    """Search endpoint"""
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({'error': 'Query parameter required'}), 400
    
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
        return jsonify({
            'status': 'success',
            'query': query,
            'results': get_mock_results(query),
            'count': 1,
            'message': 'Using mock data'
        })

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
        return jsonify({
            'status': 'success',
            'posters': get_mock_posters(),
            'count': 4,
            'message': 'Using mock data'
        })

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster images"""
    file_id = request.args.get('file_id', '')
    
    # Return placeholder for mock images
    if not file_id or file_id.startswith('mock'):
        placeholder_svg = '''
        <svg width="300" height="400" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#1a1a2e"/>
            <text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="white" font-family="Arial" font-size="16">
                SK4FiLM
            </text>
            <text x="50%" y="60%" text-anchor="middle" dy=".3em" fill="#00ccff" font-family="Arial" font-size="12">
                Movie Poster
            </text>
        </svg>
        '''
        return Response(placeholder_svg, mimetype='image/svg+xml')
    
    try:
        if User and not User.is_connected:
            await User.start()
        
        file = await User.download_media(file_id, in_memory=True)
        return Response(file.getvalue(), mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Poster download error: {e}")
        return Response(
            '<svg width="300" height="400"><rect width="100%" height="100%" fill="#1a1a2e"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="white">Error Loading</text></svg>',
            mimetype='image/svg+xml'
        )

async def start_server():
    """Start the server"""
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
    
    logger.info(f"🚀 SK4FiLM Backend Server starting on port {Config.WEB_SERVER_PORT}")
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed: {e}")
