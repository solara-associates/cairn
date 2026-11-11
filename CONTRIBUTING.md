# Contributing

CAIRN is Apache-2.0 and uses the Developer Certificate of Origin (DCO) 1.1. There is no contributor licence agreement.

## Clean-room rule

This is a greenfield, clean-room build (ADR-017). Do not copy, vendor, translate or adapt code, assets, configuration or generated output from the reference repositories listed in `docs/specs/reference-register.md`. Use them only as behavioural evidence, and record any influence in the register.

If you believe a contribution contains third-party material, say so in the pull request. Provenance ambiguity is a reason to reject.

## Before you start

- Read `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` and the relevant ADR.
- A change to a contract in sections 7 to 13 needs an ADR and a version bump.
- New scope needs a backlog story. Do not add features to R1 without removing something or recording the delay.

## Commits

Sign off every commit with `git commit -s`. The sign-off certifies the DCO. Keep commits focused and messages direct.

## Pull requests

- Explain the problem, the change and the test evidence.
- Keep the clean-room and tenant-isolation boundaries intact.
- Do not commit secrets or customer data.
- Expect review from a single maintainer, so responses may be slow.

## Code standards

Once code exists, the specification is the source of truth for boundaries, contracts and conformance. In short:
- Python 3.12 for domain and application code; Rust for transformation and measured hot paths.
- Clean/Hexagonal plus DDD, enforced by `import-linter`.
- No provider SDK imports in domain or application code.
- No customer-environment mutation before R4. Class C writes, when they exist, go only through the kernel execution gate with approval, a recovery plan that matches the mutation class, and an audit record before effect.

## Security

Follow `SECURITY.md`. Do not open a public issue for a vulnerability.

## Conduct

Be direct, specific and respectful. Critique the work, not the person.
