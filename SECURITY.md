# Security policy

CAIRN is at the specification stage. There is no supported release and no hosted service yet. This policy covers the repository and, once code exists, the software.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting on this repository: Security, then Advisories, then Report a vulnerability.

Include the affected file or component, the impact, reproduction steps and any suggested fix. You will get an acknowledgement when the report is read. This is a solo-maintained project, so there is no response-time guarantee.

## Scope

In scope:
- The repository content and build configuration.
- Code once released.
- The clean-room controls and any accidental inclusion of third-party code.

Out of scope:
- Third-party dependencies. Report those to their maintainers.
- Any deployment that is not the hosted service operated by the project.
- Unsupported self-hosted deployments by third parties.

## Handling secrets

Never commit credentials, keys, tokens or customer data. Use environment injection or a secret manager. Evidence signing keys are held by CAIRN and are never stored in this repository. If a secret is exposed, rotate it first, then report the exposure.

## Customer-environment writes (Class C)

The first usable release must not mutate customer environments. When the execution path exists in R4, it must fail closed: no Class C change without policy, revision-bound approval and an audit record written before the effect. Assessment and design services must remain structurally read-only and must not hold execution credentials. Any change to that boundary requires an ADR.
