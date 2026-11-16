//! `cairn-transform-patcher`: the transformation engine core for
//! `transform-core` (spec S16/R3-03: "pattern-driven transformation engine
//! and manifest" -- this unit is the first third, "the transformation engine
//! core (Rust patcher)").
//!
//! Takes a [`ParseOutput`] (722/723's parser crate) and the [`DetectionSet`]
//! 724's detector produced from it, and applies each rule's registered
//! rewrite deterministically, producing a [`ChangeSet`]: one [`ChangeEntry`]
//! per item in the `DetectionSet` -- every confirmed [`Detection`] *and*
//! every [`SkippedCandidate`] -- each carrying the detection/candidate it
//! came from, the resulting text edits if applied, and an explicit reason if
//! skipped or unsupported (ADR-015: "Record ... applied/skipped/unsupported
//! outcomes and reasons in the transformation manifest").
//!
//! ## Scope note: no mapping-registry call in this crate
//!
//! This is a Rust crate; R2-01's mapping resolver
//! (`cairn_modules.mappings.resolver.resolve_mapping`) is a Python module.
//! Per ADR-006's Rust/Python split, this crate cannot call it in-process --
//! 726 is the unit that wires a `TransformationPort` adapter to the real
//! resolver over a subprocess boundary.
//!
//! Neither fixed rule this unit's corpus exercises
//! (`tf-s3-bucket-inline-acl-deprecated`, `py-import-imp-deprecated`) needs a
//! service/resource equivalence judgement: both are direct syntactic
//! successor rewrites (a deprecated Terraform argument's documented
//! mechanical replacement; a deprecated Python stdlib import's documented
//! replacement module). Confirmed explicitly, not assumed: see
//! `rules::tf_s3_bucket_inline_acl_deprecated` and
//! `rules::py_import_imp_deprecated` below, neither of which reads from, nor
//! embeds, any hard-coded service/resource equivalence table (ADR-004). This
//! crate therefore defines **no** "needs external resolution" outcome --
//! inventing one with no rule to exercise it would be speculative
//! abstraction, not compliance. The first rule that *does* need a mapping
//! judgement is a gap this unit explicitly flags for 726/727 to close when
//! it is authored (see `~/solara/lz2026/s725-handover.md`).
//!
//! No network access of any kind: this crate only walks and rewrites an
//! in-memory AST. See `tests::no_network_imports_in_patcher_source`.

#![forbid(unsafe_code)]

use cairn_transform_contract::{AstNode, ParseOutput, Span};
use cairn_transform_detector::{rule_ids, Detection, DetectionSet, SkippedCandidate};
use serde::{Deserialize, Serialize};

/// Identifies this patcher implementation and its version, for the
/// transformation manifest (ADR-015), the same way `DETECTOR_VERSION`
/// identifies 724's detector.
pub const PATCHER_VERSION: &str = "cairn-transform-patcher/0.1.0";

/// A single, byte-precise text replacement: "replace the bytes in `span`
/// (against the *original* source text the `ParseOutput` was parsed from)
/// with `replacement`". This crate never reads or reconstructs the original
/// source text itself -- a `ParseOutput` does not carry it, deliberately
/// (see `cairn-transform-contract`) -- it only ever emits edits anchored to
/// spans the AST already gave it. A zero-width span (`start_byte ==
/// end_byte`) is a pure insertion at that byte offset, never a deletion.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextEdit {
    pub span: Span,
    pub replacement: String,
}

/// What happened to one item of a `DetectionSet` when the engine tried to
/// act on it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ChangeOutcome {
    /// A safe rewrite was computed and is carried in `ChangeEntry::edits`.
    Applied,
    /// The detector itself already declined this candidate
    /// (`SkippedCandidate`) -- the engine never re-applies it. "skipped:
    /// ambiguous" is a legitimate, expected outcome, not an engine failure.
    Skipped,
    /// The detector called this a confirmed `Detection`, but the engine
    /// could not compute a safe rewrite for it at patch time (for example,
    /// the value the rewrite would need is only known at a runtime the
    /// parse tree does not carry). "unsupported: no safe rewrite for this
    /// construct" is a legitimate, expected outcome, not a guess.
    Unsupported,
}

/// Which `DetectionSet` item a `ChangeEntry` traces back to. Carries the
/// whole originating struct (not just its `rule_id`/`span`) so a consumer --
/// 726's manifest, 728's diff artefact -- never has to go back to the
/// `DetectionSet` to recover the detector's own reasoning.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "origin")]
pub enum ChangeOrigin {
    #[serde(rename = "DETECTION")]
    Detection(Detection),
    #[serde(rename = "SKIPPED_CANDIDATE")]
    SkippedCandidate(SkippedCandidate),
}

/// One outcome of running the engine over one `DetectionSet` item.
///
/// Invariant (checked by `tests::applied_entries_always_carry_edits_and_no_reason`
/// and `tests::non_applied_entries_never_carry_edits`): `outcome ==
/// Applied` iff `edits` is non-empty and `reason` is `None`; otherwise
/// `edits` is empty and `reason` is `Some(..)`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangeEntry {
    pub origin: ChangeOrigin,
    pub outcome: ChangeOutcome,
    pub edits: Vec<TextEdit>,
    pub reason: Option<String>,
    pub patcher_version: String,
}

/// The output of running the engine over one `DetectionSet`. One
/// `ChangeEntry` per `Detection` plus one per `SkippedCandidate` in the
/// input set -- `entries.len() == detections.detections.len() +
/// detections.skipped.len()` always (`tests::entry_count_matches_detection_set`).
/// `entries` is a `Vec`, never a map, for the same determinism reason as
/// `DetectionSet`/`AstNode` (spec S16/R3-02): two runs over identical input
/// always serialize byte-identically.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangeSet {
    pub source_file_id: String,
    pub patcher_version: String,
    pub entries: Vec<ChangeEntry>,
}

/// Run the engine over `detections` (724's output for `parse_output`),
/// producing a `ChangeSet`. Never mutates anything `detections` did not
/// flag: it only ever reads `parse_output`'s AST to locate the exact node a
/// `Detection` already pointed at, and only ever passes `SkippedCandidate`s
/// through as `Skipped` -- it never re-evaluates or overturns the
/// detector's own skip decision.
pub fn patch(parse_output: &ParseOutput, detections: &DetectionSet) -> ChangeSet {
    let ast: Option<&AstNode> = match parse_output {
        ParseOutput::Parsed { ast, .. } => Some(ast),
        ParseOutput::Unsupported { .. } | ParseOutput::Error { .. } => None,
    };

    let mut entries: Vec<ChangeEntry> =
        Vec::with_capacity(detections.detections.len() + detections.skipped.len());

    for detection in &detections.detections {
        entries.push(apply_detection(ast, detection));
    }
    for skipped in &detections.skipped {
        // The detector already decided this candidate was unsafe to match;
        // the engine's only job here is to carry that decision forward
        // verbatim, never to re-litigate it.
        entries.push(ChangeEntry {
            origin: ChangeOrigin::SkippedCandidate(skipped.clone()),
            outcome: ChangeOutcome::Skipped,
            edits: Vec::new(),
            reason: Some(skipped.reason.clone()),
            patcher_version: PATCHER_VERSION.to_string(),
        });
    }

    ChangeSet {
        source_file_id: detections.source_file_id.clone(),
        patcher_version: PATCHER_VERSION.to_string(),
        entries,
    }
}

fn unsupported(detection: &Detection, reason: impl Into<String>) -> ChangeEntry {
    ChangeEntry {
        origin: ChangeOrigin::Detection(detection.clone()),
        outcome: ChangeOutcome::Unsupported,
        edits: Vec::new(),
        reason: Some(reason.into()),
        patcher_version: PATCHER_VERSION.to_string(),
    }
}

fn applied(detection: &Detection, edits: Vec<TextEdit>) -> ChangeEntry {
    ChangeEntry {
        origin: ChangeOrigin::Detection(detection.clone()),
        outcome: ChangeOutcome::Applied,
        edits,
        reason: None,
        patcher_version: PATCHER_VERSION.to_string(),
    }
}

fn apply_detection(ast: Option<&AstNode>, detection: &Detection) -> ChangeEntry {
    let Some(ast) = ast else {
        // Can only happen if a caller hands this engine a Detection whose
        // ParseOutput carried no AST at all -- the detector itself never
        // produces a Detection without a Parsed input, but the engine does
        // not assume that invariant holds; it says so explicitly rather
        // than guessing.
        return unsupported(
            detection,
            "unsupported: no parse tree available for this detection's source file",
        );
    };

    match detection.rule_id.as_str() {
        rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED => {
            rules::tf_s3_bucket_inline_acl_deprecated(ast, detection)
        }
        rule_ids::PY_IMPORT_IMP_DEPRECATED => rules::py_import_imp_deprecated(ast, detection),
        rule_ids::TF_DYNAMODB_TABLE_CROSS_PROVIDER_EQUIVALENCE => {
            rules::tf_dynamodb_table_cross_provider_equivalence(detection)
        }
        other => unsupported(
            detection,
            format!("unsupported: no registered rewrite rule for '{other}'"),
        ),
    }
}

mod rules {
    use super::{applied, unsupported, ChangeEntry, Detection, TextEdit};
    use cairn_transform_contract::{AstNode, Span};

    /// Rewrite for `tf-s3-bucket-inline-acl-deprecated`: a direct syntactic
    /// successor rewrite, not a service/resource equivalence judgement --
    /// the deprecated inline `acl` argument's documented, provider-level
    /// replacement is the separate `aws_s3_bucket_acl` resource, the same
    /// AWS resource type family, not a cross-provider or cross-service
    /// substitution a mapping-registry lookup would resolve. No mapping
    /// table, hard-coded or otherwise, is consulted here (ADR-004).
    ///
    /// Produces two edits: delete the inline `acl` attribute (exactly the
    /// span the detector matched -- never more, never less), and insert a
    /// new `aws_s3_bucket_acl` resource immediately after the enclosing
    /// resource block's closing brace. The insertion is a zero-width edit
    /// at the block's own end span, so it can never collide with or
    /// overwrite any other content in the file, whatever that content is --
    /// the engine does not need to see it to insert safely after it.
    ///
    /// Deliberately refuses (`Unsupported`) when the literal's text
    /// contains an unresolved `${...}` template interpolation: the parser
    /// keeps the interpolation's source text verbatim inside the string
    /// literal (see `cairn-transform-parser`'s HCL lexer) rather than
    /// evaluating it, so the *actual* value this rewrite would need to copy
    /// into the new resource is only known at `terraform apply` time -- a
    /// runtime the parse tree genuinely does not carry. The detector's own
    /// "is this a plain string literal" check cannot see this (a templated
    /// string is still syntactically one `StringLit` token); this is the
    /// engine's own, additional safety gate on the text it actually emits.
    /// See `tests::acl_value_with_runtime_interpolation_is_unsupported`
    /// (this unit's required deliberate-break case).
    pub(super) fn tf_s3_bucket_inline_acl_deprecated(
        ast: &AstNode,
        detection: &Detection,
    ) -> ChangeEntry {
        let Some((resource_name, literal_text, block_span)) = find_acl_match(ast, detection.span)
        else {
            return unsupported(
                detection,
                "unsupported: could not relocate the detected 'acl' attribute in the parse tree",
            );
        };

        if literal_text.contains("${") {
            return unsupported(
                detection,
                "unsupported: acl value contains a runtime string interpolation ('${...}'); \
                 its resolved value is only known at terraform apply time, which this parse \
                 tree does not carry, so there is no safe value to copy into the replacement \
                 resource",
            );
        }

        let delete_inline_acl = TextEdit {
            span: detection.span,
            replacement: String::new(),
        };
        let insertion_point = Span {
            start_byte: block_span.end_byte,
            end_byte: block_span.end_byte,
            start_line: block_span.end_line,
            end_line: block_span.end_line,
        };
        let insert_acl_resource = TextEdit {
            span: insertion_point,
            replacement: format!(
                "\n\nresource \"aws_s3_bucket_acl\" \"{resource_name}\" {{\n  \
                 bucket = aws_s3_bucket.{resource_name}.id\n  acl    = {literal_text}\n}}\n"
            ),
        };

        applied(detection, vec![delete_inline_acl, insert_acl_resource])
    }

    /// Locates the `aws_s3_bucket` resource block whose body contains an
    /// `acl` attribute at exactly `target_span` (the span 724's detector
    /// matched), returning the resource's name label, the literal value's
    /// raw text (quotes included, exactly as the parser kept it), and the
    /// enclosing resource block's own span. Pure AST-shape navigation --
    /// the same shape 724's detector itself walks to find a candidate in
    /// the first place, re-walked here to relocate it, not a service/
    /// resource equivalence table.
    fn find_acl_match(ast: &AstNode, target_span: Span) -> Option<(String, String, Span)> {
        for node in &ast.children {
            if node.kind != "Block" || node.text != "resource" {
                continue;
            }
            let Some(type_label) = node.children.first() else {
                continue;
            };
            if type_label.kind != "Label" || type_label.text != "aws_s3_bucket" {
                continue;
            }
            let Some(name_label) = node.children.get(1) else {
                continue;
            };
            let Some(body) = node.children.last() else {
                continue;
            };
            if body.kind != "Body" {
                continue;
            }
            for child in &body.children {
                if child.kind == "Attribute" && child.text == "acl" && child.span == target_span {
                    let literal = child
                        .children
                        .first()
                        .map(|v| v.text.clone())
                        .unwrap_or_default();
                    return Some((name_label.text.clone(), literal, node.span));
                }
            }
        }
        None
    }

    /// Rewrite for `py-import-imp-deprecated`: a direct syntactic successor
    /// rewrite -- rename the deprecated stdlib `imp` module to its
    /// documented replacement, `importlib`. No equivalence judgement is
    /// needed (it is the same language's own stdlib, not a cross-provider
    /// or cross-service substitution), so no mapping-registry call is made
    /// here either.
    ///
    /// When the detected `ImportAlias` carries an `as <alias>` clause, the
    /// detector's matched span covers the whole "imp as alias" construct
    /// (`cairn-transform-parser`'s `ImportAlias` span includes the alias),
    /// so the replacement text re-attaches the alias (`importlib as
    /// <alias>`) rather than overwriting it -- never dropping a name the
    /// rest of the file may still reference.
    pub(super) fn py_import_imp_deprecated(ast: &AstNode, detection: &Detection) -> ChangeEntry {
        let Some(alias_node) = find_import_alias(ast, detection.span) else {
            return unsupported(
                detection,
                "unsupported: could not relocate the detected 'imp' import alias in the parse tree",
            );
        };

        let replacement = match alias_node.children.first() {
            Some(alias) if alias.kind == "Alias" => format!("importlib as {}", alias.text),
            _ => "importlib".to_string(),
        };

        applied(
            detection,
            vec![TextEdit {
                span: detection.span,
                replacement,
            }],
        )
    }

    fn find_import_alias(node: &AstNode, target_span: Span) -> Option<&AstNode> {
        if node.kind == "ImportAlias" && node.span == target_span {
            return Some(node);
        }
        node.children
            .iter()
            .find_map(|child| find_import_alias(child, target_span))
    }

    /// Rewrite (refusal) for `tf-dynamodb-table-cross-provider-equivalence`
    /// (780/R4-01). Unlike every other rule in this crate, this one has
    /// *no* safe rewrite this crate can compute at all, by design: the
    /// correct remediation for an `aws_dynamodb_table` resource is a
    /// cross-provider service-equivalence judgement (which target-provider
    /// service is the real counterpart, under what caveats, or whether no
    /// counterpart is published at all), and that judgement can only come
    /// from 700/R2-01's mapping-registry resolver
    /// (`cairn_modules.mappings.resolver.resolve_mapping`) -- a Python
    /// module this Rust crate cannot call in-process (ADR-006's Rust/
    /// Python split; see this crate's module-level "Scope note" doc
    /// comment). Always returns `ChangeOutcome::Unsupported` with no
    /// edits, for every `Detection` of this rule id, unconditionally --
    /// never a guessed target resource, never a silently-upgraded
    /// "equivalent" value. The actual resolver lookup, and the honest
    /// APPROXIMATE/UNAVAILABLE-never-rendered-as-EXACT rendering R-MAP-01
    /// requires, happens one layer up, in
    /// `cairn_modules.transformation.engine.build_manifest`, the only
    /// place in this pipeline allowed to call the resolver.
    pub(super) fn tf_dynamodb_table_cross_provider_equivalence(
        detection: &Detection,
    ) -> ChangeEntry {
        unsupported(
            detection,
            "unsupported: resolving aws_dynamodb_table's cross-provider service \
             equivalence requires a mapping-registry lookup (700's resolver), which \
             this Rust engine cannot perform in-process (ADR-006); the manifest-building \
             layer resolves this separately and renders it honestly per R-MAP-01 (an \
             APPROXIMATE or UNAVAILABLE mapping is never rendered as EXACT)",
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cairn_transform_contract::{ParseInput, SourceLanguage};
    use cairn_transform_detector::detect;
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

    fn only_edit(entry: &ChangeEntry) -> &TextEdit {
        assert_eq!(entry.edits.len(), 1, "expected exactly one edit: {entry:?}");
        &entry.edits[0]
    }

    // -- Golden corpus: Terraform/HCL (724's fixtures) --------------------

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

    const MULTIPLE_S3_BUCKETS_ONE_DEPRECATED: &str = r#"
resource "aws_s3_bucket" "clean" {
  bucket = "clean-bucket"
}

resource "aws_s3_bucket" "dirty" {
  bucket = "dirty-bucket"
  acl    = "private"
}
"#;

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
    fn s3_bucket_with_inline_literal_acl_is_applied() {
        let parsed = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);

        assert_eq!(changes.source_file_id, "fixture.tf");
        assert_eq!(changes.patcher_version, PATCHER_VERSION);
        assert_eq!(changes.entries.len(), 1);

        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Applied);
        assert!(entry.reason.is_none());
        assert_eq!(entry.edits.len(), 2);

        let delete = &entry.edits[0];
        assert_eq!(delete.replacement, "");
        assert_eq!(delete.span, detections.detections[0].span);

        let insert = &entry.edits[1];
        assert_eq!(insert.span.start_byte, insert.span.end_byte);
        assert!(insert
            .replacement
            .contains("resource \"aws_s3_bucket_acl\" \"artifacts\""));
        assert!(insert
            .replacement
            .contains("bucket = aws_s3_bucket.artifacts.id"));
        assert!(insert.replacement.contains("acl    = \"public-read\""));

        match &entry.origin {
            ChangeOrigin::Detection(d) => {
                assert_eq!(d.rule_id, rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED)
            }
            other => panic!("expected a Detection origin, got {other:?}"),
        }
    }

    #[test]
    fn s3_bucket_without_acl_produces_empty_change_set() {
        let parsed = parse_hcl(&hcl_input(S3_BUCKET_WITHOUT_ACL));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert!(changes.entries.is_empty());
        assert_eq!(changes.source_file_id, "fixture.tf");
    }

    #[test]
    fn multiple_resources_only_the_matching_one_is_applied() {
        let parsed = parse_hcl(&hcl_input(MULTIPLE_S3_BUCKETS_ONE_DEPRECATED));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Applied);
        let insert = &entry.edits[1];
        assert!(insert
            .replacement
            .contains("resource \"aws_s3_bucket_acl\" \"dirty\""));
        assert!(insert.replacement.contains("acl    = \"private\""));
    }

    // -- Golden corpus: cross-provider mapping-dependent rule (780/R4-01) --

    const DYNAMODB_TABLE: &str = r#"
resource "aws_dynamodb_table" "sessions" {
  name         = "cairn-demo-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }
}
"#;

    #[test]
    fn dynamodb_table_resource_is_always_unsupported_never_guessed() {
        // This crate has no mapping-registry call available to it
        // (ADR-006) -- it must always refuse this rewrite, never invent a
        // target resource. The actual resolver lookup happens one layer
        // up, in Python; this engine's job is only to decline honestly.
        let parsed = parse_hcl(&hcl_input(DYNAMODB_TABLE));
        let detections = detect(&parsed);
        assert_eq!(detections.detections.len(), 1);
        assert!(detections.skipped.is_empty());

        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Unsupported);
        assert!(entry.edits.is_empty());
        let reason = entry
            .reason
            .as_deref()
            .expect("unsupported entries carry a reason");
        assert!(reason.contains("mapping-registry"));
        assert!(reason.contains("R-MAP-01"));
        // Must never fabricate a target-provider service name -- that
        // judgement belongs to the resolver, not this crate.
        assert!(!reason.to_lowercase().contains("bigtable"));
        assert!(!reason.to_lowercase().contains("gcp"));
    }

    #[test]
    fn acl_inside_dynamic_block_is_skipped_never_applied() {
        // 724's deliberate-break case: the detector already declined this
        // candidate. The engine must carry that decision forward as
        // `Skipped`, never silently apply it (brief: "724's deliberate-break
        // case must still come out skipped/unsupported here, not silently
        // applied").
        let parsed = parse_hcl(&hcl_input(ACL_INSIDE_DYNAMIC_BLOCK));
        let detections = detect(&parsed);
        assert!(detections.detections.is_empty());
        assert_eq!(detections.skipped.len(), 1);

        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Skipped);
        assert!(entry.edits.is_empty());
        assert!(entry.reason.as_deref().unwrap().contains("dynamic block"));
        match &entry.origin {
            ChangeOrigin::SkippedCandidate(c) => {
                assert_eq!(c.rule_id, rule_ids::TF_S3_BUCKET_INLINE_ACL_DEPRECATED)
            }
            other => panic!("expected a SkippedCandidate origin, got {other:?}"),
        }
    }

    // -- Required deliberate-break case for THIS unit's engine -----------
    //
    // Unlike 724's dynamic-block case (already a `SkippedCandidate` the
    // detector itself declines), this fixture *is* a confirmed `Detection`
    // -- it is syntactically a plain string literal, which is all the
    // detector checks. The engine must still refuse to apply it, because
    // the literal's actual value is only resolved at `terraform apply`
    // time, which the parse tree never carries.

    const ACL_WITH_RUNTIME_INTERPOLATION: &str = r#"
resource "aws_s3_bucket" "interpolated" {
  bucket = "demo-bucket"
  acl    = "${var.environment}-public-read"
}
"#;

    #[test]
    fn acl_value_with_runtime_interpolation_is_unsupported() {
        let parsed = parse_hcl(&hcl_input(ACL_WITH_RUNTIME_INTERPOLATION));
        let detections = detect(&parsed);
        // The detector's own check ("is this a plain StringLit") cannot see
        // the interpolation -- it is still syntactically one string token --
        // so this reaches the engine as a confirmed Detection, not a skip.
        assert_eq!(detections.detections.len(), 1);
        assert!(detections.skipped.is_empty());

        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Unsupported);
        assert!(entry.edits.is_empty());
        let reason = entry
            .reason
            .as_deref()
            .expect("unsupported entries carry a reason");
        assert!(reason.contains("runtime"));
        assert!(reason.contains("interpolation"));
        assert!(
            !reason.to_lowercase().contains("public-read"),
            "must never guess or carry forward the unresolved value: {reason}"
        );
    }

    // -- Golden corpus: Python (724's fixtures) ---------------------------

    const IMPORT_IMP_BARE: &str = "import imp\n";
    const IMPORT_IMP_ALIASED: &str = "import imp as compat\n";
    const IMPORT_UNRELATED: &str = "import importlib\n";
    const IMPORT_IMP_AMONG_OTHERS: &str = "import os, imp, sys\n";

    #[test]
    fn bare_import_imp_is_applied() {
        let parsed = parse_python(&python_input(IMPORT_IMP_BARE));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Applied);
        let edit = only_edit(entry);
        assert_eq!(edit.replacement, "importlib");
        assert_eq!(edit.span, detections.detections[0].span);
    }

    #[test]
    fn aliased_import_imp_preserves_the_alias() {
        let parsed = parse_python(&python_input(IMPORT_IMP_ALIASED));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let edit = only_edit(&changes.entries[0]);
        assert_eq!(edit.replacement, "importlib as compat");
    }

    #[test]
    fn unrelated_import_produces_empty_change_set() {
        let parsed = parse_python(&python_input(IMPORT_UNRELATED));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert!(changes.entries.is_empty());
    }

    #[test]
    fn import_imp_among_several_is_applied() {
        let parsed = parse_python(&python_input(IMPORT_IMP_AMONG_OTHERS));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let edit = only_edit(&changes.entries[0]);
        assert_eq!(edit.replacement, "importlib");
    }

    #[test]
    fn relative_import_of_local_imp_module_is_skipped_never_applied() {
        let parsed = parse_python(&python_input("from . import imp\n"));
        let detections = detect(&parsed);
        assert!(detections.detections.is_empty());
        assert_eq!(detections.skipped.len(), 1);

        let changes = patch(&parsed, &detections);
        assert_eq!(changes.entries.len(), 1);
        let entry = &changes.entries[0];
        assert_eq!(entry.outcome, ChangeOutcome::Skipped);
        assert!(entry.edits.is_empty());
        assert!(entry.reason.as_deref().unwrap().contains("relative import"));
    }

    #[test]
    fn dotted_submodule_named_imp_produces_empty_change_set() {
        let parsed = parse_python(&python_input("import pkg.imp as helper\n"));
        let detections = detect(&parsed);
        assert!(detections.detections.is_empty());
        assert!(detections.skipped.is_empty());
        let changes = patch(&parsed, &detections);
        assert!(changes.entries.is_empty());
    }

    // -- Unsupported / Error ParseOutput ----------------------------------

    #[test]
    fn unsupported_parse_output_produces_empty_change_set() {
        let parsed = parse_python(&python_input("if True:\n    pass\n"));
        assert!(matches!(parsed, ParseOutput::Unsupported { .. }));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert!(changes.entries.is_empty());
    }

    #[test]
    fn error_parse_output_produces_empty_change_set() {
        let parsed = parse_hcl(&hcl_input("resource \"aws_s3_bucket\" \"broken\" {\n"));
        assert!(matches!(parsed, ParseOutput::Error { .. }));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert!(changes.entries.is_empty());
    }

    // -- Invariant: Applied <=> edits non-empty and reason is None --------

    #[test]
    fn applied_entries_always_carry_edits_and_no_reason() {
        let parsed = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        for entry in &changes.entries {
            if entry.outcome == ChangeOutcome::Applied {
                assert!(!entry.edits.is_empty());
                assert!(entry.reason.is_none());
            }
        }
    }

    #[test]
    fn non_applied_entries_never_carry_edits() {
        let parsed = parse_hcl(&hcl_input(ACL_INSIDE_DYNAMIC_BLOCK));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        for entry in &changes.entries {
            if entry.outcome != ChangeOutcome::Applied {
                assert!(entry.edits.is_empty());
                assert!(entry.reason.is_some());
            }
        }
    }

    #[test]
    fn entry_count_matches_detection_set() {
        let parsed = parse_hcl(&hcl_input(MULTIPLE_S3_BUCKETS_ONE_DEPRECATED));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        assert_eq!(
            changes.entries.len(),
            detections.detections.len() + detections.skipped.len()
        );
    }

    // -- Determinism -------------------------------------------------------

    #[test]
    fn patching_is_deterministic_across_repeated_runs() {
        let parsed = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let detections = detect(&parsed);
        let first = patch(&parsed, &detections);
        let second = patch(&parsed, &detections);
        assert_eq!(
            serde_json::to_string(&first).unwrap(),
            serde_json::to_string(&second).unwrap()
        );

        let py_parsed = parse_python(&python_input(IMPORT_IMP_BARE));
        let py_detections = detect(&py_parsed);
        let py_first = patch(&py_parsed, &py_detections);
        let py_second = patch(&py_parsed, &py_detections);
        assert_eq!(
            serde_json::to_string(&py_first).unwrap(),
            serde_json::to_string(&py_second).unwrap()
        );
    }

    #[test]
    fn change_set_round_trips_through_json() {
        let parsed = parse_hcl(&hcl_input(S3_BUCKET_WITH_INLINE_ACL));
        let detections = detect(&parsed);
        let changes = patch(&parsed, &detections);
        let json = serde_json::to_string(&changes).unwrap();
        let back: ChangeSet = serde_json::from_str(&json).unwrap();
        assert_eq!(changes, back);
    }

    #[test]
    fn change_outcome_serializes_as_screaming_snake_case() {
        assert_eq!(
            serde_json::to_string(&ChangeOutcome::Applied).unwrap(),
            "\"APPLIED\""
        );
        assert_eq!(
            serde_json::to_string(&ChangeOutcome::Skipped).unwrap(),
            "\"SKIPPED\""
        );
        assert_eq!(
            serde_json::to_string(&ChangeOutcome::Unsupported).unwrap(),
            "\"UNSUPPORTED\""
        );
    }

    // -- No network access --------------------------------------------------

    #[test]
    fn no_network_imports_in_patcher_source() {
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
