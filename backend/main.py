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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

# Simple health check that always works
@app.route('/')
async def home():
    return jsonify({
        "status": "healthy", 
        "service": "SK4FiLM API",
        "message": "Server is running"
    })

@app.route('/health')
async def health():
    """Health check endpoint for Koyeb"""
    return jsonify({"status": "healthy", "service": "SK4FiLM API"})

@app.route('/api/health')
async def api_health():
    """API health check"""
    return jsonify({"status": "healthy", "service": "SK4FiLM API"})

# Telegram client (optional - will work even if Telegram fails)
User = None
try:
    if Config.USER_SESSION_STRING:
        User = Client(
            "user_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            session_string=Config.USER_SESSION_STRING
        )
        logger.info("User client initialized")
    else:
        logger.warning("USER_SESSION_STRING not provided - poster features disabled")
except Exception as e:
    logger.error(f"Failed to initialize Telegram client: {e}")
    User = None

async def web_search(query, limit=20):
    """Search movies - mock data if Telegram not available"""
    if not User:
        # Return mock data for testing
        return [
            {
                'type': 'text',
                'content': f'Mock result for: {query} - This is a test result. Telegram client not configured.',
                'date': '2024-01-01T00:00:00'
            }
        ]
    
    try:
        if not User.is_connected:
            await User.start()
    except Exception as e:
        logger.error(f"Telegram client error: {e}")
        return []
    
    results = []
    
    try:
        # Search text channels
        for channel_id in Config.TEXT_CHANNEL_IDS:
            try:
                async for msg in User.search_messages(channel_id, query=query, limit=5):
                    if msg.text:
                        results.append({
                            'type': 'text',
                            'content': msg.text[:500] + "..." if len(msg.text) > 500 else msg.text,
                            'date': msg.date.isoformat() if msg.date else None
                        })
            except Exception as e:
                logger.warning(f"Channel {channel_id} error: {e}")
        
        # Search poster channel
        try:
            async for msg in User.search_messages(Config.POSTER_CHANNEL_ID, query=query, limit=5):
                if msg.caption and msg.photo:
                    results.append({
                        'type': 'poster',
                        'content': msg.caption[:500] + "..." if len(msg.caption) > 500 else msg.caption,
                        'photo': msg.photo.file_id,
                        'date': msg.date.isoformat() if msg.date else None
                    })
        except Exception as e:
            logger.warning(f"Poster channel error: {e}")
            
    except Exception as e:
        logger.error(f"Search error: {e}")
    
    # If no results, return mock data
    if not results:
        results.append({
            'type': 'text',
            'content': f'No results found for: {query}. Try different keywords.',
            'date': '2024-01-01T00:00:00'
        })
    
    return results[:limit]

async def get_latest_posters(limit=8):
    """Get latest posters - mock data if Telegram not available"""
    if not User:
        # Return mock posters
        return [
            {
                'photo': 'mock_photo_1',
                'caption': 'Sample Movie 1 - Action Thriller',
                'search_query': 'Action Movie'
            },
            {
                'photo': 'mock_photo_2', 
                'caption': 'Sample Movie 2 - Romantic Comedy',
                'search_query': 'Comedy Movie'
            }
        ]
    
    try:
        if not User.is_connected:
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
    
    # If no posters, return mock data
    if not posters:
        posters = [
            {
                'photo': 'mock_photo_1',
                'caption': 'Latest Movie 1 - Now Available',
                'search_query': 'New Movie'
            },
            {
                'photo': 'mock_photo_2',
                'caption': 'Latest Movie 2 - Just Released', 
                'search_query': 'Latest Movie'
            }
        ]
    
    return posters[:limit]

# API Routes
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
            'status': 'success',  # Still return success but with empty results
            'query': query,
            'results': [],
            'count': 0,
            'message': 'Search service temporarily unavailable'
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
            'posters': [],
            'count': 0,
            'message': 'Posters service temporarily unavailable'
        })

@app.route('/api/get_poster')
async def api_get_poster():
    """Serve poster images"""
    file_id = request.args.get('file_id', '')
    
    # Return placeholder if no file_id or mock photo
    if not file_id or file_id.startswith('mock_'):
        # Return a placeholder image
        from quart import Response
        import base64
        
        # Simple red placeholder image
        placeholder_svg = '''
        <svg width="300" height="200" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#333"/>
            <text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="white" font-family="Arial">
                Poster Not Available
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
        # Return placeholder on error too
        return Response(
            '<svg width="300" height="200"><rect width="100%" height="100%" fill="#333"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="white">Error Loading</text></svg>',
            mimetype='image/svg+xml'
        )

async def start_server():
    """Start the server"""
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
    
    logger.info(f"Starting SK4FiLM API server on port {Config.WEB_SERVER_PORT}")
    await serve(app, config)

if __name__ == "__main__":
    # Test that basic server starts
    logger.info("SK4FiLM Backend Server Starting...")
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        # Even if there's an error, let's try to start a basic server
        import sys
        sys.exit(1)
