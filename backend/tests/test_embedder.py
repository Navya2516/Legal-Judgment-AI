import sys
import types

import numpy as np

from app.services import embedder as embedder_module


def test_sentence_transformer_wrapper_is_lazy_and_returns_float32(monkeypatch):
    created = []

    class StubModel:
        def __init__(self, name):
            created.append(name)

        def get_sentence_embedding_dimension(self):
            return 3

        def encode(self, texts, **kwargs):
            assert kwargs["normalize_embeddings"] is True
            return np.ones((len(texts), 3), dtype=np.float64) / np.sqrt(3)

    stub = types.SimpleNamespace(SentenceTransformer=StubModel)
    monkeypatch.setitem(sys.modules, "sentence_transformers", stub)

    emb = embedder_module.SentenceTransformerEmbedder("some/model")
    assert created == []  # nothing loaded until first use
    vectors = emb.embed(["a", "b"])
    emb.embed(["c"])
    assert created == ["some/model"]  # loaded once
    assert vectors.dtype == np.float32 and vectors.shape == (2, 3)
    assert emb.dim == 3


def test_preload_warms_up_the_embedder(monkeypatch):
    import app.main as main_module

    class Warm:
        loaded = False

        def warm_up(self):
            self.loaded = True

    warm = Warm()
    monkeypatch.setattr(embedder_module, "get_embedder", lambda: warm)
    main_module._preload_embedder()
    assert warm.loaded


def test_preload_failure_never_crashes_the_server(monkeypatch):
    import app.main as main_module

    def boom():
        raise RuntimeError("no internet")

    monkeypatch.setattr(embedder_module, "get_embedder", boom)
    main_module._preload_embedder()  # must not raise
