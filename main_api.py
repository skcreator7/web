# main_api.py (Koyeb - Telegram API Service)
import os
import logging
import asyncio
from typing import Dict, Any, List
from quart import Quart, request, jsonify, Response
from configs import Config
from search_utils import search_helper, safe_correct

# Telegram side - import from your existing main.py
from main import format_result, User

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sk4film-api")

api = Quart(__name__)

# Optional API token for bearer auth
API_TOKEN = os.environ.get("KOYEB_API_TOKEN")

def check_auth(req) -> bool:
    """Check Authorization header if token is set"""
    if not API_TOKEN:
        return True
    return req.headers.get("Authorization") == f"Bearer {API_TOKEN}"

@api.before_request
async def guard():
    """Guard all routes except health check"""
    if request.path.startswith("/api/health"):
        return
    if not check_auth(request):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

async def ensure_user():
    """Ensure Telegram User client is connected with retry logic"""
    if getattr(User, "is_connected", False):
        return
    for i in range(3):
        try:
            await User.start()
            logger.info("Telegram User client started successfully")
            return
        except Exception as e:
            logger.warning(f"User.start retry {i+1}/3: {e}")
            await asyncio.sleep(2 * (i + 1))
    raise RuntimeError("User client failed to start after 3 retries")

@api.get("/api/health")
async def health():
    """Health check endpoint for Koyeb probes"""
    return jsonify({"ok": True, "status": "healthy"})

@api.get("/api/posters/latest")
async def posters_latest():
    """Get latest posters from Telegram poster channel"""
    limit = int(request.args.get("limit") or 20)
    await ensure_user()
    res = []
    try:
        pc = getattr(Config, "POSTER_CHANNEL_ID", None)
        if not pc:
            return jsonify({"status": "error", "message": "POSTER_CHANNEL_ID not configured"}), 500
        
        async for msg in User.get_chat_history(pc, limit=limit):
            if getattr(msg, "photo", None) and msg.caption:
                res.append({
                    "photo": msg.photo.file_id,
                    "caption": msg.caption,
                    "date": msg.date.isoformat(),
                    "search_query": msg.caption.split("\n")[0] if msg.caption else "",
                    "chat_id": msg.chat.id,
                    "message_id": msg.id
                })
    except Exception as e:
        logger.error(f"posters_latest error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
    
    return jsonify({"status": "success", "items": res, "count": len(res)})

@api.get("/api/search")
async def api_search():
    """Search across text and poster channels"""
    q = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit") or 50)
    
    if not q:
        return jsonify({"status": "error", "message": "query parameter 'q' required"}), 400
    
    await ensure_user()
    results: List[Dict[str, Any]] = []
    corpus: List[str] = []
    
    # Search text channels
    text_channel_ids = getattr(Config, "TEXT_CHANNEL_IDS", [])
    for cid in text_channel_ids:
        try:
            async for msg in User.search_messages(cid, query=q, limit=200):
                if msg.text:
                    corpus.append(msg.text)
                    results.append({
                        "type": "text",
                        "content": format_result(msg.text),
                        "date": msg.date.isoformat(),
                        "chat_id": msg.chat.id,
                        "message_id": msg.id
                    })
        except Exception as e:
            logger.warning(f"text search channel {cid} error: {e}")
    
    # Search poster channel
    try:
        pc = getattr(Config, "POSTER_CHANNEL_ID", None)
        if pc:
            async for msg in User.search_messages(pc, query=q, limit=200):
                if msg.caption and getattr(msg, "photo", None):
                    corpus.append(msg.caption)
                    results.append({
                        "type": "poster",
                        "content": format_result(msg.caption),
                        "photo": msg.photo.file_id,
                        "date": msg.date.isoformat(),
                        "chat_id": msg.chat.id,
                        "message_id": msg.id
                    })
    except Exception as e:
        logger.warning(f"poster search error: {e}")
    
    # Sort by date descending
    results.sort(key=lambda x: x["date"], reverse=True)
    out = results[:limit]
    
    # Spell correction if no results
    corrected = None
    if not out and corpus:
        corrected = safe_correct(q, corpus)
    
    return jsonify({
        "status": "success",
        "items": out,
        "count": len(out),
        "corrected": corrected,
        "query": q
    })

@api.get("/api/get_poster")
async def api_get_poster():
    """Get poster image by chat_id+message_id or file_id (fresh reference)"""
    chat_id = request.args.get("chat_id", type=int)
    message_id = request.args.get("message_id", type=int)
    file_id = request.args.get("file_id")
    
    if not (chat_id and message_id) and not file_id:
        return jsonify({
            "status": "error",
            "message": "chat_id+message_id or file_id required"
        }), 400
    
    await ensure_user()
    
    try:
        # Preferred: refetch message for fresh file reference
        if chat_id and message_id:
            msg = await User.get_messages(chat_id, message_id)
            if not msg or not getattr(msg, "photo", None):
                return jsonify({"status": "error", "message": "no photo found"}), 404
            media = await User.download_media(msg, in_memory=True)
        else:
            # Legacy fallback: try direct file_id (may expire)
            try:
                media = await User.download_media(file_id, in_memory=True)
            except Exception as e:
                logger.warning(f"file_id download failed: {e}")
                return jsonify({
                    "status": "error",
                    "message": "expired file reference; use chat_id & message_id"
                }), 400
        
        return Response(media.getvalue(), mimetype="image/jpeg")
    
    except Exception as e:
        logger.error(f"get_poster error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@api.errorhandler(404)
async def not_found(e):
    return jsonify({"status": "error", "message": "endpoint not found"}), 404

@api.errorhandler(500)
async def server_error(e):
    return jsonify({"status": "error", "message": "internal server error"}), 500

if __name__ == "__main__":
    # Local test only; on Koyeb use Hypercorn:
    # hypercorn main_api:api --bind 0.0.0.0:8000 --workers 1
    port = int(os.environ.get("PORT", 8000))
    api.run(host="0.0.0.0", port=port, debug=False)
