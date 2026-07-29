import math
from collections import Counter
from typing import List, Callable

class BM25:
    def __init__(self, corpus: List[str], tokenizer: Callable[[str], List[str]]):
        self.tokenizer = tokenizer
        self.corpus = corpus
        self.doc_freqs = []
        self.idf = {}
        self.doc_len = []
        self.avgdl = 0.0
        self.k1 = 1.5
        self.b = 0.75
        self._initialize()

    def _initialize(self):
        df = {}
        for doc in self.corpus:
            tokens = self.tokenizer(doc)
            self.doc_len.append(len(tokens))
            freq = Counter(tokens)
            self.doc_freqs.append(freq)
            for token in freq:
                df[token] = df.get(token, 0) + 1
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        for token, freq in df.items():
            self.idf[token] = math.log((len(self.corpus) - freq + 0.5) / (freq + 0.5) + 1)

    def get_scores(self, query: str) -> List[float]:
        query_tokens = self.tokenizer(query)
        scores = []
        for i in range(len(self.corpus)):
            score = 0.0
            doc_freq = self.doc_freqs[i]
            doc_len = self.doc_len[i]
            for token in query_tokens:
                if token in doc_freq:
                    tf = doc_freq[token]
                    idf = self.idf.get(token, 0.0)
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                    score += idf * numerator / denominator
            scores.append(score)
        return scores
