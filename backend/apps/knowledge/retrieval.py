import math
import re

from .models import KnowledgeChunk, KnowledgeDocument
from .index_backend import lexical_candidates, vector_candidates


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def tokenize(value):
    return [token.lower() for token in TOKEN_PATTERN.findall(str(value or ""))]


def lexical_text(value):
    return " ".join(tokenize(value))


def estimate_tokens(value):
    return max(1, len(tokenize(value)) + math.ceil(len(value) / 12))


def _token_bounded_end(value, start, size):
    low, high = start + 1, len(value)
    best = low
    while low <= high:
        midpoint = (low + high) // 2
        if estimate_tokens(value[start:midpoint]) <= size:
            best = midpoint
            low = midpoint + 1
        else:
            high = midpoint - 1
    return min(best, len(value))


def _overlap_start(value, window_start, window_end, overlap):
    if overlap <= 0:
        return window_end
    low, high = window_start + 1, window_end
    best = window_end
    while low <= high:
        midpoint = (low + high) // 2
        if estimate_tokens(value[midpoint:window_end]) <= overlap:
            best = midpoint
            high = midpoint - 1
        else:
            low = midpoint + 1
    return best


def chunk_sections(sections, size, overlap):
    size = max(100, min(int(size), 1500))
    overlap = max(0, min(int(overlap), size // 2 - 1))
    chunks = []
    for section in sections:
        words = re.findall(r"\S+", section.text)
        if not words:
            continue
        start = 0
        while start < len(section.text):
            end = _token_bounded_end(section.text, start, size)
            if end < len(section.text):
                boundary = section.text.rfind("\n", start, end)
                if boundary <= start:
                    boundary = section.text.rfind("。", start, end)
                if boundary > start + (end - start) // 2:
                    end = boundary + 1
            value = section.text[start:end].strip()
            if value:
                chunks.append({
                    "content": value,
                    "token_count": estimate_tokens(value),
                    "page_number": section.page_number,
                    "section_path": list(section.section_path),
                    "lexical_text": lexical_text(value),
                    "metadata": {"paragraph_number": section.paragraph_number, "start": start, "end": end},
                })
            if end >= len(section.text):
                break
            start = max(start + 1, _overlap_start(
                section.text, start, end, overlap))
    return chunks


def cosine_similarity(left, right):
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def search(*, organization_id, query, knowledge_base_ids=None, limit=10, query_embedding=None,
           document_ids=None, internal=False):
    from .models import KnowledgeBase
    bases = KnowledgeBase.objects.filter(organization_id=organization_id, is_active=True)
    if not internal:
        bases = bases.filter(scope="organization")
    if knowledge_base_ids is not None:
        bases = bases.filter(pk__in=knowledge_base_ids)
    knowledge_base_ids = list(bases.values_list("pk", flat=True))
    if not knowledge_base_ids or document_ids == []:
        return "lexical", []
    terms = tokenize(query)
    queryset = KnowledgeChunk.objects.filter(
        organization_id=organization_id,
        document__status=KnowledgeDocument.Status.READY,
        document__is_deleted=False,
        revision=models_f("document__active_revision"),
    ).select_related("document", "document__knowledge_base")
    if knowledge_base_ids:
        queryset = queryset.filter(document__knowledge_base_id__in=knowledge_base_ids)
    if document_ids is not None:
        queryset = queryset.filter(document_id__in=document_ids)

    lexical_rows = lexical_candidates(
        organization_id, knowledge_base_ids or [], terms, 50, document_ids=document_ids)
    vector_rows = vector_candidates(
        organization_id, knowledge_base_ids or [], query_embedding, 50, document_ids=document_ids)
    candidate_ids = {item[0] for item in [*lexical_rows, *vector_rows]}
    chunks = {item.id: item for item in queryset.filter(id__in=candidate_ids)}
    lexical = [
        (chunks[chunk_id], score)
        for chunk_id, score in lexical_rows if chunk_id in chunks
    ]
    vector = [
        (chunks[chunk_id], score)
        for chunk_id, score in vector_rows if chunk_id in chunks
    ]
    by_id = {}
    for rank, (chunk, _) in enumerate(lexical, start=1):
        by_id.setdefault(chunk.id, [chunk, 0.0])[1] += 0.35 / (60 + rank)
    for rank, (chunk, _) in enumerate(vector, start=1):
        by_id.setdefault(chunk.id, [chunk, 0.0])[1] += 0.65 / (60 + rank)
    ranked = sorted(by_id.values(), key=lambda item: item[1], reverse=True)[:limit]
    mode = "hybrid" if query_embedding and vector and lexical else (
        "vector" if query_embedding and vector else "lexical")
    return mode, [serialize_result(chunk, score) for chunk, score in ranked]


def models_f(path):
    from django.db.models import F
    return F(path)


def serialize_result(chunk, score):
    document = chunk.document
    return {
        "chunk_id": chunk.id,
        "document_id": document.id,
        "knowledge_base_id": document.knowledge_base_id,
        "knowledge_base_name": document.knowledge_base.name,
        "title": document.title,
        "snippet": chunk.content,
        "score": round(float(score), 8),
        "page_number": chunk.page_number,
        "section_path": chunk.section_path,
        "citation": f"{document.title}#chunk-{chunk.position}",
    }
