import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, RPCError
import logging
from configs import config
from imdb import IMDb
from services import web_search
from utils import format_result, process_links

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ia = IMDb()

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
    config.BOT_SESSION_NAME,
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

User = Client(
    "user_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.USER_SESSION_STRING
) if config.USER_SESSION_STRING else None

async def delete_message(bot, message, delay=180):
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(message.chat.id, message.id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

async def schedule_deletion(bot, message, delay=180):
    asyncio.create_task(delete_message(bot, message, delay))

async def search_imdb(query):
    try:
        if query.isdigit():
            movie = ia.get_movie(query)
            return [{"title": movie["title"], "year": movie.get("year", ""), "id": movie.movieID}]
        movies = ia.search_movie(query, results=10)
        return [{
            "title": m["title"],
            "year": f" - {m.get('year', '')}",
            "id": m.movieID
        } for m in movies]
    except Exception as e:
        logger.error(f"IMDb search error: {e}")
        return []

async def web_search(query, limit=50):
    if not User or not User.is_connected:
        try:
            if User:
                await User.start()
            else:
                logger.warning("User client not configured (no session string)")
                return []
        except Exception as e:
            logger.error(f"Failed to start user client: {e}")
            return []
    
    results = []
    for channel in config.CHANNEL_IDS:
        try:
            async for msg in User.search_messages(channel, query=query, limit=limit):
                content = msg.text or msg.caption
                if content:
                    processed_content = await process_links(content)
                    formatted_content = format_result(processed_content)
                    results.append(formatted_content)
        except Exception as e:
            logger.warning(f"Error searching channel {channel}: {e}")
            continue
    
    return results

@Bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔸 Donate", url="https://example.com/donate")],
            [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{config.UPDATES_CHANNEL}")]
        ])
        
        msg = await message.reply_photo(
            photo="https://example.com/photo.jpg",
            caption=config.START_MSG.format(mention=message.from_user.mention),
            reply_markup=keyboard
        )
        await schedule_deletion(client, msg)
    except Exception as e:
        logger.error(f"Start handler error: {str(e)}")

@Bot.on_message(filters.private & ~filters.command("start"))
async def handle_search(client, message: Message):
    search_msg = await message.reply("🔍 Searching...")
    query = message.text.strip()
    
    try:
        results = await web_search(query)
        if results:
            text = f"<b>Results for '{query}':</b>\n\n{results[0]}"
            buttons = [[InlineKeyboardButton("More Results", callback_data=f"more_{query}")]]
            await search_msg.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=False
            )
        else:
            await show_imdb_suggestions(search_msg, query)
    except Exception as e:
        logger.error(f"Search error: {e}")
        await search_msg.edit_text("⚠️ An error occurred. Please try again later.")
        await schedule_deletion(client, search_msg)

async def show_imdb_suggestions(message, query):
    suggestions = await search_imdb(query)
    if suggestions:
        buttons = [
            [InlineKeyboardButton(
                f"{movie['title']} {movie.get('year', '')}",
                callback_data=f"imdb_{movie['id']}"
            )] for movie in suggestions
        ]
        await message.edit_text(
            "Select a movie:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await message.edit_text("❌ No results found. Try different keywords.")

@Bot.on_callback_query(filters.regex(r"^more_(.+)"))
async def show_more_results(client, callback: CallbackQuery):
    query = callback.matches[0].group(1)
    await callback.answer()
    
    try:
        results = await web_search(query)
        if results:
            await callback.message.edit_text(
                f"<b>More results for '{query}':</b>\n\n{results[0]}",
                disable_web_page_preview=False
            )
    except Exception as e:
        logger.error(f"More results error: {e}")
        await callback.message.edit_text("⚠️ Error loading more results")

@Bot.on_callback_query(filters.regex(r"^imdb_(\d+)"))
async def handle_imdb_selection(client, callback: CallbackQuery):
    movie_id = callback.matches[0].group(1)
    await callback.answer()
    
    try:
        movie = ia.get_movie(movie_id)
        text = f"🎬 <b>{movie['title']}</b> ({movie.get('year', 'N/A')})\n⭐ <b>Rating:</b> {movie.get('rating', 'N/A')}"
        await callback.message.edit_text(text)
    except Exception as e:
        logger.error(f"IMDb error: {e}")
        await callback.message.edit_text("⚠️ Error loading movie details")

async def run_all():
    # Start web server in background
    from app import run_server
    asyncio.create_task(run_server())
    
    # Start Telegram bot
    try:
        if await Bot.start():
            if User:
                await User.start()
            logger.info("All services started successfully")
            await asyncio.Event().wait()  # Run forever
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
