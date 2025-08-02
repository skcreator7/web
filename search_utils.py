import re
from typing import List, Dict
import logging
from rapidfuzz import process

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BANNED_SUGGESTIONS = {"of", "the", "and", "a", "is", "in", "for", "on", "to", "at", "by", "it", "be"}

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
        year_match = re.search(r'(19|20)\d{2}', query)
        year = year_match.group() if year_match else ""

        words = re.findall(r'\b[a-z0-9]{2,}\b', query.lower())
        cleaned_words = [word for word in words if word not in self.ignore_words]

        cleaned_query = ' '.join(cleaned_words)
        if year:
            cleaned_query = f"{cleaned_query} {year}" if cleaned_query else year

        return cleaned_query.strip()

    def _auto_correct(self, query: str, corpus: List[str]) -> str:
        if len(query) <= 3:
            return None

        matches = process.extract(query, corpus, limit=1)
        if matches and matches[0][1] >= 90:
            corrected = matches[0][0].lower()
            if corrected not in BANNED_SUGGESTIONS:
                return corrected
        return None

    async def advanced_search(self, query: str, corpus: List[str]) -> List[Dict]:
        cleaned_query = self._clean_query(query)
        if not cleaned_query:
            return []

        results = []
        for text in corpus:
            if cleaned_query in text.lower():
                results.append({
                    'original_text': text,
                    'score': 100,
                    'match_type': 'exact'
                })

        # If no results, try auto-correct
        if not results:
            corrected = self._auto_correct(cleaned_query, corpus)
            if corrected:
                for text in corpus:
                    if corrected in text.lower():
                        results.append({
                            'original_text': text,
                            'score': 90,
                            'match_type': f'corrected ({corrected})'
                        })

        return results

# Global instance
search_helper = SearchHelper()