# app.py (Vercel web)
from quart import Quart, render_template, request, jsonify, redirect, url_for
import os, logging
import httpx
from datetime import datetime
from collections import defaultdict
from configs import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sk4film-web")

app = Quart(__name__, template_folder="templates")
app.secret_key = Config.SECRET_KEY

KOYEB_API_BASE = os.environ.get("KOYEB_API_BASE")  # e.g., https://sk4film.koyeb.app
KOYEB_API_TOKEN = os.environ.get("KOYEB_API_TOKEN")
POSTER_BASE_URL = os.environ.get("POSTER_BASE_URL") or KOYEB_API_BASE

visitors = defaultdict(float)

def _headers():
    h = {}
    if KOYEB_API_TOKEN:
        h["Authorization"] = f"Bearer {KOYEB_API_TOKEN}"
    return h

@app.before_request
async def track_visitor():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip:
        visitors[ip.split(",")[0].strip()] = datetime.now().timestamp()

@app.get("/")
async def home():
    items = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{KOYEB_API_BASE}/api/posters/latest?limit=20", headers=_headers())
            data = r.json()
            if data.get("status") == "success":
                items = data.get("items", [])
    except Exception as e:
        logger.warning(f"home posters fetch error: {e}")
    return await render_template("index.html", config=Config, posters=items)

@app.get("/search")
async def search():
    q = (request.args.get("query") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    if not q:
        return redirect(url_for("home"))
    results = []
    corrected = None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{KOYEB_API_BASE}/api/search", params={"q": q, "limit": 100}, headers=_headers())
            data = r.json()
            if data.get("status") == "success":
                results = data.get("items", [])
                corrected = data.get("corrected")
    except Exception as e:
        logger.error(f"search error: {e}")
        return await render_template("error.html", error=str(e), config=Config, year=datetime.now().year), 500

    total = len(results)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start, end = (page - 1) * per_page, min(page * per_page, total)
    page_items = results[start:end]
    pagination = {
        "items_per_page": per_page,
        "current_page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < total_pages else None,
        "page_numbers": list(range(max(1, page - 2), min(total_pages, page + 2) + 1)),
        "start_index": start + 1,
        "end_index": end
    }

    posters = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{KOYEB_API_BASE}/api/posters/latest?limit=12", headers=_headers())
            data = r.json()
            if data.get("status") == "success":
                posters = data.get("items", [])
    except Exception as e:
        logger.warning(f"posters sidebar error: {e}")

    return await render_template(
        "results.html",
        query=q,
        corrected_query=corrected if corrected and corrected != q.lower() else None,
        results=page_items,
        total=total,
        pagination=pagination,
        config=Config,
        year=datetime.now().year,
        posters=posters
    )

@app.get("/get_poster")
async def get_poster():
    chat_id = request.args.get("chat_id")
    message_id = request.args.get("message_id")
    file_id = request.args.get("file_id")
    if chat_id and message_id:
        return redirect(f"{POSTER_BASE_URL}/api/get_poster?chat_id={chat_id}&message_id={message_id}")
    if file_id:
        # legacy fallback; may expire
        return redirect(f"{POSTER_BASE_URL}/api/get_poster?file_id={file_id}")
    return jsonify({"status": "error", "message": "chat_id+message_id or file_id required"}), 400

@app.get("/visitor_count")
async def visitor_count():
    cutoff = datetime.now().timestamp() - 1800
    active = {ip: ts for ip, ts in visitors.items() if ts > cutoff}
    visitors.clear(); visitors.update(active)
    return jsonify({"count": len(active), "updated": datetime.now().isoformat(), "status": "success"})

@app.errorhandler(404)
async def not_found(e):
    return await render_template("error.html", error="Not Found", config=Config, year=datetime.now().year), 404

@app.errorhandler(500)
async def server_error(e):
    return await render_template("error.html", error=str(e), config=Config, year=datetime.now().year), 500

if __name__ == "__main__":
    app.run()
