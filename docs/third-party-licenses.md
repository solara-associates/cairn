# Third-party licences

CAIRN is Apache-2.0 (see `LICENSE`, `NOTICE`). This page lists direct
dependencies and their licences, generated with `pip-licenses` for
Python (`uv run pip-licenses --format=markdown --with-urls`, run from a
synced `.venv`), and reviewed by hand for the npm and Rust workspaces.
All are compatible with Apache-2.0 distribution. Transitive dependency
trees are not reproduced here; re-run the generator for a complete
snapshot before a release if a stricter guarantee is needed.

**Last verified: 2026-11-17 (unit 831, `docs/roadmap-r4-r5-oss.md` §3).**
Python section re-generated and diffed against this file — no change
needed, still current. Rust section was stale (see that section's own
note) and is corrected below. No GPL, AGPL, SSPL, or other
copyleft-incompatible licence found anywhere in the dependency tree
checked; `psycopg`'s LGPL-3.0 remains the one licence requiring the
explanation already given below, unchanged.

## Python

| Name | Version | License | URL |
|---|---|---|---|
| PyJWT | 2.15.1 | MIT | https://github.com/jpadilla/pyjwt |
| PyYAML | 6.0.3 | MIT License | https://pyyaml.org/ |
| Pygments | 2.21.0 | BSD-2-Clause | https://pygments.org |
| annotated-doc | 0.0.6 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.16.0 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| certifi | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://cffi.readthedocs.io/en/latest/whatsnew.html |
| charset-normalizer | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer |
| click | 8.5.1 | BSD-3-Clause | https://github.com/pallets/click/ |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| fastapi | 0.162.5 | MIT | https://github.com/fastapi/fastapi |
| google-api-core | 2.44.0 | Apache-2.0 | https://github.com/googleapis/google-cloud-python |
| google-auth | 2.62.2 | Apache-2.0 | https://github.com/googleapis/google-cloud-python |
| google-cloud-kms | 3.19.0 | Apache-2.0 | https://github.com/googleapis/google-cloud-python |
| googleapis-common-protos | 1.76.0 | Apache-2.0 | https://github.com/googleapis/google-cloud-python |
| grimp | 3.19 | BSD License | https://grimp.readthedocs.io/ |
| grpc-google-iam-v1 | 0.14.6 | Apache-2.0 | https://github.com/googleapis/google-cloud-python |
| grpcio / grpcio-status | 1.85.1 | Apache-2.0 | https://grpc.io |
| h11 | 0.16.0 | MIT License | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httpx | 0.28.1 | BSD License | https://github.com/encode/httpx |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| import-linter | 2.16 | BSD License | https://import-linter.readthedocs.io/ |
| iniconfig | 2.3.1 | MIT | https://github.com/pytest-dev/iniconfig |
| markdown-it-py | 4.3.0 | MIT License | https://github.com/executablebooks/markdown-it-py |
| mdurl | 0.1.2 | MIT License | https://github.com/executablebooks/mdurl |
| opentelemetry-api / -sdk / -semantic-conventions | 1.45.2 / 0.66b2 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pluggy | 1.7.0 | MIT License | https://github.com/pytest-dev/pluggy |
| proto-plus | 1.29.0 | Apache-2.0 | https://github.com/googleapis/google-cloud-python |
| protobuf | 7.36.2 | BSD-3-Clause | https://developers.google.com/protocol-buffers/ |
| **psycopg / psycopg-binary** | 3.3.8 | **LGPL-3.0-only** | https://psycopg.org/ |
| pyasn1 | 0.6.5 | BSD-2-Clause | https://github.com/pyasn1/pyasn1 |
| pyasn1-modules | 0.4.2 | BSD License | https://github.com/pyasn1/pyasn1-modules |
| pycparser | 3.12 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic / pydantic_core | 2.14.3 / 2.50.4 | MIT | https://github.com/pydantic/pydantic |
| pytest | 9.2.0 | MIT | https://docs.pytest.org/en/latest/ |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| rich | 15.0.0 | MIT License | https://github.com/Textualize/rich |
| ruff | 0.17.4 | MIT | https://docs.astral.sh/ruff |
| starlette | 1.10.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| typing-inspection | 0.4.5 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 |
| uvicorn | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ |

**psycopg is LGPL-3.0-only.** It is used unmodified as a library
(imported, not vendored or statically linked into a distributed
binary), which LGPL-3.0 permits when combined with code under a
different licence. See `NOTICE`.

## npm (apps/console)

`apps/console` has **no runtime dependencies**. Its four
`devDependencies` (`vite`, `vitest`, `typescript`, `jsdom`) are build
and test tooling only, never bundled into the published static assets,
and are MIT/Apache-2.0 licensed (checked against their own published
`package.json` `license` fields). Re-run `npx license-checker` after
`pnpm install` before a release if a stricter guarantee is wanted.

## Rust (packages/transform-core)

**Corrected 2026-11-17 (unit 831) — this section was stale.** The Rust
workspace now has six members (`contract`, `parser`, `detector`,
`patcher`, `validator`, `cli` — `contract` and `cli` were added since
this section was last written) and real external crate dependencies,
pulled in starting with unit 722's parser work. Checked directly against
each crate's own `Cargo.toml` `license` field in the local registry cache
(`~/.cargo/registry/src/`):

| Name | License |
|---|---|
| serde / serde_core / serde_derive / serde_json | MIT OR Apache-2.0 |
| proc-macro2 | MIT OR Apache-2.0 |
| quote | MIT OR Apache-2.0 |
| syn | MIT OR Apache-2.0 |
| unicode-ident | (MIT OR Apache-2.0) AND Unicode-DFS-2016 |
| itoa | MIT OR Apache-2.0 |
| memchr | MIT OR Unlicense |
| zmij (transitive, via `serde_json`'s float formatting) | MIT |

All compatible with Apache-2.0 distribution. `unicode-ident`'s additional
`Unicode-DFS-2016` term applies only to its embedded Unicode character-
property data tables, not to CAIRN's own code, and permits redistribution
with attribution (already satisfied by the crate's own bundled licence
file, carried through unmodified). Re-check with `cargo tree` and re-read
each new crate's licence field whenever a new external dependency is
added — this file does not automatically track `Cargo.lock`.
