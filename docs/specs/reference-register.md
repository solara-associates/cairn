# Reference register

**Purpose:** record what CAIRN learned from each reference repository, so the greenfield provenance claim is auditable.

**Rules (ADR-017, technical specification section 17.3):**

- The reference repositories are design evidence only. No code, tests, schemas, Terraform, prompts, diagrams or configuration is copied.
- Every story that cites a reference repository adds a row here before the story is accepted.
- "Code or assets copied" must always be `No`. Any `Yes` blocks the story and requires a new ADR and a licence review.
- The pattern catalogue (`CLOUD-ARCHITECTURE-PATTERNS.md`) is the primary reference artefact.

**Status:** day zero. The rows below are planned references; they will be confirmed or amended as stories are implemented.

| Date | Story | Reference repository | Lesson or behaviour observed | Where used in CAIRN | Code or assets copied |
|---|---|---|---|---|---|
| 2026-11-09 | R0-02, R0-06 | `Meridian`, `punjab`, `barq` | Four-layer separation with explicit ports, enforced by tooling | `packages/kernel/hex`, `.importlinter` | No |
| 2026-11-09 | R0-13 | `Meridian`, `mlops-aws`, `raas` | One provider contract per capability; fake adapter for tests | `packages/adapters/provider-core` | No |
| 2026-11-09 | R5-04 | `punjab`, `byomcp`, `raas` | One MCP server per bounded context; gateway auth and audit | `packages/kits/mcp`, `apps/mcp-gateway` | No |
| 2026-11-09 | R0-11 | `tda-uk-accelerator`, `dpdp`, `feedback` | Audit-before-effect; signed artefact; offline verification | `packages/kernel/evidence` | No |
| 2026-11-09 | R1-08, R1-09 | `autoinfra`, `autoinfra_aws`, `clearvue-foundation` | One Finding model across scanners; coverage is explicit | `packages/modules/posture` | No |
| 2026-11-09 | R1-06, R1-14 | `agent-assess`, `infracc`, `anytoany` | Canonical estate model; 6R with rationale and confidence | `packages/modules/estate` | No |
| 2026-11-09 | R2-01 | `cloudshift`, `drawio-gen`, `infracc` | Equivalence semantics; immutable mapping releases | `packages/modules/mappings` | No |
| 2026-11-09 | R2-04, R2-05 | `drawio-gen` | One target model drives diagram, plan and IaC | `packages/modules/design` | No |
| 2026-11-09 | R3-02, R3-03 | `cloudshift_v2` (reference only) | Parse, detect, diff and validate as separate deterministic stages | `packages/transform-core` | No |
| 2026-11-09 | R5-01 | `clearvue-foundation`, `Meridian` | Graded remediation; attribution and unallocated spend | `packages/modules/finops` | No |
| 2026-11-09 | R5-02, R5-03 | `Meridian`, `llmops`, `mlops` | Observe/Decide/Act with policy and evidence | `packages/kits/loop` | No |
| 2026-11-09 | R0-12 | `llmops`, `punjab`, `raas` | OTel plus RED plus per-AI-call cost log | `packages/kernel/observability` | No |
| 2026-11-09 | R1-18 | `infracc`, `cockpit` | Assessment-first information architecture | `apps/console` | No |
