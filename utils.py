import re
import html
import aiohttp
import asyncio
from typing import Optional
from configs import app_config
import logging

logger = logging.getLogger(__name__)

async def shorten_url(url: str) -> str:
    """Smart URL shortener with multiple fallback options"""
    if not url or any(p in url for p in ("t.me/", "wa.me/", "chat.whatsapp.com/")):
        return url

    # Try primary shortener first
    result = await _try_mdisk_shortener(url)
    if result != url:
        return result

    # Fallback to alternative services
    for shortener in [_try_shortio, _try_shrtco]:
        result = await shortener(url)
        if result != url:
            return result

    return url

async def _try_mdisk_shortener(url: str) -> str:
    """Primary shortening service"""
    try:
        headers = {
            "Authorization": f"Bearer {app_config.SHORTENER_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "SK4FilmBot/1.0"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{app_config.SHORTENER_URL}/api",
                json={"url": url, "api_key": app_config.SHORTENER_API_KEY},
                headers=headers,
                timeout=5
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("shortenedUrl") or data.get("short_url") or url
                logger.warning(f"MDisk shortener failed: {resp.status}")
    except Exception as e:
        logger.warning(f"MDisk error: {str(e)}")
    return url

async def _try_shortio(url: str) -> str:
    """Fallback shortener 1: short.io"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.short.io/links",
                json={"originalURL": url},
                headers={
                    "Authorization": app_config.SHORTENER_API_KEY,
                    "Content-Type": "application/json"
                },
                timeout=5
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("shortURL", url)
    except Exception:
        pass
    return url

async def _try_shrtco(url: str) -> str:
    """Fallback shortener 2: shrtco.de (no API key needed)"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.shrtco.de/v2/shorten?url={url}",
                timeout=5
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data.get('result', {}).get('short_link', url)
    except Exception:
        pass
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
    """Sanitize user input while preserving URLs"""
    if not text:
        return ""
    
    text = text.strip()[:500]  # Limit to 500 characters
    
    # Preserve URLs during escaping
    url_placeholders = {}
    for i, match in enumerate(re.finditer(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)):
        url = match.group()
        placeholder = f"__URL_{i}__"
        url_placeholders[placeholder] = url
        text = text.replace(url, placeholder)
    
    # HTML escape the entire text
    text = html.escape(text)
    
    # Restore URLs (unescaped)
    for placeholder, url in url_placeholders.items():
        text = text.replace(placeholder, url)
    
    return text

def format_result(text: str) -> str:
    """Format text with clickable links and preserved formatting"""
    if not text:
        return ""
    
    text = sanitize_input(text)
    text = replace_youtube_links(text)
    
    # Make URLs clickable
    text = re.sub(
        r'(?P<url>https?://[^\s<>"]+|www\.[^\s<>"]+)',
        r'<a href="\g<url>" target="_blank" rel="noopener" class="result-link">\g<url></a>',
        text
    )
    
    # Highlight metadata tags
    text = re.sub(r'(?i)(title:|movie:|year:|rating:)', r'<strong>\1</strong>', text)
    
    return text

async def process_links(text: str) -> str:
    """Process all links in text with improved handling"""
    if not text:
        return ""
    
    # Find all unique URLs
    urls = set(re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text))
    
    for url in urls:
        processed_url = replace_youtube_links(url)
        
        # Ensure proper URL scheme
        if processed_url.startswith('www.'):
            processed_url = f'https://{processed_url}'
            
        if processed_url == url:  # Only shorten non-YouTube links
            processed_url = await shorten_url(processed_url)
        
        text = text.replace(url, processed_url)
    
    return text
