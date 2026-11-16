//! `cairn-transform-detector`: the detector core for `transform-core`.
//!
//! Takes a [`ParseOutput`] (from `cairn-transform-parser`, either language --
//! HCL from 722 or Python from 723) and runs a fixed, versioned set of
//! detection rules over its AST, producing a [`DetectionSet`]: what
//! pattern-driven transform opportunities exist in this pilot's scope.
//!
//! This is the first point `detector_version` becomes a concrete, recorded
//! string (ADR-015: "Record detector and pattern versions ... in the
//! transformation manifest") -- 726's manifest (R3-03b) carries this value
//! through unchanged.
//!
//! A file with zero matches is a legitimate, explicit [`DetectionSet::empty`],
//! never an error: `ParseOutput::Unsupported`/`ParseOutput::Error` inputs, and
//! `Parsed` inputs where no rule fires, both produce an empty set, not a
//! failure.
//!
//! Every rule is deliberately conservative: a construct that only
//! superficially resembles a rule's trigger shape, but whose value or
//! context the detector cannot safely reason about (for example, a
//! dynamically-generated block, or a relative import of a same-named local
//! module), never produces a match. It either produces nothing at all, or an
//! explicit, low-confidence entry in [`DetectionSet::skipped`] naming why --
//! never a false positive that a later unit (725's transform engine) would
//! act on unsafely.
//!
//! No network access of any kind: this crate only walks an in-memory AST.
//! See `tests::no_network_imports_in_detector_source`.

#![forbid(unsafe_code)]

use cairn_transform_contract::{ParseOutput, Span};
use serde::{Deserialize, Serialize};

/// Identifies this detector implementation and its version, for the
/// transformation manifest (ADR-015). Bump this whenever a rule's matching
/// logic changes in a way that could change which detections fire -- the
/// manifest uses this string, not the rule-set source, to say "which
/// detector produced this".
pub const DETECTOR_VERSION: &str = "cairn-detector/0.1.0";

/// How certain the detector is that a match is a true, safely-actionable
/// positive. `Low` is reserved for entries the detector chose to surface
/// anyway rather than silently drop (see [`DetectionSet::skipped`] for the
/// more common "found something but declined to call it a match" case).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Confidence {
    High,
    Medium,
    Low,
}

/// One confirmed detection: a place in the source where a fixed rule's
/// trigger shape matched *and* the detector could safely reason about the
/// matched value/context.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Detection {
    pub rule_id: String,
    pub source_file_id: String,
    pub span: Span,
    pub confidence: Confidence,
    pub detector_version: String,
    pub message: String,
}

/// A candidate the detector looked at, recognized as superficially matching
/// a rule's trigger shape, and explicitly declined to call a match -- with
/// the reason it was unsafe to apply. This is the audit trail ADR-015 asks
/// for ("skipped/unsupported outcomes and reasons"): a file can have zero
/// `detections` and a non-empty `skipped` list, and that is a legitimate,
/// fully-explained result, not a silent no-op.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SkippedCandidate {
    pub rule_id: String,
    pub source_file_id: String,
    pub span: Span,
    pub detector_version: String,
    pub reason: String,
}

/// The output of running the detector over one [`ParseOutput`]. Exactly one
/// `DetectionSet` per input; `detections` is a `Vec`, never a map, so two
/// runs over identical input always serialize byte-identically (the same
/// determinism requirement as `ParseOutput`/`AstNode`, spec S16/R3-02).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DetectionSet {
    pub source_file_id: String,
    pub detector_version: String,
    pub detections: Vec<Detection>,
    pub skipped: Vec<SkippedCandidate>,
}

impl DetectionSet {
    /// An explicit "ran the detector, found nothing" result -- the
    /// legitimate zero-match case the brief requires never be an error.
    pub fn empty(source_file_id: impl Into<String>) -> Self {
        DetectionSet {
            source_file_id: source_file_id.into(),
            detector_version: DETECTOR_VERSION.to_string(),
            detections: Vec::new(),
            skipped: Vec::new(),
        }
    }

    pub fn has_matches(&self) -> bool {
        !self.detections.is_empty()
    }
}

/// Fixed rule identifiers this unit ships. New rules get a new id and a new
/// row here; existing ids never change meaning (the manifest references them
/// by id, so silently redefining one would corrupt history).
pub mod rule_ids {
    pub const TF_S3_BUCKET_INLINE_ACL_DEPRECATED: &str = "tf-s3-bucket-inline-acl-deprecated";
    pub const PY_IMPORT_IMP_DEPRECATED: &str = "py-import-imp-deprecated";
}

/// Run every fixed rule applicable to `parse_output`'s language over its AST.
///
/// `ParseOutput::Unsupported`/`ParseOutput::Error` carry no AST, so there is
/// nothing to detect against -- both produce `DetectionSet::empty`, exactly
/// like a `Parsed` input where no rule fires. The parser's own
/// `parser_version` string is how a caller distinguishes "nothing to parse"
/// from "parsed cleanly but no detections"; this crate does not duplicate
/// that distinction.
pub fn detect(parse_output: &ParseOutput) -> DetectionSet {
    let source_file_id = parse_output.source_file_id().to_string();
    let ast = match parse_output {
        ParseOutput::Parsed { ast, .. } => ast,
        ParseOutput::Unsupported { .. } | ParseOutput::Error { .. } => {
            return DetectionSet::empty(source_file_id);
        }
    };

    let mut set = DetectionSet::empty(source_file_id.clone());

    if parse_output
        .parser_version()
        .starts_with("cairn-hcl-parser/")
    {
        rules::tf_s3_bucket_inline_acl_deprecated(ast, &source_file_id, &mut set);
    } else if parse_output
        .parser_version()
        .starts_with("cairn-python-parser/")
    {
        rules::py_import_imp_deprecated(ast, &source_file_id, &mut set);
    }
    // An unrecognized parser_version has no rules defined for it yet -- that
    // is also a legitimate empty `DetectionSet`, not an error: this crate's
    // rule set is scoped to the two parsers that exist today (ADR-015, R3
    // scope is Terraform/HCL and Python).

    set
}

mod rules {
    use super::{
        rule_ids, Confidence, Detection, DetectionSet, SkippedCandidate, DETECTOR_VERSION,
    };
    use cairn_transform_contract::AstNode;

    /// Rule: an `aws_s3_bucket` resource block with an inline `acl`
    /// attribute whose value is a plain string literal. The `acl` argument
    /// on `aws_s3_bucket` was deprecated by the AWS provider in favor of the
    /// separate `aws_s3_bucket_acl` resource; a literal value is the shape
    /// 725's transform engine can safely rewrite.
    ///
    /// Deliberately does **not** fire when the superficially identical
    /// `acl = ...` attribute sits inside a `dynamic` block: a `dynamic`
    /// block's body is a template evaluated once per `for_each` iteration,
    /// so the detector cannot know, from the AST alone, what value(s) the
    /// attribute actually takes at apply time (it is typically a traversal
    /// into the iterator variable, not a literal at all -- see the
    /// `acl_inside_dynamic_block_is_not_matched` test). That case is
    /// recorded as an explicit [`SkippedCandidate`], never a match.
    pub(super) fn tf_s3_bucket_inline_acl_deprecated(
        ast: &AstNode,
        source_file_id: &str,
        set: &mut DetectionSet,
    ) {
        // Resource blocks are always direct children of the file's root
        // `Body` -- walk one level to find each top-level `Block`.
        for node in &ast.children {
            if node.kind != "Block" || node.text != "resource" {
                continue;
            }
            let Some(resource_type) = node.children.first() else {
                continue;
            };
            if resource_type.kind != "Label" || resource_type.text != "aws_s3_bucket" {
                continue;
            }
            // Last child is always the block's `Body` (labels precede it).
            let Some(body) = node.children.last() else {
                continue;
            };
            if body.kind != "Body" {
                continue;
            }
            scan_s3_bucket_body(body, source_file_id, set);
        }
    }

    fn scan_s3_bucket_body(body: &AstNode, source_file_id: &str, set: &mut DetectionSet) {
        for child in &body.children {
            match (child.kind.as_str(), child.text.as_str()) {
                ("Attribute", "acl") => {
                    let is_literal_value = child
                        .children
                        .first()
                        .map(|v| v.kind == "StringLit")
                        .unwrap_or(false);
                    if is_literal_value {
                        set.detections.push(Detection {
                            rule_id: rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED.to_string(),
                            source_file_id: source_file_id.to_string(),
                            span: child.span,
                            confidence: Confidence::High,
                            detector_version: DETECTOR_VERSION.to_string(),
                            message: "inline 'acl' argument on aws_s3_bucket is deprecated; \
                                      the equivalent is a separate aws_s3_bucket_acl resource"
                                .to_string(),
                        });
                    } else {
                        set.skipped.push(SkippedCandidate {
                            rule_id: rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED.to_string(),
                            source_file_id: source_file_id.to_string(),
                            span: child.span,
                            detector_version: DETECTOR_VERSION.to_string(),
                            reason: "'acl' argument value is not a plain string literal; \
                                     cannot safely determine the value this rule would rewrite"
                                .to_string(),
                        });
                    }
                }
                ("Block", "dynamic") => {
                    // Deliberate-break case: an `acl`-named attribute may
                    // exist somewhere inside this dynamic block's template,
                    // but its value is produced per-iteration at apply time
                    // -- never reason into it as if it were a literal.
                    if dynamic_block_mentions_acl(child) {
                        set.skipped.push(SkippedCandidate {
                            rule_id: rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED.to_string(),
                            source_file_id: source_file_id.to_string(),
                            span: child.span,
                            detector_version: DETECTOR_VERSION.to_string(),
                            reason: "an 'acl'-shaped attribute appears inside a dynamic block; \
                                     its value is generated per for_each iteration and cannot \
                                     be safely determined from the AST alone"
                                .to_string(),
                        });
                    }
                }
                _ => {}
            }
        }
    }

    /// Looks (read-only, no rewriting) for any `Attribute` named `acl`
    /// anywhere inside a `dynamic` block's subtree, purely to decide whether
    /// this skip is worth recording -- never promoted to a `Detection`.
    fn dynamic_block_mentions_acl(dynamic_block: &AstNode) -> bool {
        if dynamic_block.kind == "Attribute" && dynamic_block.text == "acl" {
            return true;
        }
        dynamic_block
            .children
            .iter()
            .any(dynamic_block_mentions_acl)
    }

    /// Rule: `import imp` (the deprecated stdlib `imp` module; removed in
    /// Python 3.12, superseded by `importlib`). Only matches an exact,
    /// absolute, unqualified `import imp` (optionally aliased) -- never a
    /// dotted submodule that merely ends in `imp` (e.g. `import pkg.imp`,
    /// a project's own unrelated submodule), and never a relative import of
    /// a same-named local module (`from . import imp`), where "imp" does not
    /// refer to the stdlib module at all. Those are recorded, respectively,
    /// as no candidate at all and as an explicit [`SkippedCandidate`] -- see
    /// `relative_import_of_local_imp_module_is_not_matched` and
    /// `dotted_submodule_named_imp_is_not_matched`.
    pub(super) fn py_import_imp_deprecated(
        ast: &AstNode,
        source_file_id: &str,
        set: &mut DetectionSet,
    ) {
        walk_python(ast, source_file_id, set);
    }

    fn walk_python(node: &AstNode, source_file_id: &str, set: &mut DetectionSet) {
        if node.kind == "Import" {
            for alias in &node.children {
                if alias.kind == "ImportAlias" && alias.text == "imp" {
                    set.detections.push(Detection {
                        rule_id: rule_ids::PY_IMPORT_IMP_DEPRECATED.to_string(),
                        source_file_id: source_file_id.to_string(),
                        span: alias.span,
                        confidence: Confidence::High,
                        detector_version: DETECTOR_VERSION.to_string(),
                        message: "the 'imp' module is deprecated (removed in Python 3.12); \
                                  the equivalent is 'importlib'"
                            .to_string(),
                    });
                }
            }
        } else if node.kind == "ImportFrom" && node.text.starts_with('.') {
            // Deliberate-break case: a relative import whose imported name
            // happens to be "imp" is a local sibling module, not the stdlib
            // module this rule targets -- record why it was considered and
            // rejected, never match it.
            for alias in &node.children {
                if alias.kind == "ImportAlias" && alias.text == "imp" {
                    set.skipped.push(SkippedCandidate {
                        rule_id: rule_ids::PY_IMPORT_IMP_DEPRECATED.to_string(),
                        source_file_id: source_file_id.to_string(),
                        span: alias.span,
                        detector_version: DETECTOR_VERSION.to_string(),
                        reason:
                            "'imp' is imported via a relative import (from . import imp), \
                                 i.e. a local sibling module; this cannot be the deprecated \
                                 stdlib 'imp' module, which is only reachable by an absolute import"
                                .to_string(),
                    });
                }
            }
        }
        for child in &node.children {
            walk_python(child, source_file_id, set);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cairn_transform_contract::ParseInput;
    use cairn_transform_contract::SourceLanguage;
    use cairn_transform_parser::{parse_hcl, parse_python};

    fn hcl_input(source_text: &str) -> ParseInput {
        ParseInput {
            source_file_id: "fixture.tf".to_string(),
            language: SourceLanguage::Terraform,
            source_text: source_text.to_string(),
        }
    }

    fn python_input(source_text: &str) -> ParseInput {
        ParseInput {
            source_file_id: "fixture.py".to_string(),
            language: SourceLanguage::Python,
            source_text: source_text.to_string(),
        }
    }

    // -- Golden corpus: Terraform/HCL -----------------------------------

    const S3_BUCKET_WITH_INLINE_ACL: &str = r#"
resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-demo-artifacts"
  acl    = "public-read"

  tags = {
    Team = "platform"
  }
}
"#;

    const S3_BUCKET_WITHOUT_ACL: &str = r#"
resource "aws_s3_bucket" "artifacts" {
  bucket = "cairn-demo-artifacts"

  tags = {
    Team = "platform"
  }
}
"#;

    const UNRELATED_RESOURCE: &str = r#"
resource "aws_iam_role" "worker" {
  name                = "cairn-worker-role"
  assume_role_policy  = "{}"
}
"#;

    const MULTIPLE_S3_BUCKETS_ONE_DEPRECATED: &str = r#"
resource "aws_s3_bucket" "clean" {
  bucket = "clean-bucket"
}

resource "aws_s3_bucket" "dirty" {
  bucket = "dirty-bucket"
  acl    = "private"
}
"#;

    #[test]
    fn s3_bucket_with_inline_literal_acl_is_detected() {
        let output = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let set = detect(&output);
        assert_eq!(set.detections.len(), 1);
        let detection = &set.detections[0];
        assert_eq!(
            detection.rule_id,
            rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED
        );
        assert_eq!(detection.source_file_id, "fixture.tf");
        assert_eq!(detection.confidence, Confidence::High);
        assert_eq!(detection.detector_version, DETECTOR_VERSION);
        assert!(set.skipped.is_empty());
    }

    #[test]
    fn s3_bucket_without_acl_produces_empty_detection_set() {
        let output = parse_hcl(&hcl_input(S3_BUCKET_WITHOUT_ACL));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
        assert_eq!(set.source_file_id, "fixture.tf");
        assert_eq!(set.detector_version, DETECTOR_VERSION);
    }

    #[test]
    fn unrelated_resource_type_produces_empty_detection_set() {
        let output = parse_hcl(&hcl_input(UNRELATED_RESOURCE));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
    }

    #[test]
    fn multiple_resources_only_the_matching_one_is_detected() {
        let output = parse_hcl(&hcl_input(MULTIPLE_S3_BUCKETS_ONE_DEPRECATED));
        let set = detect(&output);
        assert_eq!(set.detections.len(), 1);
        assert_eq!(
            set.detections[0].rule_id,
            rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED
        );
    }

    // -- Deliberate-break case (Terraform): dynamic block ----------------
    // The "acl" shape appears, but inside a `dynamic` block templating a
    // nested block per `for_each` entry -- the value is not knowable from
    // the AST, so this must never be promoted to a match.

    const ACL_INSIDE_DYNAMIC_BLOCK: &str = r#"
resource "aws_s3_bucket" "templated" {
  bucket = "templated-bucket"

  dynamic "grant" {
    for_each = var.grants
    content {
      acl = each.value.acl
    }
  }
}
"#;

    #[test]
    fn acl_inside_dynamic_block_is_not_matched() {
        let output = parse_hcl(&hcl_input(ACL_INSIDE_DYNAMIC_BLOCK));
        let set = detect(&output);
        assert!(
            set.detections.is_empty(),
            "a dynamically-generated 'acl' attribute must never produce a match: {:?}",
            set.detections
        );
        assert_eq!(set.skipped.len(), 1);
        assert_eq!(
            set.skipped[0].rule_id,
            rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED
        );
        assert!(set.skipped[0].reason.contains("dynamic block"));
    }

    #[test]
    fn acl_set_from_a_traversal_outside_a_dynamic_block_is_skipped_not_matched() {
        // Same resource, no dynamic block, but the value still isn't a
        // literal (a plain traversal) -- also must not be promoted to a
        // match, via the other skip path (non-literal attribute value).
        const SRC: &str = r#"
resource "aws_s3_bucket" "computed" {
  bucket = "computed-bucket"
  acl    = local.computed_acl
}
"#;
        let output = parse_hcl(&hcl_input(SRC));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert_eq!(set.skipped.len(), 1);
        assert!(set.skipped[0].reason.contains("string literal"));
    }

    // -- Golden corpus: Python -------------------------------------------

    const IMPORT_IMP_BARE: &str = "import imp\n";
    const IMPORT_IMP_ALIASED: &str = "import imp as compat\n";
    const IMPORT_UNRELATED: &str = "import importlib\n";
    const IMPORT_IMP_AMONG_OTHERS: &str = "import os, imp, sys\n";

    #[test]
    fn bare_import_imp_is_detected() {
        let output = parse_python(&python_input(IMPORT_IMP_BARE));
        let set = detect(&output);
        assert_eq!(set.detections.len(), 1);
        assert_eq!(
            set.detections[0].rule_id,
            rule_ids::PY_IMPORT_IMP_DEPRECATED
        );
        assert_eq!(set.detections[0].source_file_id, "fixture.py");
        assert_eq!(set.detections[0].confidence, Confidence::High);
    }

    #[test]
    fn aliased_import_imp_is_still_detected() {
        let output = parse_python(&python_input(IMPORT_IMP_ALIASED));
        let set = detect(&output);
        assert_eq!(set.detections.len(), 1);
    }

    #[test]
    fn unrelated_import_produces_empty_detection_set() {
        let output = parse_python(&python_input(IMPORT_UNRELATED));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
    }

    #[test]
    fn import_imp_among_several_comma_separated_imports_is_detected() {
        let output = parse_python(&python_input(IMPORT_IMP_AMONG_OTHERS));
        let set = detect(&output);
        assert_eq!(set.detections.len(), 1);
    }

    // -- Deliberate-break cases (Python) ----------------------------------

    #[test]
    fn relative_import_of_local_imp_module_is_not_matched() {
        let output = parse_python(&python_input("from . import imp\n"));
        let set = detect(&output);
        assert!(
            set.detections.is_empty(),
            "a relative import of a local 'imp' module must never match the stdlib rule: {:?}",
            set.detections
        );
        assert_eq!(set.skipped.len(), 1);
        assert_eq!(set.skipped[0].rule_id, rule_ids::PY_IMPORT_IMP_DEPRECATED);
        assert!(set.skipped[0].reason.contains("relative import"));
    }

    #[test]
    fn dotted_submodule_named_imp_is_not_matched() {
        // `import pkg.imp` is a wholly different module (someone's own
        // "pkg.imp" submodule) -- a textual match on "imp" alone would be a
        // false positive. The rule's exact-equality check on the full
        // dotted name correctly produces no candidate at all here, not even
        // a skip (there is nothing resembling the stdlib module to flag).
        let output = parse_python(&python_input("import pkg.imp as helper\n"));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
    }

    // -- Unsupported / Error inputs produce an explicit empty set, not an
    // error -------------------------------------------------------------

    #[test]
    fn unsupported_parse_output_produces_empty_detection_set() {
        let output = parse_python(&python_input("if True:\n    pass\n"));
        assert!(matches!(output, ParseOutput::Unsupported { .. }));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
        assert_eq!(set.source_file_id, "fixture.py");
        assert_eq!(set.detector_version, DETECTOR_VERSION);
    }

    #[test]
    fn error_parse_output_produces_empty_detection_set() {
        let output = parse_hcl(&hcl_input("resource \"aws_s3_bucket\" \"broken\" {\n"));
        assert!(matches!(output, ParseOutput::Error { .. }));
        let set = detect(&output);
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
    }

    #[test]
    fn empty_constructor_is_explicitly_empty_not_a_default_match() {
        let set = DetectionSet::empty("nothing.tf");
        assert!(set.detections.is_empty());
        assert!(set.skipped.is_empty());
        assert!(!set.has_matches());
        assert_eq!(set.detector_version, DETECTOR_VERSION);
    }

    // -- Determinism -------------------------------------------------------

    #[test]
    fn detection_is_deterministic_across_repeated_runs() {
        let output = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let first = detect(&output);
        let second = detect(&output);
        assert_eq!(
            serde_json::to_string(&first).unwrap(),
            serde_json::to_string(&second).unwrap()
        );

        let py_output = parse_python(&python_input(IMPORT_IMP_BARE));
        let py_first = detect(&py_output);
        let py_second = detect(&py_output);
        assert_eq!(
            serde_json::to_string(&py_first).unwrap(),
            serde_json::to_string(&py_second).unwrap()
        );
    }

    #[test]
    fn detection_set_round_trips_through_json() {
        let output = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let set = detect(&output);
        let json = serde_json::to_string(&set).unwrap();
        let back: DetectionSet = serde_json::from_str(&json).unwrap();
        assert_eq!(set, back);
    }

    #[test]
    fn confidence_serializes_as_screaming_snake_case() {
        assert_eq!(
            serde_json::to_string(&Confidence::High).unwrap(),
            "\"HIGH\""
        );
        assert_eq!(serde_json::to_string(&Confidence::Low).unwrap(), "\"LOW\"");
    }

    // -- No network access --------------------------------------------------

    #[test]
    fn no_network_imports_in_detector_source() {
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
}
