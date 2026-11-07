"""
Embedding Generation
====================
Generates embeddings for document chunks using local or cloud models.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import hashlib
import json
import re

logger = logging.getLogger(__name__)

# Try to import embedding libraries
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    Groq = None


class EmbeddingGenerator:
    """
    Generates embeddings for document chunks.
    
    Supports:
    - Local sentence-transformers models
    - Cloud embeddings (if available via provider)
    - Caching to avoid recomputation
    """
    
    # Available local models
    LOCAL_MODELS = {
        "minilm": "sentence-transformers/all-MiniLM-L6-v2",  # 384 dim, fast
        "mpnet": "sentence-transformers/all-mpnet-base-v2",  # 768 dim, better quality
        "e5-small": "intfloat/e5-small-v2",  # 384 dim, good for retrieval
        "e5-base": "intfloat/e5-base-v2",  # 768 dim
        "bge-small": "BAAI/bge-small-en-v1.5",  # 384 dim
        "bge-base": "BAAI/bge-base-en-v1.5",  # 768 dim
    }
    
    def __init__(
        self, 
        model_name: str = "minilm",
        cache_dir: Optional[str] = None,
        use_cloud: bool = False,
        cloud_api_key: Optional[str] = None,
    ):
        self.model_name = model_name
        self.use_cloud = use_cloud
        self.cloud_api_key = cloud_api_key
        self.model = None
        self.embedding_dim = 384  # Default for MiniLM
        self._embedding_backend = "sentence-transformers"
        self._cache = {}
        self._cache_dir = Path(cache_dir) if cache_dir else None
        
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
    
    def load_model(self) -> None:
        """Load the embedding model."""
        if self.model is not None:
            return
        
        if self.use_cloud:
            # Cloud embeddings would be handled by the LLM provider
            # For now, we'll fall back to local
            logger.warning("Cloud embeddings not yet implemented, using local model")
            self.use_cloud = False
        
        # Resolve model name
        model_path = self.LOCAL_MODELS.get(self.model_name, self.model_name)
        try:
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                raise RuntimeError("sentence-transformers is not installed")
            logger.info("Loading embedding model: %s", model_path)
            self.model = SentenceTransformer(model_path)
            test_emb = self.model.encode(["test"])
            self.embedding_dim = len(test_emb[0])
            logger.info("Embedding dimension: %s", self.embedding_dim)
        except Exception as exc:
            # Keep PDF ingestion and search usable in offline/local installs.
            # Feature hashing is lexical, so it is less semantic than MiniLM
            # but needs no model download or remote service.
            logger.warning(
                "Embedding model %s unavailable (%s); using local hashing embeddings.",
                model_path,
                type(exc).__name__,
            )
            self.model = _HashingEmbeddingModel(self.embedding_dim)
            self._embedding_backend = "local-hashing-v1"
    
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []
        
        self.load_model()
        
        # Check cache
        uncached_texts = []
        uncached_indices = []
        results = [None] * len(texts)
        
        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                results[i] = self._cache[cache_key]
            elif self._cache_dir:
                cached = self._load_from_disk(cache_key)
                if cached is not None:
                    self._cache[cache_key] = cached
                    results[i] = cached
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)
        
        # Generate for uncached
        if uncached_texts:
            logger.info(f"Generating embeddings for {len(uncached_texts)} texts")
            embeddings = self.model.encode(uncached_texts, show_progress_bar=False)
            
            for idx, embedding in zip(uncached_indices, embeddings):
                embedding_list = embedding.tolist()
                results[idx] = embedding_list
                
                # Cache it
                cache_key = self._get_cache_key(texts[idx])
                self._cache[cache_key] = embedding_list
                if self._cache_dir:
                    self._save_to_disk(cache_key, embedding_list)
        
        return results
    
    def generate_single(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        return self.generate([text])[0]
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        # Include the effective backend so cached vectors never mix models.
        content = f"{self.model_name}:{self._embedding_backend}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]
    
    def _save_to_disk(self, key: str, embedding: List[float]) -> None:
        """Save embedding to disk cache."""
        try:
            cache_file = self._cache_dir / f"{key}.json"
            cache_file.write_text(json.dumps(embedding))
        except Exception as e:
            logger.warning(f"Failed to cache embedding: {e}")
    
    def _load_from_disk(self, key: str) -> Optional[List[float]]:
        """Load embedding from disk cache."""
        try:
            cache_file = self._cache_dir / f"{key}.json"
            if cache_file.exists():
                return json.loads(cache_file.read_text())
        except Exception:
            pass
        return None
    
    def get_dimension(self) -> int:
        """Get embedding dimension."""
        if self.model is None:
            self.load_model()
        return self.embedding_dim


class CloudEmbeddingGenerator:
    """
    Cloud-based embedding generation (placeholder for future implementation).
    
    Would use provider-specific embedding APIs.
    """
    
    def __init__(self, provider: str = "groq", api_key: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
    
    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings via cloud API."""
        # Placeholder - would implement provider-specific embedding calls
        raise NotImplementedError("Cloud embeddings not yet implemented")
    
    def generate_single(self, text: str) -> List[float]:
        return self.generate([text])[0]


def create_embedding_generator(
    model: str = "minilm",
    cache_dir: Optional[str] = None,
) -> EmbeddingGenerator:
    """Factory function to create embedding generator."""
    return EmbeddingGenerator(model_name=model, cache_dir=cache_dir)


class _HashingEmbeddingModel:
    """Small deterministic lexical encoder used when a local model is absent."""

    def __init__(self, dimension: int):
        self.dimension = int(dimension)

    def encode(self, texts: List[str], show_progress_bar: bool = False):
        import numpy as np

        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = re.findall(r"[\w]+", str(text or "").casefold(), flags=re.UNICODE)
            features = list(tokens)
            features.extend(f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))
            for feature in features:
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                vectors[row, index] += sign
            norm = float(np.linalg.norm(vectors[row]))
            if norm:
                vectors[row] /= norm
        return vectors
