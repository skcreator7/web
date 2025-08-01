import re
import html
import aiohttp
from typing import Optional
from configs import app_config
import logging

logger = logging.getLogger(__name__)

async def shorten_url(url: str) -> Optional[str]:
    """Shorten URL using mdiskshortner.link API with improved error handling"""
    if not url or any(p in url for p in ("t.me/", "wa.me/", "chat.whatsapp.com/")):
        return url
        
    try:
        headers = {
            "Authorization": f"Bearer {app_config.SHORTENER_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{app_config.SHORTENER_URL}/api",
                json={"url": url},
                headers=headers,
                timeout=10
            ) as resp:
                # Check content type first
                if 'application/json' not in resp.headers.get('Content-Type', ''):
                    error_text = await resp.text()
                    logger.warning(f"Unexpected response: {error_text}")
                    return url
                
                data = await resp.json()
                if resp.status == 200:
                    return data.get("short_url", url)
                logger.warning(f"URL shortening failed with status {resp.status}: {data}")
                return url
    except asyncio.TimeoutError:
        logger.warning("URL shortening timeout")
        return url
    except Exception as e:
        logger.warning(f"URL shortening error: {e}")
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
    """Sanitize user input to prevent XSS while preserving links"""
    if not text:
        return ""
    
    text = text.strip()[:500]  # Limit to 500 characters
    
    # First preserve URLs before escaping
    url_pattern = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')
    urls = {match.group(): f"__URL_PLACEHOLDER_{i}__" for i, match in enumerate(url_pattern.finditer(text))}
    
    # Replace URLs with placeholders
    for original, placeholder in urls.items():
        text = text.replace(original, placeholder)
    
    # HTML escape the entire text
    text = html.escape(text)
    
    # Restore the original URLs (unescaped)
    for original, placeholder in urls.items():
        text = text.replace(placeholder, original)
    
    return text

def format_result(text: str) -> str:
    """Format the result text to make URLs clickable and preserve formatting"""
    if not text:
        return ""
    
    text = sanitize_input(text)
    text = replace_youtube_links(text)
    
    # Make URLs clickable (handles both http and www links)
    text = re.sub(
        r'(?P<url>https?://[^\s<>"]+|www\.[^\s<>"]+)',
        r'<a href="\g<url>" target="_blank" rel="noopener noreferrer" class="result-link">\g<url></a>',
        text
    )
    
    # Highlight metadata tags
    text = re.sub(r'(?i)(title:|movie:|year:|rating:)', r'<span class="meta-tag">\1</span>', text)
    
    return text

async def process_links(text: str) -> str:
    """Process all links in text (replace YouTube and shorten others)"""
    if not text:
        return ""
    
    # Find all URLs
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
    urls = {match.group() for match in url_pattern.finditer(text)}
    
    for url in urls:
        processed_url = replace_youtube_links(url)
        
        # Ensure URLs have proper scheme
        if processed_url.startswith('www.'):
            processed_url = f'https://{processed_url}'
            
        if processed_url == url:  # Only shorten if not a replaced YouTube link
            processed_url = await shorten_url(processed_url)
        
        text = text.replace(url, processed_url)
    
    return text
