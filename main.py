import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, RPCError
import logging
from configs import Config
import html
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    for channel in Config.CHANNEL_IDS:
        try:
            async for msg in User.search_messages(channel, query=query, limit=limit):
                content = msg.text or msg.caption
                if content:
                    results.append(format_result(content))
        except Exception as e:
            logger.warning(f"Error searching channel {channel}: {e}")
            continue
    
    return results

@Bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message: Message):
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔸 Donate", url="https://example.com/donate")],
            [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{Config.UPDATES_CHANNEL}")]
        ])
        
        msg = await message.reply_photo(
            photo="https://example.com/photo.jpg",
            caption=Config.START_MSG.format(mention=message.from_user.mention),
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Start handler error: {str(e)}")

@Bot.on_message(filters.private & ~filters.command("start"))
async def handle_search(client, message: Message):
    search_msg = await message.reply("🔍 Cleaning and searching...")
    original_query = message.text.strip()
    
    try:
        results = await web_search(original_query)
        if results:
            text = f"<b>Results for '{original_query}':</b>\n\n{results[0]}"
            buttons = [[InlineKeyboardButton("More Results", callback_data=f"more_{original_query}")]]
            await search_msg.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=False
            )
        else:
            await search_msg.edit_text("❌ No results found after cleaning common terms. Try different keywords.")
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
            await callback.message.edit_text(
                f"<b>More results for '{query}':</b>\n\n{results[0]}",
                disable_web_page_preview=False
            )
    except Exception as e:
        logger.error(f"More results error: {e}")
        await callback.message.edit_text("⚠️ Error loading more results")

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
