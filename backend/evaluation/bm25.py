"""Baselines for the retrieval comparison: BM25 keyword search and random order.

They are here so the paper can say how much the embedding model adds over a
plain keyword search, instead of reporting retrieval scores with nothing to
compare them with.
"""
import math
import random
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter = Counter()
        for c in self.docs:
            df.update(c.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def rank(self, query: str) -> list[int]:
        """Document indexes, best first. Ties keep document order (stable)."""
        terms = set(tokenize(query))
        scores = []
        for i, c in enumerate(self.docs):
            norm = self.k1 * (1 - self.b + self.b * (self.lengths[i] / self.avg if self.avg else 0))
            s = 0.0
            for t in terms:
                f = c.get(t, 0)
                if f:
                    s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + norm)
            scores.append(s)
        return sorted(range(len(scores)), key=lambda i: -scores[i])


def random_rank(n: int, seed: int) -> list[int]:
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order
