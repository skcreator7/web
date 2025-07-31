import re
from typing import Optional
import aiohttp
import html
from configs import Config
import logging

logger = logging.getLogger(__name__)

async def shorten_url(url: str) -> Optional[str]:
    """Shorten URL using your shortener API"""
    if not url or any(p in url for p in ("t.me/", "wa.me/", "chat.whatsapp.com/")):
        return url
        
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://mdiskshortner.link",
                json={"url": url},
                headers={"Authorization": f"Bearer {Config.SHORTENER_API_KEY}"},
                timeout=5
            ) as resp:
                data = await resp.json()
                return data.get("short_url", url)
    except Exception as e:
        logger.warning(f"URL shortening failed: {e}")
        return url

def replace_youtube_links(text: str) -> str:
    """Replace specific YouTube links"""
    replacements = {
        "https://youtu.be/fVL7DfhnwWM": "https://youtu.be/z69laOmRDBo",
        "https://www.youtube.com/watch?v=fVL7DfhnwWM": "https://www.youtube.com/watch?v=z69laOmRDBo",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return text

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent XSS and other attacks"""
    if not text:
        return ""
    text = text.strip()[:500]  # Limit to 500 characters
    return html.escape(text)

def format_result(text: str) -> str:
    """Format the result text to make it more readable"""
    if not text:
        return ""
    
    text = sanitize_input(text)
    text = replace_youtube_links(text)
    text = re.sub(r'(?i)(title:|movie:|year:|rating:)', r'<b>\1</b>', text)
    return text

async def process_links(text: str) -> str:
    """Process all links in text (replace YouTube and shorten others)"""
    if not text:
        return ""
    
    # Find all URLs
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    
    for url in set(urls):  # Process unique URLs only
        processed_url = replace_youtube_links(url)
        if processed_url == url:  # Only shorten if not a replaced YouTube link
            processed_url = await shorten_url(processed_url)
        text = text.replace(url, processed_url)
    
    return text
