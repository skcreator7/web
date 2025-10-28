# main_api.py (Koyeb)
import os
import logging
import asyncio
from typing import Dict, Any, List
from quart import Quart, request, jsonify, Response
from configs import Config
from search_utils import search_helper, safe_correct

# Telegram side
from main import format_result, User  # your existing Pyrogram setup in main.py

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sk4film-api")

api = Quart(__name__)

API_TOKEN = os.environ.get("KOYEB_API_TOKEN")

def check_auth(req) -> bool:
    if not API_TOKEN:
        return True
    return req.headers.get("Authorization") == f"Bearer {API_TOKEN}"

@api.before_request
async def guard():
    if request.path.startswith("/api/health"):
        return
    if not check_auth(request):
        return jsonify({"status": "error", "message": "unauthorized"}), 401

async def ensure_user():
    if getattr(User, "is_connected", False):
        return
    for i in range(3):
        try:
            await User.start()
            return
        except Exception as e:
            logger.warning(f"User.start retry {i+1}: {e}")
            await asyncio.sleep(2 * (i + 1))
    raise RuntimeError("User client failed to start after retries")

@api.get("/api/health")
async def health():
    return jsonify({"ok": True})

@api.get("/api/posters/latest")
async def posters_latest():
    limit = int(request.args.get("limit") or 20)
    await ensure_user()
    res = []
    try:
        pc = getattr(Config, "POSTER_CHANNEL_ID", None)
        if pc:
            async for msg in User.get_chat_history(pc, limit=limit):
                if getattr(msg, "photo", None) and msg.caption:
                    res.append({
                        "photo": msg.photo.file_id,
                        "caption": msg.caption,
                        "date": msg.date.isoformat(),
                        "search_query": msg.caption.split("\n")[0],
                        "chat_id": msg.chat.id,
                        "message_id": msg.id
                    })
    except Exception as e:
        logger.error(f"posters_latest: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success", "items": res})

@api.get("/api/search")
async def api_search():
    q = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit") or 50)
    if not q:
        return jsonify({"status": "error", "message": "q required"}), 400
    await ensure_user()
    results: List[Dict[str, Any]] = []
    corpus: List[str] = []
    # text channels
    for cid in getattr(Config, "TEXT_CHANNEL_IDS", []):
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
            logger.warning(f"text search {cid}: {e}")
    # poster channel
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
        logger.warning(f"poster search: {e}")
    # sort desc by date
    results.sort(key=lambda x: x["date"], reverse=True)
    out = results[:limit]
    corrected = None
    if not out:
        corrected = safe_correct(q, corpus)
    return jsonify({"status": "success", "items": out, "corrected": corrected})

@api.get("/api/get_poster")
async def api_get_poster():
    chat_id = request.args.get("chat_id", type=int)
    message_id = request.args.get("message_id", type=int)
    file_id = request.args.get("file_id")
    if not (chat_id and message_id) and not file_id:
        return jsonify({"status":"error","message":"chat_id+message_id or file_id required"}), 400
    await ensure_user()
    try:
        if chat_id and message_id:
            msg = await User.get_messages(chat_id, message_id)
            media = await User.download_media(msg, in_memory=True)
        else:
            try:
                media = await User.download_media(file_id, in_memory=True)
            except Exception:
                return jsonify({"status":"error","message":"expired reference; pass chat_id & message_id"}), 400
        return Response(media.getvalue(), mimetype="image/jpeg")
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

if __name__ == "__main__":
    # Local test only; on Koyeb set entrypoint to Hypercorn:
    # hypercorn main_api:api --bind 0.0.0.0:8000 --workers 1
    api.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
