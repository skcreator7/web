import re
from typing import Tuple, List, Dict
from rapidfuzz import fuzz
import nltk
from nltk.corpus import stopwords

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

    async def build_index(self, corpus: List[str]):
        """Build a search index from the corpus."""
        self.search_index.clear()
        for text in corpus:
            words = re.findall(r'\b[a-z0-9]{2,}\b', text.lower())
            for word in words:
                if word not in self.stop_words:
                    self.search_index.add(word)

    async def search(self, query: str, corpus: List[str]) -> Tuple[str, List[Dict]]:
        """
        Perform direct fuzzy search (without auto-correct).
        Returns (original_query, matched_results)
        """
        query = query.strip().lower()

        results = []
        for text in corpus:
            text_lower = text.lower()
            ratio = fuzz.ratio(query, text_lower)
            partial = fuzz.partial_ratio(query, text_lower)
            token_set = fuzz.token_set_ratio(query, text_lower)

            composite_score = (token_set * 0.5) + (partial * 0.3) + (ratio * 0.2)

            if composite_score > 65:
                results.append({
                    'text': text,
                    'score': composite_score,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        results.sort(key=lambda x: (-x['score'], x['match_type'] == 'fuzzy'))
        return query, results

# ✅ Global instance
search_helper = SearchHelper()
