import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, RPCError
import logging
from configs import Config
import html
import re
from quart import Quart, jsonify, request
from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Quart app for API
api_app = Quart(__name__)
api_app.secret_key = Config.SECRET_KEY

class MovieBot(Client):
    async def start(self):
        retries = 0
        max_retries = 5
        while retries < max_retries:
            try:
                await super().start()
                logger.info("Bot started successfully")
                return True
            except FloodWait as e:
                wait_time = e.value + 5
                logger.warning(f"FloodWait: Waiting {wait_time} seconds")
                await asyncio.sleep(wait_time)
                retries += 1
            except Exception as e:
                logger.error(f"Start error: {str(e)}")
                await asyncio.sleep(5)
                retries += 1
        return False

Bot = MovieBot(
    Config.BOT_SESSION_NAME,
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

User = Client(
    "user_session",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    session_string=Config.USER_SESSION_STRING
) if Config.USER_SESSION_STRING else None

def format_result(text):
    """Format the result text"""
    if not text:
        return ""
    text = html.escape(text)
    text = re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank">\1</a>', text)
    return text

async def web_search(query, limit=50):
    """Search across both text and poster channels"""
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
    
    results = []
    
    # Search in text channels
    for channel_id in Config.TEXT_CHANNEL_IDS:
        try:
            async for msg in User.search_messages(channel_id, query=query, limit=limit):
                if msg.text:
                    results.append({
                        'type': 'text',
                        'content': format_result(msg.text),
                        'date': msg.date.timestamp() if msg.date else None
                    })
        except Exception as e:
            logger.warning(f"Error searching text channel {channel_id}: {e}")
    
    # Search in poster channel
    try:
        async for msg in User.search_messages(Config.POSTER_CHANNEL_ID, query=query, limit=limit):
            if msg.caption and msg.photo:
                results.append({
                    'type': 'poster',
                    'content': format_result(msg.caption),
                    'photo': msg.photo.file_id,
                    'date': msg.date.timestamp() if msg.date else None
                })
    except Exception as e:
        logger.warning(f"Error searching poster channel: {e}")
    
    # Sort by date (newest first)
    results.sort(key=lambda x: x.get('date', 0), reverse=True)
    
    return results[:limit]

async def get_latest_posters(limit=20):
    """Get latest posters from poster channel"""
    if not User or not User.is_connected:
        try:
            if User:
                await User.start()
            else:
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
                    'date': msg.date.timestamp() if msg.date else None,
                    'search_query': msg.caption.split('\n')[0] if msg.caption else "Movie"
                })
    except Exception as e:
        logger.error(f"Error getting posters: {e}")
    
    return posters

# API Routes
@api_app.route('/api/search')
async def api_search():
    """API endpoint for movie search"""
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
        return jsonify({'error': str(e)}), 500

@api_app.route('/api/latest_posters')
async def api_latest_posters():
    """API endpoint for latest posters"""
    try:
        posters = await get_latest_posters()
        return jsonify({
            'status': 'success',
            'posters': posters,
            'count': len(posters)
        })
    except Exception as e:
        logger.error(f"API posters error: {e}")
        return jsonify({'error': str(e)}), 500

@api_app.route('/api/get_poster')
async def api_get_poster():
    """API endpoint to serve poster images"""
    file_id = request.args.get('file_id')
    if not file_id:
        return jsonify({'error': 'No file_id provided'}), 400
    
    try:
        if not User or not User.is_connected:
            await User.start()
        
        file = await User.download_media(file_id, in_memory=True)
        from quart import Response
        return Response(file.getvalue(), mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error getting poster: {e}")
        return jsonify({'error': str(e)}), 500

@api_app.route('/api/health')
async def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'SK4FiLM Backend',
        'timestamp': asyncio.get_event_loop().time()
    })

# Telegram Bot Handlers (Original functionality)
@Bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔸 Donate", url="https://example.com/donate")],
            [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{Config.UPDATES_CHANNEL}")]
        ])
        
        await message.reply_photo(
            photo="https://example.com/photo.jpg",
            caption=Config.START_MSG.format(mention=message.from_user.mention),
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Start handler error: {str(e)}")

@Bot.on_message(filters.private & ~filters.command("start"))
async def handle_search(client, message: Message):
    search_msg = await message.reply("🔍 Searching in all channels...")
    original_query = message.text.strip()
    
    try:
        results = await web_search(original_query)
        if results:
            first_result = results[0]
            if first_result['type'] == 'poster':
                text = f"<b>🎬 Poster Result:</b>\n\n{first_result['content']}"
                buttons = [[InlineKeyboardButton("More Results", callback_data=f"more_{original_query}")]]
                await search_msg.delete()
                await message.reply_photo(
                    photo=first_result['photo'],
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                text = f"<b>Results for '{original_query}':</b>\n\n{first_result['content']}"
                buttons = [[InlineKeyboardButton("More Results", callback_data=f"more_{original_query}")]]
                await search_msg.edit_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=False
                )
        else:
            await search_msg.edit_text("❌ No results found. Try different keywords.")
    except Exception as e:
        logger.error(f"Search error: {e}")
        await search_msg.edit_text("⚠️ An error occurred. Please try again later.")

@Bot.on_callback_query(filters.regex(r"^more_(.+)"))
async def show_more_results(client, callback: CallbackQuery):
    query = callback.matches[0].group(1)
    await callback.answer()
    
    try:
        results = await web_search(query)
        if results:
            formatted_results = []
            for result in results:
                if result['type'] == 'poster':
                    formatted_results.append(f"🎬 <b>Poster:</b>\n{result['content']}")
                else:
                    formatted_results.append(result['content'])
            
            await callback.message.edit_text(
                f"<b>All results for '{query}':</b>\n\n" + "\n\n".join(formatted_results),
                disable_web_page_preview=False
            )
    except Exception as e:
        logger.error(f"More results error: {e}")
        await callback.message.edit_text("⚠️ Error loading more results")

async def run_all():
    """Start both Telegram bot and API server"""
    # Start API server
    api_config = HyperConfig()
    api_config.bind = [f"0.0.0.0:{Config.WEB_SERVER_PORT}"]
    api_task = asyncio.create_task(serve(api_app, api_config))
    
    # Start Telegram bot
    try:
        if await Bot.start():
            if User:
                await User.start()
            logger.info("All services started successfully")
            
            # Wait for both tasks
            await asyncio.gather(api_task)
    except Exception as e:
        logger.error(f"Failed to start services: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
