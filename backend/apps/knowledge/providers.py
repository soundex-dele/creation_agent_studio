import requests
from django.conf import settings

from apps.enterprise.services import resolve_provider


class ProviderUnavailable(RuntimeError):
    pass


class EmbeddingVectors(list):
    def __init__(self, values, *, usage=None, model=""):
        super().__init__(values)
        self.usage = usage or {}
        self.model = model


def _provider(organization, provider_name, model):
    queryset = organization.providers.filter(is_active=True)
    if provider_name:
        queryset = queryset.filter(name=provider_name)
    provider = queryset.order_by("-routing_weight", "id").first()
    if provider is None:
        raise ProviderUnavailable("No active model provider is configured.")
    routed = resolve_provider(organization, model)
    if provider_name:
        secret = organization.secret_references.filter(name=provider.secret_ref).first() \
            if provider.secret_ref else None
        from apps.enterprise.services import resolve_secret
        api_key = resolve_secret(secret) if secret else ""
        return provider, api_key, model or (provider.available_models[0] if provider.available_models else "")
    if not routed:
        raise ProviderUnavailable("No active model provider is configured.")
    return routed["provider"], routed["api_key"], routed["model"]


def embed_texts(organization, provider_name, model, texts):
    provider, api_key, selected_model = _provider(organization, provider_name, model)
    if not selected_model:
        raise ProviderUnavailable("An embedding model must be configured.")
    response = requests.post(
        f"{provider.base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": selected_model,
            "input": texts,
            "dimensions": settings.KNOWLEDGE_EMBEDDING_DIMENSIONS,
        },
        timeout=provider.timeout_seconds,
    )
    if not response.ok:
        raise RuntimeError(f"Embedding provider returned HTTP {response.status_code}: {response.text[:200]}")
    payload = response.json()
    data = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") or [] for item in data]
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding provider returned an unexpected result count.")
    for vector in vectors:
        if len(vector) != settings.KNOWLEDGE_EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {settings.KNOWLEDGE_EMBEDDING_DIMENSIONS}, got {len(vector)}."
            )
    return EmbeddingVectors(
        vectors,
        usage=payload.get("usage") or {},
        model=payload.get("model") or selected_model,
    )


def answer_question(organization, provider_name, model, query, results):
    provider, api_key, selected_model = _provider(organization, provider_name, model)
    if not selected_model:
        raise ProviderUnavailable("An answer model must be configured.")
    sources = "\n\n".join(
        f"[{index}] {item['title']}"
        + (f" 第{item['page_number']}页" if item.get("page_number") else "")
        + f"\n{item['snippet']}"
        for index, item in enumerate(results, start=1)
    )
    response = requests.post(
        f"{provider.base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": selected_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": "仅依据给定资料回答。每个事实使用 [数字] 引用；资料不足时明确说明未找到足够依据。"},
                {"role": "user", "content": f"问题：{query}\n\n资料：\n{sources}"},
            ],
        },
        timeout=provider.timeout_seconds,
    )
    if not response.ok:
        raise RuntimeError(f"Answer provider returned HTTP {response.status_code}: {response.text[:200]}")
    payload = response.json()
    return (
        payload["choices"][0]["message"]["content"],
        payload.get("usage") or {},
        payload.get("model") or selected_model,
    )
