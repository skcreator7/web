import re
from typing import Tuple, List, Dict
from rapidfuzz import fuzz
import nltk
from nltk.corpus import stopwords
from imdb import IMDb

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
        """Corpus से searchable index तैयार करो।"""
        self.search_index.clear()
        for text in corpus:
            words = re.findall(r'\b[a-z0-9]{2,}\b', text.lower())
            for word in words:
                if word not in self.stop_words:
                    self.search_index.add(word)

    async def search(self, query: str, corpus: List[str]) -> Tuple[str, List[Dict]]:
        """
        Fuzzy search (बिना auto-correct के)।
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

            if composite_score > 60:  # Tune threshold here
                results.append({
                    'text': text,
                    'score': composite_score,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        results.sort(key=lambda x: (-x['score'], x['match_type'] == 'fuzzy'))
        return query, results

    async def correct_query_with_imdb(self, query: str) -> str:
        """
        IMDb से query correct करें।
        """
        try:
            results = self.imdb_client.search_movie(query)
            if results:
                title = results[0]['title']
                year = results[0].get('year')
                corrected_title = f"{title} ({year})" if year else title
                return corrected_title
        except Exception as e:
            print("IMDb Error:", e)

        # fallback: वही query लौटाओ
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


# ✅ Global instance
search_helper = SearchHelper()
