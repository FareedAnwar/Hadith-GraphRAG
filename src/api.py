# src/api.py
# ─────────────────────────────────────────────────────────────────────────────
# FastAPI backend for the Hadith GraphRAG system.
#
# Endpoints:
#   POST /ask                  — GraphRAG question answering
#   GET  /search               — Vector similarity search over nodes
#   GET  /graph/{name}         — Return neighbourhood subgraph of an entity
#   GET  /stats                — Database statistics
#   GET  /health               — Health check
#   POST /cypher               — Run a raw read-only Cypher query (dev mode)
#   GET  /hadiths              — List Hadith nodes
#   GET  /books                — List Hadith books
#   GET  /narrator/{name}/narrations — Narrations connected to a narrator
# ─────────────────────────────────────────────────────────────────────────────

from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import Neo4jConnection
from embeddings import find_top_nodes
from graphrag import graphrag_answer, retrieve_subgraph, subgraph_to_context

load_dotenv()

app = FastAPI(
    title="Hadith GraphRAG API",
    description="Knowledge graph-powered question answering over Hadith data using Neo4j + Ollama",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single shared connection. Make sure Neo4j is running before starting FastAPI.
db = Neo4jConnection()


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, example="اعرض لي حديثًا عن النية")
    top_k: int = Field(default=3, ge=1, le=10, description="Number of starting nodes for graph traversal")
    hops: int = Field(default=2, ge=1, le=4, description="Traversal depth from each starting node")


class QuestionResponse(BaseModel):
    question: str
    answer: str
    retrieved_nodes: list[dict]
    context_preview: str


class CypherRequest(BaseModel):
    query: str = Field(..., example="MATCH (h:Hadith) RETURN h.auto_id LIMIT 5")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Confirm the API and database are reachable."""
    try:
        count = db.read("MATCH (n) RETURN count(n) AS total")[0]["total"]
        return {"status": "ok", "node_count": count}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/ask", response_model=QuestionResponse)
def ask(req: QuestionRequest):
    """
    Answer a natural language question about Hadith using GraphRAG.

    The pipeline:
    1. Embed the question using Ollama embeddings
    2. Find the most relevant graph nodes
    3. Traverse each node's neighbourhood
    4. Ask local Ollama Qwen to answer using only the retrieved context
    """
    try:
        result = graphrag_answer(
            question=req.question,
            db=db,
            top_k=req.top_k,
            hops=req.hops,
        )
        return QuestionResponse(
            question=req.question,
            answer=result["answer"],
            retrieved_nodes=result["retrieved_nodes"],
            context_preview=result["context"][:500],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search")
def search(
    q: str = Query(..., description="Search term"),
    top_k: int = Query(default=5, ge=1, le=20),
    label: Optional[str] = Query(
        default=None,
        description="Filter by node label: Hadith, Narrator, HadithBook, HadithChapter, HadithBookSection, HadithType, HadithSourceType, PlaceClassification, HadithVolume, HadithPage",
    ),
):
    """Vector similarity search over graph nodes."""
    try:
        labels = [label] if label else None
        results = find_top_nodes(q, db, top_k=top_k, labels=labels)
        return {
            "query": q,
            "results": [
                {"label": r["label"], "name": r["name"], "score": round(r["score"], 4)}
                for r in results
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/{entity_name}")
def get_subgraph(
    entity_name: str,
    label: str = Query(default="Hadith", description="Node label"),
    hops: int = Query(default=2, ge=1, le=4),
):
    """Return the neighbourhood subgraph of a named entity as structured text."""
    try:
        sg = retrieve_subgraph(entity_name, label, db, hops=hops)
        context = subgraph_to_context(sg)
        if not context:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' not found as {label}")
        return {"entity": entity_name, "label": label, "context": context}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
def stats():
    """Return counts of nodes and relationship types in the graph."""
    node_counts = db.read(
        """
        MATCH (n)
        RETURN labels(n)[0] AS label, count(n) AS count
        ORDER BY count DESC
        """
    )
    rel_counts = db.read(
        """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(r) AS count
        ORDER BY count DESC
        """
    )
    return {"nodes": node_counts, "relationships": rel_counts}


@app.post("/cypher")
def run_cypher(req: CypherRequest):
    """
    Execute a raw Cypher query in dev mode.

    Only read-style queries are allowed here. Write operations are rejected.
    """
    query_upper = req.query.strip().upper()
    forbidden = ["CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "CALL DBMS"]
    for word in forbidden:
        if word in query_upper:
            raise HTTPException(
                status_code=400,
                detail=f"Write operation '{word}' not permitted on this endpoint.",
            )
    try:
        rows = db.read(req.query)
        return {"results": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/hadiths")
def list_hadiths(limit: int = Query(default=20, ge=1, le=200)):
    """Return Hadith nodes with book/chapter context when available."""
    rows = db.read(
        """
        MATCH (h:Hadith)
        OPTIONAL MATCH (h)-[:IN_BOOK]->(b:HadithBook)
        OPTIONAL MATCH (h)-[:IN_CHAPTER]->(c:HadithChapter)
        RETURN h.auto_id AS auto_id,
               coalesce(h.text, h.hadith_text, h.arabic_text, h.english_text, h.matn, h.content, '') AS text,
               b.name AS book,
               c.name AS chapter
        ORDER BY h.auto_id
        LIMIT $limit
        """,
        {"limit": limit},
    )
    return {"hadiths": rows}


@app.get("/books")
def list_books(limit: int = Query(default=100, ge=1, le=500)):
    """Return Hadith books."""
    rows = db.read(
        """
        MATCH (b:HadithBook)
        RETURN b.book_id AS book_id,
               coalesce(b.name, b.book_name, b.title, b.arabic_name, '') AS name,
               b.author AS author,
               b.compiler AS compiler
        ORDER BY b.book_id
        LIMIT $limit
        """,
        {"limit": limit},
    )
    return {"books": rows}


@app.get("/narrator/{name}/narrations")
def narrator_narrations(name: str, limit: int = Query(default=50, ge=1, le=200)):
    """Return Hadiths connected to a narrator directly or through the chain."""
    rows = db.read(
        """
        MATCH (n:Narrator {name: $name})<-[r:NARRATED_BY|HAS_CHAIN_NARRATOR]-(h:Hadith)
        OPTIONAL MATCH (h)-[:IN_BOOK]->(b:HadithBook)
        RETURN h.auto_id AS auto_id,
               coalesce(h.text, h.hadith_text, h.arabic_text, h.english_text, h.matn, h.content, '') AS text,
               type(r) AS relation,
               r.order AS chain_order,
               r.source AS source,
               b.name AS book
        ORDER BY h.auto_id, chain_order
        LIMIT $limit
        """,
        {"name": name, "limit": limit},
    )
    return {"narrator": name, "narrations": rows}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
