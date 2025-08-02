from typing import Tuple, List, Dict
from quart import Quart, render_template, request, jsonify
import logging
from configs import Config
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from main import format_result
import asyncio
from datetime import datetime
from collections import defaultdict
from search_utils import search_helper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

# Visitor tracking
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

async def web_search(query: str, limit: int = 50) -> Tuple[str, str, List[str]]:
    """Auto-correcting search that returns (original_query, corrected_query, results)"""
    from main import User  # Import here to avoid circular imports

    logger.info(f"Starting search for: {query}")
    
    if not User or not User.is_connected:
        try:
            logger.info("User client not connected, attempting to start...")
            if User:
                await User.start()
            else:
                logger.warning("User client not configured")
                return query, query, []
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            return query, query, []

    corpus = []
    for channel in Config.CHANNEL_IDS:
        try:
            logger.info(f"Searching in channel: {channel}")
            async for msg in User.search_messages(channel, query=query, limit=200):
                content = msg.text or msg.caption
                if content:
                    corpus.append(content)
        except Exception as e:
            logger.warning(f"Error building corpus from {channel}: {e}")
            continue

    logger.info(f"Built corpus with {len(corpus)} items")
    
    await search_helper.build_index(corpus)
    original_query, corrected_query, matches = await search_helper.advanced_search(query, corpus)
    formatted_results = [format_result(match['original_text']) for match in matches[:limit]]

    logger.info(f"Found {len(formatted_results)} results")
    return original_query, corrected_query, formatted_results

@app.before_request
async def track_visitor():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip:
        ip = ip.split(',')[0].strip()
        visitors[ip] = datetime.now().timestamp()

@app.route('/')
async def home():
    return await render_template('index.html', config=Config)

@app.route('/search')
async def search():
    query = request.args.get('query', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    if not query:
        return await render_template('index.html', config=Config)

    try:
        original_query, corrected_query, results = await web_search(query)
        show_correction = corrected_query.lower() != original_query.lower()

        paginator = Paginator(results, items_per_page=per_page)
        page_data = paginator.get_page(page)

        return await render_template(
            'results.html',
            query=original_query,
            corrected_query=corrected_query if show_correction else None,
            results=page_data['items'],
            total=len(results),
            pagination=page_data,
            config=Config,
            year=datetime.now().year,
            debug=True  # For debugging purposes
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
