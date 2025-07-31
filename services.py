import logging
from pyrogram import Client
from configs import config
from utils import process_links, format_result
from typing import List

logger = logging.getLogger(__name__)

async def web_search(query: str, limit: int = 50) -> List[str]:
    """Search for content in configured Telegram channels"""
    user_client = Client(
        "user_session",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        session_string=config.USER_SESSION_STRING
    ) if config.USER_SESSION_STRING else None
    
    if not user_client:
        logger.warning("User client not configured (no session string)")
        return []
    
    try:
        if not user_client.is_connected:
            await user_client.start()
    except Exception as e:
        logger.error(f"Failed to start user client: {e}")
        return []
    
    results = []
    for channel in config.CHANNEL_IDS:
        try:
            async for msg in user_client.search_messages(channel, query=query, limit=limit):
                content = msg.text or msg.caption
                if content:
                    processed_content = await process_links(content)
                    formatted_content = format_result(processed_content)
                    results.append(formatted_content)
        except Exception as e:
            logger.warning(f"Error searching channel {channel}: {e}")
            continue
    
    return results
