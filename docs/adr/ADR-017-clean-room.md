# ADR-017: Greenfield clean-room implementation; no code reuse from reference repositories

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Product owner (Allan Smeyatsky)
- **Related:** Implementation spec §17, ADR-015, ADR-006

## Context

CAIRN was initially planned on the premise that the 43 archived repositories in `asmeyatsky-work` could supply reusable code. On review that premise does not hold:

- The repositories are archived prototypes. The source analysis already flags one empty repository, a frontend-only prototype, missing READMEs and several POCs.
- Licence, provenance and quality are unresolved for most of them, so lifting code would require a due-diligence pass per repository before any benefit.
- Their interfaces reflect prototype assumptions that conflict with CAIRN's kernel, tenancy and evidence contracts.
- Mixing lifted code into a new platform makes provenance hard to explain to customers and auditors.

The product owner has decided that this is a greenfield build.

## Decision

- No source code, tests, schemas, Terraform, prompts, diagrams or configuration is reused from the reference repositories.
- No vendoring, submodules, forked dependencies or run-time dependency on a reference repository.
- The repositories are design evidence only. Team members may read them, and the pattern catalogue may cite them, but nothing is pasted into CAIRN.
- Every story that cites a reference repository records what was learned, not what was copied, in `docs/specs/reference-register.md`.
- Code review treats unexplained similarity to a reference repository as a defect.
- The transformation engine is built clean-room (ADR-015).
- Any future exception requires a new ADR and a licence review before the asset is used.

## Consequences

**Positive**

- Clean provenance: every line of CAIRN has a known origin.
- No inherited licence ambiguity, prototype debt or hidden coupling.
- One contract set and one test suite, designed for the platform rather than adapted from a demo.
- Easier security and customer due diligence.

**Negative**

- The build is larger than a lift/adapt plan; the earlier schedule is withdrawn and re-baselined in spec section 16.2.
- Behaviours already solved in the reference repositories must be rediscovered and re-tested.
- The pattern catalogue remains necessary reading, so onboarding takes longer than reading a single codebase.

**Neutral**

- The 43-repository analysis retains value as evidence and as a source of test cases, not as a dependency.

## Alternatives considered

1. **Lift and adapt selected repositories.** Faster on paper, but requires per-repository licence, security and quality review and reintroduces prototype interfaces.
2. **Fork or vendor the strongest repositories.** Keeps their behaviour but makes provenance and upgrades harder.
3. **Hybrid: reuse libraries, rewrite services.** Still inherits licence and compatibility risk at the library boundary.

## If rejected

Reversing this decision reinstates the extraction and due-diligence plan, invalidates spec section 17 and the re-baselined schedule, and requires ADR-015 to be superseded again.
