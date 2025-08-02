import re
from typing import Tuple, List, Dict
from rapidfuzz import fuzz
import nltk
from nltk.corpus import stopwords
from imdb import IMDb
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Download NLTK data
nltk.download('stopwords', quiet=True)
nltk.download('punkt', quiet=True)

class SearchHelper:
    def __init__(self):
        self.search_index = set()
        self.stop_words = set(stopwords.words('english')).union({
            'movie', 'film', 'hd', 'full', 'part', 'scene', 'trailer',
            'download', 'watch', 'free', 'online', 'stream', 'bluray',
            'torrent', 'subtitle'
        })
        self.imdb_client = IMDb()

    async def build_index(self, corpus: List[str]):
        """Build searchable index from corpus"""
        self.search_index.clear()
        for text in corpus:
            words = re.findall(r'\b[a-z0-9]{2,}\b', text.lower())
            for word in words:
                if word not in self.stop_words:
                    self.search_index.add(word)

    async def search(self, query: str, corpus: List[str]) -> Tuple[str, List[Dict]]:
        """
        Fuzzy search
        Returns: (original_query, results)
        """
        query = query.strip().lower()
        results = []

        for text in corpus:
            text_lower = text.lower()
            ratio = fuzz.ratio(query, text_lower)
            partial = fuzz.partial_ratio(query, text_lower)
            token_set = fuzz.token_set_ratio(query, text_lower)

            composite_score = (token_set * 0.5) + (partial * 0.3) + (ratio * 0.2)

            if composite_score > 60:  # Adjust threshold as needed
                results.append({
                    'original_text': text,
                    'score': composite_score,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        results.sort(key=lambda x: (-x['score'], x['match_type'] == 'fuzzy'))
        return query, results

    async def correct_query_with_imdb(self, query: str) -> str:
        """Correct query using IMDb"""
        try:
            results = self.imdb_client.search_movie(query)
            if results:
                title = results[0]['title']
                year = results[0].get('year')
                return f"{title} ({year})" if year else title
        except Exception as e:
            logger.error(f"IMDb Error: {e}")
        return query

    async def advanced_search(self, query: str, corpus: List[str]) -> Tuple[str, str, List[Dict]]:
        """
        Auto-correct + fuzzy search
        Returns: original query, corrected query, and results
        """
        original_query = query.strip()
        corrected = await self.correct_query_with_imdb(original_query)
        _, results = await self.search(corrected, corpus)
        return original_query, corrected, results

# Global instance
search_helper = SearchHelper()
