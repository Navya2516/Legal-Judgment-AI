"""Stand-ins used only by tests and offline smoke runs.

A report built with these says so at the top and must never be quoted as a
result: they exist to check the plumbing, not to measure anything.
"""
import re
import zlib

import numpy as np


class HashEmbedder:
    name = "fake-hash-embedder"
    dim = 256

    def embed(self, texts):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                out[row, zlib.crc32(word.encode()) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


def is_test_name(name: str) -> bool:
    return "fake" in (name or "").lower()
