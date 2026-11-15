# Governance

CAIRN has one maintainer today: Allan Smeyatsky, on behalf of Solara
Associates. This document describes how decisions are made now, and how
that is expected to change as the project grows.

## Current model: single maintainer

- The maintainer reviews and merges all pull requests, triages issues,
  and owns ADR acceptance (`docs/adr/`).
- A change to a contract described in the technical specification
  (sections 7 to 13) needs an ADR and a version bump, decided by the
  maintainer.
- There is no vote, no steering committee, and no formal RFC process
  yet. For a project with one maintainer, that overhead would slow
  things down without adding accountability.
- Response times are best-effort. See `SECURITY.md` for the one
  exception (private vulnerability reports), which get a faster
  acknowledgement.

## What contributors can expect

- Issues and pull requests are read and triaged, but not on a fixed
  schedule.
- Significant design changes are expected to go through an ADR
  (`docs/adr/README.md` explains the format) before implementation,
  so there is a durable record of why a decision was made.
- Disagreements about direction are the maintainer's call to make,
  explained in writing (an ADR, an issue comment, or a PR review).

## How this changes

As the contributor base grows, governance should grow with it. The
maintainer intends to revisit this document -- for example, adding
designated reviewers for specific areas, or a lightweight proposal
process for larger changes -- once there is a regular set of
contributors to involve in that decision. There is no fixed trigger or
date for this; it is intentionally left as a judgment call rather than
a premature promise.

## Contact

For anything not covered by `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, or
`SECURITY.md`, reach the maintainer at `info@solara.associates`.
