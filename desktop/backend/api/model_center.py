"""Model configuration center mapping between UI payload and project config."""

from __future__ import annotations

import copy
from typing import Any, Dict

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_ROLE_PROVIDER = {
    "writing": "anthropic_primary",
    "analysis": "anthropic_analysis",
    "rag_llm": "rag_llm",
    "embedding": "rag_embedding",
    "rerank": "rag_rerank",
}
DEFAULT_PROVIDER_KIND = {
    "anthropic_primary": "anthropic",
    "anthropic_analysis": "anthropic",
    "anthropic_fallback": "anthropic",
    "rag_llm": "openai_compatible",
    "rag_embedding": "openai_compatible",
    "rag_rerank": "openai_compatible",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_providers(payload: Any) -> Dict[str, Dict[str, str]]:
    raw = _as_dict(payload)
    out: Dict[str, Dict[str, str]] = {}
    for provider_id, item in raw.items():
        if not isinstance(provider_id, str) or not provider_id.strip():
            continue
        data = _as_dict(item)
        out[provider_id] = {
            "kind": _as_str(data.get("kind"), "custom"),
            "api_key": _as_str(data.get("api_key")),
            "base_url": _as_str(data.get("base_url")),
        }
    return out


def _normalize_roles(payload: Any) -> Dict[str, Dict[str, Any]]:
    raw = _as_dict(payload)
    out: Dict[str, Dict[str, Any]] = {}
    for role_id, item in raw.items():
        if not isinstance(role_id, str) or not role_id.strip():
            continue
        data = _as_dict(item)
        role: Dict[str, Any] = {
            "provider": _as_str(data.get("provider")),
            "model": _as_str(data.get("model")),
        }
        for key in ("temperature", "timeout", "max_tokens", "dim"):
            if key in data:
                role[key] = data.get(key)
        out[role_id] = role
    return out


def _normalize_runtime(payload: Any) -> Dict[str, Any]:
    raw = _as_dict(payload)
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip():
            out[k] = v
    return out


def _normalize_pricing(payload: Any) -> Dict[str, Dict[str, float]]:
    raw = _as_dict(payload)
    out: Dict[str, Dict[str, float]] = {}
    for model_key, item in raw.items():
        if not isinstance(model_key, str) or not model_key.strip():
            continue
        data = _as_dict(item)
        out[model_key] = {
            "input": _as_float(data.get("input"), 0.0),
            "output": _as_float(data.get("output"), 0.0),
            "cache_read": _as_float(data.get("cache_read"), 0.0),
            "cache_write": _as_float(data.get("cache_write"), 0.0),
        }
    return out


def _ensure_provider(
    providers: Dict[str, Dict[str, str]],
    provider_id: str,
    *,
    kind: str,
    api_key: str,
    base_url: str,
) -> None:
    current = providers.get(provider_id, {})
    providers[provider_id] = {
        "kind": _as_str(current.get("kind"), kind),
        "api_key": api_key,
        "base_url": base_url,
    }


def _provider_config(
    providers: Dict[str, Dict[str, str]],
    provider_id: str,
    *,
    fallback_provider_id: str,
    default_kind: str = "custom",
) -> Dict[str, str]:
    data = _as_dict(providers.get(provider_id))
    if not data:
        data = _as_dict(providers.get(fallback_provider_id))
    return {
        "kind": _as_str(data.get("kind"), default_kind),
        "api_key": _as_str(data.get("api_key")),
        "base_url": _as_str(data.get("base_url")),
    }


def project_config_to_model_center(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build model-center payload from project config.yaml shape."""
    anthropic = _as_dict(config.get("anthropic"))
    fallback = _as_dict(anthropic.get("fallback"))
    writing_api_key = _as_str(anthropic.get("writing_api_key"), _as_str(anthropic.get("api_key")))
    writing_base_url = _as_str(
        anthropic.get("writing_base_url"),
        _as_str(anthropic.get("base_url"), DEFAULT_ANTHROPIC_BASE_URL),
    )
    analysis_api_key = _as_str(anthropic.get("analysis_api_key"), writing_api_key)
    analysis_base_url = _as_str(anthropic.get("analysis_base_url"), writing_base_url)
    analysis_provider_default = "anthropic_analysis"
    if analysis_api_key == writing_api_key and analysis_base_url == writing_base_url:
        analysis_provider_default = "anthropic_primary"

    lightrag = _as_dict(config.get("lightrag"))
    rag_llm = _as_dict(lightrag.get("llm"))
    rag_embedding = _as_dict(lightrag.get("embedding"))
    rag_rerank = _as_dict(lightrag.get("rerank"))

    metadata = _as_dict(config.get("model_center"))
    providers = _normalize_providers(metadata.get("providers"))
    roles = _normalize_roles(metadata.get("roles"))
    runtime = _normalize_runtime(metadata.get("runtime"))

    # Ensure defaults exist first
    for provider_id, kind in DEFAULT_PROVIDER_KIND.items():
        providers.setdefault(provider_id, {"kind": kind, "api_key": "", "base_url": ""})

    # Use current runtime config as source of truth for bound channels.
    _ensure_provider(
        providers,
        "anthropic_primary",
        kind="anthropic",
        api_key=writing_api_key,
        base_url=writing_base_url,
    )
    _ensure_provider(
        providers,
        "anthropic_analysis",
        kind="anthropic",
        api_key=analysis_api_key,
        base_url=analysis_base_url,
    )
    _ensure_provider(
        providers,
        "anthropic_fallback",
        kind="anthropic",
        api_key=_as_str(fallback.get("api_key")),
        base_url=_as_str(fallback.get("base_url"), DEFAULT_ANTHROPIC_BASE_URL),
    )
    _ensure_provider(
        providers,
        "rag_llm",
        kind="openai_compatible",
        api_key=_as_str(rag_llm.get("api_key")),
        base_url=_as_str(rag_llm.get("base_url")),
    )
    _ensure_provider(
        providers,
        "rag_embedding",
        kind="openai_compatible",
        api_key=_as_str(rag_embedding.get("api_key")),
        base_url=_as_str(rag_embedding.get("base_url")),
    )
    _ensure_provider(
        providers,
        "rag_rerank",
        kind="openai_compatible",
        api_key=_as_str(rag_rerank.get("api_key")),
        base_url=_as_str(rag_rerank.get("base_url")),
    )

    # Known roles with defaults, preserving custom provider bindings from metadata.
    writing_provider = _as_str(_as_dict(roles.get("writing")).get("provider"), "anthropic_primary")
    analysis_provider = _as_str(_as_dict(roles.get("analysis")).get("provider"), analysis_provider_default)
    rag_llm_provider = _as_str(_as_dict(roles.get("rag_llm")).get("provider"), "rag_llm")
    embedding_provider = _as_str(_as_dict(roles.get("embedding")).get("provider"), "rag_embedding")
    rerank_provider = _as_str(_as_dict(roles.get("rerank")).get("provider"), "rag_rerank")

    roles["writing"] = {
        **_as_dict(roles.get("writing")),
        "provider": writing_provider,
        "model": _as_str(anthropic.get("writing_model"), "claude-opus-4-6-20260205"),
        "temperature": _as_float(anthropic.get("writing_temperature"), 0.8),
    }
    roles["analysis"] = {
        **_as_dict(roles.get("analysis")),
        "provider": analysis_provider,
        "model": _as_str(anthropic.get("analysis_model"), "claude-sonnet-4-6-20260219"),
        "temperature": _as_float(anthropic.get("analysis_temperature"), 0.3),
    }
    roles["rag_llm"] = {
        **_as_dict(roles.get("rag_llm")),
        "provider": rag_llm_provider,
        "model": _as_str(rag_llm.get("model"), "qwen3.5-plus"),
        "timeout": _as_int(rag_llm.get("timeout"), 180),
        "max_tokens": _as_int(rag_llm.get("max_tokens"), 4096),
    }
    roles["embedding"] = {
        **_as_dict(roles.get("embedding")),
        "provider": embedding_provider,
        "model": _as_str(rag_embedding.get("model"), "BAAI/bge-m3"),
        "dim": _as_int(rag_embedding.get("dim"), 1024),
        "max_tokens": _as_int(rag_embedding.get("max_tokens"), 8192),
    }
    roles["rerank"] = {
        **_as_dict(roles.get("rerank")),
        "provider": rerank_provider,
        "model": _as_str(rag_rerank.get("model"), "BAAI/bge-reranker-v2-m3"),
    }

    runtime["max_retries"] = _as_int(anthropic.get("max_retries"), 3)
    runtime["timeout"] = _as_int(anthropic.get("timeout"), 600)

    pricing = anthropic.get("pricing_usd_per_million")
    if not isinstance(pricing, dict):
        pricing = metadata.get("pricing_usd_per_million", {})

    return {
        "providers": providers,
        "roles": roles,
        "runtime": runtime,
        "pricing_usd_per_million": _normalize_pricing(pricing),
    }


def model_center_to_config_patch(model_center: Dict[str, Any]) -> Dict[str, Any]:
    """Convert model-center payload back to project config patch."""
    providers = _normalize_providers(model_center.get("providers"))
    roles = _normalize_roles(model_center.get("roles"))
    runtime = _normalize_runtime(model_center.get("runtime"))
    pricing = _normalize_pricing(model_center.get("pricing_usd_per_million"))

    # Fill missing known provider ids with safe defaults.
    for provider_id, kind in DEFAULT_PROVIDER_KIND.items():
        providers.setdefault(provider_id, {"kind": kind, "api_key": "", "base_url": ""})

    writing = _as_dict(roles.get("writing"))
    analysis = _as_dict(roles.get("analysis"))
    rag_llm = _as_dict(roles.get("rag_llm"))
    embedding = _as_dict(roles.get("embedding"))
    rerank = _as_dict(roles.get("rerank"))

    writing_provider_id = _as_str(writing.get("provider"), DEFAULT_ROLE_PROVIDER["writing"])
    analysis_provider_id = _as_str(analysis.get("provider"), DEFAULT_ROLE_PROVIDER["analysis"])
    rag_llm_provider_id = _as_str(rag_llm.get("provider"), DEFAULT_ROLE_PROVIDER["rag_llm"])
    embedding_provider_id = _as_str(embedding.get("provider"), DEFAULT_ROLE_PROVIDER["embedding"])
    rerank_provider_id = _as_str(rerank.get("provider"), DEFAULT_ROLE_PROVIDER["rerank"])

    writing_provider = _provider_config(
        providers,
        writing_provider_id,
        fallback_provider_id="anthropic_primary",
        default_kind="anthropic",
    )
    analysis_provider = _provider_config(
        providers,
        analysis_provider_id,
        fallback_provider_id=writing_provider_id,
        default_kind="anthropic",
    )
    # Backward compatibility: if analysis provider exists but credentials are empty,
    # fall back to writing provider to avoid writing empty analysis credentials.
    if not _as_str(analysis_provider.get("api_key")) and not _as_str(analysis_provider.get("base_url")):
        analysis_provider = writing_provider
    fallback_provider = _provider_config(
        providers,
        "anthropic_fallback",
        fallback_provider_id=analysis_provider_id,
        default_kind="anthropic",
    )
    rag_llm_provider = _provider_config(
        providers,
        rag_llm_provider_id,
        fallback_provider_id="rag_llm",
        default_kind="openai_compatible",
    )
    rag_embedding_provider = _provider_config(
        providers,
        embedding_provider_id,
        fallback_provider_id="rag_embedding",
        default_kind="openai_compatible",
    )
    rag_rerank_provider = _provider_config(
        providers,
        rerank_provider_id,
        fallback_provider_id="rag_rerank",
        default_kind="openai_compatible",
    )

    patch = {
        "anthropic": {
            # Backward-compatible defaults still point to writing provider.
            "api_key": _as_str(writing_provider.get("api_key")),
            "base_url": _as_str(writing_provider.get("base_url"), DEFAULT_ANTHROPIC_BASE_URL),
            # New split endpoints for role-level custom providers.
            "writing_api_key": _as_str(writing_provider.get("api_key")),
            "writing_base_url": _as_str(writing_provider.get("base_url"), DEFAULT_ANTHROPIC_BASE_URL),
            "analysis_api_key": _as_str(analysis_provider.get("api_key")),
            "analysis_base_url": _as_str(analysis_provider.get("base_url"), DEFAULT_ANTHROPIC_BASE_URL),
            "writing_model": _as_str(writing.get("model"), "claude-opus-4-6-20260205"),
            "analysis_model": _as_str(analysis.get("model"), "claude-sonnet-4-6-20260219"),
            "writing_temperature": _as_float(writing.get("temperature"), 0.8),
            "analysis_temperature": _as_float(analysis.get("temperature"), 0.3),
            "max_retries": _as_int(runtime.get("max_retries"), 3),
            "timeout": _as_int(runtime.get("timeout"), 600),
            "fallback": {
                "api_key": _as_str(fallback_provider.get("api_key")),
                "base_url": _as_str(fallback_provider.get("base_url"), DEFAULT_ANTHROPIC_BASE_URL),
            },
            "pricing_usd_per_million": pricing,
        },
        "lightrag": {
            "llm": {
                "model": _as_str(rag_llm.get("model"), "qwen3.5-plus"),
                "api_key": _as_str(rag_llm_provider.get("api_key")),
                "base_url": _as_str(rag_llm_provider.get("base_url")),
                "timeout": _as_int(rag_llm.get("timeout"), 180),
                "max_tokens": _as_int(rag_llm.get("max_tokens"), 4096),
            },
            "embedding": {
                "model": _as_str(embedding.get("model"), "BAAI/bge-m3"),
                "api_key": _as_str(rag_embedding_provider.get("api_key")),
                "base_url": _as_str(rag_embedding_provider.get("base_url")),
                "dim": _as_int(embedding.get("dim"), 1024),
                "max_tokens": _as_int(embedding.get("max_tokens"), 8192),
            },
            "rerank": {
                "model": _as_str(rerank.get("model"), "BAAI/bge-reranker-v2-m3"),
                "api_key": _as_str(rag_rerank_provider.get("api_key")),
                "base_url": _as_str(rag_rerank_provider.get("base_url")),
            },
        },
        # Persist full model center metadata so dynamic providers/roles are not lost.
        "model_center": {
            "providers": copy.deepcopy(providers),
            "roles": copy.deepcopy(roles),
            "runtime": copy.deepcopy(runtime),
            "pricing_usd_per_million": copy.deepcopy(pricing),
        },
    }
    return patch
