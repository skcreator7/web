import re
import html
import aiohttp
import asyncio
from typing import List, Dict
from configs import app_config
import logging

logger = logging.getLogger(__name__)

async def bulk_shorten_urls(urls: List[str]) -> Dict[str, str]:
    """Process multiple URLs efficiently with caching and parallel requests"""
    results = {}
    
    # Process URLs in parallel
    tasks = [process_single_url(url) for url in urls]
    shortened_urls = await asyncio.gather(*tasks)
    
    return dict(zip(urls, shortened_urls))

async def process_single_url(url: str) -> str:
    """Process individual URL with caching and fallback logic"""
    if not url or any(p in url for p in ("t.me/", "wa.me/", "chat.whatsapp.com/")):
        return url
    
    # Ensure proper URL scheme
    if url.startswith('www.'):
        url = f'https://{url}'
    
    # Add caching layer here if needed
    # shortened = cache.get(url)
    # if shortened:
    #     return shortened
    
    # Try shortening services in order
    for shortener in [try_mdisk_shortener, try_shrtco_shortener]:
        try:
            shortened = await shortener(url)
            if shortened != url:
                # cache.set(url, shortened)  # Add to cache
                return shortened
        except Exception as e:
            logger.warning(f"Shortener failed: {str(e)}")
            continue
    
    return url

async def try_mdisk_shortener(url: str) -> str:
    """Try MDisk shortener with proper headers"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{app_config.SHORTENER_URL}/api",
                json={"url": url},
                headers={
                    "Authorization": f"Bearer {app_config.SHORTENER_API_KEY}",
                    "Content-Type": "application/json"
                },
                timeout=5
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("short_url", url)
                logger.debug(f"MDisk response: {resp.status}")
    except Exception as e:
        logger.warning(f"MDisk error: {str(e)}")
    return url

async def try_shrtco_shortener(url: str) -> str:
    """Fallback to free shrtco.de service"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.shrtco.de/v2/shorten?url={url}",
                timeout=5
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data.get('result', {}).get('short_link', url)
    except Exception as e:
        logger.warning(f"Shrtco error: {str(e)}")
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
    """Sanitize input while preserving URLs"""
    if not text:
        return ""
    
    text = text.strip()[:2000]  # Increased limit for bulk processing
    
    # Preserve URLs during escaping
    url_placeholders = {}
    for i, match in enumerate(re.finditer(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)):
        url = match.group()
        placeholder = f"__URL_{i}__"
        url_placeholders[placeholder] = url
        text = text.replace(url, placeholder)
    
    text = html.escape(text)
    
    # Restore URLs
    for placeholder, url in url_placeholders.items():
        text = text.replace(placeholder, url)
    
    return text

async def bulk_process_links(texts: List[str]) -> List[str]:
    """Process multiple text entries with bulk URL handling"""
    # Extract all unique URLs first
    all_urls = set()
    url_mapping = {}
    
    for text in texts:
        if not text:
            continue
        urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
        all_urls.update(urls)
    
    # Bulk shorten URLs
    shortened = await bulk_shorten_urls(list(all_urls))
    
    # Process all texts
    results = []
    for text in texts:
        if not text:
            results.append("")
            continue
        
        text = sanitize_input(text)
        text = replace_youtube_links(text)
        
        # Replace all URLs
        for original, short in shortened.items():
            text = text.replace(original, short)
        
        # Format final output
        text = re.sub(
            r'(?P<url>https?://[^\s<>"]+|www\.[^\s<>"]+)',
            r'<a href="\g<url>" target="_blank" class="result-link">\g<url></a>',
            text
        )
        
        text = re.sub(r'(?i)(title:|movie:|year:|rating:)', r'<strong>\1</strong>', text)
        results.append(text)
    
    return results
