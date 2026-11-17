# Security policy

CAIRN has substantial, tested code: R0-R3 (foundation, assessment, design, clean-room transformation) are complete, R4 (the kernel execution gate -- policy, approval and recovery) is partially built, and R5 (operate loops -- FinOps, LLMOps, MLOps, resilience, sovereignty, MCP/A2A, a vertical accelerator pack) is complete. All of it is built and tested against a fake/deterministic adapter or a synthetic estate; no code in this repository has executed a write against a real customer cloud account. There is no tagged release and no hosted service yet -- see [README.md](README.md) for the current status in full. This policy covers the repository today and will cover the running software once a release and a hosted service exist.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting on this repository: Security, then Advisories, then Report a vulnerability.

Include the affected file or component, the impact, reproduction steps and any suggested fix. You will get an acknowledgement when the report is read. This is a solo-maintained project, so there is no response-time guarantee.

## Scope

In scope:
- The repository content and build configuration.
- The code in this repository today, and any tagged release once one exists.
- The clean-room controls and any accidental inclusion of third-party code.

Out of scope:
- Third-party dependencies. Report those to their maintainers.
- Any deployment that is not the hosted service operated by the project.
- Unsupported self-hosted deployments by third parties.

## Handling secrets

Never commit credentials, keys, tokens or customer data. Use environment injection or a secret manager. Evidence signing keys are held by CAIRN and are never stored in this repository. If a secret is exposed, rotate it first, then report the exposure.

## Customer-environment writes (Class C)

The first usable release must not mutate customer environments. When the execution path exists in R4, it must fail closed: no Class C change without policy, revision-bound approval, a validated rollback or compensation plan, and an audit record written before the effect. Irreversible changes additionally require explicit risk acceptance. Assessment and design services must remain structurally read-only and must not hold execution credentials. Any change to that boundary requires an ADR.
