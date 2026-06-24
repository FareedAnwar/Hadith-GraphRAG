# Cypher Query Practice — Hadith Knowledge Graph

This practice file is tailored for the **Hadith GraphRAG** project.

It uses the same graph structure loaded by `src/hadith_loader.py`:

```text
Hadith
Narrator
HadithBook
HadithBookSection
HadithChapter
HadithVolume
HadithPage
HadithType
HadithSourceType
HadithNumber
PlaceClassification
```

---

## 1. Open Neo4j Browser

Start Neo4j:

```bash
docker compose up neo4j -d
```

Open:

```text
http://localhost:7474
username: neo4j
password: hadith2026
```

Load the project data first:

```bash
cd src
python hadith_loader.py
```

---

## 2. Check Database Status

```cypher
MATCH (n)
RETURN labels(n)[0] AS label, count(n) AS count
ORDER BY count DESC;
```

```cypher
MATCH ()-[r]->()
RETURN type(r) AS relationship, count(r) AS count
ORDER BY count DESC;
```

---

## 3. Constraints Used by the Project

These are already created by `hadith_loader.py`, but they are useful to understand:

```cypher
CREATE CONSTRAINT hadith_auto_id IF NOT EXISTS
FOR (h:Hadith) REQUIRE h.auto_id IS UNIQUE;

CREATE CONSTRAINT narrator_name IF NOT EXISTS
FOR (n:Narrator) REQUIRE n.name IS UNIQUE;

CREATE CONSTRAINT hadith_book_id IF NOT EXISTS
FOR (b:HadithBook) REQUIRE b.book_id IS UNIQUE;

CREATE CONSTRAINT hadith_chapter_key IF NOT EXISTS
FOR (c:HadithChapter) REQUIRE c.chapter_key IS UNIQUE;
```

---

## 4. Finding Nodes

### List Hadith records

```cypher
MATCH (h:Hadith)
RETURN h.auto_id AS id,
       coalesce(h.text, h.hadith_text, h.arabic_text, h.matn, h.content) AS text
ORDER BY h.auto_id
LIMIT 20;
```

### List narrators

```cypher
MATCH (n:Narrator)
RETURN n.name AS narrator
ORDER BY narrator
LIMIT 50;
```

### List books

```cypher
MATCH (b:HadithBook)
RETURN b.book_id AS book_id,
       coalesce(b.name, b.book_name, b.title, b.arabic_name) AS book
ORDER BY book_id
LIMIT 50;
```

### Find one narrator by exact name

```cypher
MATCH (n:Narrator {name: "أبو هريرة"})
RETURN n;
```

### Search narrators by partial Arabic name

```cypher
MATCH (n:Narrator)
WHERE n.name CONTAINS "هريرة"
RETURN n.name AS narrator
ORDER BY narrator;
```

---

## 5. Relationships

### Hadith → Book

```cypher
MATCH (h:Hadith)-[:IN_BOOK]->(b:HadithBook)
RETURN h.auto_id AS hadith_id,
       coalesce(b.name, b.book_name, b.title, b.arabic_name) AS book
ORDER BY hadith_id
LIMIT 25;
```

### Hadith → Chapter

```cypher
MATCH (h:Hadith)-[:IN_CHAPTER]->(c:HadithChapter)
RETURN h.auto_id AS hadith_id,
       coalesce(c.name, c.chapter_name, c.title) AS chapter
ORDER BY hadith_id
LIMIT 25;
```

### Hadith → Main narrator

```cypher
MATCH (h:Hadith)-[r:NARRATED_BY]->(n:Narrator)
RETURN h.auto_id AS hadith_id,
       n.name AS narrator,
       r.source AS source
ORDER BY hadith_id
LIMIT 25;
```

### Hadith → Chain narrators

```cypher
MATCH (h:Hadith)-[r:HAS_CHAIN_NARRATOR]->(n:Narrator)
RETURN h.auto_id AS hadith_id,
       r.order AS chain_order,
       n.name AS narrator
ORDER BY hadith_id, chain_order
LIMIT 50;
```

---

## 6. Multi-Hop Traversal

### Narrator → Hadith → Book

```cypher
MATCH (n:Narrator {name: "أبو هريرة"})<-[:NARRATED_BY|HAS_CHAIN_NARRATOR]-(h:Hadith)-[:IN_BOOK]->(b:HadithBook)
RETURN DISTINCT h.auto_id AS hadith_id,
       coalesce(h.text, h.hadith_text, h.arabic_text, h.matn, h.content) AS text,
       coalesce(b.name, b.book_name, b.title, b.arabic_name) AS book
ORDER BY hadith_id
LIMIT 20;
```

### Narrator → Hadith → Chapter → Book

```cypher
MATCH (n:Narrator {name: "أبو هريرة"})<-[:NARRATED_BY|HAS_CHAIN_NARRATOR]-(h:Hadith)
OPTIONAL MATCH (h)-[:IN_CHAPTER]->(c:HadithChapter)
OPTIONAL MATCH (h)-[:IN_BOOK]->(b:HadithBook)
RETURN DISTINCT h.auto_id AS hadith_id,
       n.name AS narrator,
       coalesce(c.name, c.chapter_name, c.title) AS chapter,
       coalesce(b.name, b.book_name, b.title, b.arabic_name) AS book
ORDER BY hadith_id
LIMIT 20;
```

### Hadith → Page → Volume

```cypher
MATCH (h:Hadith)-[:ON_PAGE]->(p:HadithPage)-[:PAGE_IN_VOLUME]->(v:HadithVolume)
RETURN h.auto_id AS hadith_id,
       p.page_key AS page,
       v.volume_key AS volume
ORDER BY hadith_id
LIMIT 30;
```

---

## 7. Aggregation

### Number of Hadiths per book

```cypher
MATCH (h:Hadith)-[:IN_BOOK]->(b:HadithBook)
RETURN coalesce(b.name, b.book_name, b.title, b.arabic_name) AS book,
       count(h) AS hadith_count
ORDER BY hadith_count DESC;
```

### Most frequent narrators

```cypher
MATCH (h:Hadith)-[:NARRATED_BY|HAS_CHAIN_NARRATOR]->(n:Narrator)
RETURN n.name AS narrator,
       count(DISTINCT h) AS connected_hadiths
ORDER BY connected_hadiths DESC
LIMIT 20;
```

### Hadith count per type

```cypher
MATCH (h:Hadith)-[:HAS_HADITH_TYPE]->(t:HadithType)
RETURN t.name AS type,
       count(h) AS count
ORDER BY count DESC;
```

### Hadith count per source type

```cypher
MATCH (h:Hadith)-[:HAS_SOURCE_TYPE]->(s:HadithSourceType)
RETURN coalesce(s.name, s.type, toString(s.type_id)) AS source_type,
       count(h) AS count
ORDER BY count DESC;
```

---

## 8. Working with Properties

### Show hadith text safely

```cypher
MATCH (h:Hadith)
RETURN h.auto_id AS id,
       coalesce(h.text, h.hadith_text, h.arabic_text, h.english_text, h.matn, h.content, "") AS text
LIMIT 10;
```

### Find Hadiths containing a word

```cypher
MATCH (h:Hadith)
WITH h, coalesce(h.text, h.hadith_text, h.arabic_text, h.matn, h.content, "") AS text
WHERE text CONTAINS "الصلاة"
RETURN h.auto_id AS id, text
LIMIT 20;
```

### Check which narrators have embeddings

```cypher
MATCH (n:Narrator)
RETURN n.name AS narrator,
       n.embedding IS NOT NULL AS has_embedding,
       n.embedding_text AS embedding_text
ORDER BY has_embedding DESC, narrator
LIMIT 50;
```

---

## 9. GraphRAG Debug Queries

### Reproduce the API's narrator context

```cypher
MATCH (n:Narrator {name: "أبو هريرة"})
OPTIONAL MATCH (n)<-[rel:NARRATED_BY|HAS_CHAIN_NARRATOR]-(h:Hadith)
OPTIONAL MATCH (h)-[:IN_BOOK]->(b:HadithBook)
OPTIONAL MATCH (h)-[:IN_SECTION]->(s:HadithBookSection)
OPTIONAL MATCH (h)-[:IN_CHAPTER]->(c:HadithChapter)
OPTIONAL MATCH (h)-[:ON_PAGE]->(p:HadithPage)
OPTIONAL MATCH (p)-[:PAGE_IN_VOLUME]->(v:HadithVolume)
OPTIONAL MATCH (h)-[:HAS_HADITH_TYPE]->(ht:HadithType)
OPTIONAL MATCH (h)-[:HAS_SOURCE_TYPE]->(st:HadithSourceType)
OPTIONAL MATCH (h)-[:HAS_NUMBER]->(num:HadithNumber)
RETURN n AS narrator,
       h AS hadith,
       type(rel) AS relation,
       rel.order AS chain_order,
       b AS book,
       s AS section,
       c AS chapter,
       p AS page,
       v AS volume,
       ht AS hadith_type,
       st AS source_type,
       num AS hadith_number
ORDER BY h.auto_id, chain_order
LIMIT 30;
```

### Generic neighbourhood around any node

```cypher
MATCH (start:Narrator {name: "أبو هريرة"})
OPTIONAL MATCH path = (start)-[*1..2]-(neighbor)
RETURN path
LIMIT 25;
```

---

## 10. Read-Only Queries for `/cypher`

The API endpoint `/cypher` rejects write operations such as `CREATE`, `MERGE`, `SET`, and `DELETE`.

Safe example:

```cypher
MATCH (h:Hadith)-[:IN_BOOK]->(b:HadithBook)
RETURN h.auto_id AS HadithId, b.name AS Book
LIMIT 15
```

Blocked example:

```cypher
CREATE (:Test {name: "should not run"})
```

---

## 11. Practice Challenges

1. Return the first 10 Hadiths with book and chapter.
2. Find the narrator connected to the highest number of Hadiths.
3. Find Hadiths that have a page but no volume relationship.
4. List books that have sections.
5. List chapters grouped by book.
6. Find all Hadiths connected to a narrator through `HAS_CHAIN_NARRATOR`, ordered by chain order.
7. Count Hadiths by `HadithType`.
8. Count Hadiths by `HadithSourceType`.
9. Find Hadiths where the text contains a specific Arabic word.
10. Return a complete 2-hop graph around a selected Hadith.

---

## 12. Cypher Cheat Sheet

```cypher
-- Find nodes
MATCH (n:Label)
RETURN n
LIMIT 10;

-- Find relationships
MATCH (a)-[r:RELATIONSHIP]->(b)
RETURN a, r, b
LIMIT 10;

-- Optional relationships
OPTIONAL MATCH (h:Hadith)-[:IN_CHAPTER]->(c:HadithChapter)
RETURN h, c
LIMIT 10;

-- Filter
MATCH (n:Narrator)
WHERE n.name CONTAINS "أبو"
RETURN n;

-- Aggregate
MATCH (h:Hadith)-[:IN_BOOK]->(b:HadithBook)
RETURN b.name, count(h);

-- Multi-hop
MATCH path = (n:Narrator)-[*1..2]-(x)
RETURN path
LIMIT 20;
```
