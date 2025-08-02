import re
from typing import List, Dict
from rapidfuzz import fuzz
import nltk
from nltk.corpus import stopwords
from difflib import get_close_matches

nltk.download('stopwords', quiet=True)
nltk.download('punkt', quiet=True)

class SearchHelper:
    def __init__(self):
        self.search_index = set()
        self.stop_words = set(stopwords.words('english')).union({
            'movie', 'film', 'hd', '4k', 'official', 'trailer',
            'full', 'latest', 'download', 'watch', 'new', 'free',
            'bollywood', 'hollywood', 'south', 'dubbed', 'english',
            'hindi', 'telugu', 'tamil', 'malayalam', 'kannada',
            'bengali', 'marathi', 'urdu', 'punjabi', 'web', 'series',
            'camrip', 'bluray', 'hdrip', 'dvdrip', 'webrip', 'print',
            'dual', 'audio', 'exclusive', 'original', 'uncut'
        })
        self.blocked_terms = {'full', 'movie'}

    def clean_query(self, query: str) -> str:
        tokens = nltk.word_tokenize(query.lower())
        tokens = [t for t in tokens if t not in self.stop_words or re.fullmatch(r'\d{4}', t)]
        return ' '.join(tokens).strip()

    def is_reserved_word_only(self, query: str) -> bool:
        tokens = nltk.word_tokenize(query.lower())
        return all(t in self.blocked_terms for t in tokens)

    def exact_match(self, query: str, corpus: List[str]) -> List[Dict]:
        query_lower = query.lower()
        return [
            {'original_text': text}
            for text in corpus
            if query_lower in text.lower()
        ]

    async def advanced_search(self, raw_query: str, corpus: List[str]) -> List[Dict]:
        if self.is_reserved_word_only(raw_query):
            return []

        cleaned_query = self.clean_query(raw_query)
        if not cleaned_query:
            return []

        matches = self.exact_match(cleaned_query, corpus)

        if not matches and len(cleaned_query) >= 3:
            corrected = safe_correct(cleaned_query, list({self.clean_query(text) for text in corpus}))
            if corrected and corrected != cleaned_query:
                matches = self.exact_match(corrected, corpus)

        return matches

def safe_correct(word: str, candidates: List[str], cutoff=0.8) -> str:
    matches = get_close_matches(word, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else word

search_helper = SearchHelper()
