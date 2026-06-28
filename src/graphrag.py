# src/graphrag.py
# ─────────────────────────────────────────────────────────────────────────────
# GraphRAG pipeline for the Hadith Knowledge Graph.
#
# This version works with narrator-only embeddings:
#   1. Vector Search finds the closest Narrator nodes only
#   2. Graph Traversal gets all Hadiths connected to those Narrators
#   3. Context Assembly builds rich Hadith context
#   4. Ollama Qwen generates the final answer from context only
# ─────────────────────────────────────────────────────────────────────────────

import os
import re

import httpx
from dotenv import load_dotenv

from db import Neo4jConnection
from embeddings import find_top_nodes

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:3b")


# Helpers

def _validate_label(label: str) -> str:
    """Allow only safe Neo4j label names because labels cannot be parameterised."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
        raise ValueError(f"Invalid Neo4j label: {label}")
    return label


def _first_value(props: dict, *keys: str, default: str = "") -> str:
    """Return the first non-empty property value from possible keys."""
    for key in keys:
        value = props.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _clean_props(props: dict) -> dict:
    """Remove heavy/internal properties from context."""
    skip = {"embedding", "embedding_text"}
    return {k: v for k, v in props.items() if k not in skip and v is not None}


def _hadith_text(h: dict) -> str:
    text = _first_value(
        h,
        "text",
        "hadith_text",
        "arabic_text",
        "english_text",
        "matn",
        "content",
        "body",
        default="",
    )

    # Remove XML-like tags from hadith text
    text = re.sub(r"</?(SANAD|MATN|NAR)>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


# STAGE 2= Graph Traversal

def retrieve_narrator_hadith_context(
    narrator_name: str,
    db: Neo4jConnection,
    limit: int = 25,
) -> dict:
    """
    Retrieve rich Hadith context around a Narrator.

    Since embeddings are now stored only on Narrator nodes, this function expands
    from the narrator to connected Hadiths and retrieves their book, chapter,
    section, page, volume, type, source type, and number when available.
    """
    rows = db.read(
        """
        MATCH (n:Narrator {name: $name})
        OPTIONAL MATCH (n)<-[rel:NARRATED_BY|HAS_CHAIN_NARRATOR]-(h:Hadith)

        OPTIONAL MATCH (h)-[:IN_BOOK]->(b:HadithBook)
        OPTIONAL MATCH (h)-[:IN_SECTION]->(s:HadithBookSection)
        OPTIONAL MATCH (h)-[:IN_CHAPTER]->(c:HadithChapter)
        OPTIONAL MATCH (h)-[:ON_PAGE]->(p:HadithPage)
        OPTIONAL MATCH (p)-[:PAGE_IN_VOLUME]->(v:HadithVolume)
        OPTIONAL MATCH (h)-[:HAS_HADITH_TYPE]->(ht:HadithType)
        OPTIONAL MATCH (h)-[:HAS_SOURCE_TYPE]->(st:HadithSourceType)
        OPTIONAL MATCH (h)-[:HAS_NUMBER]->(num:HadithNumber)

        RETURN
            n AS narrator,
            h AS hadith,
            type(rel) AS relation,
            rel.order AS chain_order,
            rel.source AS relation_source,
            b AS book,
            s AS section,
            c AS chapter,
            p AS page,
            v AS volume,
            ht AS hadith_type,
            st AS source_type,
            num AS hadith_number
        ORDER BY h.auto_id, chain_order
        LIMIT $limit
        """,
        {
            "name": narrator_name,
            "limit": limit,
        },
    )

    if not rows:
        return {}

    narrator = rows[0].get("narrator")
    if not narrator:
        return {}

    return {
        "center": narrator,
        "label": "Narrator",
        "rows": rows,
    }


def retrieve_subgraph(
    node_name: str,
    node_label: str,
    db: Neo4jConnection,
    hops: int = 2,
) -> dict:
    """
    Retrieve graph context.

    Main path:
        Narrator → connected Hadiths → Book / Chapter / Section / Page / Type / Number

    Fallback:
        Generic traversal for non-Narrator labels, kept for API Explore page.
    """
    node_label = _validate_label(node_label)

    if node_label == "Narrator":
        return retrieve_narrator_hadith_context(
            narrator_name=node_name,
            db=db,
            limit=30,
        )

    hops = max(1, min(int(hops), 4))

    query = f"""
        MATCH (start:{node_label})
        WHERE toString(start.name) = $name
           OR toString(start.title) = $name
           OR toString(start.auto_id) = $name
           OR toString(start.id) = $name
           OR toString(start.book_id) = $name
           OR toString(start.type_id) = $name
           OR toString(start.section_key) = $name
           OR toString(start.chapter_key) = $name
           OR toString(start.volume_key) = $name
           OR toString(start.page_key) = $name

        CALL {{
            WITH start
            OPTIONAL MATCH path = (start)-[*1..{hops}]-(neighbor)
            WITH last(relationships(path)) AS rel
            WHERE rel IS NOT NULL
            RETURN collect(DISTINCT {{
                from: COALESCE(
                    startNode(rel).name,
                    startNode(rel).title,
                    toString(startNode(rel).auto_id),
                    toString(startNode(rel).book_id),
                    toString(startNode(rel).chapter_key),
                    toString(startNode(rel).section_key),
                    toString(startNode(rel).page_key),
                    labels(startNode(rel))[0]
                ),
                rel: type(rel),
                to: COALESCE(
                    endNode(rel).name,
                    endNode(rel).title,
                    toString(endNode(rel).auto_id),
                    toString(endNode(rel).book_id),
                    toString(endNode(rel).chapter_key),
                    toString(endNode(rel).section_key),
                    toString(endNode(rel).page_key),
                    labels(endNode(rel))[0]
                ),
                to_label: labels(endNode(rel))[0]
            }}) AS edges
        }}

        RETURN start, labels(start)[0] AS start_label, edges
        LIMIT 1
    """

    rows = db.read(query, {"name": str(node_name)})

    if not rows:
        return {}

    row = rows[0]

    return {
        "center": row["start"],
        "label": row["start_label"],
        "edges": [
            e for e in row.get("edges", [])
            if e.get("from") and e.get("to")
        ],
    }


# STAGE 3= Context Assembly

def _center_name(center: dict, label: str) -> str:
    for key in (
        "name",
        "title",
        "book_name",
        "chapter_name",
        "section_name",
        "auto_id",
        "id",
        "book_id",
        "chapter_key",
        "section_key",
        "page_key",
    ):
        value = center.get(key)
        if value is not None and str(value).strip():
            if label == "Hadith" and key in {"auto_id", "id"}:
                return f"Hadith {value}"
            return str(value)
    return "Unknown"


def _format_narrator_context(subgraph: dict) -> str:
    narrator = subgraph.get("center") or {}
    rows = subgraph.get("rows") or []

    narrator_name = _first_value(
        narrator,
        "name",
        "full_name",
        "arabic_name",
        default="Unknown narrator",
    )

    lines = [
        f"ENTITY: {narrator_name} [Narrator]",
        "",
        "CONNECTED HADITHS:",
    ]

    seen_hadiths = set()
    hadith_count = 0

    for row in rows:
        h = row.get("hadith")

        if not h:
            continue

        auto_id = _first_value(h, "auto_id", "id", "hadith_id", default="unknown")
        if auto_id in seen_hadiths:
            continue

        seen_hadiths.add(auto_id)
        hadith_count += 1

        text = _hadith_text(h)
        grade = _first_value(h, "grade", "hukm", "classification", "type", default="")
        relation = row.get("relation") or ""
        chain_order = row.get("chain_order")
        relation_source = row.get("relation_source") or ""

        book = row.get("book") or {}
        section = row.get("section") or {}
        chapter = row.get("chapter") or {}
        page = row.get("page") or {}
        volume = row.get("volume") or {}
        hadith_type = row.get("hadith_type") or {}
        source_type = row.get("source_type") or {}
        hadith_number = row.get("hadith_number") or {}

        book_name = _first_value(book, "name", "book_name", "arabic_name", "title", default="")
        section_name = _first_value(section, "name", "section_name", "title", default="")
        chapter_name = _first_value(chapter, "name", "chapter_name", "title", default="")
        page_key = _first_value(page, "page_key", "id", default="")
        volume_key = _first_value(volume, "volume_key", "id", default="")
        type_name = _first_value(hadith_type, "name", "type", default="")
        source_type_name = _first_value(source_type, "name", "type", default="")
        number_value = _first_value(hadith_number, "number", default="")

        lines.append("")
        lines.append(f"Hadith auto_id: {auto_id}")

        if number_value:
            lines.append(f"Hadith number: {number_value}")

        if text:
            lines.append(f"Text: {text}")

        if grade:
            lines.append(f"Grade/classification: {grade}")

        if type_name:
            lines.append(f"Hadith type: {type_name}")

        if source_type_name:
            lines.append(f"Source type: {source_type_name}")

        if relation:
            relation_line = f"Narrator relation: {relation}"
            if chain_order is not None:
                relation_line += f", chain_order={chain_order}"
            if relation_source:
                relation_line += f", source={relation_source}"
            lines.append(relation_line)

        if book_name:
            lines.append(f"Book: {book_name}")

        if section_name:
            lines.append(f"Section: {section_name}")

        if chapter_name:
            lines.append(f"Chapter: {chapter_name}")

        if volume_key:
            lines.append(f"Volume: {volume_key}")

        if page_key:
            lines.append(f"Page: {page_key}")

    if hadith_count == 0:
        lines.append("No connected Hadiths were found for this narrator.")

    return "\n".join(lines)


def _format_generic_context(subgraph: dict) -> str:
    if not subgraph or not subgraph.get("center"):
        return ""

    center = subgraph["center"]
    label = subgraph.get("label", "")

    props = ", ".join(
        f"{k}={v}" for k, v in _clean_props(center).items()
    )

    lines = [
        f"ENTITY: {_center_name(center, label)} [{label}]",
        f"Properties: {props}",
        "",
        "CONNECTIONS:",
    ]

    seen = set()

    for edge in subgraph.get("edges", []):
        triple = (edge["from"], edge["rel"], edge["to"])

        if triple in seen:
            continue

        seen.add(triple)
        lines.append(f"  • {edge['from']} –[{edge['rel']}]→ {edge['to']}")

    return "\n".join(lines)


def subgraph_to_context(subgraph: dict) -> str:
    """
    Convert a subgraph dict into LLM-readable text.

    Narrator subgraphs get rich Hadith context.
    Other labels use generic relationship text.
    """
    if not subgraph or not subgraph.get("center"):
        return ""

    if subgraph.get("label") == "Narrator":
        return _format_narrator_context(subgraph)

    return _format_generic_context(subgraph)


# STAGE 4= LLM Answer Generation using Ollama Qwen

SYSTEM_PROMPT = """You are a careful assistant for a Hadith knowledge graph system.

Use only the structured context provided in the user message. Do not invent
hadith text, narrators, grading, references, explanations, or religious rulings.
If the context is insufficient, say clearly that the available data is insufficient.
Answer in the same language as the user's question when possible.
Keep the answer direct, clear, and concise."""


def generate_answer(question: str, context: str) -> str:
    """Generate a final answer using local Ollama Qwen."""
    if not context.strip():
        return "لم أجد سياقًا كافيًا داخل قاعدة البيانات للإجابة على هذا السؤال."

    user_msg = f"""Answer the question using ONLY this Hadith knowledge graph context.

QUESTION:
{question}

CONTEXT:
{context}

Rules:
- Use only the context above.
- If the question asks about narrations, روايات, أحاديث, or اعرض, list the connected Hadith records.
- For each Hadith, show:
  1. Hadith auto_id
  2. Hadith number if available
  3. Hadith text if available
  4. Book, chapter, section, page if available
- Do NOT answer with narrator names only unless the user asks specifically for narrators.
- Do NOT output raw tags such as <NAR>, </NAR>, <SANAD>, <MATN>.
- Do NOT answer with relationship names only like HAS_CHAIN_NARRATOR or NARRATED_BY.
- If the context is not enough, say the available data is insufficient.
- Do not invent facts.
- Answer in Arabic if the question is Arabic.
"""

    response = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_LLM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_msg,
                },
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        },
        timeout=180,
    )

    response.raise_for_status()

    data = response.json()
    return data["message"]["content"].strip()


# FULL PIPELINE

def graphrag_answer(
    question: str,
    db: Neo4jConnection,
    top_k: int = 3,
    hops: int = 2,
    verbose: bool = False,
) -> dict:
    """
    Answer a question about Hadith using the full GraphRAG pipeline.

    Since embeddings are narrator-only, relevant_nodes will be Narrator nodes.
    For each narrator, we retrieve connected Hadith context from Neo4j.
    """
    relevant_nodes = find_top_nodes(question, db, top_k=top_k)

    if not relevant_nodes:
        return {
            "answer": "لم أجد أي رواة مرتبطين بالسؤال داخل قاعدة بيانات الأحاديث.",
            "context": "",
            "retrieved_nodes": [],
        }

    if verbose:
        print(f"\n[Vector Search] Top {top_k} narrator nodes:")
        for n in relevant_nodes:
            print(f"  [{n['label']:<16}] {n['name']:<40} score={n['score']:.3f}")

    context_blocks = []

    for node in relevant_nodes:
        sg = retrieve_subgraph(
            node_name=node["name"],
            node_label=node["label"],
            db=db,
            hops=hops,
        )

        block = subgraph_to_context(sg)

        if block:
            context_blocks.append(block)

    context = "\n\n───────────────────────────────────\n\n".join(context_blocks)

    if verbose:
        fact_count = context.count("Hadith auto_id:")
        print(
            f"[Traversal] {fact_count} connected Hadith records "
            f"collected across {len(context_blocks)} narrator subgraphs"
        )

    answer = generate_answer(question, context)

    return {
        "answer": answer,
        "context": context,
        "retrieved_nodes": [
            {
                "name": n["name"],
                "label": n["label"],
                "score": n["score"],
            }
            for n in relevant_nodes
        ],
    }


# QUICK TEST

if __name__ == "__main__":
    questions = [
        "أبو هريرة",
        "اعرض روايات أبي هريرة",
        "ما الأحاديث المرتبطة بعمر بن الخطاب؟",
    ]

    with Neo4jConnection() as db:
        print(f"Using Ollama LLM model: {OLLAMA_LLM_MODEL}")

        for q in questions:
            print(f"\n{'=' * 65}")
            print(f"Q: {q}")
            print("─" * 65)

            result = graphrag_answer(
                question=q,
                db=db,
                top_k=3,
                hops=2,
                verbose=True,
            )

            print(f"\nA: {result['answer']}")
