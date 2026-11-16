//! `cairn-transform-parser`: language parsers for `transform-core`, built on
//! the shared [`cairn_transform_contract`] I/O contract.
//!
//! R3 scope (ADR-015): Terraform/HCL (this unit, `hcl`) and Python (723).
//! Java and .NET are out of scope until a new ADR -- this crate has no module
//! for either.
//!
//! No network access of any kind: this crate parses in-memory source text
//! only. See `tests::no_network_imports_in_parser_source` for the
//! construction-proof check.

#![forbid(unsafe_code)]

pub mod hcl;

pub use hcl::{parse_hcl, PARSER_VERSION};

#[cfg(test)]
mod tests {
    use super::*;
    use cairn_transform_contract::{ParseInput, ParseOutput, SourceLanguage};
    use std::fs;
    use std::path::Path;

    fn input(source_file_id: &str, source_text: &str) -> ParseInput {
        ParseInput {
            source_file_id: source_file_id.to_string(),
            language: SourceLanguage::Terraform,
            source_text: source_text.to_string(),
        }
    }

    // -- Golden corpus: synthetic, pilot-scope Terraform/HCL fixtures --------
    // Covers resource blocks, variables, modules, and locals at minimum
    // (spec S16/R3-02), plus provider/output/data as naturally-supported
    // instances of the same generic block grammar.

    const RESOURCE_BLOCK: &str = r#"
resource "aws_instance" "web" {
  ami           = "ami-0abcdef1234567890"
  instance_type = "t3.micro"
  count         = 2

  tags = {
    Name        = "web-server"
    Environment = "staging"
  }
}
"#;

    const VARIABLE_BLOCK: &str = r#"
variable "region" {
  type    = string
  default = "us-east-1"
}

variable "allowed_cidrs" {
  type    = list(string)
  default = ["10.0.0.0/16", "10.1.0.0/16"]
}
"#;

    const MODULE_BLOCK: &str = r#"
module "vpc" {
  source  = "./modules/vpc"
  version = "1.2.0"

  cidr_block = "10.0.0.0/16"
  enabled    = true
}
"#;

    const LOCALS_BLOCK: &str = r#"
locals {
  full_name = "${var.project}-${var.environment}"
  is_prod   = false
  nothing   = null
}
"#;

    const PROVIDER_AND_OUTPUT: &str = r#"
provider "aws" {
  region = var.region
}

data "aws_ami" "latest" {
  most_recent = true
}

output "instance_id" {
  value = aws_instance.web.id
}
"#;

    const HEREDOC_BLOCK: &str = r#"
resource "local_file" "script" {
  content = <<-EOT
    #!/bin/bash
    echo "hello"
  EOT
  filename = "run.sh"
}
"#;

    const MIXED_FIXTURE: &str = r#"
variable "name" {
  default = "demo"
}

module "network" {
  source = "./modules/network"
  cidrs  = ["10.0.0.0/16", "10.1.0.0/16"]
}

locals {
  tags = {
    Name  = var.name
    Owner = "platform"
  }
}

resource "aws_instance" "app" {
  ami   = "ami-123"
  count = 1
  tags  = local.tags
}
"#;

    fn golden_fixtures() -> Vec<(&'static str, &'static str)> {
        vec![
            ("resource_block.tf", RESOURCE_BLOCK),
            ("variable_block.tf", VARIABLE_BLOCK),
            ("module_block.tf", MODULE_BLOCK),
            ("locals_block.tf", LOCALS_BLOCK),
            ("provider_and_output.tf", PROVIDER_AND_OUTPUT),
            ("heredoc_block.tf", HEREDOC_BLOCK),
            ("mixed_fixture.tf", MIXED_FIXTURE),
        ]
    }

    #[test]
    fn golden_corpus_parses_successfully() {
        for (name, src) in golden_fixtures() {
            let output = parse_hcl(&input(name, src));
            match &output {
                ParseOutput::Parsed { ast, .. } => {
                    assert_eq!(ast.kind, "Body");
                    assert!(
                        !ast.children.is_empty(),
                        "{name}: expected at least one top-level block/attribute"
                    );
                }
                other => panic!("{name}: expected ParseOutput::Parsed, got {other:?}"),
            }
        }
    }

    #[test]
    fn golden_corpus_matches_fixture_files_on_disk() {
        // Keeps the corpus honest: the fixtures embedded above are mirrored as
        // real files under tests/fixtures/hcl so the corpus can grow as plain
        // .tf files, not just string constants, in a later unit.
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hcl");
        let mut found = 0;
        for entry in fs::read_dir(&dir).expect("fixtures/hcl must exist") {
            let entry = entry.expect("readable fixture dir entry");
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("tf") {
                continue;
            }
            let src = fs::read_to_string(&path).expect("readable fixture file");
            let id = path.file_name().unwrap().to_string_lossy().to_string();
            let output = parse_hcl(&input(&id, &src));
            assert!(
                output.is_parsed(),
                "{id}: expected to parse, got {output:?}"
            );
            found += 1;
        }
        assert!(
            found >= 4,
            "expected at least 4 on-disk golden fixtures, found {found}"
        );
    }

    #[test]
    fn resource_block_structure_is_as_expected() {
        let output = parse_hcl(&input("resource.tf", RESOURCE_BLOCK));
        let ast = match output {
            ParseOutput::Parsed { ast, .. } => ast,
            other => panic!("expected Parsed, got {other:?}"),
        };
        let block = &ast.children[0];
        assert_eq!(block.kind, "Block");
        assert_eq!(block.text, "resource");
        // labels: "aws_instance", "web", then the Body
        assert_eq!(block.children.len(), 3);
        assert_eq!(block.children[0].kind, "Label");
        assert_eq!(block.children[0].text, "aws_instance");
        assert_eq!(block.children[1].text, "web");
        let body = &block.children[2];
        assert_eq!(body.kind, "Body");
        let ami_attr = body
            .children
            .iter()
            .find(|c| c.kind == "Attribute" && c.text == "ami")
            .expect("ami attribute present");
        assert_eq!(ami_attr.children[0].kind, "StringLit");
    }

    // -- Determinism: same input parsed twice -> byte-identical serialization --

    #[test]
    fn parsing_is_deterministic_across_repeated_runs() {
        for (name, src) in golden_fixtures() {
            let first = parse_hcl(&input(name, src));
            let second = parse_hcl(&input(name, src));
            let first_json = serde_json::to_string(&first).unwrap();
            let second_json = serde_json::to_string(&second).unwrap();
            assert_eq!(first_json, second_json, "{name}: non-deterministic output");
        }
    }

    // -- Deliberate break (required, step 4 of the brief) --------------------

    #[test]
    fn unterminated_block_returns_explicit_error_not_a_partial_ast() {
        let malformed = r#"
resource "aws_instance" "web" {
  ami = "ami-123"
"#; // missing closing '}'
        let output = parse_hcl(&input("unterminated_block.tf", malformed));
        match output {
            ParseOutput::Error { error, .. } => {
                assert!(
                    error.reason.to_lowercase().contains("unterminated"),
                    "reason should name the unterminated-block problem: {}",
                    error.reason
                );
                assert!(error.span.is_some());
            }
            other => panic!(
                "expected ParseOutput::Error for an unterminated block, got {other:?} \
                 (a partial AST presented as complete, or a panic, would both be failures here)"
            ),
        }
    }

    #[test]
    fn heredoc_with_no_closing_marker_returns_explicit_error() {
        let malformed = r#"
resource "local_file" "script" {
  content = <<-EOT
    #!/bin/bash
    echo "no closing marker below"
  filename = "run.sh"
}
"#; // heredoc never closed with a line containing exactly "EOT"
        let output = parse_hcl(&input("unterminated_heredoc.tf", malformed));
        match output {
            ParseOutput::Error { error, .. } => {
                assert!(
                    error.reason.to_lowercase().contains("heredoc"),
                    "reason should name the heredoc problem: {}",
                    error.reason
                );
            }
            other => {
                panic!("expected ParseOutput::Error for an unterminated heredoc, got {other:?}")
            }
        }
    }

    #[test]
    fn deliberately_broken_inputs_never_panic() {
        let inputs = [
            "resource \"x\" \"y\" {",
            "variable \"v\" { default = <<-EOF\nno marker",
            "locals { a = [1, 2,",
            "locals { a = {",
            "locals { a = (1",
            "resource \"x\" \"y\"",
            "= missing name",
            "locals { a = \"unterminated string",
            "/* unterminated comment",
            "<<nomark",
        ];
        for src in inputs {
            let output = parse_hcl(&input("broken.tf", src));
            assert!(
                matches!(output, ParseOutput::Error { .. }),
                "expected an explicit error (never a panic, never an Unsupported \
                 masking a syntax problem) for input {src:?}, got {output:?}"
            );
        }
    }

    // -- Construction-proof: no network access anywhere in this crate --------

    #[test]
    fn no_network_imports_in_parser_source() {
        let src_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        for entry in fs::read_dir(&src_dir).expect("readable src dir") {
            let path = entry.expect("readable dir entry").path();
            if path.extension().and_then(|e| e.to_str()) != Some("rs") {
                continue;
            }
            let text = fs::read_to_string(&path).expect("readable source file");
            // Scan only the production code, not this very test module (which
            // necessarily mentions the forbidden substrings in its own
            // assertions below).
            let production_code = match text.find("#[cfg(test)]") {
                Some(idx) => &text[..idx],
                None => &text[..],
            };
            let forbidden_net: String = ["std", "::", "net", "::"].concat();
            let forbidden_reqwest: String = ["req", "west", "::"].concat();
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
