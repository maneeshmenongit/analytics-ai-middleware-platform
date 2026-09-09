"""OpenTelemetry GenAI attribute names, pinned.

PulseWise adopts OTel GenAI semantic-convention *attribute names* for
call-level AI context, so client products emit vendor-neutral keys instead of
inventing their own. This module is the single place those names are defined.

**Pinned version: OpenTelemetry semantic conventions v1.41.1.**

Why that version specifically. The GenAI conventions are still marked
"Development" — not one `gen_ai.*` attribute has reached Stable — and the names
drift between releases. In semconv v1.42.0 (June 2026) every `gen_ai.*`
attribute was *deprecated in the main semantic-conventions repository* and moved
to a dedicated `open-telemetry/semantic-conventions-genai` repository, which has
not yet cut a tagged release. So:

  - v1.41.1 is the last main-repo release where these names are live rather
    than deprecated, and it is an immutable tag we can cite.
  - Pinning a post-1.42 main-repo version would mean pinning to a spec that
    formally disowns the attributes.
  - Pinning the new repo would mean pinning an untagged moving target.

Revisit when semantic-conventions-genai publishes its first tagged release.
Adopt the names; do not chase the churn.

This module is pure stdlib and carries no OpenTelemetry dependency — PulseWise
uses the *names*, not the SDK.
"""
from __future__ import annotations

from typing import Final

#: The pinned semantic-conventions release these names are taken from.
OTEL_SEMCONV_VERSION: Final[str] = "1.41.1"

#: Where that version is published, for anyone auditing the pin.
OTEL_SEMCONV_SOURCE: Final[str] = (
    "https://github.com/open-telemetry/semantic-conventions/releases/tag/v1.41.1"
)

# Request-side attributes.
GEN_AI_REQUEST_MODEL: Final[str] = "gen_ai.request.model"
GEN_AI_PROVIDER_NAME: Final[str] = "gen_ai.provider.name"
GEN_AI_OPERATION_NAME: Final[str] = "gen_ai.operation.name"

# Usage attributes.
GEN_AI_USAGE_INPUT_TOKENS: Final[str] = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final[str] = "gen_ai.usage.output_tokens"

# Response-side attributes.
GEN_AI_RESPONSE_MODEL: Final[str] = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH_REASONS: Final[str] = "gen_ai.response.finish_reasons"

#: Every attribute name this pin covers. Clients emitting call-level AI context
#: inside `PulseEvent.context` should use these keys.
GEN_AI_ATTRIBUTES: Final[frozenset[str]] = frozenset({
    GEN_AI_REQUEST_MODEL,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_OPERATION_NAME,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
})
