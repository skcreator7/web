import re
from typing import List, Dict
from rapidfuzz import fuzz
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SearchHelper:
    def __init__(self):
        # Words to ignore in search queries
        self.ignore_words = {
            'movie', 'film', 'hd', 'full', 'part', 'scene', 'trailer',
            'download', 'watch', 'free', 'online', 'stream', 'bluray',
            'torrent', 'subtitle', 'print', 'quality', 'version', 'rip',
            'dvd', 'web', 'brrip', 'yts', 'x264', 'x265', '1080p', '720p',
            '480p', '4k', 'uhd', 'hindi', 'english', 'dual', 'audio'
        }

    def _clean_query(self, query: str) -> str:
        """Remove common movie-related words from query"""
        # Split query into words and filter out ignored words
        words = re.findall(r'\b[a-z0-9]{2,}\b', query.lower())
        cleaned_words = [word for word in words if word not in self.ignore_words]
        return ' '.join(cleaned_words)

    async def advanced_search(self, query: str, corpus: List[str]) -> List[Dict]:
        """
        Advanced fuzzy search with query cleaning
        Returns: List of matched results with scores
        """
        # Clean the query first
        cleaned_query = self._clean_query(query)
        if not cleaned_query:
            return []

        results = []
        for text in corpus:
            text_lower = text.lower()
            
            # Calculate multiple similarity metrics
            ratio = fuzz.ratio(cleaned_query, text_lower)
            partial = fuzz.partial_ratio(cleaned_query, text_lower)
            token_set = fuzz.token_set_ratio(cleaned_query, text_lower)
            
            # Weighted composite score
            composite_score = (token_set * 0.5) + (partial * 0.3) + (ratio * 0.2)

            if composite_score > 60:  # Adjust threshold as needed
                results.append({
                    'original_text': text,
                    'score': composite_score,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        # Sort by score (highest first)
        results.sort(key=lambda x: -x['score'])
        return results

# Global instance
search_helper = SearchHelper()
