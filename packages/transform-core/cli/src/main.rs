//! `cairn-transform-cli`: the thin Rust binary that chains the
//! parser -> detector -> patcher pipeline end to end over 722's
//! versioned JSON contract, read from stdin and written to stdout.
//!
//! This is the subprocess boundary 726's Python-side `TransformationPort`
//! adapter invokes (per `~/solara/lz2026/cairn-r3-briefs.md` §7's
//! open-question 1 resolution: a subprocess over the versioned JSON
//! contract, not an in-process FFI extension -- ADR-006's Rust/Python
//! split stays one-directional and this process is trivial to sandbox,
//! 731). No crate before this one chained parser->detector->patcher into
//! a single callable unit; this crate is exactly that, and nothing more.
//!
//! Protocol: read exactly one JSON-encoded `cairn_transform_contract::
//! ParseInput` object from stdin (to EOF), run it through the matching
//! language parser (722's `parse_hcl` for `Terraform`, 723's
//! `parse_python` for `Python`), then 724's `detect` and 725's `patch`,
//! and write exactly one JSON-encoded `CliOutput` object to stdout,
//! terminated by a newline. On any input/parse-dispatch error (malformed
//! JSON, an input whose `language` is `Unsupported`), write a one-line
//! JSON error object to stdout instead and exit non-zero -- never a
//! panic, never partial output, so the Python-side adapter can always
//! either parse a `CliOutput` or get a clean failure to raise on.
//!
//! No network access of any kind: this binary only reads stdin, writes
//! stdout, and calls the three in-memory pipeline crates. See
//! `tests::no_network_imports_in_cli_source`.

#![forbid(unsafe_code)]

use std::io::{self, Read, Write};
use std::process::ExitCode;

use cairn_transform_contract::{ParseInput, ParseOutput, SourceLanguage};
use cairn_transform_detector::{detect, DETECTOR_VERSION};
use cairn_transform_parser::{parse_hcl, parse_python, HCL_PARSER_VERSION, PYTHON_PARSER_VERSION};
use cairn_transform_patcher::{patch, ChangeSet, PATCHER_VERSION};
use serde::{Deserialize, Serialize};

/// Unit 727's end-to-end golden-corpus/deliberate-break pass over this
/// pipeline found a real gap, not a hypothetical one: when `ParseOutput`
/// is `Unsupported` or `Error` (722's unterminated-block/heredoc cases;
/// 723's f-string/walrus/control-flow cases), `detect()` returns an
/// empty `DetectionSet` (724's own documented behaviour -- "no AST at
/// all" produces `DetectionSet::empty`), so `patch()` in turn produces a
/// `ChangeSet` with zero entries. Before this field existed, that file's
/// manifest line was *indistinguishable from a file that parsed cleanly
/// and simply had nothing to flag* -- the parse failure was swallowed by
/// the detector stage, exactly the failure mode ADR-015's "applied/
/// skipped/unsupported outcomes and reasons" manifest requirement exists
/// to prevent. `parse_status` carries the parse stage's own outcome
/// forward explicitly, so 726's `build_manifest` can synthesize a
/// manifest entry for a file whose `change_set` is empty *because
/// parsing never produced an AST to detect against*, rather than that
/// file silently vanishing from the manifest.
#[derive(Debug, Serialize, Deserialize)]
pub struct ParseStatus {
    /// `"PARSED"`, `"UNSUPPORTED"`, or `"ERROR"` -- mirrors
    /// `ParseOutput`'s three variants by name.
    pub status: String,
    /// `None` iff `status == "PARSED"`; the parser's own `reason`
    /// (`Unsupported`) or `error.reason` (`Error`) otherwise.
    pub reason: Option<String>,
}

/// The exact shape written to stdout on success. `parser_version` is
/// surfaced here explicitly (not only inside `ParseOutput`, which this
/// binary does not emit at all) because 726's Python-side manifest needs
/// it per-entry and the `ChangeSet`/`ChangeEntry` types 725 shipped never
/// carry it -- only the detector/patcher versions do.
#[derive(Debug, Serialize, Deserialize)]
pub struct CliOutput {
    pub parser_version: String,
    pub detector_version: String,
    pub patcher_version: String,
    pub change_set: ChangeSet,
    pub parse_status: ParseStatus,
}

/// A one-line error payload, written to stdout (not stderr) so the
/// adapter only ever has one stream to read for the contract, and exits
/// non-zero so a caller checking the exit code never mistakes this for
/// success.
#[derive(Debug, Serialize, Deserialize)]
pub struct CliError {
    pub error: String,
}

fn run(source_text: &str) -> Result<CliOutput, String> {
    let input: ParseInput =
        serde_json::from_str(source_text).map_err(|e| format!("invalid ParseInput JSON: {e}"))?;

    let (parse_output, parser_version): (ParseOutput, &str) = match input.language {
        SourceLanguage::Terraform => (parse_hcl(&input), HCL_PARSER_VERSION),
        SourceLanguage::Python => (parse_python(&input), PYTHON_PARSER_VERSION),
        SourceLanguage::Unsupported => {
            return Err(format!(
                "cannot parse source_file_id {:?}: language is UNSUPPORTED \
                 (ADR-015 R3 scope is Terraform/HCL and Python only)",
                input.source_file_id
            ));
        }
    };

    let parse_status = match &parse_output {
        ParseOutput::Parsed { .. } => ParseStatus {
            status: "PARSED".to_string(),
            reason: None,
        },
        ParseOutput::Unsupported { reason, .. } => ParseStatus {
            status: "UNSUPPORTED".to_string(),
            reason: Some(reason.clone()),
        },
        ParseOutput::Error { error, .. } => ParseStatus {
            status: "ERROR".to_string(),
            reason: Some(error.reason.clone()),
        },
    };

    let detections = detect(&parse_output);
    let change_set = patch(&parse_output, &detections);

    Ok(CliOutput {
        parser_version: parser_version.to_string(),
        detector_version: DETECTOR_VERSION.to_string(),
        patcher_version: PATCHER_VERSION.to_string(),
        change_set,
        parse_status,
    })
}

fn main() -> ExitCode {
    let mut source_text = String::new();
    if let Err(e) = io::stdin().read_to_string(&mut source_text) {
        let _ = writeln!(
            io::stdout(),
            "{}",
            serde_json::to_string(&CliError {
                error: format!("could not read stdin: {e}")
            })
            .unwrap_or_else(|_| "{\"error\":\"could not read stdin\"}".to_string())
        );
        return ExitCode::FAILURE;
    }

    match run(&source_text) {
        Ok(output) => match serde_json::to_string(&output) {
            Ok(json) => {
                let _ = writeln!(io::stdout(), "{json}");
                ExitCode::SUCCESS
            }
            Err(e) => {
                let _ = writeln!(
                    io::stdout(),
                    "{}",
                    serde_json::to_string(&CliError {
                        error: format!("could not serialize CliOutput: {e}")
                    })
                    .unwrap_or_else(|_| "{\"error\":\"could not serialize output\"}".to_string())
                );
                ExitCode::FAILURE
            }
        },
        Err(message) => {
            let _ = writeln!(
                io::stdout(),
                "{}",
                serde_json::to_string(&CliError { error: message })
                    .unwrap_or_else(|_| "{\"error\":\"unknown error\"}".to_string())
            );
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::Path;

    fn hcl_input(source_file_id: &str, source_text: &str) -> String {
        serde_json::json!({
            "source_file_id": source_file_id,
            "language": "TERRAFORM",
            "source_text": source_text,
        })
        .to_string()
    }

    fn python_input(source_file_id: &str, source_text: &str) -> String {
        serde_json::json!({
            "source_file_id": source_file_id,
            "language": "PYTHON",
            "source_text": source_text,
        })
        .to_string()
    }

    const S3_ACL_FIXTURE: &str = r#"
resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-demo-artifacts"
  acl    = "public-read"
}
"#;

    const IMPORT_IMP_FIXTURE: &str = "import imp\n";

    #[test]
    fn hcl_fixture_runs_end_to_end_and_applies_the_acl_rewrite() {
        let output = run(&hcl_input("s3.tf", S3_ACL_FIXTURE)).expect("pipeline should succeed");
        assert_eq!(output.parser_version, HCL_PARSER_VERSION);
        assert_eq!(output.detector_version, DETECTOR_VERSION);
        assert_eq!(output.patcher_version, PATCHER_VERSION);
        assert_eq!(output.change_set.entries.len(), 1);
        assert_eq!(
            output.change_set.entries[0].outcome,
            cairn_transform_patcher::ChangeOutcome::Applied
        );
    }

    #[test]
    fn python_fixture_runs_end_to_end_and_applies_the_import_rewrite() {
        let output =
            run(&python_input("mod.py", IMPORT_IMP_FIXTURE)).expect("pipeline should succeed");
        assert_eq!(output.parser_version, PYTHON_PARSER_VERSION);
        assert_eq!(output.change_set.entries.len(), 1);
        assert_eq!(
            output.change_set.entries[0].outcome,
            cairn_transform_patcher::ChangeOutcome::Applied
        );
    }

    #[test]
    fn unsupported_language_is_a_clean_error_not_a_panic() {
        let input = serde_json::json!({
            "source_file_id": "weird.bin",
            "language": "UNSUPPORTED",
            "source_text": "",
        })
        .to_string();
        let result = run(&input);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("UNSUPPORTED"));
    }

    #[test]
    fn malformed_json_input_is_a_clean_error_not_a_panic() {
        let result = run("not valid json at all");
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("invalid ParseInput JSON"));
    }

    #[test]
    fn output_round_trips_through_json_byte_identically_across_repeated_runs() {
        let first = run(&hcl_input("s3.tf", S3_ACL_FIXTURE)).unwrap();
        let second = run(&hcl_input("s3.tf", S3_ACL_FIXTURE)).unwrap();
        assert_eq!(
            serde_json::to_string(&first).unwrap(),
            serde_json::to_string(&second).unwrap()
        );
    }

    #[test]
    fn deliberate_break_case_runtime_interpolation_is_unsupported_not_applied() {
        let fixture = r#"
resource "aws_s3_bucket" "interpolated" {
  bucket = "demo-bucket"
  acl    = "${var.environment}-public-read"
}
"#;
        let output = run(&hcl_input("interpolated.tf", fixture)).unwrap();
        assert_eq!(output.change_set.entries.len(), 1);
        assert_eq!(
            output.change_set.entries[0].outcome,
            cairn_transform_patcher::ChangeOutcome::Unsupported
        );
    }

    #[test]
    fn hcl_fixture_runs_end_to_end_reports_parsed_status() {
        let output = run(&hcl_input("s3.tf", S3_ACL_FIXTURE)).unwrap();
        assert_eq!(output.parse_status.status, "PARSED");
        assert!(output.parse_status.reason.is_none());
    }

    // Unit 727's required deliberate-break case, re-run through the
    // *CLI* layer this crate owns: 722's own `unterminated block` case
    // (its handover documents the exact reason prefix
    // "unterminated block: expected closing '}'"). Confirms the parse
    // failure is visible on `CliOutput` itself, not only inside the
    // change set (which, per the comment on `ParseStatus` above, is
    // empty either way and therefore cannot carry this on its own).
    #[test]
    fn unterminated_hcl_block_reports_error_parse_status_with_empty_change_set() {
        let fixture = r#"
resource "aws_s3_bucket" "broken" {
  bucket = "demo"
"#;
        let output = run(&hcl_input("broken.tf", fixture)).expect("pipeline should still succeed");
        assert_eq!(output.parse_status.status, "ERROR");
        let reason = output
            .parse_status
            .reason
            .expect("ERROR status must carry a reason");
        assert!(
            reason.contains("unterminated block"),
            "reason should name the parse failure, got: {reason}"
        );
        assert!(
            output.change_set.entries.is_empty(),
            "an unparsed file has no detections to patch -- the change set alone cannot \
             carry this failure forward, which is exactly why parse_status exists"
        );
    }

    // 723's required deliberate-break case (f-strings are outside the
    // pilot's Python subset) re-run through the CLI layer: `Unsupported`,
    // not `Error` -- the file is readable Python, this pilot simply
    // declines to represent the construct.
    #[test]
    fn fstring_python_construct_reports_unsupported_parse_status_with_empty_change_set() {
        let output = run(&python_input("greet.py", "greeting = f\"hello {name}\"\n")).unwrap();
        assert_eq!(output.parse_status.status, "UNSUPPORTED");
        let reason = output
            .parse_status
            .reason
            .expect("UNSUPPORTED status must carry a reason");
        assert!(
            reason.contains("f-string"),
            "reason should name the unsupported construct, got: {reason}"
        );
        assert!(output.change_set.entries.is_empty());
    }

    #[test]
    fn no_network_imports_in_cli_source() {
        let src_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        for entry in fs::read_dir(&src_dir).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().and_then(|e| e.to_str()) != Some("rs") {
                continue;
            }
            let contents = fs::read_to_string(&path).unwrap();
            let without_test_mod = contents.split("#[cfg(test)]").next().unwrap_or(&contents);
            assert!(
                !without_test_mod.contains("std::net")
                    && !without_test_mod.contains("use std::net"),
                "{path:?} must not import std::net"
            );
            assert!(
                !without_test_mod.contains("reqwest"),
                "{path:?} must not depend on reqwest"
            );
        }
    }
}
