"""
app/vector_store.py
-------------------
ChromaDB-based persistent vector store for GRC control embeddings.

Responsibilities:
  - Embed all GRC controls using the active embedding provider (Azure or Google)
  - Persist the index to disk (.chromadb/) so it survives app restarts
  - Use a hash of the inventory to detect changes and only re-embed when needed
  - Provide a query interface for semantic nearest-neighbour search

The index is keyed by a hash of the full inventory content. If the Excel file
changes (controls added/edited/removed), the hash changes → index rebuilds
automatically. If the inventory is unchanged, the cached index is reused
(zero embedding API calls on subsequent runs).
"""

from __future__ import annotations

import hashlib
import json
import logging

from config import AppConfig, EmbeddingConfig
from app.embedder import get_embedder, format_control_for_embedding

logger = logging.getLogger(__name__)

# ChromaDB collection name for GRC controls
_COLLECTION_NAME = "grc_controls"

# Metadata key used to store the inventory hash inside the ChromaDB collection
_HASH_METADATA_KEY = "inventory_hash"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_inventory(inventory: list[dict]) -> str:
    """
    Compute a stable SHA-256 hash of the inventory content.

    Used to detect whether the inventory has changed since the last index build.
    Sorting keys ensures consistent hashing regardless of dict key order.

    Args:
        inventory: List of control dicts from load_inventory().

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    serialised = json.dumps(inventory, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def _get_chroma_client():
    """
    Return a ChromaDB PersistentClient pointed at the configured data path.
    Lazy import to avoid import errors when chromadb is not installed.
    """
    try:
        import chromadb
    except ImportError as exc:
        raise ImportError(
            "chromadb package is required for RAG mode. "
            "Run: pip install chromadb"
        ) from exc

    return chromadb.PersistentClient(path=AppConfig.VECTOR_DB_PATH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_or_build_control_index(
    inventory: list[dict],
    force_rebuild: bool = False,
    progress_callback=None,
) -> object:
    """
    Return a ChromaDB collection containing embeddings for all GRC controls.

    Strategy:
      1. Compute hash of current inventory
      2. If a collection exists with the same hash → return it (cache hit)
      3. Otherwise → embed all controls and build a fresh collection

    Args:
        inventory:         List of control dicts from inventory.load_inventory().
        force_rebuild:     If True, always rebuild even if hash matches.
        progress_callback: Optional callable(message: str) for UI status updates.

    Returns:
        chromadb.Collection with all controls embedded and indexed.

    Raises:
        RuntimeError: If embedding configuration is missing or API calls fail.
        ImportError:  If chromadb is not installed.
    """
    client = _get_chroma_client()
    inventory_hash = _hash_inventory(inventory)

    # ── Try to use cached collection ──────────────────────────────────────────
    if not force_rebuild:
        try:
            collection = client.get_collection(_COLLECTION_NAME)
            stored_hash = collection.metadata.get(_HASH_METADATA_KEY, "")
            if stored_hash == inventory_hash:
                logger.info(
                    "Vector index cache hit — %d controls loaded from disk.",
                    collection.count(),
                )
                if progress_callback:
                    progress_callback(
                        f"✅ Index loaded from cache — {collection.count()} controls ready."
                    )
                return collection
            # Hash mismatch: inventory has changed → rebuild
            logger.info(
                "Inventory changed (hash mismatch) — rebuilding vector index."
            )
            client.delete_collection(_COLLECTION_NAME)
        except Exception:
            # Collection does not exist yet — normal on first run
            pass

    # ── Build fresh index ─────────────────────────────────────────────────────
    total = len(inventory)
    logger.info("Building vector index for %d controls...", total)

    if progress_callback:
        progress_callback(
            f"🔄 Building semantic index for {total} controls "
            f"using {EmbeddingConfig.provider_display()}..."
        )

    # Format controls as rich text for embedding
    texts = [format_control_for_embedding(ctrl) for ctrl in inventory]
    ids = [ctrl["control_id"] for ctrl in inventory]

    # Embed all controls (single batched call where the provider supports it)
    embedder = get_embedder()
    embeddings = embedder.embed_documents(texts)

    if len(embeddings) != len(inventory):
        raise RuntimeError(
            f"Embedding count mismatch: expected {len(inventory)}, "
            f"got {len(embeddings)}. Check embedding provider response."
        )

    # Sanitise metadata: ChromaDB requires all values to be str/int/float/bool
    metadatas = []
    for ctrl in inventory:
        metadatas.append({k: str(v) if v is not None else "" for k, v in ctrl.items()})

    # Create collection with hash stored in metadata
    collection = client.create_collection(
        name=_COLLECTION_NAME,
        metadata={
            _HASH_METADATA_KEY: inventory_hash,
            "provider": EmbeddingConfig.PROVIDER,
            "embedding_model": (
                EmbeddingConfig.AZURE_DEPLOYMENT
                if EmbeddingConfig.PROVIDER == "azure"
                else EmbeddingConfig.GOOGLE_MODEL
            ),
            "control_count": str(total),
        },
    )

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    logger.info("Vector index built — %d controls indexed.", total)

    if progress_callback:
        progress_callback(
            f"✅ Semantic index built — {total} controls indexed and ready."
        )

    return collection


def query_controls(
    collection,
    query_text: str,
    top_k: int = None,
) -> list[dict]:
    """
    Perform a semantic nearest-neighbour search against the control index.

    Args:
        collection: ChromaDB collection from get_or_build_control_index().
        query_text: The enforcement theme or root cause text to search for.
        top_k:      Number of results to return. Defaults to AppConfig.RETRIEVAL_TOP_K.

    Returns:
        List of dicts, each containing:
          - "control_id": str
          - "document":   str  (the formatted text used for embedding)
          - "metadata":   dict (original control fields)
          - "distance":   float (lower = more similar)
    """
    top_k = top_k or AppConfig.RETRIEVAL_TOP_K
    n_results = min(top_k, collection.count())

    if n_results == 0:
        return []

    embedder = get_embedder()
    query_embedding = embedder.embed_query(query_text)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for ctrl_id, doc, meta, dist in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({
            "control_id": ctrl_id,
            "document": doc,
            "metadata": meta,
            "distance": dist,
        })

    return output


def delete_control_index() -> bool:
    """
    Delete the persisted control index.

    Useful for forced rebuilds or during testing.

    Returns:
        True if the collection was deleted, False if it did not exist.
    """
    try:
        client = _get_chroma_client()
        client.delete_collection(_COLLECTION_NAME)
        logger.info("Vector index deleted.")
        return True
    except Exception:
        return False


def get_index_info() -> dict:
    """
    Return metadata about the current persisted index, or None if it doesn't exist.

    Returns:
        Dict with keys: control_count, provider, embedding_model, inventory_hash
        or None if no index exists.
    """
    try:
        client = _get_chroma_client()
        collection = client.get_collection(_COLLECTION_NAME)
        meta = collection.metadata or {}
        return {
            "control_count": collection.count(),
            "provider": meta.get("provider", "unknown"),
            "embedding_model": meta.get("embedding_model", "unknown"),
            "inventory_hash": meta.get(_HASH_METADATA_KEY, "unknown"),
        }
    except Exception:
        return None
