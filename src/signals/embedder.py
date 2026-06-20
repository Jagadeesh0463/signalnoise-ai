"""
src/signals/embedder.py

Embedder — converts anonymized text into vectors and stores them in ChromaDB.
Uses MiniLM-L6-v2 (384-dimensional, fast, free, runs on CPU).

Pipeline position:
    Anonymizer → Embedder → Detector (BERTopic)

Design rules:
    - Only receives AnonymizedDocument — never raw text with PII
    - Model loaded once at module level — not per call
    - ChromaDB collection persists to disk (config.CHROMA_DB_PATH)

Usage:
    from src.signals.embedder import embed_document, get_all_embeddings

    embed_document(anon_doc)
    docs, embeddings, metadatas = get_all_embeddings()
"""

import logging
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from src.config import config
from src.exceptions import EmbeddingError
from src.models import AnonymizedDocument

logger = logging.getLogger(__name__)

# ── Model + ChromaDB — loaded once at module level ────────────────────────────

MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "signalnoise_documents"

_model: SentenceTransformer | None = None
_chroma_client: chromadb.PersistentClient | None = None
_collection = None


def _get_model() -> SentenceTransformer:
    """Load MiniLM model once. ~80MB download on first run."""
    global _model
    if _model is None:
        logger.info("Loading SentenceTransformer model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("Model loaded — embedding dimension: %d", _model.get_sentence_embedding_dimension())
    return _model


def _get_collection():
    """Get or create ChromaDB persistent collection."""
    global _chroma_client, _collection
    if _collection is None:
        db_path = str(config.CHROMA_DB_PATH)
        logger.info("Connecting to ChromaDB at: %s", db_path)
        _chroma_client = chromadb.PersistentClient(path=db_path)
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},   # cosine similarity for text
        )
        logger.info(
            "ChromaDB collection '%s' ready — %d documents stored.",
            COLLECTION_NAME,
            _collection.count(),
        )
    return _collection


# ── Public API ────────────────────────────────────────────────────────────────

def embed_document(anon_doc: AnonymizedDocument) -> list[float]:
    """
    Generate an embedding for one AnonymizedDocument and store it in ChromaDB.

    Args:
        anon_doc: Output from the Privacy Shield — anonymized text only.

    Returns:
        list[float] — 384-dimensional embedding vector.

    Raises:
        EmbeddingError: If embedding generation or ChromaDB storage fails.
    """
    if not anon_doc.anonymized_text.strip():
        raise EmbeddingError(
            f"AnonymizedDocument '{anon_doc.id[:8]}' has empty text — cannot embed."
        )

    try:
        model = _get_model()
        collection = _get_collection()

        # Generate embedding
        vector = model.encode(anon_doc.anonymized_text, show_progress_bar=False).tolist()

        # Store in ChromaDB with metadata for later retrieval
        collection.upsert(
            ids=[anon_doc.document_id],
            embeddings=[vector],
            documents=[anon_doc.anonymized_text],
            metadatas=[{
                "anon_doc_id": anon_doc.id,
                "document_id": anon_doc.document_id,
                "processed_at": anon_doc.processed_at.isoformat(),
            }],
        )

        logger.info(
            "Embedded doc_id=%s — vector dim=%d, stored in ChromaDB.",
            anon_doc.document_id[:8],
            len(vector),
        )
        return vector

    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError(
            f"Failed to embed doc_id={anon_doc.document_id[:8]}: {exc}"
        ) from exc


def embed_documents(anon_docs: list[AnonymizedDocument]) -> list[list[float]]:
    """
    Embed a batch of AnonymizedDocuments. More efficient than one-by-one.

    Args:
        anon_docs: List of AnonymizedDocuments from the Privacy Shield.

    Returns:
        List of 384-dimensional embedding vectors (one per document).

    Raises:
        EmbeddingError: If any document fails.
    """
    if not anon_docs:
        raise EmbeddingError("No documents provided for embedding.")

    try:
        model = _get_model()
        collection = _get_collection()

        texts = [doc.anonymized_text for doc in anon_docs]
        ids = [doc.document_id for doc in anon_docs]
        metadatas = [
            {
                "anon_doc_id": doc.id,
                "document_id": doc.document_id,
                "processed_at": doc.processed_at.isoformat(),
            }
            for doc in anon_docs
        ]

        logger.info("Embedding batch of %d documents...", len(anon_docs))
        vectors = model.encode(texts, show_progress_bar=False, batch_size=32).tolist()

        collection.upsert(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )

        logger.info(
            "Batch embedded %d documents — stored in ChromaDB. "
            "Collection total: %d.",
            len(anon_docs),
            collection.count(),
        )
        return vectors

    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError(f"Batch embedding failed: {exc}") from exc


def get_all_embeddings() -> tuple[list[str], list[list[float]], list[dict]]:
    """
    Retrieve all stored documents and their embeddings from ChromaDB.
    This is what the Detector (BERTopic) calls to get its input.

    Returns:
        Tuple of (documents, embeddings, metadatas)
        - documents:  list of anonymized text strings
        - embeddings: list of 384-dim vectors
        - metadatas:  list of metadata dicts
    """
    try:
        collection = _get_collection()
        count = collection.count()

        if count == 0:
            logger.warning("ChromaDB collection is empty — no documents to retrieve.")
            return [], [], []

        result = collection.get(include=["documents", "embeddings", "metadatas"])

        documents = result.get("documents", [])
        embeddings = result.get("embeddings", [])
        metadatas = result.get("metadatas", [])

        logger.info(
            "Retrieved %d documents from ChromaDB for signal detection.",
            len(documents),
        )
        return documents, embeddings, metadatas

    except Exception as exc:
        raise EmbeddingError(f"Failed to retrieve embeddings from ChromaDB: {exc}") from exc


def collection_size() -> int:
    """Return the number of documents currently stored in ChromaDB."""
    try:
        return _get_collection().count()
    except Exception:
        return 0
