import numpy as np

import document_processor.embeddings as embeddings


def test_missing_local_model_falls_back_to_deterministic_hash_embeddings(monkeypatch, tmp_path):
    def unavailable_model(*_args, **_kwargs):
        raise OSError("model is not cached and network is unavailable")

    monkeypatch.setattr(embeddings, "SENTENCE_TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(embeddings, "SentenceTransformer", unavailable_model)
    generator = embeddings.EmbeddingGenerator(cache_dir=str(tmp_path))

    first = generator.generate_single("Juniper Lantern September sales 491200")
    similar = generator.generate_single("Juniper Lantern sales in September")
    unrelated = generator.generate_single("Quarterly weather forecast for April")

    assert generator._embedding_backend == "local-hashing-v1"
    assert len(first) == 384
    assert np.isclose(np.linalg.norm(first), 1.0)
    assert np.dot(first, similar) > np.dot(first, unrelated)
    assert generator._get_cache_key("Juniper Lantern") != embeddings.EmbeddingGenerator()._get_cache_key("Juniper Lantern")
