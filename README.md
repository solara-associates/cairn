# CAIRN

CAIRN is a cloud modernization platform. It assesses an estate, applies 6R dispositions, designs a target architecture, modernizes code and infrastructure, and records every governed change as signed evidence.

This repository is at the **specification stage**. It contains architecture, decision and requirements documents. There is no runnable product yet, no supported release and no hosted service. Nothing here should be used against a live environment.

## What is being built

- **CAIRN Kernel**: shared domain model, provider ports, evidence, audit and conformance.
- **CAIRN Assess**: posture, cost, 6R and a canonical estate model.
- **CAIRN Design**: target architecture, patterns and migration plans from one model.
- **CAIRN Modernize**: clean-room transformation of Terraform and Python first.
- **CAIRN Operate**: FinOps and operational loops.
- **CAIRN Govern**: policy, approval and immutable evidence.

The first usable release is a commercial multi-tenant SaaS on Google Cloud, aimed at the mid-market and launched with a United Kingdom jurisdiction pack. It is read-only against customer environments: R1 does assessment, workspace decisions and evidence. Governed customer-environment writes start only in R4, through a kernel execution gate with policy, immutable revision approval, audit-before-effect, evidence and rollback.

## Documents

| Document | Purpose |
|---|---|
| [Technical implementation specification](CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md) | Contracts, schemas, deployment, backlog and delivery outlook |
| [Architecture patterns](CLOUD-ARCHITECTURE-PATTERNS.md) | Design evidence from prior work; nothing is reused as code |
| [Architecture decision records](docs/adr/README.md) | ADR-001 to ADR-018, all accepted 9 November 2026 |
| [Reference register](docs/specs/reference-register.md) | Clean-room evidence log |
| `Cloud_Modernization_Platform_PRD.docx` | Product requirements baseline with revision notes |

## Status

- Decisions: accepted (ADR-001 to ADR-018).
- Code: none.
- Team: one maintainer.
- Timeline: ASAP, with no committed date. The specification gives a solo outlook of R0 in 8 to 12 weeks and R1 in 9 to 15 months.

## Licence

Apache-2.0. See [LICENSE](LICENSE). Professional services are available separately. There is no open-core gate.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions use the Developer Certificate of Origin. The clean-room policy is strict: no code, assets or configuration from the reference repositories listed in the reference register.

## Security

See [SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability. The project makes no support or warranty promise without a separate engagement.
