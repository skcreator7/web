from quart import Quart, render_template, request, jsonify, Response
import logging
from configs import Config
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from main import format_result, User
import asyncio
from datetime import datetime
from collections import defaultdict
from search_utils import search_helper, safe_correct

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

visitors = defaultdict(float)

class Paginator:
    def __init__(self, items, items_per_page=10, window_size=5):
        self.items = items
        self.items_per_page = items_per_page
        self.window_size = window_size
        self.total_items = len(items)
        self.total_pages = max(1, (self.total_items + items_per_page - 1) // items_per_page)

    def get_page(self, page_number):
        page_number = max(1, min(page_number, self.total_pages))
        start_index = (page_number - 1) * self.items_per_page
        end_index = min(start_index + self.items_per_page, self.total_items)

        half_window = self.window_size // 2
        start_page = max(1, page_number - half_window)
        end_page = min(self.total_pages, start_page + self.window_size - 1)

        if end_page - start_page + 1 < self.window_size:
            if page_number <= half_window:
                end_page = min(self.window_size, self.total_pages)
            else:
                start_page = max(1, end_page - self.window_size + 1)

        page_numbers = list(range(start_page, end_page + 1))

        return {
            'items': self.items[start_index:end_index],
            'current_page': page_number,
            'total_pages': self.total_pages,
            'has_prev': page_number > 1,
            'has_next': page_number < self.total_pages,
            'prev_page': page_number - 1 if page_number > 1 else None,
            'next_page': page_number + 1 if page_number < self.total_pages else None,
            'page_numbers': page_numbers,
            'first_page': 1,
            'last_page': self.total_pages,
            'start_index': start_index + 1,
            'end_index': end_index,
            'items_per_page': self.items_per_page
        }

async def web_search(query: str, limit: int = 50) -> tuple:
    """Search across both text and poster channels"""
    if not User or not User.is_connected:
        try:
            if User:
                await User.start()
            else:
                logger.warning("User client not configured")
                return [], []
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            return [], []

    results = []
    corpus = []
    
    # Search in text channels
    for channel_id in Config.TEXT_CHANNEL_IDS:
        try:
            async for msg in User.search_messages(channel_id, query=query, limit=200):
                if msg.text:
                    corpus.append(msg.text)
                    results.append({
                        'type': 'text',
                        'content': format_result(msg.text),
                        'date': msg.date
                    })
        except Exception as e:
            logger.warning(f"Error searching text channel {channel_id}: {e}")
    
    # Search in poster channel
    try:
        async for msg in User.search_messages(Config.POSTER_CHANNEL_ID, query=query, limit=200):
            if msg.caption and msg.photo:
                corpus.append(msg.caption)
                results.append({
                    'type': 'poster',
                    'content': format_result(msg.caption),
                    'photo': msg.photo.file_id,
                    'date': msg.date
                })
    except Exception as e:
        logger.warning(f"Error searching poster channel: {e}")
    
    # Sort by date (newest first)
    results.sort(key=lambda x: x['date'], reverse=True)
    
    return results[:limit], corpus

async def get_latest_posters(limit=10):
    """Get latest posters from poster channel"""
    if not User or not User.is_connected:
        try:
            if User:
                await User.start()
            else:
                logger.warning("User client not configured")
                return []
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            return []

    posters = []
    try:
        async for msg in User.get_chat_history(Config.POSTER_CHANNEL_ID, limit=limit):
            if msg.photo and msg.caption:
                posters.append({
                    'photo': msg.photo.file_id,
                    'caption': msg.caption,
                    'date': msg.date,
                    'search_query': msg.caption.split('\n')[0]  # First line as search query
                })
    except Exception as e:
        logger.error(f"Error getting posters: {e}")
    
    return posters

@app.route('/get_poster')
async def get_poster():
    """Endpoint to serve poster images"""
    file_id = request.args.get('file_id')
    if not file_id:
        return jsonify({'status': 'error', 'message': 'No file_id provided'}), 400
    
    try:
        if not User or not User.is_connected:
            await User.start()
        
        file = await User.download_media(file_id, in_memory=True)
        return Response(file.getvalue(), mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error getting poster: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.before_request
async def track_visitor():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip:
        ip = ip.split(',')[0].strip()
        visitors[ip] = datetime.now().timestamp()

@app.route('/')
async def home():
    posters = await get_latest_posters()
    return await render_template('index.html', config=Config, posters=posters)

@app.route('/search')
async def search():
    query = request.args.get('query', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    if not query:
        posters = await get_latest_posters()
        return await render_template('index.html', config=Config, posters=posters)

    try:
        results, corpus = await web_search(query)
        posters = await get_latest_posters()

        corrected_query = None
        if not results:
            corrected_query = safe_correct(query, corpus)
            if corrected_query and corrected_query != query.lower():
                logger.info(f"Trying corrected query: {corrected_query}")
                results, _ = await web_search(corrected_query)

        paginator = Paginator(results, items_per_page=per_page)
        page_data = paginator.get_page(page)

        return await render_template(
            'results.html',
            query=query,
            corrected_query=corrected_query if corrected_query != query.lower() else None,
            results=page_data['items'],
            total=len(results),
            pagination=page_data,
            config=Config,
            year=datetime.now().year,
            posters=posters
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        return await render_template('error.html', error=str(e), config=Config, year=datetime.now().year), 500

@app.route('/visitor_count')
async def visitor_count():
    cutoff = datetime.now().timestamp() - 1800
    active = {ip: ts for ip, ts in visitors.items() if ts > cutoff}
    visitors.clear()
    visitors.update(active)
    return jsonify({
        'count': len(active),
        'updated': datetime.now().isoformat(),
        'status': 'success'
    })

async def run_server():
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
    config.startup_timeout = 30.0
    config.lifespan = "on"

    logger.info(f"Starting server on port {Config.WEB_SERVER_PORT}")
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except Exception as e:
        logger.critical(f"Server failed: {e}")
        raise
