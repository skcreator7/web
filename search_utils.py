import re
from typing import List, Dict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SearchHelper:
    def __init__(self):
        self.ignore_words = {
            'movie', 'film', 'hd', 'full', 'part', 'scene', 'trailer',
            'download', 'watch', 'free', 'online', 'stream', 'bluray',
            'torrent', 'subtitle', 'print', 'quality', 'version', 'rip',
            'dvd', 'web', 'brrip', 'yts', 'x264', 'x265', '1080p', '720p',
            '480p', '4k', 'uhd', 'hindi', 'english', 'dual', 'audio'
        }

    def _clean_query(self, query: str) -> str:
        """Remove common movie-related words from query"""
        # Extract year if present
        year_match = re.search(r'(19|20)\d{2}', query)
        year = year_match.group() if year_match else ""
        
        # Split and clean words
        words = re.findall(r'\b[a-z0-9]{2,}\b', query.lower())
        cleaned_words = [word for word in words if word not in self.ignore_words]
        
        # Reconstruct query
        cleaned_query = ' '.join(cleaned_words)
        if year:
            cleaned_query = f"{cleaned_query} {year}" if cleaned_query else year
        
        return cleaned_query.strip()

    async def advanced_search(self, query: str, corpus: List[str]) -> List[Dict]:
        """Perform cleaned search"""
        cleaned_query = self._clean_query(query)
        if not cleaned_query:
            return []

        results = []
        for text in corpus:
            text_lower = text.lower()
            if cleaned_query in text_lower:
                results.append({
                    'original_text': text,
                    'score': 100,  # Exact match
                    'match_type': 'exact'
                })
        
        return results

# Global instance
search_helper = SearchHelper()
