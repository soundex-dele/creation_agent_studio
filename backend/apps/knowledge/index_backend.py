import json

from django.conf import settings
from django.db import connection


_SQLITE_VEC_CONNECTION_IDS = set()


def load_sqlite_vec(db=None):
    db = db or connection
    if db.vendor != "sqlite":
        return
    raw = db.connection
    if raw is None:
        db.ensure_connection()
        raw = db.connection
    connection_id = id(raw)
    if connection_id in _SQLITE_VEC_CONNECTION_IDS:
        return
    raw.enable_load_extension(True)
    try:
        import sqlite_vec
        sqlite_vec.load(raw)
    finally:
        raw.enable_load_extension(False)
    _SQLITE_VEC_CONNECTION_IDS.add(connection_id)


def ensure_native_indexes(schema_editor=None):
    db = schema_editor.connection if schema_editor else connection
    dimensions = int(settings.KNOWLEDGE_EMBEDDING_DIMENSIONS)
    if db.vendor == "sqlite":
        load_sqlite_vec(db)
        raw = db.connection
        raw.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vector_index USING vec0(
                embedding float[{dimensions}],
                organization_id text partition key,
                knowledge_base_id integer partition key,
                document_id integer,
                revision integer
            )
        """)
        raw.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_lexical_index USING fts5(
                chunk_id UNINDEXED,
                organization_id UNINDEXED,
                knowledge_base_id UNINDEXED,
                document_id UNINDEXED,
                revision UNINDEXED,
                lexical_text
            )
        """)
    elif db.vendor == "postgresql":
        with db.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS knowledge_vector_index (
                    chunk_id bigint PRIMARY KEY REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
                    organization_id uuid NOT NULL,
                    knowledge_base_id bigint NOT NULL,
                    document_id bigint NOT NULL,
                    revision integer NOT NULL,
                    embedding vector({dimensions}) NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS knowledge_vector_hnsw_idx
                ON knowledge_vector_index USING hnsw (embedding vector_cosine_ops)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS knowledge_vector_scope_idx
                ON knowledge_vector_index (organization_id, knowledge_base_id, revision)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_lexical_index (
                    chunk_id bigint PRIMARY KEY REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
                    organization_id uuid NOT NULL,
                    knowledge_base_id bigint NOT NULL,
                    document_id bigint NOT NULL,
                    revision integer NOT NULL,
                    lexical_text text NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS knowledge_lexical_fts_idx
                ON knowledge_lexical_index USING gin (to_tsvector('simple', lexical_text))
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS knowledge_lexical_scope_idx
                ON knowledge_lexical_index (organization_id, knowledge_base_id, revision)
            """)


def native_index_health():
    try:
        if connection.vendor == "sqlite":
            load_sqlite_vec()
            with connection.cursor() as cursor:
                cursor.execute("SELECT vec_version()")
                cursor.fetchone()
                cursor.execute("""
                    SELECT COUNT(*) FROM sqlite_master
                    WHERE name IN ('knowledge_vector_index', 'knowledge_lexical_index')
                """)
                return cursor.fetchone()[0] == 2
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector'),
                           to_regclass('knowledge_vector_index') IS NOT NULL,
                           to_regclass('knowledge_lexical_index') IS NOT NULL
                """)
                return all(cursor.fetchone())
    except Exception:
        return False
    return False


def replace_document_index(document, chunks):
    if connection.vendor == "sqlite":
        load_sqlite_vec()
        raw = connection.connection
        raw.execute("DELETE FROM knowledge_vector_index WHERE document_id = ?", (document.id,))
        raw.execute("DELETE FROM knowledge_lexical_index WHERE document_id = ?", (document.id,))
        for chunk in chunks:
            if chunk.embedding:
                raw.execute(
                    "INSERT INTO knowledge_vector_index(rowid, embedding, organization_id, knowledge_base_id, document_id, revision) VALUES (?, ?, ?, ?, ?, ?)",
                    (chunk.id, json.dumps(chunk.embedding), str(document.organization_id), document.knowledge_base_id, document.id, chunk.revision),
                )
            raw.execute(
                "INSERT INTO knowledge_lexical_index(chunk_id, organization_id, knowledge_base_id, document_id, revision, lexical_text) VALUES (?, ?, ?, ?, ?, ?)",
                (chunk.id, str(document.organization_id), document.knowledge_base_id, document.id, chunk.revision, chunk.lexical_text),
            )
    elif connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM knowledge_vector_index WHERE document_id = %s", [document.id])
            cursor.execute("DELETE FROM knowledge_lexical_index WHERE document_id = %s", [document.id])
            for chunk in chunks:
                if chunk.embedding:
                    cursor.execute(
                        "INSERT INTO knowledge_vector_index(chunk_id, organization_id, knowledge_base_id, document_id, revision, embedding) VALUES (%s,%s,%s,%s,%s,%s::vector)",
                        [chunk.id, document.organization_id, document.knowledge_base_id, document.id, chunk.revision, json.dumps(chunk.embedding)],
                    )
                cursor.execute(
                    "INSERT INTO knowledge_lexical_index(chunk_id, organization_id, knowledge_base_id, document_id, revision, lexical_text) VALUES (%s,%s,%s,%s,%s,%s)",
                    [chunk.id, document.organization_id, document.knowledge_base_id, document.id, chunk.revision, chunk.lexical_text],
                )


def delete_document_index(document_id):
    load_sqlite_vec()
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM knowledge_vector_index WHERE document_id = %s",
            [document_id],
        )
        cursor.execute(
            "DELETE FROM knowledge_lexical_index WHERE document_id = %s",
            [document_id],
        )


def vector_candidates(organization_id, knowledge_base_ids, query_embedding, limit=50):
    if not query_embedding or not knowledge_base_ids:
        return []
    if connection.vendor == "sqlite":
        load_sqlite_vec()
        placeholders = ",".join("%s" for _ in knowledge_base_ids)
        params = [json.dumps(query_embedding), limit, str(organization_id), *knowledge_base_ids]
        sql = f"""
            SELECT rowid, distance FROM knowledge_vector_index
            WHERE embedding MATCH %s AND k = %s AND organization_id = %s
              AND knowledge_base_id IN ({placeholders})
            ORDER BY distance
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [(row[0], max(0.0, 1.0 - float(row[1]))) for row in cursor.fetchall()]
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score
                FROM knowledge_vector_index
                WHERE organization_id = %s AND knowledge_base_id = ANY(%s)
                ORDER BY embedding <=> %s::vector LIMIT %s
            """, [json.dumps(query_embedding), organization_id, knowledge_base_ids, json.dumps(query_embedding), limit])
            return [(row[0], float(row[1])) for row in cursor.fetchall()]
    return []


def lexical_candidates(organization_id, knowledge_base_ids, terms, limit=50):
    if not terms or not knowledge_base_ids:
        return []
    if connection.vendor == "sqlite":
        load_sqlite_vec()
        placeholders = ",".join("%s" for _ in knowledge_base_ids)
        match = " OR ".join(f'"{term}"' for term in terms)
        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT chunk_id, -bm25(knowledge_lexical_index) AS score
                FROM knowledge_lexical_index
                WHERE knowledge_lexical_index MATCH %s AND organization_id = %s
                  AND knowledge_base_id IN ({placeholders})
                ORDER BY bm25(knowledge_lexical_index) LIMIT %s
            """, [match, str(organization_id), *knowledge_base_ids, limit])
            return [(int(row[0]), float(row[1])) for row in cursor.fetchall()]
    if connection.vendor == "postgresql":
        query = " | ".join(terms)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT chunk_id,
                       ts_rank_cd(to_tsvector('simple', lexical_text), to_tsquery('simple', %s)) AS score
                FROM knowledge_lexical_index
                WHERE organization_id = %s AND knowledge_base_id = ANY(%s)
                  AND to_tsvector('simple', lexical_text) @@ to_tsquery('simple', %s)
                ORDER BY score DESC LIMIT %s
            """, [query, organization_id, knowledge_base_ids, query, limit])
            return [(row[0], float(row[1])) for row in cursor.fetchall()]
    return []
