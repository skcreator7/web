from quart import Quart, render_template, request, jsonify
import logging
from configs import Config
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from main import web_search, format_result
import asyncio
import os
from collections import defaultdict
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = Config.SECRET_KEY

# Visitor tracking
visitors = defaultdict(int)
last_reset = datetime.now()

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

@app.before_serving
async def reset_visitor_count():
    global last_reset, visitors
    while True:
        now = datetime.now()
        if now - last_reset > timedelta(hours=1):
            visitors.clear()
            last_reset = now
        await asyncio.sleep(3600)  # Check every hour

@app.before_request
async def track_visitor():
    if request.remote_addr:
        visitors[request.remote_addr] = datetime.now().timestamp()

@app.route('/visitor_count')
async def get_visitor_count():
    # Clean up old visitors (last seen more than 30 minutes ago)
    cutoff = datetime.now().timestamp() - 1800
    active_visitors = {ip: ts for ip, ts in visitors.items() if ts > cutoff}
    visitors.clear()
    visitors.update(active_visitors)
    return jsonify({'count': len(visitors)})

@app.route('/health')
async def health_check():
    return jsonify({"status": "healthy"})

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
        results = await web_search(query)
        
        paginator = Paginator(results, items_per_page=per_page)
        page_data = paginator.get_page(page)
        
        return await render_template(
            'results.html',
            query=query,
            results=page_data['items'],
            total=len(results),
            pagination=page_data,
            config=Config
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        return await render_template('error.html', error=str(e), config=Config), 500

async def run_server():
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
    await serve(app, config)

if __name__ == "__main__":
    asyncio.run(run_server())
