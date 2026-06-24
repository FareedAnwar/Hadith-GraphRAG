# Hadith GraphRAG — Complete Project Walkthrough

This document explains the current Hadith GraphRAG project, file by file and concept by concept.

---

## Table of Contents

1. [What problem does this solve?](#1-what-problem-does-this-solve)
2. [Big picture flow](#2-big-picture-flow)
3. [Knowledge graph design](#3-knowledge-graph-design)
4. [File-by-file breakdown](#4-file-by-file-breakdown)
5. [Embeddings design](#5-embeddings-design)
6. [GraphRAG pipeline](#6-graphrag-pipeline)
7. [FastAPI layer](#7-fastapi-layer)
8. [Streamlit layer](#8-streamlit-layer)
9. [Docker and infrastructure](#9-docker-and-infrastructure)
10. [Known limitations and next improvements](#10-known-limitations-and-next-improvements)

---

## 1. What Problem Does This Solve?

A normal RAG system stores documents as text chunks and searches by semantic similarity.

That is useful for document Q&A, but Hadith data is relational:

- A Hadith belongs to a book.
- A Hadith belongs to a chapter.
- A Hadith has a number.
- A Hadith may have a type and source type.
- A Hadith has narrators.
- A narrator can be connected to many Hadith records.
- A chain narrator can appear at a specific order in the chain.

A graph database is better for this kind of data because it can answer connection questions directly:

```text
Narrator → Hadith → Book → Chapter → Page → Volume
```

GraphRAG combines graph traversal with LLM generation:

1. Use embeddings to find relevant graph nodes.
2. Use Cypher to retrieve connected facts from Neo4j.
3. Convert graph facts into clear context.
4. Ask the LLM to answer using only that context.

---

## 2. Big Picture Flow

```text
DATA SETUP
──────────────────────────────────────────────
src/data/hadith_data.py
        ↓
src/hadith_loader.py
        ↓
Neo4j graph nodes + relationships
        ↓
src/embeddings.py
        ↓
Narrator nodes get embedding + embedding_text


USER REQUEST
──────────────────────────────────────────────
User asks in Streamlit
        ↓
app.py sends POST /ask
        ↓
api.py receives the question
        ↓
graphrag.py runs the pipeline
        ↓
embeddings.py finds similar Narrator nodes
        ↓
graphrag.py retrieves connected Hadiths
        ↓
Qwen via Ollama generates final answer
        ↓
Streamlit displays answer + used nodes
```

---

## 3. Knowledge Graph Design

### Nodes

| Label | Description |
|---|---|
| `Hadith` | Main Hadith record |
| `Narrator` | Person who narrated or appears in the chain |
| `HadithBook` | Book or collection |
| `HadithBookSection` | Section inside a book |
| `HadithChapter` | Chapter inside a book/section |
| `HadithVolume` | Volume |
| `HadithPage` | Page |
| `HadithType` | Hadith type |
| `HadithSourceType` | Source classification |
| `HadithNumber` | Hadith number |
| `PlaceClassification` | Place-related classification |

### Relationships

```cypher
(Hadith)-[:IN_BOOK]->(HadithBook)
(Hadith)-[:IN_SECTION]->(HadithBookSection)
(Hadith)-[:IN_CHAPTER]->(HadithChapter)
(Hadith)-[:ON_PAGE]->(HadithPage)
(HadithPage)-[:PAGE_IN_VOLUME]->(HadithVolume)
(Hadith)-[:HAS_HADITH_TYPE]->(HadithType)
(Hadith)-[:HAS_SOURCE_TYPE]->(HadithSourceType)
(Hadith)-[:HAS_NUMBER]->(HadithNumber)
(Hadith)-[:NARRATED_BY {source}]->(Narrator)
(Hadith)-[:HAS_CHAIN_NARRATOR {order}]->(Narrator)
```

### Why this ontology works

It keeps the Hadith record as the central node. Everything else describes or connects to it. That makes retrieval easy:

```text
Start from Narrator
→ collect Hadith records
→ enrich each Hadith with book/chapter/page/type/number
→ send structured context to LLM
```

---

## 4. File-by-File Breakdown

### `src/db.py`

A small wrapper around the Neo4j Python driver.

Main methods:

```python
read(query, params) -> list[dict]
write(query, params) -> None
write_batch(query, rows, batch_size) -> int
close() -> None
```

Why it exists:

- Keeps database access in one place.
- Reads credentials from `.env`.
- Uses one Neo4j driver instance per process.
- Supports batch loading with `UNWIND`.

---

### `src/hadith_loader.py`

Loads all graph data from `src/data/hadith_data.py`.

Main steps:

1. Create uniqueness constraints.
2. Load all node types.
3. Load all relationship types.
4. Print node and relationship summary.

Important design:

```python
load_all(db, clear_first=True)
```

When `clear_first=True`, the loader clears the graph first:

```cypher
MATCH (n) DETACH DELETE n
```

Then it rebuilds the graph cleanly.

---

### `src/embeddings.py`

Handles local Ollama embeddings.

Current design:

- Embeds `Narrator` nodes only.
- Embedding text is the narrator name only.
- Stores:
  - `n.embedding`
  - `n.embedding_text`

The file uses Ollama endpoint:

```text
POST /api/embed
```

Default model:

```text
nomic-embed-text:latest
```

Search is brute-force:

1. Embed the question.
2. Load all narrator embeddings from Neo4j.
3. Compute cosine similarity in Python.
4. Return top-k narrators.

This is simple and works for small/medium datasets.

---

### `src/graphrag.py`

The core GraphRAG pipeline.

Main responsibilities:

1. Validate labels.
2. Retrieve rich narrator context.
3. Format graph data into LLM-readable text.
4. Call Qwen through Ollama.
5. Return answer, context, and retrieved nodes.

Default LLM:

```text
qwen2.5:3b
```

The system prompt is strict:

- Use only provided context.
- Do not invent Hadith text.
- Do not invent narrators or grading.
- Say clearly when data is insufficient.
- Answer in the user's language.

---

### `src/api.py`

FastAPI backend.

Important endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Confirms API and Neo4j are reachable |
| `POST /ask` | Runs the full GraphRAG pipeline |
| `GET /search` | Vector search over narrator nodes |
| `GET /graph/{entity_name}` | Returns graph context for an entity |
| `GET /stats` | Node/relationship counts |
| `POST /cypher` | Runs read-only Cypher |
| `GET /hadiths` | Lists Hadith records |
| `GET /books` | Lists books |
| `GET /narrator/{name}/narrations` | Lists narrations for a narrator |

Security note:

`/cypher` blocks common write keywords, but it is still a development endpoint. Do not expose it publicly without authentication.

---

### `src/app.py`

Streamlit frontend.

Pages:

| Page | Purpose |
|---|---|
| Chat | Ask questions |
| Explore | Browse graph context by entity |
| Hadiths | Browse Hadith records |
| Books | Browse books |
| Stats | View database statistics and run read-only Cypher |

The app talks to FastAPI using:

```python
API_URL = os.getenv("API_URL", "http://localhost:8000")
```

In Docker Compose, this becomes:

```text
http://api:8000
```

---

## 5. Embeddings Design

### What is embedded?

Only narrator names:

```text
أبو هريرة
عمر بن الخطاب
عبد الله بن عمر
...
```

### Why?

Because the first retrieval stage is narrator-first. The system finds likely narrators, then retrieves all connected Hadith records from the graph.

### Where embeddings are stored

Embeddings are stored directly on Neo4j nodes:

```cypher
(n:Narrator {
  name: "...",
  embedding: "[0.01, -0.02, ...]",
  embedding_text: "..."
})
```

### Pros

- Simple.
- No extra vector database.
- Easy to inspect in Neo4j.
- Good for narrator-focused questions.

### Cons

- Not ideal for topic-only questions.
- Brute-force search is slower at very large scale.
- It ignores Hadith text, chapters, and book sections.

### Recommended upgrade

Embed multiple labels:

```text
Narrator
Hadith
HadithChapter
HadithBookSection
HadithBook
```

Then search can answer both:

```text
اعرض روايات أبي هريرة
```

and:

```text
ما الأحاديث المرتبطة بالصلاة؟
```

---

## 6. GraphRAG Pipeline

### Stage 1 — Vector Search

Function:

```python
find_top_nodes(question, db, top_k)
```

Output example:

```json
[
  {"label": "Narrator", "name": "أبو هريرة", "score": 0.91},
  {"label": "Narrator", "name": "عبد الله بن عمر", "score": 0.82}
]
```

### Stage 2 — Graph Traversal

Function:

```python
retrieve_subgraph(node_name, node_label, db, hops)
```

For narrator nodes, it uses a rich query that retrieves:

- Hadith
- Book
- Section
- Chapter
- Page
- Volume
- Hadith type
- Source type
- Hadith number
- Relationship type and chain order

### Stage 3 — Context Assembly

Function:

```python
subgraph_to_context(subgraph)
```

The context is plain structured text, like:

```text
ENTITY: أبو هريرة [Narrator]

CONNECTED HADITHS:

Hadith auto_id: 123
Hadith number: 45
Text: ...
Narrator relation: HAS_CHAIN_NARRATOR, chain_order=2
Book: ...
Chapter: ...
Page: ...
```

### Stage 4 — LLM Answer Generation

Function:

```python
generate_answer(question, context)
```

It calls Ollama:

```text
POST http://localhost:11434/api/chat
```

and asks Qwen to answer from the context only.

---

## 7. FastAPI Layer

FastAPI is the stable interface between UI and graph logic.

### Example request

```http
POST /ask
Content-Type: application/json

{
  "question": "اعرض روايات أبي هريرة",
  "top_k": 3,
  "hops": 2
}
```

### Example response shape

```json
{
  "question": "اعرض روايات أبي هريرة",
  "answer": "...",
  "retrieved_nodes": [
    {"name": "أبو هريرة", "label": "Narrator", "score": 0.91}
  ],
  "context_preview": "ENTITY: أبو هريرة..."
}
```

---

## 8. Streamlit Layer

Streamlit is intentionally simple:

- Sidebar checks `/health`.
- Chat page sends `/ask`.
- Explore page uses `/graph` and `/search`.
- Hadiths page uses `/hadiths`.
- Books page uses `/books`.
- Stats page uses `/stats` and `/cypher`.

This makes it easy to replace later with React, Flutter, or another frontend.

---

## 9. Docker and Infrastructure

### Services

| Service | Role |
|---|---|
| `neo4j` | Stores graph |
| `ollama` | Hosts embedding model + LLM |
| `api` | Runs FastAPI |
| `streamlit` | Runs web UI |
| `loader` | One-off graph loading command |
| `embedder` | One-off embeddings command |
| `ollama-pull` | One-off model pull command |

### Typical Docker workflow

```bash
docker compose up --build
docker compose --profile setup up ollama-pull
docker compose run --rm loader
docker compose run --rm embedder
```

Then open Streamlit:

```text
http://localhost:8501
```

---

## 10. Known Limitations and Next Improvements

### 1. Narrator-only embeddings

Good for narrator questions, weaker for topic questions.

Recommended:

- Embed Hadith text.
- Embed chapters.
- Embed sections.

### 2. Brute-force similarity search

Current search loads all narrator embeddings and compares in Python.

Recommended:

- Use Neo4j vector index.
- Or move embeddings to Qdrant/Chroma/FAISS.

### 3. `/hadiths` and `/books` can return richer data

Current UI expects some optional fields like type/narrators/hadith_count. Add them to API queries for a cleaner UI.

### 4. `/cypher` endpoint is dev-only

It blocks write keywords but should still be protected before production.

### 5. LLM answer quality depends on context quality

The LLM is instructed not to invent. If graph context is sparse, answers should say data is insufficient.

---

## Interview / Teaching Summary

This project demonstrates:

- Property graph modeling with Neo4j.
- Cypher constraints and relationship traversal.
- Local embeddings with Ollama.
- GraphRAG instead of plain chunk-based RAG.
- FastAPI backend design.
- Streamlit frontend integration.
- Docker Compose multi-service development.
