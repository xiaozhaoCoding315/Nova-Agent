import asyncio
import psycopg
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from app.config import settings
from app.core.embedding.embedder import get_embedder
from app.utils.text_splitter import clean_markdown, chunk_document
from app.utils.entity_extractor import extract_entities, extract_relationships
from app.db.neo4j import upsert_entity, upsert_relationship, init_graph
from app.db import transaction

_qdrant = QdrantClient(url=settings.qdrant_url)
_embedder = get_embedder()


async def process_and_index(filename: str, raw_text: str) -> dict:
    """Full pipeline: clean → chunk → embed → index to Qdrant, PG, Neo4j.

    Code files (by extension) go through the declaration-aware chunker and
    keep their language tag in metadata; prose stays on the markdown chunker.
    """
    # 1. Clean (markdown cleaning is a no-op for code semantics, but
    # normalises excessive blank lines)
    clean = clean_markdown(raw_text)

    # 2. Chunk — language-aware dispatch
    chunks = chunk_document(clean, source=filename)

    # 3. Embed all chunk contents
    texts = [c.content for c in chunks]
    vectors = await _embedder.embed(texts)

    # 4. Store vectors in Qdrant
    points = [
        PointStruct(
            id=chunk.id,
            vector=vectors[i],
            payload={
                "content": chunk.content,
                "source": chunk.source,
                "chunk_index": chunk.metadata.get("chunk_index", i),
            }
        )
        for i, chunk in enumerate(chunks)
    ]
    _qdrant.upsert(collection_name="novatech_docs", points=points)

    # 5. Store text in PostgreSQL (metadata carries language for code files)
    queries = [
        (
            "INSERT INTO documents (id, content, source, metadata) VALUES (%s, %s, %s, %s)",
            (chunk.id, chunk.content, chunk.source, psycopg.types.json.Json(chunk.metadata)),
        )
        for chunk in chunks
    ]
    await transaction(queries)

    # 6. Extract entities + relationships → Neo4j
    all_entities = []
    all_relationships = []
    for chunk in chunks:
        all_entities.extend(extract_entities(chunk.content, chunk.source))
        all_relationships.extend(extract_relationships(chunk.content, chunk.source))

    # Deduplicate entities
    seen_entities = set()
    unique_entities = []
    for ent in all_entities:
        key = f"{ent['name'].lower()}:{ent['type']}"
        if key not in seen_entities:
            seen_entities.add(key)
            unique_entities.append(ent)

    # Deduplicate relationships
    seen_rels = set()
    unique_rels = []
    for rel in all_relationships:
        key = f"{rel['from'].lower()}|{rel['type']}|{rel['to'].lower()}"
        if key not in seen_rels:
            seen_rels.add(key)
            unique_rels.append(rel)

    # Write to Neo4j
    for ent in unique_entities:
        await upsert_entity(ent["name"], ent["type"], ent["source"])
    for rel in unique_rels[:500]:  # cap to avoid overload
        await upsert_relationship(rel["from"], rel["to"], rel["type"], rel["source"])

    return {
        "doc_id": filename,
        "chunks_count": len(chunks),
        "entities_count": len(unique_entities),
        "relationships_count": len(unique_rels),
    }
