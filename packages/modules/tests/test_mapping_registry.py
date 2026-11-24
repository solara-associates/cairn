from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cairn_contracts.estate import Equivalence
from cairn_contracts.mapping import MappingRelease, ReleaseStatus
from cairn_kernel.errors import ValidationError
from cairn_modules.mappings import load_mapping_release
from pydantic import ValidationError as PydanticValidationError

REPO_ROOT = Path(__file__).parents[3]
SEED_PATH = REPO_ROOT / "mappings" / "service-map.yaml"


def _payload() -> dict[str, Any]:
    return {
        "version": "2026.11.1",
        "released_at": "2026-11-09T00:00:00Z",
        "status": "PUBLISHED",
        "entries": [
            {
                "id": "s3-to-gcs",
                "source_provider": "aws",
                "source_service": "s3",
                "target_provider": "gcp",
                "target_service": "cloud-storage",
                "equivalence": "APPROXIMATE",
                "caveat": "Consistency semantics differ",
                "regions": ["europe-west2"],
                "evidence": "public documentation",
            }
        ],
    }


def _release(payload: dict[str, Any] | None = None) -> MappingRelease:
    return MappingRelease.model_validate(payload or _payload())


def test_seed_release_loads() -> None:
    release = load_mapping_release(SEED_PATH)

    assert release.version == "2026.11.2"
    # R2-02: this is the real top-40-per-pilot-pair candidate content,
    # proposed via MappingRepository.propose and currently IN_REVIEW
    # (docs/specs/mapping-seed-review.md). MappingRelease.content_hash is
    # computed assuming ``status=DRAFT`` always (see
    # cairn_modules.mappings.domain's module docstring), which is also the
    # only legal status a release may carry when passed to ``propose()`` --
    # so the committed seed file's own top-level ``status`` field is DRAFT,
    # not a claim about the real release's current ADR-004 workflow status.
    assert release.status is ReleaseStatus.DRAFT
    assert len(release.entries) >= 40
    s3 = next(entry for entry in release.entries if entry.id == "s3-to-gcs")
    assert s3.equivalence is Equivalence.APPROXIMATE
    assert s3.caveat
    assert s3.regions == ("europe-west2", "us-central1", "asia-south1")


def test_content_hash_is_stable_across_round_trip() -> None:
    release = _release()

    reparsed = MappingRelease.model_validate_json(release.model_dump_json())

    assert reparsed.content_hash == release.content_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": "2026-11.1"},
        {"released_at": "2026-11-09T00:00:00"},
        {"status": "UNKNOWN"},
        {"entries": []},
    ],
)
def test_release_rejects_invalid_top_level_fields(overrides: dict[str, Any]) -> None:
    payload = _payload()
    payload.update(overrides)

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


@pytest.mark.parametrize(
    "entry_overrides",
    [
        {"caveat": None},
        {"target_service": None},
        {"evidence": "  "},
        {"regions": ["europe-west2", "europe-west2"]},
        {"source_provider": ""},
    ],
)
def test_entry_rejects_invalid_fields(entry_overrides: dict[str, Any]) -> None:
    payload = _payload()
    payload["entries"][0].update(entry_overrides)

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


def test_entry_requires_target_service_for_exact_mapping() -> None:
    payload = _payload()
    payload["entries"][0].update(
        {"equivalence": "EXACT", "target_service": None, "caveat": None}
    )

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


def test_release_rejects_duplicate_entry_ids() -> None:
    payload = _payload()
    payload["entries"].append(deepcopy(payload["entries"][0]))

    with pytest.raises(PydanticValidationError):
        MappingRelease.model_validate(payload)


def test_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot read"):
        load_mapping_release(tmp_path / "missing.yaml")


def test_loader_rejects_malformed_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("version: [unterminated", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid YAML"):
        load_mapping_release(path)


def test_loader_rejects_non_mapping_document(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- version\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="must be a YAML mapping"):
        load_mapping_release(path)


def test_loader_wraps_schema_errors(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("version: not-a-version\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid mapping release"):
        load_mapping_release(path)


# --- R2-02: coverage/schema checks on the real seed candidate ---------------
#
# These assert properties of the real `mappings/service-map.yaml` content
# that aren't already implied by `test_seed_release_loads` succeeding at all
# (which already proves "every entry valid" via `MappingEntry`'s own
# validators, including "every non-exact entry has a caveat" --
# `MappingEntry._validate_equivalence` raises otherwise). ADR-017's
# clean-room rule is the one property the schema itself cannot check: no
# `evidence` string may name a reference-portfolio repository, since that
# would cite a non-public, non-citable source for a judgement this story
# must ground in public vendor documentation only.

# Every repository named in CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md section
# 17's source analysis and in `docs/specs/reference-register.md` --
# ADR-017: "design evidence only... nothing is pasted into CAIRN," which
# this story's own brief extends to citation: a reference-portfolio
# repository is never a citable public source for an `evidence` string.
#
# Held as SHA-256 hex digests of each name, lowercased, rather than as
# plaintext (s879 hygiene pass): the names themselves are prior-work
# repository identifiers that must never be cited in this codebase, and a
# denylist naming them defeats its own purpose by being exactly such a
# citation. `_tokenize` below extracts each candidate token from an
# evidence string and hashes it the same way before checking membership,
# so the test still fails the moment a real name appears anywhere it
# scans -- it just never has to spell one out to do it. Regenerate with
# `hashlib.sha256(name.lower().encode()).hexdigest()` for each name if
# this set ever needs a new entry; do not add a plaintext name next to it.
REFERENCE_PORTFOLIO_REPOSITORY_HASHES: frozenset[str] = frozenset(
    (
        "e416435a1f8d19180a71d7ba3835cf151f74ec76291823e877e5f2ca7d8f3311",
        "b6c4ac412ac8822355239dd717c11ca5b07373e4db550d0423c1b6aeceef8493",
        "d59c9d5485df2fb3fe2dd547287b010ce4573e20e87e98f4a90de2029d6a159e",
        "3517efc324466969394924bd3473c57dbff483e63c494a6df5e81c2e31d664f6",
        "d4ea85cd5a75a4fa41bd55ae2110c4edff55aae94fd1a904ff99becdfdf82f8f",
        "effc5355da6acf9ec72d24c871c8c0ea8d0a59ba7815116cf35b059fb2e7a7f8",
        "0820c280b7ceff979f8c9efba71c3df93c43a7d604e8ee7cad731b75acb96eb3",
        "981d153e7600f0255bc30aa482bf0429e0d64ec1d37785b00487024720a12d9b",
        "fcab9e686f87810fe5c53df16c01ca7d8ce7eea7d359da151c988a0304930bc5",
        "1102178abc3503ce06c0d3779e092367bef28f17d834487375fad90b7b246b1c",
        "bde4e01f8ba1ddb2f1f217d13992ab876ff9bbc90bd10a485cb416595304e9d3",
        "05c1c67c02a1ff239ba0d2a1b2a6097c9b239bafc1fab959425994adb5b26a40",
        "d4021486b8b6683cba8d6714ff562c30ea81cb69e10654aed22b9019860669fb",
        "423fb404ba34657a6f5ffbd3b09bd4aa9be296440fd2f1caaa0055c9c575ad4c",
        "b934361290df16b58b2424804d821e920037e52446af0ee17c6cb5c76e0262f1",
        "f508a05936bfb5e5c6dd5eda71d685a2eb4d5dd3fb8592a8628bbb9bb180ecce",
        "4635a72ee9882d960ca1bcd03772d0f47dc4a07d8e83ef8835f56dcb69aef96e",
        "15d71d4bc4b158a55507873cce9340b8f055c8955493a2319ac4cde4c1e887f5",
        "19c52821fa3f774b1d7bc9a5b66ce597a9e28a2e6c91d69cbbd73181428e6d1b",
        "72ccb8227d29b59b2a99b29363e1c0541b11a5ef850c6bc069eb670b4c6a4dbc",
        "de75f24335d8115eeca6b04b0fc32f68f6ade13d7c6305be2fe347ebf7f5bf04",
        "1d4b6289382b90c6e06c3a85204ce4edd8351cdb98fc9e6a154b64ae8656b9f1",
        "1f4f4954cb64b1723252fd0090cc461eaf0162bbea0bb541402961e68104c5b7",
        "6fda1d6958588b156fb07e6bb8f8935bf9badaf33cebfce4840ae43d948d676b",
        "6211d7401f23d4e92945976111461671dbaa00ff8290a700b0613e4b8ea975f9",
        "48ab4d8e97945d5489b3b2a90a4ec09e6f464f4768b2cdfdfa0779b0488d0616",
        "1b269162f8eeb4c268071d19b28463476b070f85c8b07e21f11ccdbd37625201",
        "bb4c8eb92b6ec7b9055c94a397581544693c61da0f8f6cbb808681ccd0d9ce9b",
        "2305c525a043d6f95fdb395260ac2304f3c3b3e9e39b1a1e32ecd7d15c8ab7c4",
        "1506430f762682f307f19b4e41adece51140b94a96d331dcb4eb50c6136f3c7a",
        "7de80d884d24552ebc1ddc1f1bda7e3391a2ac8acb2dea924adf19e31877ce5e",
        "01f2ba2e6129261f7a54927e5e0c08544ca9cad1baaaa5a81f7ba4636e5b5f99",
        "59bda3f8ee98128d543572e0d29f27ad5343f0c88c36e7bf4672c4c3ab6245b4",
        "bb77941dd8b59fe8e0dde25f0b06856221a86a44ec0ff421bd303e5b1902431d",
        "cbd8069a4b7afe1e8c6529741877c1aaed479ff7e9d635dd2aa9ada5141fcdef",
        "b40cf0c5081906f2c7de69ed9340fd6c06c5030ca5b0d4440089631b5388788d",
        "58a59cf2689f72a9bc720c04bd9e7ecd0ac55785fa3b7876ec732595330f6823",
        "ac7dec645119583d5f47e5208b771544dab614d48020bdf9b4c961e61ca33f08",
        "e694344e46e8a1de50447625161a323f57049bb9e7ce703a4bfae92a109c96ad",
        "dd751b4e69f1e31008061675ff15b3a35a8dc69b054ffcc8d674649b3f0f950c",
        "fc5201c7606bfedbbd28b21c4451b7d88428355b1b8f142ad97aed58843084e7",
    )
)


def _tokenize_for_reference_portfolio_check(text: str) -> set[str]:
    """Candidate tokens to hash-check against
    ``REFERENCE_PORTFOLIO_REPOSITORY_HASHES``: runs of letters, digits,
    hyphens and underscores, lowercased -- the character set every
    reference-portfolio name is made of, so a hyphenated or underscored
    codename survives as one token while surrounding prose, punctuation
    and possessives ("example-tool's" -> "example-tool") are stripped
    away. This catches a name cited as its own word the same way the
    plaintext substring check it replaces did; it does not catch one run
    together with adjacent prose with no separator at all
    (`theexampletool`), which is not a realistic way anyone would
    actually write a citation.
    """

    return set(re.findall(r"[A-Za-z0-9_-]+", text.lower()))


def test_seed_entry_count_reaches_the_adr_004_top_40_floor() -> None:
    release = load_mapping_release(SEED_PATH)

    assert len(release.entries) >= 40


def test_seed_every_non_exact_entry_has_a_caveat() -> None:
    # Belt-and-braces alongside the schema-level guarantee: makes the
    # ADR-004 requirement an explicit, separately readable assertion about
    # the real candidate content rather than only an implication of
    # `test_seed_release_loads` not raising.
    release = load_mapping_release(SEED_PATH)

    for entry in release.entries:
        if entry.equivalence is not Equivalence.EXACT:
            assert entry.caveat, f"{entry.id}: non-exact entry must carry a caveat"


def test_seed_no_evidence_string_names_a_reference_portfolio_repository() -> None:
    release = load_mapping_release(SEED_PATH)

    for entry in release.entries:
        for token in _tokenize_for_reference_portfolio_check(entry.evidence):
            digest = hashlib.sha256(token.encode()).hexdigest()
            assert digest not in REFERENCE_PORTFOLIO_REPOSITORY_HASHES, (
                f"{entry.id}: evidence {entry.evidence!r} names a reference-portfolio"
                " repository -- ADR-017 forbids citing a reference-portfolio repository"
                " as a source; evidence must name public vendor documentation only"
            )


def test_seed_gap_entries_are_unresolved_not_guessed() -> None:
    # ADR-004: "gaps are labelled UNRESOLVED; gaps, not guessed." The
    # shipped `Equivalence` enum (cairn_contracts.estate.model) has no
    # `UNRESOLVED` member -- it has `UNSUPPORTED`, which this story uses as
    # that same concept (see docs/specs/mapping-seed-review.md). An honest
    # gap entry never names a guessed `target_service`.
    release = load_mapping_release(SEED_PATH)

    gaps = [entry for entry in release.entries if entry.equivalence is Equivalence.UNSUPPORTED]
    assert len(gaps) >= 1
    for entry in gaps:
        assert entry.target_service is None, f"{entry.id}: an unresolved gap must not guess a target_service"
        assert entry.caveat


def test_seed_covers_both_assumed_pilot_provider_pairs() -> None:
    # docs/pilot/, docs/residency/uk-residency-matrix.md and spec section
    # 7.2's own illustrative examples already assume AWS->GCP and
    # Azure->GCP; this story replaces the illustrative file's content, not
    # which pairs it targets.
    release = load_mapping_release(SEED_PATH)

    pairs = {(entry.source_provider, entry.target_provider) for entry in release.entries}
    assert ("aws", "gcp") in pairs
    assert ("azure", "gcp") in pairs
