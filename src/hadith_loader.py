# -*- coding: utf-8 -*-
# src/hadith_loader.py
# ─────────────────────────────────────────────────────────────────────────────
# Neo4j loader for src/data/hadith_data.py.
# Put this file beside db.py and put hadith_data.py inside src/data/.
# ─────────────────────────────────────────────────────────────────────────────

from db import Neo4jConnection
from data.hadith_data import (
    BOOKS, SOURCE_TYPES, HADITH_TYPES, PLACE_CLASSIFICATIONS,
    BOOK_SECTIONS, CHAPTERS, VOLUMES, PAGES, NARRATORS, HADITHS,
    HADITH_IN_BOOK, HADITH_HAS_SOURCE_TYPE, HADITH_HAS_TYPE,
    HADITH_IN_SECTION, HADITH_IN_CHAPTER, HADITH_ON_PAGE,
    HADITH_NARRATED_BY, HADITH_CHAIN_NARRATORS, HADITH_NUMBERS,
)

CONSTRAINTS = [
    "CREATE CONSTRAINT hadith_auto_id IF NOT EXISTS FOR (h:Hadith) REQUIRE h.auto_id IS UNIQUE",
    "CREATE CONSTRAINT hadith_book_id IF NOT EXISTS FOR (b:HadithBook) REQUIRE b.book_id IS UNIQUE",
    "CREATE CONSTRAINT hadith_source_type IF NOT EXISTS FOR (t:HadithSourceType) REQUIRE t.type_id IS UNIQUE",
    "CREATE CONSTRAINT hadith_type_name IF NOT EXISTS FOR (t:HadithType) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT hadith_section_key IF NOT EXISTS FOR (s:HadithBookSection) REQUIRE s.section_key IS UNIQUE",
    "CREATE CONSTRAINT hadith_chapter_key IF NOT EXISTS FOR (c:HadithChapter) REQUIRE c.chapter_key IS UNIQUE",
    "CREATE CONSTRAINT hadith_volume_key IF NOT EXISTS FOR (v:HadithVolume) REQUIRE v.volume_key IS UNIQUE",
    "CREATE CONSTRAINT hadith_page_key IF NOT EXISTS FOR (p:HadithPage) REQUIRE p.page_key IS UNIQUE",
    "CREATE CONSTRAINT narrator_name IF NOT EXISTS FOR (n:Narrator) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT place_classification_name IF NOT EXISTS FOR (p:PlaceClassification) REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT hadith_number IF NOT EXISTS FOR (n:HadithNumber) REQUIRE n.number IS UNIQUE",
]


def setup_constraints(db: Neo4jConnection) -> None:
    for constraint in CONSTRAINTS:
        db.write(constraint)


def load_nodes(db: Neo4jConnection) -> None:
    db.write_batch("""
        UNWIND $rows AS row
        MERGE (b:HadithBook {book_id: row.book_id})
        SET b += row
    """, BOOKS)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (t:HadithSourceType {type_id: row.type_id})
        SET t += row
    """, SOURCE_TYPES)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (t:HadithType {name: row.name})
        SET t += row
    """, HADITH_TYPES)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (p:PlaceClassification {name: row.name})
        SET p += row
    """, PLACE_CLASSIFICATIONS)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (s:HadithBookSection {section_key: row.section_key})
        SET s += row
    """, BOOK_SECTIONS)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (c:HadithChapter {chapter_key: row.chapter_key})
        SET c += row
    """, CHAPTERS)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (v:HadithVolume {volume_key: row.volume_key})
        SET v += row
    """, VOLUMES)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (p:HadithPage {page_key: row.page_key})
        SET p += row
    """, PAGES)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (n:Narrator {name: row.name})
        SET n += row
    """, NARRATORS)

    db.write_batch("""
        UNWIND $rows AS row
        MERGE (h:Hadith {auto_id: row.auto_id})
        SET h += row
    """, HADITHS, batch_size=100)


def load_relationships(db: Neo4jConnection) -> None:
    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (b:HadithBook {book_id: row[1]})
        MERGE (h)-[:IN_BOOK]->(b)
    """, HADITH_IN_BOOK)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (t:HadithSourceType {type_id: row[1]})
        MERGE (h)-[:HAS_SOURCE_TYPE]->(t)
    """, HADITH_HAS_SOURCE_TYPE)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (t:HadithType {name: row[1]})
        MERGE (h)-[:HAS_HADITH_TYPE]->(t)
    """, HADITH_HAS_TYPE)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (s:HadithBookSection {section_key: row[1]})
        MERGE (h)-[:IN_SECTION]->(s)
    """, HADITH_IN_SECTION)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (c:HadithChapter {chapter_key: row[1]})
        MERGE (h)-[:IN_CHAPTER]->(c)
    """, HADITH_IN_CHAPTER)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (p:HadithPage {page_key: row[1]})
        MERGE (h)-[:ON_PAGE]->(p)
    """, HADITH_ON_PAGE)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (n:Narrator {name: row[1]})
        MERGE (h)-[r:NARRATED_BY]->(n)
        SET r.source = row[2]
    """, HADITH_NARRATED_BY)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MATCH (n:Narrator {name: row[2]})
        MERGE (h)-[r:HAS_CHAIN_NARRATOR {order: row[1]}]->(n)
    """, HADITH_CHAIN_NARRATORS, batch_size=500)

    db.write_batch("""
        UNWIND $rows AS row
        MATCH (h:Hadith {auto_id: row[0]})
        MERGE (num:HadithNumber {number: row[1]})
        MERGE (h)-[:HAS_NUMBER]->(num)
    """, HADITH_NUMBERS)

    db.write("""
        MATCH (s:HadithBookSection), (b:HadithBook {book_id: s.book_id})
        MERGE (s)-[:SECTION_OF]->(b)
    """)

    db.write("""
        MATCH (c:HadithChapter), (b:HadithBook {book_id: c.book_id})
        MERGE (c)-[:CHAPTER_OF]->(b)
    """)

    db.write("""
        MATCH (c:HadithChapter)
        WHERE c.section_key IS NOT NULL
        MATCH (s:HadithBookSection {section_key: c.section_key})
        MERGE (c)-[:CHAPTER_IN_SECTION]->(s)
    """)

    db.write("""
        MATCH (v:HadithVolume), (b:HadithBook {book_id: v.book_id})
        MERGE (v)-[:VOLUME_OF]->(b)
    """)

    db.write("""
        MATCH (p:HadithPage), (v:HadithVolume {volume_key: toString(p.book_id) + ':' + toString(p.folder_num)})
        MERGE (p)-[:PAGE_IN_VOLUME]->(v)
    """)


def load_all(db: Neo4jConnection, clear_first: bool = False) -> None:
    if clear_first:
        db.write("MATCH (n) DETACH DELETE n")

    setup_constraints(db)
    load_nodes(db)
    load_relationships(db)

    summary = db.read("""
        MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count
        ORDER BY count DESC
    """)
    rel_total = db.read("MATCH ()-[r]->() RETURN count(r) AS total")[0]["total"]

    print(" Hadith Graph Summary ")
    for row in summary:
        print(f"{row['label']:<24} {row['count']}")
    print(f"{'Relationships':<24} {rel_total}")
    print("="*40)


if __name__ == "__main__":
    with Neo4jConnection() as db:
        load_all(db, clear_first=True)
        print("✓ Hadith Knowledge Graph loaded.")
