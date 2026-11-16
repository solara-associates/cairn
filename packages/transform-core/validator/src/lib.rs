//! `cairn-transform-validator`: the static-validation half of spec S16/R3-05
//! ("Implement validation adapters (static, tests, dependency)"), and spec
//! §5.4's `ValidationPort | transformation | test/static runner, fake` row.
//!
//! This crate answers exactly one question, deterministically and without
//! any external process, network call, or linter: **does the rewritten
//! text 725's patcher proposes still parse under 722/723's own parser?**
//! It is a syntactic self-check, never an external linter and never a
//! semantic judgement -- the same "does the rule's own earlier stage still
//! agree with itself" discipline the rest of `transform-core` already uses
//! (724's detector re-walking the same AST a parser produced; 725's patcher
//! re-locating the exact span a detector matched).
//!
//! ## Why this crate defines its own `ProposedEdit`/`ProposedChangeSet`,
//! not 725's `cairn_transform_patcher::{TextEdit, ChangeSet}`
//!
//! The only facts this check needs about a proposed change are "which
//! bytes get replaced, with what" -- exactly `TextEdit`'s two fields,
//! already filtered down to `ChangeOutcome::Applied` entries (a `Skipped`/
//! `Unsupported` entry has no edits to re-check in the first place). 725's
//! `ChangeEntry`/`ChangeSet` additionally carry `ChangeOrigin` (the whole
//! originating `Detection`/`SkippedCandidate`), which this check never
//! reads and which 726's Python-side manifest (`ManifestEntry`) does not
//! carry forward verbatim either -- reconstructing a byte-identical
//! `ChangeOrigin` from a `ManifestEntry` on the Python side just to satisfy
//! this crate's input type would be manufactured work with no reader. This
//! crate therefore depends on `cairn-transform-contract` and
//! `cairn-transform-parser` only -- not `cairn-transform-detector` or
//! `cairn-transform-patcher` -- and defines the minimal input shape its one
//! check actually needs. A caller (726's manifest, 728's diff artefact, or
//! this crate's own `validator_cli` binary) is responsible for flattening
//! whichever `Applied` entries it already has into this shape.
//!
//! No network access of any kind: this crate only parses in-memory text.
//! See `tests::no_network_imports_in_validator_source`.

#![forbid(unsafe_code)]

use cairn_transform_contract::{ParseInput, ParseOutput, Span};
use cairn_transform_parser::{parse_hcl, parse_python, HCL_PARSER_VERSION, PYTHON_PARSER_VERSION};
use serde::{Deserialize, Serialize};

/// This crate's one check id, for the transformation manifest's
/// aggregation layer (729/R3-05's Python-side `cairn_modules.transformation.
/// validation`) to key results by. Never a real detector/patcher rule id
/// (724's `rule_ids` module) -- this is a validation check id, a distinct
/// namespace, the same way 727's `PARSE_INCOMPLETE_RULE_ID` is named
/// explicitly as its own sentinel rather than reusing a rule id.
pub const STATIC_REPARSE_CHECK_ID: &str = "static-reparse";

/// Identifies this validator implementation and its version, mirroring
/// `DETECTOR_VERSION`/`PATCHER_VERSION`'s own naming convention.
pub const VALIDATOR_VERSION: &str = "cairn-transform-validator/0.1.0";

/// One byte-precise proposed replacement -- the same shape as 725's
/// `TextEdit`, defined independently here (see module docs for why).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProposedEdit {
    pub span: Span,
    pub replacement: String,
}

/// The proposed change to one source file: every `Applied` edit a caller
/// wants this check to re-verify, already flattened out of whatever
/// detection/skip bookkeeping produced them. An empty `edits` list is a
/// legitimate "no proposed change for this file" input -- the check still
/// runs (the "rewritten" text is then identical to the original), it is
/// never an error to call this with nothing to apply.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProposedChangeSet {
    pub source_file_id: String,
    pub edits: Vec<ProposedEdit>,
}

/// One check's outcome. `reason` is `None` iff `passed` -- the same
/// invariant 725's `ChangeEntry` already uses for `Applied` vs. everything
/// else, checked by `tests::failing_result_always_carries_a_reason`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValidationResult {
    pub check_id: String,
    pub passed: bool,
    pub reason: Option<String>,
}

impl ValidationResult {
    fn pass(check_id: impl Into<String>) -> Self {
        Self {
            check_id: check_id.into(),
            passed: true,
            reason: None,
        }
    }

    fn fail(check_id: impl Into<String>, reason: impl Into<String>) -> Self {
        Self {
            check_id: check_id.into(),
            passed: false,
            reason: Some(reason.into()),
        }
    }
}

/// Apply every edit in `edits` to `source_text`, back-to-front by
/// `start_byte` (the same ordering discipline `cairn_modules.transformation.
/// diff._apply_edits` uses on the Python side, for the identical reason:
/// an earlier edit's byte offsets are never invalidated by a later edit
/// shifting the buffer). Byte-precise against the UTF-8 encoding of
/// `source_text`, never against `char`/`str` indices -- 722/723's parsers
/// measure spans the same way (see `cairn_transform_contract::Span`'s own
/// docs).
fn apply_edits(source_text: &str, edits: &[ProposedEdit]) -> String {
    let mut ordered: Vec<&ProposedEdit> = edits.iter().collect();
    ordered.sort_by(|a, b| b.span.start_byte.cmp(&a.span.start_byte));

    let mut buffer: Vec<u8> = source_text.as_bytes().to_vec();
    for edit in ordered {
        let start = edit.span.start_byte.min(buffer.len());
        let end = edit.span.end_byte.min(buffer.len()).max(start);
        let mut next = Vec::with_capacity(buffer.len());
        next.extend_from_slice(&buffer[..start]);
        next.extend_from_slice(edit.replacement.as_bytes());
        next.extend_from_slice(&buffer[end..]);
        buffer = next;
    }
    String::from_utf8(buffer).unwrap_or_else(|err| {
        // Only reachable if a caller's edits slice a multi-byte UTF-8
        // sequence in half -- never silently produce replacement
        // characters or lossy text; a caller that did this gets a loud,
        // deterministic panic rather than a validator that quietly
        // "passed" over corrupted text. 725's patcher never emits an edit
        // whose span falls inside a multi-byte character (spans always
        // come from the AST's own token boundaries), so this is a
        // defensive check against a malformed caller, not a case this
        // crate's own golden corpus should ever reach.
        panic!("apply_edits produced invalid UTF-8: {err}")
    })
}

fn parser_version_language(
    parser_version: &str,
) -> Option<cairn_transform_contract::SourceLanguage> {
    use cairn_transform_contract::SourceLanguage;
    if parser_version == HCL_PARSER_VERSION {
        Some(SourceLanguage::Terraform)
    } else if parser_version == PYTHON_PARSER_VERSION {
        Some(SourceLanguage::Python)
    } else {
        None
    }
}

/// Run every static check this crate defines (today: exactly one, the
/// re-parse self-check) over one file's original text, its authoritative
/// `ParseOutput` (722/723's parser output for `source_text` -- never
/// re-derived here; the caller already has it and this check must not
/// silently disagree with it), and the proposed change. Spec S16/R3-05:
/// "Results per check" -- a `Vec`, one entry per check, never collapsed
/// into a single pass/fail bit, so a caller can report *which* check
/// failed and why.
pub fn validate(
    source_text: &str,
    parse_output: &ParseOutput,
    proposed: &ProposedChangeSet,
) -> Vec<ValidationResult> {
    vec![validate_static_reparse(source_text, parse_output, proposed)]
}

fn validate_static_reparse(
    source_text: &str,
    parse_output: &ParseOutput,
    proposed: &ProposedChangeSet,
) -> ValidationResult {
    if !parse_output.is_parsed() {
        return ValidationResult::fail(
            STATIC_REPARSE_CHECK_ID,
            format!(
                "cannot validate a proposed change to {:?}: the original source did not parse \
                 in the first place (parser_version {:?})",
                parse_output.source_file_id(),
                parse_output.parser_version()
            ),
        );
    }

    let language = match parser_version_language(parse_output.parser_version()) {
        Some(language) => language,
        None => {
            return ValidationResult::fail(
                STATIC_REPARSE_CHECK_ID,
                format!(
                    "unrecognized parser_version {:?}; cannot select a grammar to re-check \
                     the proposed change against",
                    parse_output.parser_version()
                ),
            );
        }
    };

    let rewritten_text = apply_edits(source_text, &proposed.edits);
    let reparse_input = ParseInput {
        source_file_id: proposed.source_file_id.clone(),
        language,
        source_text: rewritten_text,
    };

    use cairn_transform_contract::SourceLanguage;
    let reparsed = match language {
        SourceLanguage::Terraform => parse_hcl(&reparse_input),
        SourceLanguage::Python => parse_python(&reparse_input),
        SourceLanguage::Unsupported => unreachable!(
            "parser_version_language never returns Unsupported for a recognized parser_version"
        ),
    };

    match reparsed {
        ParseOutput::Parsed { .. } => ValidationResult::pass(STATIC_REPARSE_CHECK_ID),
        ParseOutput::Unsupported { reason, .. } => ValidationResult::fail(
            STATIC_REPARSE_CHECK_ID,
            format!(
                "the proposed change produces text this parser can no longer represent: {reason}"
            ),
        ),
        ParseOutput::Error { error, .. } => ValidationResult::fail(
            STATIC_REPARSE_CHECK_ID,
            format!(
                "the proposed change produces text that no longer parses: {}",
                error.reason
            ),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cairn_transform_contract::SourceLanguage;

    fn parse(source_file_id: &str, language: SourceLanguage, source_text: &str) -> ParseOutput {
        let input = ParseInput {
            source_file_id: source_file_id.to_string(),
            language,
            source_text: source_text.to_string(),
        };
        match language {
            SourceLanguage::Terraform => parse_hcl(&input),
            SourceLanguage::Python => parse_python(&input),
            SourceLanguage::Unsupported => panic!("not used in these tests"),
        }
    }

    const HCL_FIXTURE: &str = r#"
resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-demo-artifacts"
  acl    = "public-read"
}
"#;

    const PY_FIXTURE: &str = "import imp\n";

    #[test]
    fn a_safe_hcl_rewrite_still_parses_and_passes() {
        let parse_output = parse("s3.tf", SourceLanguage::Terraform, HCL_FIXTURE);
        // Replace the literal "public-read" value with "private" -- a
        // same-shape string literal substitution, still valid HCL.
        let start = HCL_FIXTURE.find("\"public-read\"").unwrap();
        let end = start + "\"public-read\"".len();
        let proposed = ProposedChangeSet {
            source_file_id: "s3.tf".to_string(),
            edits: vec![ProposedEdit {
                span: Span {
                    start_byte: start,
                    end_byte: end,
                    start_line: 4,
                    end_line: 4,
                },
                replacement: "\"private\"".to_string(),
            }],
        };
        let results = validate(HCL_FIXTURE, &parse_output, &proposed);
        assert_eq!(results.len(), 1);
        assert!(results[0].passed, "{:?}", results[0]);
        assert_eq!(results[0].check_id, STATIC_REPARSE_CHECK_ID);
        assert!(results[0].reason.is_none());
    }

    #[test]
    fn a_rewrite_that_breaks_hcl_syntax_fails_the_reparse_check() {
        let parse_output = parse("broken_rewrite.tf", SourceLanguage::Terraform, HCL_FIXTURE);
        // Delete the closing brace of the resource block -- a rewrite
        // that would genuinely corrupt the file. The static check must
        // catch this, not rubber-stamp it.
        let brace_pos = HCL_FIXTURE.rfind('}').unwrap();
        let proposed = ProposedChangeSet {
            source_file_id: "broken_rewrite.tf".to_string(),
            edits: vec![ProposedEdit {
                span: Span {
                    start_byte: brace_pos,
                    end_byte: brace_pos + 1,
                    start_line: 5,
                    end_line: 5,
                },
                replacement: String::new(),
            }],
        };
        let results = validate(HCL_FIXTURE, &parse_output, &proposed);
        assert_eq!(results.len(), 1);
        assert!(!results[0].passed);
        let reason = results[0]
            .reason
            .as_ref()
            .expect("a failing result must carry a reason");
        assert!(
            reason.to_lowercase().contains("no longer parses"),
            "reason: {reason}"
        );
    }

    #[test]
    fn a_safe_python_rewrite_still_parses_and_passes() {
        let parse_output = parse("mod.py", SourceLanguage::Python, PY_FIXTURE);
        let proposed = ProposedChangeSet {
            source_file_id: "mod.py".to_string(),
            edits: vec![ProposedEdit {
                span: Span {
                    start_byte: "import ".len(),
                    end_byte: "import imp".len(),
                    start_line: 1,
                    end_line: 1,
                },
                replacement: "importlib".to_string(),
            }],
        };
        let results = validate(PY_FIXTURE, &parse_output, &proposed);
        assert!(results[0].passed, "{:?}", results[0]);
    }

    #[test]
    fn a_rewrite_that_breaks_python_syntax_fails_the_reparse_check() {
        let parse_output = parse("broken_rewrite.py", SourceLanguage::Python, PY_FIXTURE);
        // Replace the whole line with something syntactically invalid
        // under this pilot's grammar (an unterminated string).
        let proposed = ProposedChangeSet {
            source_file_id: "broken_rewrite.py".to_string(),
            edits: vec![ProposedEdit {
                span: Span {
                    start_byte: 0,
                    end_byte: PY_FIXTURE.len(),
                    start_line: 1,
                    end_line: 1,
                },
                replacement: "x = \"unterminated".to_string(),
            }],
        };
        let results = validate(PY_FIXTURE, &parse_output, &proposed);
        assert!(!results[0].passed);
        assert!(results[0].reason.is_some());
    }

    #[test]
    fn an_empty_proposed_change_set_still_passes_when_the_original_already_parses() {
        let parse_output = parse("untouched.tf", SourceLanguage::Terraform, HCL_FIXTURE);
        let proposed = ProposedChangeSet {
            source_file_id: "untouched.tf".to_string(),
            edits: vec![],
        };
        let results = validate(HCL_FIXTURE, &parse_output, &proposed);
        assert!(results[0].passed);
    }

    #[test]
    fn an_original_parse_failure_is_reported_explicitly_not_silently_passed() {
        let broken_source = "resource \"aws_instance\" \"web\" {\n  ami = \"ami-123\"\n";
        let parse_output = parse("unterminated.tf", SourceLanguage::Terraform, broken_source);
        assert!(matches!(parse_output, ParseOutput::Error { .. }));
        let proposed = ProposedChangeSet {
            source_file_id: "unterminated.tf".to_string(),
            edits: vec![],
        };
        let results = validate(broken_source, &parse_output, &proposed);
        assert!(!results[0].passed);
        assert!(
            results[0]
                .reason
                .as_ref()
                .unwrap()
                .contains("did not parse"),
            "{:?}",
            results[0]
        );
    }

    #[test]
    fn failing_result_always_carries_a_reason_passing_result_never_does() {
        for source_file_id in ["a.tf", "b.tf"] {
            let parse_output = parse(source_file_id, SourceLanguage::Terraform, HCL_FIXTURE);
            let proposed = ProposedChangeSet {
                source_file_id: source_file_id.to_string(),
                edits: vec![],
            };
            for result in validate(HCL_FIXTURE, &parse_output, &proposed) {
                assert_eq!(result.passed, result.reason.is_none());
            }
        }
    }

    #[test]
    fn validation_is_deterministic_across_repeated_runs() {
        let parse_output = parse("s3.tf", SourceLanguage::Terraform, HCL_FIXTURE);
        let proposed = ProposedChangeSet {
            source_file_id: "s3.tf".to_string(),
            edits: vec![],
        };
        let first = validate(HCL_FIXTURE, &parse_output, &proposed);
        let second = validate(HCL_FIXTURE, &parse_output, &proposed);
        assert_eq!(
            serde_json::to_string(&first).unwrap(),
            serde_json::to_string(&second).unwrap()
        );
    }

    #[test]
    fn no_network_imports_in_validator_source() {
        use std::fs;
        use std::path::Path;

        let src_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let forbidden_net: String = ["std", "::", "net", "::"].concat();
        let forbidden_reqwest: String = ["req", "west", "::"].concat();
        for entry in fs::read_dir(&src_dir).expect("readable src dir") {
            let path = entry.expect("readable dir entry").path();
            if path.extension().and_then(|e| e.to_str()) != Some("rs") {
                continue;
            }
            let text = fs::read_to_string(&path).expect("readable source file");
            let production_code = match text.find("#[cfg(test)]") {
                Some(idx) => &text[..idx],
                None => &text[..],
            };
            assert!(
                !production_code.contains(&forbidden_net),
                "{}: must not import std::net",
                path.display()
            );
            assert!(
                !production_code.contains(&forbidden_reqwest),
                "{}: must not depend on reqwest",
                path.display()
            );
        }
    }
}
