//! `cairn-transform-contract`: the versioned, serializable parse I/O contract shared
//! by every `transform-core` Rust unit that touches source parsing --
//! `cairn-transform-parser` (this unit's HCL parser, 723's Python parser),
//! `cairn-transform-detector` (724), and the Python-side adapter (726).
//!
//! Deliberately small and stable. Anything language-specific (concrete AST node
//! kinds for HCL vs. Python, lexer/parser internals, detector heuristics) belongs
//! in `parser` / `detector`, not here -- this crate only fixes the shape that
//! crosses the boundary, so 723/724/726 can all build against it without waiting
//! on each other or coupling to one language's internals.
//!
//! Scope lock (ADR-015: "R3 scope is Terraform/HCL and Python source. Java and
//! .NET are out of scope until a new ADR"): [`SourceLanguage`] has exactly the
//! members that line permits, plus `Unsupported` for every other readable file
//! `SourceFile` (721, R3-01) can carry -- never dropped, never guessed at.

#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};

/// Mirrors `cairn_contracts.transformation.model.SourceLanguage` on the Python
/// side (packages/contracts/src/cairn_contracts/transformation/model.py, from
/// 721/R3-01). Kept in lockstep deliberately: this is the language axis every
/// later stage branches on.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SourceLanguage {
    Terraform,
    Python,
    Unsupported,
}

/// A byte/line range into the original source text. Lines are 1-indexed; bytes
/// are 0-indexed, half-open (`[start_byte, end_byte)`), matching the source
/// text's own UTF-8 byte offsets so a caller can slice back into it without
/// re-deriving offsets from line/column math.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Span {
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: u32,
    pub end_line: u32,
}

/// One node of the deterministic AST/IR. Intentionally generic at this layer --
/// a `kind` tag plus `text` plus ordered `children` is enough structure for the
/// contract to carry any language's tree without this crate knowing what a
/// "resource block" or a "Python function def" is. Children are an ordered
/// `Vec`, never a map, so two parses of identical input always serialize
/// byte-identically (determinism requirement, spec S16/R3-02).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstNode {
    pub kind: String,
    pub text: String,
    pub children: Vec<AstNode>,
    pub span: Span,
}

/// Why a parser could not honestly produce an AST. Never used to carry a
/// partial tree -- a `ParseError` means no tree is returned at all.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParseError {
    pub reason: String,
    pub span: Option<Span>,
}

/// Input to a parser: source text, its detected language, and an id tracing
/// back to the originating `SourceFile` (721/R3-01's
/// `cairn_contracts.transformation.model.SourceFile`). The parser does not
/// interpret `source_file_id` -- it is carried through untouched so downstream
/// stages (detector, manifest, evidence record) can attribute output back to
/// the file that produced it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParseInput {
    pub source_file_id: String,
    pub language: SourceLanguage,
    pub source_text: String,
}

/// Output of a parser. Exactly one of: a complete deterministic AST, an
/// explicit "I understood this file's language but not this construct"
/// unsupported result, or an explicit parse error -- never a best-effort,
/// partially-complete tree presented as whole. `parser_version` identifies
/// which parser implementation (and its version) produced this output, for
/// the transformation manifest (ADR-015: "Record detector and pattern
/// versions ... in the transformation manifest").
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status")]
pub enum ParseOutput {
    #[serde(rename = "PARSED")]
    Parsed {
        parser_version: String,
        source_file_id: String,
        ast: AstNode,
    },
    /// The input is readable and its language is in scope, but this specific
    /// construct is not one the parser can honestly represent (e.g. an HCL
    /// feature outside the pilot's covered grammar). Not an error: the file
    /// was read fine, the parser is just declining to guess.
    #[serde(rename = "UNSUPPORTED")]
    Unsupported {
        parser_version: String,
        source_file_id: String,
        reason: String,
    },
    #[serde(rename = "ERROR")]
    Error {
        parser_version: String,
        source_file_id: String,
        error: ParseError,
    },
}

impl ParseOutput {
    pub fn source_file_id(&self) -> &str {
        match self {
            ParseOutput::Parsed { source_file_id, .. }
            | ParseOutput::Unsupported { source_file_id, .. }
            | ParseOutput::Error { source_file_id, .. } => source_file_id,
        }
    }

    pub fn parser_version(&self) -> &str {
        match self {
            ParseOutput::Parsed { parser_version, .. }
            | ParseOutput::Unsupported { parser_version, .. }
            | ParseOutput::Error { parser_version, .. } => parser_version,
        }
    }

    pub fn is_parsed(&self) -> bool {
        matches!(self, ParseOutput::Parsed { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_ast() -> AstNode {
        AstNode {
            kind: "Body".to_string(),
            text: String::new(),
            children: vec![AstNode {
                kind: "Attribute".to_string(),
                text: "name".to_string(),
                children: vec![AstNode {
                    kind: "StringLit".to_string(),
                    text: "\"value\"".to_string(),
                    children: vec![],
                    span: Span {
                        start_byte: 7,
                        end_byte: 14,
                        start_line: 1,
                        end_line: 1,
                    },
                }],
                span: Span {
                    start_byte: 0,
                    end_byte: 14,
                    start_line: 1,
                    end_line: 1,
                },
            }],
            span: Span {
                start_byte: 0,
                end_byte: 14,
                start_line: 1,
                end_line: 1,
            },
        }
    }

    #[test]
    fn parse_output_round_trips_through_json() {
        let output = ParseOutput::Parsed {
            parser_version: "cairn-hcl-parser/0.1.0".to_string(),
            source_file_id: "main.tf".to_string(),
            ast: sample_ast(),
        };
        let json = serde_json::to_string(&output).unwrap();
        let back: ParseOutput = serde_json::from_str(&json).unwrap();
        assert_eq!(output, back);
    }

    #[test]
    fn parse_output_serialization_is_deterministic() {
        let output = ParseOutput::Parsed {
            parser_version: "cairn-hcl-parser/0.1.0".to_string(),
            source_file_id: "main.tf".to_string(),
            ast: sample_ast(),
        };
        let first = serde_json::to_string(&output).unwrap();
        let second = serde_json::to_string(&output.clone()).unwrap();
        assert_eq!(first, second);
    }

    #[test]
    fn unsupported_and_error_variants_carry_a_reason_not_a_tree() {
        let unsupported = ParseOutput::Unsupported {
            parser_version: "cairn-hcl-parser/0.1.0".to_string(),
            source_file_id: "weird.tf".to_string(),
            reason: "construct outside pilot scope".to_string(),
        };
        assert!(!unsupported.is_parsed());

        let error = ParseOutput::Error {
            parser_version: "cairn-hcl-parser/0.1.0".to_string(),
            source_file_id: "broken.tf".to_string(),
            error: ParseError {
                reason: "unterminated block".to_string(),
                span: None,
            },
        };
        assert!(!error.is_parsed());
        assert_eq!(error.source_file_id(), "broken.tf");
    }

    #[test]
    fn no_network_imports_in_contract_source() {
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
                "{}: must not import reqwest",
                path.display()
            );
        }
    }

    #[test]
    fn source_language_serializes_as_screaming_snake_case() {
        assert_eq!(
            serde_json::to_string(&SourceLanguage::Terraform).unwrap(),
            "\"TERRAFORM\""
        );
        assert_eq!(
            serde_json::to_string(&SourceLanguage::Python).unwrap(),
            "\"PYTHON\""
        );
        assert_eq!(
            serde_json::to_string(&SourceLanguage::Unsupported).unwrap(),
            "\"UNSUPPORTED\""
        );
    }
}
