import re
from typing import Tuple, List, Dict
from rapidfuzz import fuzz, process
from textblob import TextBlob
import nltk
from nltk.corpus import stopwords

# Download NLTK data
nltk.download('stopwords', quiet=True)
nltk.download('punkt', quiet=True)

class SearchHelper:
    def __init__(self, correction_threshold=85, match_threshold=60):
        self.search_index = set()
        self.stop_words = set(stopwords.words('english')).union({
            'movie', 'film', 'hd', 'full', 'part', 'scene', 'trailer',
            'download', 'watch', 'free', 'online', 'stream', 'bluray',
            '1080p', '720p', '4k', 'torrent', 'subtitle'
        })
        self.correction_threshold = correction_threshold
        self.match_threshold = match_threshold

    async def build_index(self, corpus: List[str]):
        """Build a search index from content"""
        self.search_index.clear()
        for text in corpus:
            words = re.findall(r'\b\w{3,}\b', text.lower())  # Corrected regex
            for word in words:
                if word not in self.stop_words:
                    self.search_index.add(word)

    def _correct_word(self, word: str) -> str:
        """Correct a single word using TextBlob and fuzzy match"""
        if len(word) <= 2 or word in self.stop_words:
            return word

        # TextBlob correction
        corrected = str(TextBlob(word).correct())

        # Avoid overcorrection
        if corrected != word and fuzz.ratio(word, corrected) < self.correction_threshold:
            corrected = word

        # Fuzzy match with index
        if self.search_index:
            match = process.extractOne(
                corrected,
                self.search_index,
                scorer=fuzz.ratio
            )
            if match:
                best_match, score, _ = match
                if score > self.correction_threshold:
                    return best_match
        return corrected

    def auto_correct(self, query: str) -> str:
        """Correct search query spelling"""
        words = re.findall(r"\b[\w']+\b", query.lower())
        corrected_words = [self._correct_word(word) for word in words]

        # Reconstruct preserving casing
        original_tokens = query.split()
        corrected = []
        for original, fixed in zip(original_tokens, corrected_words):
            if original.istitle():
                corrected.append(fixed.title())
            elif original.isupper():
                corrected.append(fixed.upper())
            else:
                corrected.append(fixed)
        return ' '.join(corrected)

    async def advanced_search(self, query: str, corpus: List[str]) -> Tuple[str, List[Dict]]:
        """
        Perform auto-corrected fuzzy search
        Returns: (corrected_query, results)
        """
        corrected_query = self.auto_correct(query)

        results = []
        for text in corpus:
            ratio = fuzz.ratio(corrected_query.lower(), text.lower())
            partial = fuzz.partial_ratio(corrected_query.lower(), text.lower())
            token_set = fuzz.token_set_ratio(corrected_query.lower(), text.lower())

            composite_score = (token_set * 0.5) + (partial * 0.3) + (ratio * 0.2)

            if composite_score >= self.match_threshold:
                results.append({
                    'text': text,
                    'score': round(composite_score, 2),
                    'original_text': text,
                    'match_type': 'fuzzy' if composite_score < 90 else 'exact'
                })

        results.sort(key=lambda x: (-x['score'], x['match_type'] == 'fuzzy'))

        return corrected_query, results

# Global instance
search_helper = SearchHelper()
