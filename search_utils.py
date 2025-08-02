import re
from typing import Tuple, List, Dict
from rapidfuzz import fuzz, process
from textblob import TextBlob
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
        self.low_priority_words = {'720p', '1080p', '480p', 'hevc'}

    async def build_index(self, corpus: List[str]):
        """Build a search index from available content"""
        self.search_index.clear()
        for text in corpus:
            words = re.findall(r'\b[a-z0-9]{3,}\b', text.lower())
            for word in words:
                if word not in self.stop_words:
                    self.search_index.add(word)

    def clean_query(self, query: str) -> str:
        """Remove stopwords before correcting"""
        words = re.findall(r'\b[\w]{2,}\b', query.lower())
        return ' '.join([w for w in words if w not in self.stop_words])

    def _correct_word(self, word: str) -> str:
        """Correct a single word using multiple strategies"""
        if len(word) <= 2 or word in self.stop_words:
            return word

        corrected = str(TextBlob(word).correct())

        if self.search_index:
            match = process.extractOne(
                corrected,
                self.search_index,
                scorer=fuzz.ratio
            )
            if match and match[1] > 85:
                return match[0]
        return corrected

    def auto_correct(self, query: str) -> str:
        """Automatically correct spelling mistakes in search query"""
        words = re.findall(r"\b[\w']+\b", query.lower())
        corrected_words = [self._correct_word(word) for word in words]

        # Reconstruct query with original capitalization
        corrected = []
        for original, fixed in zip(query.split(), corrected_words):
            if original.istitle():
                corrected.append(fixed.title())
            elif original.isupper():
                corrected.append(fixed.upper())
            else:
                corrected.append(fixed)
        return ' '.join(corrected)

    async def advanced_search(self, query: str, corpus: List[str]) -> Tuple[str, List[Dict]]:
        """
        Perform auto-correcting search.
        Returns: (corrected_query, results)
        """
        cleaned = self.clean_query(query)
        corrected_query = self.auto_correct(cleaned)

        results = []
        for text in corpus:
            text_lower = text.lower()
            corrected_lower = corrected_query.lower()

            ratio = fuzz.ratio(corrected_lower, text_lower)
            partial = fuzz.partial_ratio(corrected_lower, text_lower)
            token_set = fuzz.token_set_ratio(corrected_lower, text_lower)

            # Composite score
            composite_score = (token_set * 0.5) + (partial * 0.3) + (ratio * 0.2)

            # Penalize low-priority words
            for word in self.low_priority_words:
                if word in text_lower and word not in corrected_lower:
                    composite_score -= 5

            if composite_score > 65:
                results.append({
                    'text': text,
                    'score': composite_score,
                    'original_text': text,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        # Sort by relevance
        results.sort(key=lambda x: (-x['score'], x['match_type'] == 'fuzzy'))

        return corrected_query, results


# ✅ Global instance
search_helper = SearchHelper()
