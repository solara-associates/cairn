//! `cairn-transform-validator-cli`: the thin Rust binary that is this
//! unit's (729/R3-05) subprocess boundary, the same shape 726's
//! `cairn-transform-cli` already established for `TransformationPort`.
//! Spec §5.4's `ValidationPort | transformation | test/static runner,
//! fake` -- this binary is the "static runner" half's process boundary;
//! Python's `cairn_adapters.validation_static.subprocess_adapter` invokes
//! it the same way `cairn_adapters.transform_core.subprocess_adapter`
//! invokes 726's CLI.
//!
//! Protocol: read exactly one JSON `ValidatorCliInput` object from stdin
//! (to EOF) -- the original source text, its language, and the proposed
//! edits to re-check -- parse `source_text` with the matching language
//! parser *here* (never trust a caller-supplied `ParseOutput`: this binary
//! is the one place that re-derives it, so the check can never silently
//! disagree with a stale or hand-built parse result), run
//! `cairn_transform_validator::validate`, and write exactly one JSON
//! `{"results": [...]}` object to stdout. On any input error (malformed
//! JSON, an `UNSUPPORTED` language), write a one-line `{"error": ...}`
//! payload to stdout instead and exit non-zero -- never a panic, never
//! partial output, mirroring `cairn-transform-cli`'s own discipline.
//!
//! No network access of any kind: this binary only reads stdin, writes
//! stdout, and calls the in-memory parser/validator crates. See
//! `tests::no_network_imports_in_validator_cli_source`.

#![forbid(unsafe_code)]

use std::io::{self, Read, Write};
use std::process::ExitCode;

use cairn_transform_contract::{ParseInput, SourceLanguage};
use cairn_transform_parser::{parse_hcl, parse_python};
use cairn_transform_validator::{validate, ProposedChangeSet, ProposedEdit, ValidationResult};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
struct ValidatorCliInput {
    source_file_id: String,
    language: SourceLanguage,
    source_text: String,
    edits: Vec<ProposedEdit>,
}

#[derive(Debug, Serialize)]
struct ValidatorCliOutput {
    results: Vec<ValidationResult>,
}

#[derive(Debug, Serialize)]
struct ValidatorCliError {
    error: String,
}

fn run(raw_input: &str) -> Result<ValidatorCliOutput, String> {
    let input: ValidatorCliInput = serde_json::from_str(raw_input)
        .map_err(|e| format!("invalid ValidatorCliInput JSON: {e}"))?;

    let parse_input = ParseInput {
        source_file_id: input.source_file_id.clone(),
        language: input.language,
        source_text: input.source_text.clone(),
    };

    let parse_output = match input.language {
        SourceLanguage::Terraform => parse_hcl(&parse_input),
        SourceLanguage::Python => parse_python(&parse_input),
        SourceLanguage::Unsupported => {
            return Err(format!(
                "cannot validate source_file_id {:?}: language is UNSUPPORTED \
                 (ADR-015 R3 scope is Terraform/HCL and Python only)",
                input.source_file_id
            ));
        }
    };

    let proposed = ProposedChangeSet {
        source_file_id: input.source_file_id,
        edits: input.edits,
    };

    let results = validate(&input.source_text, &parse_output, &proposed);
    Ok(ValidatorCliOutput { results })
}

fn main() -> ExitCode {
    let mut raw_input = String::new();
    if let Err(e) = io::stdin().read_to_string(&mut raw_input) {
        let _ = writeln!(
            io::stdout(),
            "{}",
            serde_json::to_string(&ValidatorCliError {
                error: format!("could not read stdin: {e}")
            })
            .unwrap_or_else(|_| "{\"error\":\"could not read stdin\"}".to_string())
        );
        return ExitCode::FAILURE;
    }

    match run(&raw_input) {
        Ok(output) => match serde_json::to_string(&output) {
            Ok(json) => {
                let _ = writeln!(io::stdout(), "{json}");
                ExitCode::SUCCESS
            }
            Err(e) => {
                let _ = writeln!(
                    io::stdout(),
                    "{}",
                    serde_json::to_string(&ValidatorCliError {
                        error: format!("could not serialize ValidatorCliOutput: {e}")
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
                serde_json::to_string(&ValidatorCliError { error: message })
                    .unwrap_or_else(|_| "{\"error\":\"unknown error\"}".to_string())
            );
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hcl_input(source_file_id: &str, source_text: &str, edits: &str) -> String {
        format!(
            r#"{{"source_file_id": {source_file_id:?}, "language": "TERRAFORM", "source_text": {source_text:?}, "edits": {edits}}}"#
        )
    }

    const HCL_FIXTURE: &str = "resource \"aws_s3_bucket\" \"a\" {\n  acl = \"public-read\"\n}\n";

    #[test]
    fn a_clean_input_with_no_edits_passes() {
        let output = run(&hcl_input("s3.tf", HCL_FIXTURE, "[]")).expect("should succeed");
        assert_eq!(output.results.len(), 1);
        assert!(output.results[0].passed);
    }

    #[test]
    fn a_syntax_breaking_edit_fails() {
        let brace_pos = HCL_FIXTURE.rfind('}').unwrap();
        let edits = format!(
            r#"[{{"span": {{"start_byte": {brace_pos}, "end_byte": {end}, "start_line": 3, "end_line": 3}}, "replacement": ""}}]"#,
            end = brace_pos + 1
        );
        let output = run(&hcl_input("broken.tf", HCL_FIXTURE, &edits)).expect("should succeed");
        assert!(!output.results[0].passed);
        assert!(output.results[0].reason.is_some());
    }

    #[test]
    fn unsupported_language_is_a_clean_error_not_a_panic() {
        let input = r#"{"source_file_id": "x.bin", "language": "UNSUPPORTED", "source_text": "", "edits": []}"#;
        let result = run(input);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("UNSUPPORTED"));
    }

    #[test]
    fn malformed_json_input_is_a_clean_error_not_a_panic() {
        let result = run("not valid json");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .contains("invalid ValidatorCliInput JSON"));
    }

    #[test]
    fn no_network_imports_in_validator_cli_source() {
        use std::fs;
        use std::path::Path;

        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/bin/validator_cli.rs");
        let text = fs::read_to_string(&path).expect("readable source file");
        let production_code = text.split("#[cfg(test)]").next().unwrap_or(&text);
        let forbidden_net: String = ["std", "::", "net", "::"].concat();
        let forbidden_reqwest: String = ["req", "west", "::"].concat();
        assert!(!production_code.contains(&forbidden_net));
        assert!(!production_code.contains(&forbidden_reqwest));
    }
}
