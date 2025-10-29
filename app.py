from quart import Quart, render_template, request, jsonify
import logging
import os
import aiohttp
import asyncio
from datetime import datetime
from collections import defaultdict

# Configuration
class Config:
    BOT_SESSION_NAME = "SK4FiLM"
    WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "https://your-app.vercel.app/")
    KOYEB_BACKEND_URL = os.environ.get("KOYEB_BACKEND_URL", "https://your-bot-app.koyeb.app/")
    SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

visitors = defaultdict(float)

class Paginator:
    def __init__(self, items, items_per_page=10):
        self.items = items
        self.items_per_page = items_per_page
        self.total_items = len(items)
        self.total_pages = max(1, (self.total_items + items_per_page - 1) // items_per_page)

    def get_page(self, page_number):
        page_number = max(1, min(page_number, self.total_pages))
        start_index = (page_number - 1) * self.items_per_page
        end_index = min(start_index + self.items_per_page, self.total_items)
        
        return {
            'items': self.items[start_index:end_index],
            'current_page': page_number,
            'total_pages': self.total_pages,
            'has_prev': page_number > 1,
            'has_next': page_number < self.total_pages,
            'prev_page': page_number - 1,
            'next_page': page_number + 1
        }

async def fetch_from_backend(endpoint, params=None):
    """Fetch data from Koyeb backend"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{Config.KOYEB_BACKEND_URL}{endpoint}"
            async with session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception as e:
        logger.error(f"Backend fetch error: {e}")
        return None

async def search_movies(query):
    """Search movies from Koyeb backend"""
    return await fetch_from_backend("/api/search", {"query": query})

async def get_latest_posters():
    """Get latest posters from Koyeb backend"""
    return await fetch_from_backend("/api/latest_posters")

async def get_poster_url(file_id):
    """Get poster image URL"""
    return f"{Config.KOYEB_BACKEND_URL}/api/get_poster?file_id={file_id}"

@app.before_request
async def track_visitor():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip:
        ip = ip.split(',')[0].strip()
        visitors[ip] = datetime.now().timestamp()

@app.route('/')
async def home():
    posters_data = await get_latest_posters()
    posters = posters_data.get('posters', []) if posters_data else []
    
    # Add full poster URLs
    for poster in posters:
        if 'photo' in poster:
            poster['photo_url'] = await get_poster_url(poster['photo'])
    
    return await render_template('index.html', config=Config, posters=posters)

@app.route('/search')
async def search():
    query = request.args.get('query', '').strip()
    page = request.args.get('page', 1, type=int)
    
    if not query:
        return await home()
    
    try:
        # Search from Koyeb backend
        search_data = await search_movies(query)
        
        if search_data and 'results' in search_data:
            results = search_data['results']
            # Add poster URLs
            for result in results:
                if result.get('type') == 'poster' and 'photo' in result:
                    result['photo_url'] = await get_poster_url(result['photo'])
        else:
            results = []
        
        paginator = Paginator(results)
        page_data = paginator.get_page(page)
        
        return await render_template(
            'results.html',
            query=query,
            results=page_data['items'],
            total=len(results),
            pagination=page_data,
            config=Config,
            year=datetime.now().year,
            posters=await get_latest_posters() or []
        )
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return await render_template('error.html', error=str(e), config=Config, year=datetime.now().year)

@app.route('/visitor_count')
async def visitor_count():
    cutoff = datetime.now().timestamp() - 1800
    active = {ip: ts for ip, ts in visitors.items() if ts > cutoff}
    return jsonify({
        'count': len(active),
        'updated': datetime.now().isoformat()
    })

# Vercel handler
async def app_handler(scope, receive, send):
    await app(scope, receive, send)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
