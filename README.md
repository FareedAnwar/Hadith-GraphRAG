# 📜 Hadith GraphRAG

A GraphRAG system for asking questions over a structured **Hadith knowledge graph**.

The project combines:

| Layer | Technology |
|---|---|
| Graph database | Neo4j |
| Local embeddings | Ollama `nomic-embed-text` |
| Local LLM | Ollama `qwen2.5:3b` |
| Backend API | FastAPI |
| Frontend | Streamlit |
| Data loader | Python + Cypher |

The current pipeline is intentionally focused on **Narrator-first retrieval**:

```text
User question
   ↓
Embed question with Ollama
   ↓
Find closest Narrator nodes
   ↓
Traverse connected Hadith records in Neo4j
   ↓
Build structured context
   ↓
Generate a grounded Arabic/English answer using Qwen
```

---

## Project Structure

```text
hadith-graphrag/
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.streamlit
├── requirements.txt
├── .env.example
└── src/
    ├── api.py              # FastAPI backend
    ├── app.py              # Streamlit frontend
    ├── db.py               # Neo4j connection wrapper
    ├── embeddings.py       # Ollama embeddings for Narrator nodes
    ├── graphrag.py         # GraphRAG retrieval + answer generation
    ├── hadith_loader.py    # Loads Hadith graph into Neo4j
    └── data/
        └── hadith_data.py  # Hadith dataset: nodes + relationships
```

---

## Knowledge Graph Ontology

### Main Nodes

| Label | Meaning | Common properties |
|---|---|---|
| `Hadith` | Hadith record | `auto_id`, `text`, `hadith_text`, `matn`, `grade` |
| `Narrator` | Hadith narrator | `name`, `full_name`, `arabic_name` |
| `HadithBook` | Book/source collection | `book_id`, `name`, `author`, `compiler` |
| `HadithBookSection` | Book section | `section_key`, `name`, `book_id` |
| `HadithChapter` | Chapter | `chapter_key`, `name`, `book_id`, `section_key` |
| `HadithVolume` | Volume | `volume_key`, `book_id` |
| `HadithPage` | Page | `page_key`, `book_id`, `folder_num` |
| `HadithType` | Hadith type | `name` |
| `HadithSourceType` | Source type | `type_id`, `name` |
| `HadithNumber` | Hadith number | `number` |
| `PlaceClassification` | Place classification | `name` |

### Main Relationships

```cypher
(Hadith)-[:IN_BOOK]->(HadithBook)
(Hadith)-[:IN_SECTION]->(HadithBookSection)
(Hadith)-[:IN_CHAPTER]->(HadithChapter)
(Hadith)-[:ON_PAGE]->(HadithPage)
(HadithPage)-[:PAGE_IN_VOLUME]->(HadithVolume)
(Hadith)-[:HAS_HADITH_TYPE]->(HadithType)
(Hadith)-[:HAS_SOURCE_TYPE]->(HadithSourceType)
(Hadith)-[:HAS_NUMBER]->(HadithNumber)
(Hadith)-[:NARRATED_BY]->(Narrator)
(Hadith)-[:HAS_CHAIN_NARRATOR {order}]->(Narrator)
```

---

## Setup Option A — Local Python + Local Ollama

### 1. Create environment file

```bash
cp .env.example .env
```

Default `.env`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=hadith2026

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=nomic-embed-text:latest
OLLAMA_LLM_MODEL=qwen2.5:3b

API_URL=http://localhost:8000
```

### 2. Start Neo4j

```bash
docker compose up neo4j -d
```

Open Neo4j Browser:

```text
http://localhost:7474
username: neo4j
password: hadith2026
```

### 3. Start Ollama and pull models

Install Ollama, then run:

```bash
ollama pull nomic-embed-text:latest
ollama pull qwen2.5:3b
```

### 4. Install Python dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 5. Load the Hadith graph

```bash
cd src
python hadith_loader.py
```

This creates constraints, loads nodes, loads relationships, and prints a graph summary.

### 6. Create narrator embeddings

```bash
python embeddings.py
```

This removes old embeddings and stores embeddings only on `Narrator` nodes.

### 7. Start FastAPI

```bash
uvicorn api:app --reload --port 8000
```

Open:

```text
http://localhost:8000/docs
```

### 8. Start Streamlit

Open a new terminal:

```bash
cd src
streamlit run app.py
```

Open:

```text
http://localhost:8501
```

---

## Setup Option B — Docker Compose

Start Neo4j, Ollama, FastAPI, and Streamlit:

```bash
docker compose up --build
```

Pull Ollama models into the Docker volume:

```bash
docker compose --profile setup up ollama-pull
```

Load graph data:

```bash
docker compose run --rm loader
```

Create embeddings:

```bash
docker compose run --rm embedder
```

Then open:

| Service | URL |
|---|---|
| Neo4j Browser | http://localhost:7474 |
| FastAPI Docs | http://localhost:8000/docs |
| Streamlit App | http://localhost:8501 |
| Ollama API | http://localhost:11434 |

---

## API Endpoints

### Health check

```bash
curl http://localhost:8000/health
```

### Ask a GraphRAG question

```bash
curl -X POST http://localhost:8000/ask ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"اعرض روايات أبي هريرة\",\"top_k\":3,\"hops\":2}"
```

macOS/Linux:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"اعرض روايات أبي هريرة","top_k":3,"hops":2}'
```

### Vector search over narrator nodes

```bash
curl "http://localhost:8000/search?q=أبو%20هريرة&top_k=5"
```

### Explore a graph entity

```bash
curl "http://localhost:8000/graph/أبو%20هريرة?label=Narrator&hops=2"
```

### List Hadith records

```bash
curl "http://localhost:8000/hadiths?limit=20"
```

### List books

```bash
curl "http://localhost:8000/books?limit=100"
```

### Narrator narrations

```bash
curl "http://localhost:8000/narrator/أبو%20هريرة/narrations?limit=20"
```

---

## Streamlit Pages

| Page | Purpose |
|---|---|
| 💬 Chat | Ask natural-language Hadith questions |
| 🔍 Explore | Explore an entity neighbourhood |
| 📜 Hadiths | Browse Hadith records |
| 📚 Books | Browse Hadith books |
| 📊 Stats | View graph counts and run read-only Cypher |

---

## Important Design Notes

### Why narrator-only embeddings?

The current `embeddings.py` embeds **Narrator** nodes only. This makes retrieval simple and focused:

```text
Question → similar narrators → connected hadiths
```

This is good when the main user questions are like:

- "اعرض روايات أبي هريرة"
- "ما الأحاديث المرتبطة بعمر بن الخطاب؟"
- "من الرواة المرتبطون بالأحاديث المتاحة؟"

### Limitation

If the user asks a topic-only question like:

```text
ما الأحاديث المرتبطة بالصلاة؟
```

narrator-only search may not be enough unless narrator names are semantically close to the query. For better topic search, extend embeddings to include `Hadith`, `HadithChapter`, and `HadithBookSection` nodes.

---

## Recommended Next Improvements

1. Embed Hadith text and chapters, not narrators only.
2. Add a Neo4j vector index instead of brute-force Python cosine search.
3. Add pagination and search filters for `/hadiths`.
4. Improve `/books` to return `hadith_count`.
5. Add authentication before exposing `/cypher`.
6. Add source references in the final LLM answer.

---

## Troubleshooting

### API says Neo4j is unreachable

Check:

```bash
docker compose ps
docker compose logs neo4j
```

Confirm your `.env` password matches the compose password.

### Ollama model not found

Run:

```bash
ollama pull nomic-embed-text:latest
ollama pull qwen2.5:3b
```

For Docker:

```bash
docker compose --profile setup up ollama-pull
```

### Streamlit cannot connect to API

Local mode:

```env
API_URL=http://localhost:8000
```

Docker mode:

```yaml
API_URL: http://api:8000
```

### Arabic text looks broken in terminal

Use a UTF-8 terminal and keep files saved as UTF-8.

---

## Safe Git Reminder

Do not commit `.env`, Neo4j data, or Ollama model volumes.
