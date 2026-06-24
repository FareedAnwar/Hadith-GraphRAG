# src/embeddings.py
# ─────────────────────────────────────────────────────────────────────────────
# Ollama embeddings for Hadith GraphRAG
#
# This version:
#   - Embeds Narrator nodes only
#   - Embedding text = narrator name only
#   - Search returns Narrator nodes only
#   - Uses elementId() instead of deprecated id()
#   - Removes old embeddings from all nodes before creating narrator embeddings
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
from typing import Any

import httpx
import numpy as np
from dotenv import load_dotenv

from db import Neo4jConnection

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")



def _first_value(props: dict, *keys: str, default: str = "") -> str:
    """Return the first non-empty property value from possible keys."""
    for key in keys:
        value = props.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def narrator_to_text(props: dict) -> str:
    """
    Convert Narrator node to embedding text.

    Important:
    We embed the narrator name only.
    """
    return _first_value(
        props,
        "name",
        "full_name",
        "arabic_name",
        default="Unknown narrator",
    )


# Keep this name because other files may import/use node_to_text
def node_to_text(props: dict, label: str) -> str:
    if label == "Narrator":
        return narrator_to_text(props)
    return ""


# Ollama Embedding Calls

def embed_text(text: str) -> list[float]:
    """Embed a single text using Ollama /api/embed."""
    text = str(text).strip()

    if not text:
        raise ValueError("Cannot embed empty text.")

    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={
            "model": EMBED_MODEL,
            "input": text,
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()
    embeddings = data.get("embeddings")

    if not embeddings:
        raise RuntimeError(f"Ollama returned no embeddings. Response: {data}")

    return embeddings[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed texts one by one using local Ollama."""
    vectors = []

    for index, text in enumerate(texts, start=1):
        vectors.append(embed_text(text))

        if index % 100 == 0:
            print(f"  Embedded {index}/{len(texts)} narrators...")

    return vectors


# ─────────────────────────────────────────────────────────────────────────────
# Store Narrator Embeddings
# ─────────────────────────────────────────────────────────────────────────────

def clear_existing_embeddings(db: Neo4jConnection) -> None:
    """
    Remove old embeddings from all nodes.

    This is important if you previously embedded:
        Hadith
        HadithBook
        HadithChapter
        HadithPage
        etc.

    After this, only Narrator nodes will have embeddings.
    """
    db.write("""
        MATCH (n)
        REMOVE n.embedding, n.embedding_text
    """)

    print("  ✓ Old embeddings removed from all nodes")


def add_embeddings(db: Neo4jConnection, clear_existing: bool = True) -> None:
    """
    Embed Narrator nodes only.

    Stored properties:
        n.embedding
        n.embedding_text

    embedding_text will contain narrator name only.
    """
    if clear_existing:
        clear_existing_embeddings(db)

    rows = db.read("""
        MATCH (n:Narrator)
        RETURN n, elementId(n) AS eid
        ORDER BY n.name
    """)

    if not rows:
        print("  No Narrator nodes found, skipping.")
        return

    texts = []
    eids = []

    for row in rows:
        props = row["n"]
        text = narrator_to_text(props)

        if not text or text == "Unknown narrator":
            continue

        texts.append(text)
        eids.append(row["eid"])

    print(f"  Found {len(texts)} narrators to embed")

    vectors = embed_batch(texts)

    for index, (eid, vec, txt) in enumerate(zip(eids, vectors, texts), start=1):
        db.write(
            """
            MATCH (n)
            WHERE elementId(n) = $eid
            SET n.embedding = $vec,
                n.embedding_text = $txt
            """,
            {
                "eid": eid,
                "vec": json.dumps(vec),
                "txt": txt,
            },
        )

        if index % 100 == 0:
            print(f"  Stored {index}/{len(texts)} narrator embeddings...")

    print(f"  ✓ {len(texts)} Narrator nodes embedded")


# ─────────────────────────────────────────────────────────────────────────────
# Similarity Search
# ─────────────────────────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)

    return float(
        np.dot(va, vb) /
        (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9)
    )


def _node_display_name(props: dict, label: str) -> str:
    if label == "Narrator":
        return narrator_to_text(props)

    return _first_value(
        props,
        "name",
        "title",
        "auto_id",
        "id",
        default=label,
    )


def find_top_nodes(
    question: str,
    db: Neo4jConnection,
    top_k: int = 3,
    labels: list[str] | None = None,
) -> list[dict]:
    """
    Embed the question and return top_k similar Narrator nodes only.

    Important:
    This ignores the labels parameter on purpose.
    Search must stay on Narrator only.
    """
    q_vec = embed_text(question)

    rows = db.read("""
        MATCH (n:Narrator)
        WHERE n.embedding IS NOT NULL
        RETURN n, labels(n)[0] AS lbl
    """)

    scored = []

    for row in rows:
        props: dict[str, Any] = row["n"]

        try:
            vec = json.loads(props.get("embedding", "[]"))
        except Exception:
            continue

        if not vec:
            continue

        score = cosine_similarity(q_vec, vec)

        scored.append(
            {
                "label": row["lbl"],
                "name": _node_display_name(props, row["lbl"]),
                "score": score,
                "properties": props,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# Run directly
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with Neo4jConnection() as db:
        print(f"Using Ollama embeddings model: {EMBED_MODEL}")
        print("Computing embeddings for Narrator names only...")

        add_embeddings(db, clear_existing=True)

        print("\n✓ Narrator embeddings stored.")

        print("\nTest search: 'أبو هريرة'")
        results = find_top_nodes("أبو هريرة", db, top_k=5)

        for r in results:
            print(
                f"  [{r['label']:<16}] "
                f"{r['name']:<40} "
                f"score={r['score']:.3f}"
            )
