# -*- coding: utf-8 -*-
# src/app.py
# ─────────────────────────────────────────────────────────────────────────────
# Streamlit frontend for the Hadith GraphRAG system.
#
# Pages:
#   💬 Chat      — Conversational Hadith question answering
#   🔍 Explore   — Browse the graph by entity
#   📜 Hadiths   — Browse Hadith records
#   📚 Books     — Browse Hadith books
#   📊 Stats     — Database and graph statistics
# ─────────────────────────────────────────────────────────────────────────────

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000")

LABELS = [
    "Hadith",
    "Narrator",
    "HadithBook",
    "HadithSourceType",
    "HadithType",
    "PlaceClassification",
    "HadithBookSection",
    "HadithChapter",
    "HadithVolume",
    "HadithPage",
    "HadithNumber",
]


# ─────────────────────────────────────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Hadith GraphRAG",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stChatMessage { border-radius: 12px; }
    .entity-chip {
        display: inline-block;
        background: #2E7D32;
        color: white;
        border-radius: 20px;
        padding: 2px 10px;
        margin: 2px;
        font-size: 0.8em;
    }
    .score-bar {
        height: 8px;
        background: linear-gradient(90deg, #2E7D32, #A5D6A7);
        border-radius: 4px;
    }
    .hadith-card {
        padding: 10px 12px;
        border: 1px solid #E0E0E0;
        border-radius: 10px;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# API Helper
# ─────────────────────────────────────────────────────────────────────────────

def api_post(endpoint: str, payload: dict) -> dict | None:
    try:
        r = httpx.post(f"{API_URL}{endpoint}", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.error(f"API error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        st.error(f"Connection error: {e}")
    return None


def api_get(endpoint: str, params: dict | None = None) -> dict | None:
    try:
        r = httpx.get(f"{API_URL}{endpoint}", params=params or {}, timeout=30)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.error(f"API error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        st.error(f"Connection error: {e}")
    return None


def shorten(text: str | None, limit: int = 260) -> str:
    if not text:
        return ""
    value = str(text).replace("\n", " ").strip()
    return value if len(value) <= limit else value[:limit - 3] + "..."


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📜 Hadith GraphRAG")
    st.caption("Hadith Knowledge Graph × LLM")
    st.divider()

    page = st.radio(
        "Navigate",
        ["💬 Chat", "🔍 Explore", "📜 Hadiths", "📚 Books", "📊 Stats"],
        label_visibility="collapsed",
    )

    st.divider()
    st.subheader("Chat Settings")
    top_k = st.slider(
        "Starting nodes (top_k)",
        1,
        6,
        3,
        help="How many graph nodes to use as context anchors",
    )
    hops = st.slider(
        "Traversal depth (hops)",
        1,
        4,
        2,
        help="How many relationship hops to follow from each node",
    )

    st.divider()
    health = api_get("/health")
    if health:
        st.success(f"✓ Graph: {health['node_count']} nodes")
    else:
        st.error("✗ API unreachable")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Chat
# ─────────────────────────────────────────────────────────────────────────────

if page == "💬 Chat":
    st.header("💬 Ask About the Hadith Data")
    st.caption("Answers are generated from the connected Hadith graph context only.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.expander("✨ Suggested questions", expanded=True):
        suggestions = [
            "ما الأحاديث المرتبطة بالصلاة؟",
            "ما الكتب الموجودة في بيانات الأحاديث؟",
            "من الرواة المرتبطون بالأحاديث المتاحة؟",
            "اعرض الأحاديث الموجودة في باب محدد.",
            "ما أنواع الأحاديث الموجودة في البيانات؟",
            "اذكر العلاقات المتاحة حول حديث معين.",
        ]
        cols = st.columns(2)
        for i, suggestion in enumerate(suggestions):
            if cols[i % 2].button(suggestion, use_container_width=True, key=f"sug_{i}"):
                st.session_state.pending_question = suggestion

    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and "nodes" in msg:
                with st.expander("📍 Nodes used as context", expanded=False):
                    for node in msg["nodes"]:
                        score_pct = int(node["score"] * 100)
                        st.markdown(
                            f'<span class="entity-chip">{node["label"]}</span> '
                            f'**{node["name"]}** — {score_pct}% match',
                            unsafe_allow_html=True,
                        )

    pending = st.session_state.pop("pending_question", None)
    user_input = st.chat_input("Ask about Hadith texts, narrators, books, chapters, or classifications...")
    question = pending or user_input

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Searching the Hadith knowledge graph..."):
                result = api_post("/ask", {"question": question, "top_k": top_k, "hops": hops})

            if result:
                st.markdown(result["answer"])

                with st.expander("📍 Nodes used as context", expanded=False):
                    for node in result["retrieved_nodes"]:
                        score_pct = int(node["score"] * 100)
                        st.markdown(
                            f'<span class="entity-chip">{node["label"]}</span> '
                            f'**{node["name"]}** — {score_pct}% match',
                            unsafe_allow_html=True,
                        )

                with st.expander("🕸️ Raw Hadith context", expanded=False):
                    st.code(result["context_preview"] + "\n...", language="text")

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "nodes": result["retrieved_nodes"],
                })
            else:
                st.error("Could not get a response. Please check the API connection.")

    if st.session_state.messages:
        if st.button("🗑️ Clear conversation", type="secondary"):
            st.session_state.messages = []
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Explore
# ─────────────────────────────────────────────────────────────────────────────

elif page == "🔍 Explore":
    st.header("🔍 Explore the Hadith Knowledge Graph")

    col1, col2 = st.columns([2, 1])
    with col1:
        entity_name = st.text_input("Entity value", placeholder="e.g. narrator name, book name, auto_id, chapter_key")
    with col2:
        entity_label = st.selectbox("Node label", LABELS)

    explore_hops = st.slider("Traversal depth", 1, 4, 2)

    if st.button("🔍 Explore", type="primary") and entity_name:
        with st.spinner("Traversing graph..."):
            result = api_get(f"/graph/{entity_name}", {"label": entity_label, "hops": explore_hops})

        if result:
            st.subheader(f"Neighbourhood of: {entity_name}")
            st.code(result["context"], language="text")

    st.divider()
    st.subheader("🔎 Similarity Search")
    search_q = st.text_input("Search by topic or keyword", placeholder="e.g. الصلاة، الزكاة، Narrator name")
    search_label = st.selectbox("Restrict to label", ["(all)"] + LABELS)

    if st.button("Search") and search_q:
        params = {"q": search_q, "top_k": 8}
        if search_label != "(all)":
            params["label"] = search_label

        results = api_get("/search", params)
        if results:
            st.subheader(f"Top matches for: '{search_q}'")
            for row in results["results"]:
                score_pct = int(row["score"] * 100)
                col_a, col_b, col_c = st.columns([3, 1, 2])
                col_a.write(f"**{row['name']}**")
                col_b.write(f"`{row['label']}`")
                col_c.progress(row["score"], text=f"{score_pct}%")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Hadiths
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📜 Hadiths":
    st.header("📜 Hadith Records")

    limit = st.slider("Number of records", 5, 100, 20, step=5)
    data = api_get("/hadiths", {"limit": limit})

    if data:
        records = data["hadiths"]
        st.caption(f"Showing {len(records)} Hadith records")

        for item in records:
            title = f"📜 Hadith #{item.get('auto_id', '')}"
            if item.get("book"):
                title += f" — {item['book']}"

            with st.expander(title):
                st.write(shorten(item.get("text"), 1200))
                col_a, col_b, col_c = st.columns(3)
                col_a.write(f"**Book:** {item.get('book') or '-'}")
                col_b.write(f"**Type:** {item.get('type') or '-'}")
                narrators = ", ".join(item.get("narrators") or [])
                col_c.write(f"**Narrators:** {narrators or '-'}")

                if st.button("Show graph context", key=f"ctx_{item.get('auto_id')}"):
                    result = api_get(f"/graph/{item.get('auto_id')}", {"label": "Hadith", "hops": 2})
                    if result:
                        st.code(result["context"], language="text")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Books
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📚 Books":
    st.header("📚 Hadith Books")

    data = api_get("/books", {"limit": 100})
    if data:
        books = data["books"]
        st.caption(f"Showing {len(books)} books")

        for book in books:
            name = book.get("arabic_name") or book.get("name") or f"Book {book.get('book_id')}"
            with st.expander(f"📚 {name}"):
                col_a, col_b, col_c = st.columns(3)
                col_a.write(f"**Book ID:** {book.get('book_id')}")
                col_b.write(f"**Hadith count:** {book.get('hadith_count')}")
                col_c.write(f"**Author:** {book.get('author') or '-'}")

                if st.button("Show graph context", key=f"book_{book.get('book_id')}"):
                    lookup_value = book.get("name") or book.get("arabic_name") or book.get("book_id")
                    result = api_get(f"/graph/{lookup_value}", {"label": "HadithBook", "hops": 2})
                    if result:
                        st.code(result["context"], language="text")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Stats
# ─────────────────────────────────────────────────────────────────────────────

elif page == "📊 Stats":
    st.header("📊 Knowledge Graph Statistics")

    data = api_get("/stats")
    if data:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Node Counts")
            total_nodes = sum(row["count"] for row in data["nodes"])
            st.metric("Total Nodes", total_nodes)
            for row in data["nodes"]:
                st.progress(row["count"] / max(total_nodes, 1), text=f"{row['label']}: {row['count']}")

        with col2:
            st.subheader("Relationship Counts")
            total_rels = sum(row["count"] for row in data["relationships"])
            st.metric("Total Relationships", total_rels)
            for row in data["relationships"]:
                st.progress(row["count"] / max(total_rels, 1), text=f"{row['rel_type']}: {row['count']}")

    st.divider()
    st.subheader("🔬 Try a Raw Cypher Query")
    st.caption("Read-only queries only")

    default_q = "MATCH (h:Hadith)-[:IN_BOOK]->(b:HadithBook) RETURN h.auto_id AS HadithId, b.name AS Book LIMIT 15"
    cypher_input = st.text_area("Cypher query", value=default_q, height=80)

    if st.button("▶ Run Query", type="primary"):
        result = api_post("/cypher", {"query": cypher_input})
        if result:
            st.caption(f"{result['count']} rows returned")
            st.dataframe(result["results"], use_container_width=True)
