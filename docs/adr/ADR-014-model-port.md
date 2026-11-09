# ADR-014: Gemini-only model provider behind ModelPort; no other providers at launch

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §5, §11, ADR-005

## Context

CAIRN uses models for summarisation, drafting and agent workflows. The PRD leaves provider policy open. Hard-coding one vendor SDK would lock the platform in; testing every provider's parity from day one would multiply cost and delay the assessment release.

## Decision

- Define a `ModelPort` in the kernel with a narrow request/response contract: prompt, structured output expectations, token and latency telemetry, safety metadata, and no authority to perform irreversible actions.
- Ship Gemini as the only real provider at launch. No Bedrock or Azure OpenAI adapter is built until a new ADR justifies it.
- No customer bring-your-own-key at launch; model access is CAIRN-operated.
- A fake adapter is mandatory for deterministic tests.
- Prompt versions, model ids and parameters are recorded in evidence where model output influenced a decision.
- Model output that proposes an action must be validated against the domain contract and, if irreversible, approved before execution.

## Consequences

**Positive**

- Provider choice is reversible.
- Deterministic tests without network calls.
- Cost and latency are observable per call.

**Negative**

- The lowest-common-denominator contract limits provider-specific features.
- One provider is a single dependency and a single point of failure at launch.
- Provider-specific capabilities cannot be used directly, even when they would help.

**Neutral**

- Provider selection may become a per-tenant configuration later without changing modules.

## Alternatives considered

1. **Call one vendor SDK everywhere.** Fastest, but violates the architecture boundary and locks in the platform.
2. **Multi-provider at launch.** Maximum flexibility with disproportionate parity cost.
3. **No model usage in MVP.** Safest, but removes the AI-assisted parts of the assessment experience.

## If rejected

Expect either vendor lock-in or a parity cost that delays the first release.
