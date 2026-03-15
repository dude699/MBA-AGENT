"""
============================================================
PRISM v0.1 — EMBEDDING ENGINE (LOCAL SENTENCE-TRANSFORMERS)
============================================================
Zero-cost local embedding engine using all-MiniLM-L6-v2 model.
Provides 384-dimensional dense vector embeddings for:

    1. A-06 Dedup Engine — Layer 4: Semantic similarity detection
    2. A-08 PPO Optimizer — V11: CV-to-JD cosine similarity scoring
    3. A-10 ATS Simulator — Keyword gap analysis via embedding overlap

Architecture:
    - Lazy-loading: Model loaded on first use (~30s, ~80MB RAM)
    - Thread-safe singleton with LRU embedding cache
    - Batch embedding support for pipeline efficiency
    - Cosine similarity with configurable thresholds
    - Zero API cost — 100% local inference

Model: sentence-transformers/all-MiniLM-L6-v2
    - Dimensions: 384
    - Max sequence length: 256 tokens
    - Trained on 1B+ sentence pairs
    - Size: ~80MB
    - Speed: ~1000 embeddings/sec on CPU

Memory Considerations (Render 512MB):
    - Model footprint: ~80MB in RAM
    - Cache: ~10K embeddings = ~15MB
    - Total: ~95MB — fits within Render constraints
    - LAZY_LOAD_EMBEDDINGS=true recommended
============================================================
"""

import os
import sys
import time
import hashlib
import threading
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import (
    Dict, List, Optional, Tuple, Any, Union, Set
)
from dataclasses import dataclass, field
from collections import OrderedDict
from functools import lru_cache

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_DIMENSIONS = 384
DEFAULT_MAX_SEQ_LENGTH = 256
DEFAULT_CACHE_SIZE = 10000
DEFAULT_BATCH_SIZE = 32


# ============================================================
# EMBEDDING RESULT DATA MODEL
# ============================================================

@dataclass
class EmbeddingResult:
    """Result from an embedding operation."""
    vector: np.ndarray
    text_hash: str
    model_name: str
    dimensions: int
    cached: bool = False
    latency_ms: float = 0.0
    timestamp: str = ""

    def to_list(self) -> List[float]:
        """Convert numpy vector to Python list for JSON serialization."""
        return self.vector.tolist()

    def to_dict(self) -> Dict[str, Any]:
        """Full serializable representation."""
        return {
            'vector': self.to_list(),
            'text_hash': self.text_hash,
            'model_name': self.model_name,
            'dimensions': self.dimensions,
            'cached': self.cached,
            'latency_ms': self.latency_ms,
        }


@dataclass
class SimilarityResult:
    """Result from a similarity comparison."""
    score: float  # Cosine similarity (0.0 to 1.0)
    score_percentage: float  # Score scaled to 0-100
    is_duplicate: bool  # Above dedup threshold
    is_good_match: bool  # Above CV-JD good match threshold
    is_excellent_match: bool  # Above CV-JD excellent match threshold
    text_a_hash: str = ""
    text_b_hash: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'score': round(self.score, 4),
            'score_percentage': round(self.score_percentage, 1),
            'is_duplicate': self.is_duplicate,
            'is_good_match': self.is_good_match,
            'is_excellent_match': self.is_excellent_match,
        }


# ============================================================
# LRU EMBEDDING CACHE
# ============================================================

class EmbeddingCache:
    """
    Thread-safe LRU cache for embedding vectors.
    Keyed by text hash to avoid re-computing embeddings.
    Configurable max size with automatic eviction.
    """

    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict[str, Tuple[np.ndarray, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, text: str) -> str:
        """Generate a deterministic hash key for the text."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

    def get(self, text: str) -> Optional[np.ndarray]:
        """Get cached embedding vector for text."""
        key = self._make_key(text)
        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                self._hits += 1
                vector, _timestamp = self._cache[key]
                return vector.copy()
            self._misses += 1
            return None

    def put(self, text: str, vector: np.ndarray):
        """Cache an embedding vector for text."""
        key = self._make_key(text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = (vector.copy(), time.time())
            else:
                if len(self._cache) >= self.max_size:
                    # Evict oldest (first) entry
                    self._cache.popitem(last=False)
                self._cache[key] = (vector.copy(), time.time())

    def get_batch(self, texts: List[str]) -> Tuple[Dict[int, np.ndarray], List[int]]:
        """
        Check cache for a batch of texts.
        Returns:
            - Dict[original_index, vector]: cached results
            - List[original_index]: indices that need computation
        """
        cached_results = {}
        uncached_indices = []
        for i, text in enumerate(texts):
            vector = self.get(text)
            if vector is not None:
                cached_results[i] = vector
            else:
                uncached_indices.append(i)
        return cached_results, uncached_indices

    def put_batch(self, texts: List[str], vectors: np.ndarray):
        """Cache a batch of embedding vectors."""
        for i, text in enumerate(texts):
            self.put(text, vectors[i])

    def clear(self):
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            'size': len(self._cache),
            'max_size': self.max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(self._hits / total * 100, 1) if total > 0 else 0,
            'memory_est_mb': round(
                len(self._cache) * DEFAULT_DIMENSIONS * 4 / (1024 * 1024), 2
            ),
        }


# ============================================================
# MAIN EMBEDDING ENGINE
# ============================================================

class EmbeddingEngine:
    """
    PRISM v0.1 — Local Embedding Engine (Singleton).

    Provides high-performance text embedding using sentence-transformers
    with lazy loading, caching, and batch processing.

    Usage:
        engine = get_embedding_engine()
        vector = engine.embed("some text")
        similarity = engine.cosine_similarity("text A", "text B")
        is_dup = engine.is_semantic_duplicate("listing A", "listing B")
        ppo_v11 = engine.cv_jd_match_score(cv_text, jd_text)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Load configuration
        try:
            from core.config import get_config
            config = get_config()
            self._model_name = config.embedding.model_name
            self._dimensions = config.embedding.dimensions
            self._lazy_load = config.embedding.lazy_load
            self._cache_size = config.embedding.cache_size
            self._batch_size = config.embedding.batch_size
            self._normalize = config.embedding.normalize_embeddings
            self._dedup_threshold = config.embedding.dedup_similarity_threshold
            self._good_match_threshold = config.embedding.cv_jd_good_match
            self._excellent_match_threshold = config.embedding.cv_jd_excellent_match
        except Exception as e:
            logger.warning(f"[EMBEDDING] Config load fallback: {e}")
            self._model_name = DEFAULT_MODEL_NAME
            self._dimensions = DEFAULT_DIMENSIONS
            self._lazy_load = True
            self._cache_size = DEFAULT_CACHE_SIZE
            self._batch_size = DEFAULT_BATCH_SIZE
            self._normalize = True
            self._dedup_threshold = 0.85
            self._good_match_threshold = 0.60
            self._excellent_match_threshold = 0.75

        # Model (lazy-loaded)
        self._model = None
        self._model_lock = threading.Lock()
        self._model_loaded = False

        # Cache
        self._cache = EmbeddingCache(max_size=self._cache_size)

        # Stats
        self._total_embeddings = 0
        self._total_comparisons = 0
        self._total_latency_ms = 0.0
        self._load_time_ms = 0.0

        # CV embedding cache (special: persists separately)
        self._cv_embedding: Optional[np.ndarray] = None
        self._cv_embedding_time: Optional[datetime] = None
        self._cv_text_hash: str = ""

        if not self._lazy_load:
            self._ensure_model_loaded()

        logger.info(
            f"[EMBEDDING] Engine initialized (model={self._model_name}, "
            f"dims={self._dimensions}, lazy={self._lazy_load}, "
            f"cache={self._cache_size})"
        )

    # ----------------------------------------------------------
    # MODEL LOADING
    # ----------------------------------------------------------

    def _ensure_model_loaded(self) -> bool:
        """Load the sentence-transformers model if not already loaded."""
        if self._model_loaded and self._model is not None:
            return True

        with self._model_lock:
            # Double-check after acquiring lock
            if self._model_loaded and self._model is not None:
                return True

            try:
                start = time.time()
                logger.info(
                    f"[EMBEDDING] Loading model '{self._model_name}'... "
                    f"(~80MB, first load may take 30s)"
                )

                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self._model_name,
                    device='cpu',  # Render doesn't have GPU
                )
                self._model.max_seq_length = DEFAULT_MAX_SEQ_LENGTH

                self._load_time_ms = (time.time() - start) * 1000
                self._model_loaded = True

                logger.info(
                    f"[EMBEDDING] Model loaded in {self._load_time_ms:.0f}ms "
                    f"(dims={self._model.get_sentence_embedding_dimension()}, "
                    f"max_seq={self._model.max_seq_length})"
                )
                return True

            except ImportError:
                logger.error(
                    "[EMBEDDING] sentence-transformers not installed! "
                    "Install with: pip install sentence-transformers"
                )
                return False
            except Exception as e:
                logger.error(f"[EMBEDDING] Model load failed: {e}")
                return False

    @property
    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self._model_loaded and self._model is not None

    # ----------------------------------------------------------
    # CORE EMBEDDING
    # ----------------------------------------------------------

    def embed(self, text: str, use_cache: bool = True) -> Optional[EmbeddingResult]:
        """
        Embed a single text string into a dense vector.

        Args:
            text: Input text to embed (will be truncated to max_seq_length)
            use_cache: Whether to use the embedding cache

        Returns:
            EmbeddingResult with the vector, or None on failure
        """
        if not text or not text.strip():
            return None

        text = text.strip()
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]

        # Check cache
        if use_cache:
            cached_vector = self._cache.get(text)
            if cached_vector is not None:
                return EmbeddingResult(
                    vector=cached_vector,
                    text_hash=text_hash,
                    model_name=self._model_name,
                    dimensions=self._dimensions,
                    cached=True,
                    latency_ms=0.0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        # Ensure model is loaded
        if not self._ensure_model_loaded():
            return None

        try:
            start = time.time()
            vector = self._model.encode(
                text,
                normalize_embeddings=self._normalize,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            latency_ms = (time.time() - start) * 1000

            # Ensure correct shape
            if isinstance(vector, np.ndarray) and vector.ndim == 1:
                pass  # Already correct shape
            elif isinstance(vector, np.ndarray) and vector.ndim == 2:
                vector = vector[0]
            else:
                vector = np.array(vector, dtype=np.float32).flatten()

            # Cache the result
            if use_cache:
                self._cache.put(text, vector)

            # Update stats
            self._total_embeddings += 1
            self._total_latency_ms += latency_ms

            return EmbeddingResult(
                vector=vector,
                text_hash=text_hash,
                model_name=self._model_name,
                dimensions=len(vector),
                cached=False,
                latency_ms=round(latency_ms, 2),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            logger.error(f"[EMBEDDING] Embed failed: {e}")
            return None

    def embed_batch(
        self,
        texts: List[str],
        use_cache: bool = True,
    ) -> List[Optional[EmbeddingResult]]:
        """
        Embed a batch of texts efficiently.
        Uses cache for already-computed embeddings, batches the rest.

        Args:
            texts: List of input texts
            use_cache: Whether to use the embedding cache

        Returns:
            List of EmbeddingResult (same order as input), None for failures
        """
        if not texts:
            return []

        results: List[Optional[EmbeddingResult]] = [None] * len(texts)

        # Clean texts
        clean_texts = [t.strip() if t else "" for t in texts]

        # Check cache
        if use_cache:
            cached, uncached_indices = self._cache.get_batch(clean_texts)
            for idx, vector in cached.items():
                text_hash = hashlib.sha256(
                    clean_texts[idx].encode('utf-8')
                ).hexdigest()[:16]
                results[idx] = EmbeddingResult(
                    vector=vector,
                    text_hash=text_hash,
                    model_name=self._model_name,
                    dimensions=self._dimensions,
                    cached=True,
                    latency_ms=0.0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
        else:
            uncached_indices = list(range(len(texts)))

        # Nothing to compute
        if not uncached_indices:
            return results

        # Filter out empty texts
        valid_indices = [i for i in uncached_indices if clean_texts[i]]
        if not valid_indices:
            return results

        # Ensure model is loaded
        if not self._ensure_model_loaded():
            return results

        try:
            start = time.time()
            batch_texts = [clean_texts[i] for i in valid_indices]

            # Process in sub-batches to avoid memory issues
            all_vectors = []
            for batch_start in range(0, len(batch_texts), self._batch_size):
                batch_end = min(batch_start + self._batch_size, len(batch_texts))
                sub_batch = batch_texts[batch_start:batch_end]

                vectors = self._model.encode(
                    sub_batch,
                    normalize_embeddings=self._normalize,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    batch_size=self._batch_size,
                )
                all_vectors.append(vectors)

            # Concatenate all sub-batch results
            if len(all_vectors) == 1:
                all_vectors_np = all_vectors[0]
            else:
                all_vectors_np = np.vstack(all_vectors)

            latency_ms = (time.time() - start) * 1000
            per_text_latency = latency_ms / len(valid_indices)

            # Assign results
            for i, orig_idx in enumerate(valid_indices):
                vector = all_vectors_np[i]
                text_hash = hashlib.sha256(
                    clean_texts[orig_idx].encode('utf-8')
                ).hexdigest()[:16]

                results[orig_idx] = EmbeddingResult(
                    vector=vector,
                    text_hash=text_hash,
                    model_name=self._model_name,
                    dimensions=len(vector),
                    cached=False,
                    latency_ms=round(per_text_latency, 2),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

                # Cache
                if use_cache:
                    self._cache.put(clean_texts[orig_idx], vector)

            # Update stats
            self._total_embeddings += len(valid_indices)
            self._total_latency_ms += latency_ms

            logger.debug(
                f"[EMBEDDING] Batch embed: {len(valid_indices)} texts in "
                f"{latency_ms:.0f}ms ({per_text_latency:.1f}ms/text)"
            )

        except Exception as e:
            logger.error(f"[EMBEDDING] Batch embed failed: {e}")

        return results

    # ----------------------------------------------------------
    # SIMILARITY COMPUTATION
    # ----------------------------------------------------------

    def cosine_similarity(
        self,
        text_a: str,
        text_b: str,
        use_cache: bool = True,
    ) -> Optional[SimilarityResult]:
        """
        Compute cosine similarity between two texts.

        Args:
            text_a: First text
            text_b: Second text
            use_cache: Whether to use embedding cache

        Returns:
            SimilarityResult with score and classification, or None on failure
        """
        start = time.time()

        emb_a = self.embed(text_a, use_cache=use_cache)
        emb_b = self.embed(text_b, use_cache=use_cache)

        if emb_a is None or emb_b is None:
            return None

        try:
            # Cosine similarity (vectors are already normalized if config says so)
            if self._normalize:
                score = float(np.dot(emb_a.vector, emb_b.vector))
            else:
                norm_a = np.linalg.norm(emb_a.vector)
                norm_b = np.linalg.norm(emb_b.vector)
                if norm_a == 0 or norm_b == 0:
                    score = 0.0
                else:
                    score = float(
                        np.dot(emb_a.vector, emb_b.vector) / (norm_a * norm_b)
                    )

            # Clamp to [0, 1] (cosine sim can be slightly negative for dissimilar texts)
            score = max(0.0, min(1.0, score))

            latency_ms = (time.time() - start) * 1000
            self._total_comparisons += 1

            return SimilarityResult(
                score=score,
                score_percentage=score * 100,
                is_duplicate=score >= self._dedup_threshold,
                is_good_match=score >= self._good_match_threshold,
                is_excellent_match=score >= self._excellent_match_threshold,
                text_a_hash=emb_a.text_hash,
                text_b_hash=emb_b.text_hash,
                latency_ms=round(latency_ms, 2),
            )

        except Exception as e:
            logger.error(f"[EMBEDDING] Similarity computation failed: {e}")
            return None

    def cosine_similarity_vectors(
        self,
        vector_a: np.ndarray,
        vector_b: np.ndarray,
    ) -> float:
        """
        Compute cosine similarity between two pre-computed vectors.
        Used when vectors are already available (e.g., from DB).
        """
        try:
            if self._normalize:
                return float(np.dot(vector_a, vector_b))
            else:
                norm_a = np.linalg.norm(vector_a)
                norm_b = np.linalg.norm(vector_b)
                if norm_a == 0 or norm_b == 0:
                    return 0.0
                return float(np.dot(vector_a, vector_b) / (norm_a * norm_b))
        except Exception:
            return 0.0

    # ----------------------------------------------------------
    # PRISM-SPECIFIC METHODS
    # ----------------------------------------------------------

    def is_semantic_duplicate(
        self,
        text_a: str,
        text_b: str,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, float]:
        """
        A-06 Dedup Engine — Layer 4: Check if two listing descriptions
        are semantic duplicates.

        Args:
            text_a: Description of listing A
            text_b: Description of listing B
            threshold: Custom threshold (default from config: 0.85)

        Returns:
            Tuple of (is_duplicate, similarity_score)
        """
        threshold = threshold or self._dedup_threshold
        result = self.cosine_similarity(text_a, text_b)
        if result is None:
            return False, 0.0
        return result.score >= threshold, result.score

    def cv_jd_match_score(
        self,
        cv_text: str,
        jd_text: str,
    ) -> Dict[str, Any]:
        """
        A-08 PPO V11: Compute semantic CV-to-JD match score.
        This is the V11 variable in the 11-variable PPO formula.

        Args:
            cv_text: Full CV/resume text
            jd_text: Full job description text

        Returns:
            Dict with:
                - raw_score: Cosine similarity (0.0-1.0)
                - scaled_score: Score scaled to 0-100 for PPO
                - match_level: 'excellent' / 'good' / 'moderate' / 'weak'
                - success: Whether computation succeeded
        """
        result = self.cosine_similarity(cv_text, jd_text)

        if result is None:
            return {
                'raw_score': 0.0,
                'scaled_score': 50.0,  # Default neutral score on failure
                'match_level': 'unknown',
                'success': False,
            }

        # Scale to 0-100 for PPO compatibility
        scaled = result.score * 100

        # Determine match level
        if result.is_excellent_match:
            match_level = 'excellent'
        elif result.is_good_match:
            match_level = 'good'
        elif result.score >= 0.40:
            match_level = 'moderate'
        else:
            match_level = 'weak'

        return {
            'raw_score': round(result.score, 4),
            'scaled_score': round(scaled, 1),
            'match_level': match_level,
            'success': True,
            'latency_ms': result.latency_ms,
        }

    def set_cv_embedding(self, cv_text: str) -> bool:
        """
        Pre-compute and cache the user's CV embedding.
        This is called once (or daily) and reused for all JD comparisons.

        Args:
            cv_text: Full CV/resume text

        Returns:
            True if successfully embedded
        """
        result = self.embed(cv_text, use_cache=True)
        if result is None:
            return False

        self._cv_embedding = result.vector
        self._cv_embedding_time = datetime.now(timezone.utc)
        self._cv_text_hash = result.text_hash

        logger.info(
            f"[EMBEDDING] CV embedding cached "
            f"(hash={result.text_hash}, dims={result.dimensions})"
        )
        return True

    def fast_cv_jd_score(self, jd_text: str) -> float:
        """
        Fast CV-JD match using pre-cached CV embedding.
        Only embeds the JD text (not the CV every time).

        Args:
            jd_text: Job description text

        Returns:
            Similarity score (0.0-1.0), or 0.5 if CV not cached
        """
        if self._cv_embedding is None:
            return 0.5  # Neutral fallback

        jd_result = self.embed(jd_text, use_cache=True)
        if jd_result is None:
            return 0.5

        return self.cosine_similarity_vectors(
            self._cv_embedding, jd_result.vector
        )

    def batch_cv_jd_scores(
        self,
        jd_texts: List[str],
    ) -> List[float]:
        """
        Batch CV-JD matching for multiple job descriptions.
        Uses pre-cached CV embedding for efficiency.

        Args:
            jd_texts: List of job description texts

        Returns:
            List of similarity scores (0.0-1.0)
        """
        if self._cv_embedding is None:
            return [0.5] * len(jd_texts)

        jd_results = self.embed_batch(jd_texts, use_cache=True)
        scores = []
        for result in jd_results:
            if result is not None:
                score = self.cosine_similarity_vectors(
                    self._cv_embedding, result.vector
                )
                scores.append(max(0.0, min(1.0, score)))
            else:
                scores.append(0.5)

        return scores

    # ----------------------------------------------------------
    # BATCH SIMILARITY MATRIX
    # ----------------------------------------------------------

    def pairwise_similarity_matrix(
        self,
        texts: List[str],
    ) -> Optional[np.ndarray]:
        """
        Compute pairwise cosine similarity matrix for a list of texts.
        Used by A-06 Dedup for finding all duplicates in a batch.

        Args:
            texts: List of texts to compare

        Returns:
            NxN numpy matrix of similarity scores, or None on failure
        """
        if not texts:
            return None

        results = self.embed_batch(texts, use_cache=True)
        vectors = []
        for r in results:
            if r is not None:
                vectors.append(r.vector)
            else:
                vectors.append(np.zeros(self._dimensions))

        matrix = np.array(vectors)

        # Cosine similarity matrix (for normalized vectors: just dot product)
        if self._normalize:
            return np.dot(matrix, matrix.T)
        else:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1  # Avoid division by zero
            normalized = matrix / norms
            return np.dot(normalized, normalized.T)

    def find_duplicates_in_batch(
        self,
        texts: List[str],
        threshold: Optional[float] = None,
    ) -> List[Tuple[int, int, float]]:
        """
        Find all duplicate pairs in a batch of texts.
        Returns list of (index_a, index_b, similarity_score) for pairs
        above the threshold.

        Args:
            texts: List of texts to check
            threshold: Similarity threshold (default: dedup_threshold from config)

        Returns:
            List of (idx_a, idx_b, score) tuples for duplicate pairs
        """
        threshold = threshold or self._dedup_threshold
        sim_matrix = self.pairwise_similarity_matrix(texts)
        if sim_matrix is None:
            return []

        duplicates = []
        n = len(texts)
        for i in range(n):
            for j in range(i + 1, n):
                score = float(sim_matrix[i, j])
                if score >= threshold:
                    duplicates.append((i, j, round(score, 4)))

        return sorted(duplicates, key=lambda x: x[2], reverse=True)

    # ----------------------------------------------------------
    # HEALTH & MONITORING
    # ----------------------------------------------------------

    def get_health(self) -> Dict[str, Any]:
        """Get embedding engine health and statistics."""
        avg_latency = (
            self._total_latency_ms / self._total_embeddings
            if self._total_embeddings > 0 else 0
        )

        return {
            'model_loaded': self._model_loaded,
            'model_name': self._model_name,
            'dimensions': self._dimensions,
            'load_time_ms': round(self._load_time_ms, 0),
            'total_embeddings': self._total_embeddings,
            'total_comparisons': self._total_comparisons,
            'avg_latency_ms': round(avg_latency, 2),
            'cache': self._cache.get_stats(),
            'cv_embedding_cached': self._cv_embedding is not None,
            'cv_embedding_hash': self._cv_text_hash or 'none',
            'thresholds': {
                'dedup': self._dedup_threshold,
                'good_match': self._good_match_threshold,
                'excellent_match': self._excellent_match_threshold,
            },
        }

    def warmup(self):
        """
        Warm up the engine by loading the model and embedding a test text.
        Call this during startup if LAZY_LOAD_EMBEDDINGS=false.
        """
        logger.info("[EMBEDDING] Warming up engine...")
        start = time.time()

        if not self._ensure_model_loaded():
            logger.error("[EMBEDDING] Warmup failed: model not loaded")
            return

        # Embed a test text to warm up the inference pipeline
        test_result = self.embed("MBA internship marketing analytics India")
        if test_result:
            logger.info(
                f"[EMBEDDING] Warmup complete in {(time.time() - start) * 1000:.0f}ms "
                f"(test vector: {test_result.dimensions}d)"
            )
        else:
            logger.warning("[EMBEDDING] Warmup: test embedding failed")

    def unload_model(self):
        """
        Unload the model to free memory.
        Useful if memory is critically low on Render.
        """
        with self._model_lock:
            if self._model is not None:
                del self._model
                self._model = None
                self._model_loaded = False
                logger.info("[EMBEDDING] Model unloaded to free memory")

                # Force garbage collection
                import gc
                gc.collect()


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

_engine_instance: Optional[EmbeddingEngine] = None
_engine_lock = threading.Lock()


def get_embedding_engine() -> EmbeddingEngine:
    """Get the singleton EmbeddingEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = EmbeddingEngine()
    return _engine_instance


# ============================================================
# CLI / TESTING
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PRISM v0.1 — Embedding Engine Test")
    print("=" * 60)

    engine = get_embedding_engine()

    # Test basic embedding
    print("\n[TEST 1] Basic Embedding")
    result = engine.embed("MBA Marketing Internship at McKinsey India")
    if result:
        print(f"  Vector dims: {result.dimensions}")
        print(f"  Latency: {result.latency_ms:.1f}ms")
        print(f"  Cached: {result.cached}")
    else:
        print("  FAILED: sentence-transformers not installed")
        print("  Install with: pip install sentence-transformers")
        sys.exit(0)

    # Test similarity
    print("\n[TEST 2] Cosine Similarity")
    sim = engine.cosine_similarity(
        "Marketing Manager Internship at Unilever",
        "Brand Marketing Intern at Hindustan Unilever"
    )
    if sim:
        print(f"  Score: {sim.score:.4f} ({sim.score_percentage:.1f}%)")
        print(f"  Duplicate: {sim.is_duplicate}")
        print(f"  Good match: {sim.is_good_match}")

    # Test dedup
    print("\n[TEST 3] Semantic Duplicate Detection")
    is_dup, score = engine.is_semantic_duplicate(
        "Finance Analyst Intern at Goldman Sachs Mumbai",
        "Financial Analysis Internship - Goldman Sachs - Mumbai"
    )
    print(f"  Is duplicate: {is_dup} (score={score:.4f})")

    # Test CV-JD match
    print("\n[TEST 4] CV-JD Match Score (PPO V11)")
    cv = "MBA student with experience in financial modeling, equity research, Python, SQL"
    jd = "Seeking MBA intern for equity research role. Required: financial modeling, Python, SQL"
    match = engine.cv_jd_match_score(cv, jd)
    print(f"  Raw score: {match['raw_score']}")
    print(f"  Scaled score: {match['scaled_score']}")
    print(f"  Match level: {match['match_level']}")

    # Test batch
    print("\n[TEST 5] Batch Duplicate Finding")
    texts = [
        "Marketing Intern at HUL",
        "Brand Marketing Internship - Hindustan Unilever",
        "Finance Analyst Intern at JPMorgan",
        "Data Science Intern at Google",
    ]
    dups = engine.find_duplicates_in_batch(texts, threshold=0.5)
    for a, b, s in dups:
        print(f"  [{a}] vs [{b}]: {s:.4f}")

    # Health
    print("\n[HEALTH]")
    health = engine.get_health()
    for k, v in health.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
