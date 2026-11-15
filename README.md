# CAIRN

CAIRN is a cloud modernization platform. It assesses an estate, applies 6R dispositions, designs a target architecture, modernizes code and infrastructure, and records every governed change as signed evidence.

**Status: R0 (foundation) and R1 (assessment) are complete. R2 through R5 are planned, not built.** CAIRN today can ingest an estate, run a 6R assessment, compute cost/TCO, check posture against a control catalogue, and produce a signed evidence package -- all read-only against any customer environment. It cannot yet design a target architecture, transform infrastructure or code, run FinOps loops, or write anything back to a customer's cloud account. There is no hosted service and no supported release; nothing here should be pointed at a production environment.

## What's built (R0-R1) vs. planned (R2-R5)

| Capability | Status |
|---|---|
| **CAIRN Kernel** -- domain model, provider ports, evidence, audit, tenancy, conformance | Built (R0) |
| **CAIRN Assess** -- estate ingestion, posture, cost/TCO, 6R classification, signed evidence | Built (R1) |
| **CAIRN Design** -- target architecture, patterns and migration plans from one model | Planned (R2) |
| **CAIRN Modernize** -- clean-room transformation of Terraform and Python | Planned (R3) |
| **CAIRN Operate** -- FinOps and operational loops | Planned (R5) |
| **CAIRN Govern** -- policy, approval and immutable evidence for customer-environment writes | Planned (R4) |

CAIRN is read-only against customer environments through R1 -- R1 does assessment, workspace decisions and evidence, with no write or execute credential ever requested or stored. Governed customer-environment writes start only in R4, through a kernel execution gate with policy, immutable revision approval, audit-before-effect, evidence and a recovery plan that matches the mutation class.

## Architecture overview

- **Hexagonal/DDD, enforced by tooling** (ADR-002): domain and application code never import a provider SDK directly; everything crosses a port, checked by `import-linter` in CI.
- **Python 3.12** for domain and application code; **Rust** for the transformation engine and other measured hot paths (ADR-006).
- **Multi-tenant Postgres** with forced row-level security, signed tenant-context assertions, and an append-only audit ledger (ADR-007, ADR-012).
- **Signed, hash-chained evidence envelopes** for every governed action, verifiable offline without a network call (ADR-008).
- **Provider-neutral adapter contracts** (inventory, billing, posture) with a deterministic fake for tests, so the same contract suite runs against a real GCP adapter or a synthetic one.
- **OpenID Connect for identity, no hosted provider**: see [Identity and sign-in](docs/identity.md).
- **GCP-first** (ADR-005), with a UK jurisdiction pack as the first launch target (ADR-016) -- the architecture is not GCP-exclusive by design, just GCP-first in sequencing.

See [Architecture decision records](docs/adr/README.md) for the full set of accepted decisions, and the [technical implementation specification](CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md) for contracts and schemas.

## Quickstart

Requires Docker and Docker Compose.

```
docker compose up --build
```

This starts:

- the **API** on `http://localhost:8080` (liveness `GET /healthz`, readiness `GET /readyz`)
- the **worker** on `http://localhost:8081` (same health endpoints)
- the **console** on `http://localhost:3000`
- a local **dex** identity provider, so the console has somewhere to sign in against with no setup -- see [Identity and sign-in](docs/identity.md) for exactly what it does and why it is local-only

Open `http://localhost:3000` and sign in. The bundled dex instance gives you one fixed local demo identity (no password prompt) with enough roles to explore the read-only assessment screens. This is a development convenience only -- it is not how a real deployment authenticates; see `docs/identity.md` for bringing your own OIDC provider.

## Roadmap

| Release | Scope | Status |
|---|---|---|
| **R0** | Kernel, tenancy, evidence, audit, observability, conformance | Complete |
| **R1** | Estate ingestion, posture, cost/TCO, 6R classification, assessment console, signed evidence packages | Complete |
| **R2** | Target architecture design, equivalence mapping, migration plans | Planned |
| **R3** | Clean-room transformation engine (Terraform and Python first) | Planned |
| **R4** | Kernel execution gate: policy, approval, audit-before-effect, governed customer-environment writes | Planned |
| **R5** | FinOps/operational loops, MCP/A2A surfaces | Planned |

See the [technical implementation specification](CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md) for the detailed backlog and [docs/acceptance/r0-20-review.md](docs/acceptance/r0-20-review.md) for the R0 acceptance evidence.

## Documents

| Document | Purpose |
|---|---|
| [Technical implementation specification](CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md) | Contracts, schemas, deployment, backlog and delivery outlook |
| [Architecture patterns](CLOUD-ARCHITECTURE-PATTERNS.md) | Design evidence from prior work; nothing is reused as code |
| [Architecture decision records](docs/adr/README.md) | ADR-001 to ADR-018 |
| [Reference register](docs/specs/reference-register.md) | Clean-room evidence log |
| [Identity and sign-in](docs/identity.md) | OIDC, local dex quickstart, bring-your-own-IdP for deployments |
| [Third-party licences](docs/third-party-licenses.md) | Direct dependency licences |
| `Cloud_Modernization_Platform_PRD.docx` | Product requirements baseline with revision notes |
| `CAIRN_Architecture_Review_and_R0_Resolution.docx` | Architecture review that drove the pre-R0 corrections and release boundary |

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Professional services are available separately. There is no open-core gate.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions use the Developer Certificate of Origin. The clean-room policy is strict: no code, assets or configuration from the reference repositories listed in the reference register. See also [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and [GOVERNANCE.md](GOVERNANCE.md).

## Security

See [SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability -- use GitHub's private security advisories. The project makes no support or warranty promise without a separate engagement.
