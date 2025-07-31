from quart import Quart, render_template, request, jsonify
import logging
from configs import config
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from services import web_search
from utils import format_result, process_links
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from quart_rate_limiter import rate_limit, RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Quart(__name__)
app.secret_key = config.SECRET_KEY
rate_limiter = RateLimiter(app)

# Visitor tracking system
visitors = defaultdict(float)  # {ip: last_active_timestamp}

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
async def startup():
    """Initialize application resources"""
    logger.info("Application starting up...")

@app.before_request
async def track_visitor():
    """Track visitor activity"""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip:
        ip = ip.split(',')[0].strip()  # Handle proxy chains
        visitors[ip] = datetime.now().timestamp()

def get_active_visitors():
    """Count visitors active in last 30 minutes"""
    cutoff = datetime.now().timestamp() - 1800
    return {ip: ts for ip, ts in visitors.items() if ts > cutoff}

@app.route('/visitor_count')
async def visitor_count():
    """Endpoint for visitor count data"""
    active = get_active_visitors()
    visitors.clear()
    visitors.update(active)
    return jsonify({
        'count': len(active),
        'updated': datetime.now().isoformat(),
        'status': 'success'
    })

@app.route('/health')
async def health_check():
    return jsonify({
        "status": "healthy",
        "visitors": len(visitors),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/')
async def home():
    """Main page with visitor counter"""
    return await render_template('index.html', config=config)

@app.route('/search')
@rate_limit(config.RATE_LIMIT, timedelta(minutes=1))
async def search():
    query = request.args.get('query', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    if not query:
        return await render_template('index.html', config=config)
    
    try:
        results = await web_search(query)
        processed_results = []
        for result in results:
            processed_result = await process_links(result)
            processed_results.append(format_result(processed_result))
            
        paginator = Paginator(processed_results, items_per_page=per_page)
        page_data = paginator.get_page(page)
        
        return await render_template(
            'results.html',
            query=query,
            results=page_data['items'],
            total=len(results),
            pagination=page_data,
            config=config
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        return await render_template('error.html', error=str(e), config=config), 500

async def run_server():
    """Configure and run the server"""
    config = HyperConfig()
    config.bind = [f"0.0.0.0:{config.WEB_SERVER_PORT}"]
    config.startup_timeout = 30.0
    config.lifespan = "on"
    
    logger.info(f"Starting server on port {config.WEB_SERVER_PORT}")
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except Exception as e:
        logger.critical(f"Server failed: {e}")
        raise
