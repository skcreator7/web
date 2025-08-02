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
            'torrent', 'subtitle'  # ध्यान दें: 720p, 1080p यहां से हटाए गए हैं
        })

    async def build_index(self, corpus: List[str]):
        """Build a search index from the corpus."""
        self.search_index.clear()
        for text in corpus:
            words = re.findall(r'\b[a-z]{2,}\b', text.lower())  # Words with at least 2 letters
            for word in words:
                if word not in self.stop_words:
                    self.search_index.add(word)

    def _correct_word(self, word: str) -> str:
        """Correct a word using TextBlob + fuzzy, but preserve short movie codes."""
        
        if word in self.stop_words:
            return word

        # Preserve 2- or 3-letter important movie codes (e.g. kgf, leo, rrr)
        if len(word) <= 3:
            return word

        # TextBlob correction
        corrected = str(TextBlob(word).correct())

        # Fuzzy match with our index
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
        """Automatically correct spelling mistakes in search query."""
        words = re.findall(r"\b[\w']+\b", query.lower())
        corrected_words = [self._correct_word(word) for word in words]

        # Reconstruct original case
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
        Returns (corrected_query, matched_results)
        """
        corrected_query = self.auto_correct(query)

        results = []
        for text in corpus:
            ratio = fuzz.ratio(corrected_query.lower(), text.lower())
            partial = fuzz.partial_ratio(corrected_query.lower(), text.lower())
            token_set = fuzz.token_set_ratio(corrected_query.lower(), text.lower())

            composite_score = (token_set * 0.5) + (partial * 0.3) + (ratio * 0.2)

            if composite_score > 65:
                results.append({
                    'text': text,
                    'score': composite_score,
                    'original_text': text,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        results.sort(key=lambda x: (-x['score'], x['match_type'] == 'fuzzy'))
        return corrected_query, results

# ✅ Global instance
search_helper = SearchHelper()
