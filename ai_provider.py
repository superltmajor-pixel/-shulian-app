"""Known OpenAI-compatible AI providers and runtime detection helpers.

The API key itself is never persisted here.  This module only describes public
provider endpoints and orders safe validation candidates for a key entered in
the local login gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


AUTO_PROVIDER_NAMES = {"", "auto", "detect", "generic", "any"}


@dataclass(frozen=True)
class ProviderProfile:
    """The minimum information needed by the OpenAI-compatible adapter."""

    id: str
    label: str
    base_url: str
    preferred_models: tuple[str, ...] = ()
    key_prefixes: tuple[str, ...] = ()


# Keep this catalog deliberately limited to providers exposing the same
# /models and /chat/completions protocol.  Native Anthropic/Gemini APIs need a
# different adapter and must not be probed with an OpenAI client.
PROVIDER_CATALOG: tuple[ProviderProfile, ...] = (
    ProviderProfile(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com",
        ("deepseek-flash",),
    ),
    ProviderProfile(
        "doubao",
        "豆包",
        "https://ark.cn-beijing.volces.com/api/v3",
        ("doubao-seed-character-260628",),
        ("ark-",),
    ),
)

_BY_ID = {profile.id: profile for profile in PROVIDER_CATALOG}


def _env(environ: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return environ if environ is not None else os.environ


def configured_profile(environ: Mapping[str, str] | None = None) -> ProviderProfile | None:
    """Return an explicit .env provider, or ``None`` for automatic mode."""

    values = _env(environ)
    provider_id = values.get("SHULIAN_AI_PROVIDER", "").strip().lower()
    base_url = values.get("SHULIAN_BASE_URL", "").strip().rstrip("/")
    # Keep compatibility with the formal edition's existing .env template.
    # Newer builds use SHULIAN_BASE_URL, while older formal installations use
    # DEEPSEEK_BASE_URL.
    if not base_url:
        base_url = values.get("DEEPSEEK_BASE_URL", "").strip().rstrip("/")
        if base_url and not provider_id:
            provider_id = "deepseek"
    label = values.get("SHULIAN_PROVIDER_LABEL", "").strip()
    if provider_id in AUTO_PROVIDER_NAMES and not base_url:
        return None

    profile = _BY_ID.get(provider_id)
    if profile is None:
        if not base_url:
            return None
        return ProviderProfile(
            provider_id if provider_id not in AUTO_PROVIDER_NAMES else "custom",
            label or "自定义 AI 服务",
            base_url,
            (),
        )

    return ProviderProfile(
        profile.id,
        label or profile.label,
        base_url or profile.base_url,
        profile.preferred_models,
        profile.key_prefixes,
    )


def candidate_profiles(
    api_key: str,
    environ: Mapping[str, str] | None = None,
) -> tuple[ProviderProfile, ...]:
    """Order providers for one key without exposing the key to application logs.

    A strong, vendor-specific prefix is routed directly.  Generic ``sk-`` keys
    belong to the formal edition's DeepSeek connection and must never be
    probed against public third-party model catalogs.
    """

    explicit = configured_profile(environ)
    if explicit is not None:
        return (explicit,)

    normalized = api_key.strip().lower()
    matched = tuple(
        profile
        for profile in PROVIDER_CATALOG
        if any(normalized.startswith(prefix.lower()) for prefix in profile.key_prefixes)
    )
    if matched:
        return matched
    deepseek = _BY_ID.get("deepseek")
    return (deepseek,) if deepseek is not None else ()


def model_candidates(
    model_ids: list[str] | tuple[str, ...] | set[str],
    profile: ProviderProfile,
    preferred_model: str = "",
) -> tuple[str, ...]:
    """Return only product-approved model IDs with the best model first.

    A provider's ``/models`` response is an availability check, not a product
    catalog.  Never expose or auto-select arbitrary upstream models.
    """

    # Some authenticated provider catalogs omit experimental or endpoint-bound
    # models even while chat completions accept them.  The listing proves the
    # credential is accepted; the product allowlist remains authoritative.
    _ = model_ids
    approved = list(profile.preferred_models)
    preferred = preferred_model.strip()
    ordered = [preferred] if preferred in approved else []
    ordered.extend(value for value in approved if value not in ordered)
    return tuple(ordered)
