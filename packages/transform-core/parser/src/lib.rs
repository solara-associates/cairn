//! `cairn-transform-parser`: language parsers for `transform-core`, built on
//! the shared [`cairn_transform_contract`] I/O contract.
//!
//! R3 scope (ADR-015): Terraform/HCL (`hcl`, 722) and Python (`python`, this
//! unit, 723). Java and .NET are out of scope until a new ADR -- this crate
//! has no module for either.
//!
//! No network access of any kind: this crate parses in-memory source text
//! only. See `tests::no_network_imports_in_parser_source` for the
//! construction-proof check.

#![forbid(unsafe_code)]

pub mod hcl;
pub mod python;

pub use hcl::{parse_hcl, PARSER_VERSION as HCL_PARSER_VERSION};
pub use python::{parse_python, PARSER_VERSION as PYTHON_PARSER_VERSION};

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

#[cfg(test)]
mod python_tests {
    use super::*;
    use cairn_transform_contract::{ParseInput, ParseOutput, SourceLanguage};
    use std::fs;
    use std::path::Path;

    fn input(source_file_id: &str, source_text: &str) -> ParseInput {
        ParseInput {
            source_file_id: source_file_id.to_string(),
            language: SourceLanguage::Python,
            source_text: source_text.to_string(),
        }
    }

    // -- Golden corpus: synthetic, pilot-scope Python fixtures ---------------
    // Covers module-level imports, function/class defs, assignments, and
    // calls (the pilot subset this unit's brief named).

    const IMPORTS: &str = r#"
import os
import os.path as ospath
from collections import OrderedDict, namedtuple
from . import sibling
from ..pkg import thing as renamed
from mypkg.sub import (
    first,
    second as alias_second,
)
from mypkg import *
"#;

    const FUNCTION_DEF: &str = r#"
def greet(name: str, greeting: str = "hello", *args, **kwargs) -> str:
    message = combine(greeting, name)
    return message
"#;

    const CLASS_DEF: &str = r#"
class Widget(Base, metaclass=WidgetMeta):
    """A widget."""

    kind: str = "generic"

    def __init__(self, name):
        self.name = name
        self.tags = ["default"]

    def describe(self):
        return self.name
"#;

    const ASSIGNMENTS_AND_CALLS: &str = r#"
x = 1
y = "two"
z = [1, 2, 3]
cfg = {"a": 1, "b": 2}
point = (1, 2)
result = compute(x, y, keyword=z, *args, **cfg)
obj.attr.nested = result
print(result)
"#;

    const DECORATED_FUNCTION: &str = r#"
@staticmethod
@app.route("/health")
def health_check():
    pass
"#;

    const MIXED_FIXTURE: &str = r#"
import json
from typing import Optional

class Config:
    name: str = "demo"

    def __init__(self, path):
        self.path = path
        self.data = {}

    def load(self):
        with_default = json.loads(self.path)
        self.data = with_default
        return self.data

def main():
    cfg = Config("settings.json")
    cfg.load()
    return cfg
"#;

    fn golden_fixtures() -> Vec<(&'static str, &'static str)> {
        vec![
            ("imports.py", IMPORTS),
            ("function_def.py", FUNCTION_DEF),
            ("class_def.py", CLASS_DEF),
            ("assignments_and_calls.py", ASSIGNMENTS_AND_CALLS),
            ("decorated_function.py", DECORATED_FUNCTION),
            ("mixed_fixture.py", MIXED_FIXTURE),
        ]
    }

    #[test]
    fn golden_corpus_parses_successfully() {
        for (name, src) in golden_fixtures() {
            let output = parse_python(&input(name, src));
            match &output {
                ParseOutput::Parsed { ast, .. } => {
                    assert_eq!(ast.kind, "Module");
                    assert!(
                        !ast.children.is_empty(),
                        "{name}: expected at least one top-level statement"
                    );
                }
                other => panic!("{name}: expected ParseOutput::Parsed, got {other:?}"),
            }
        }
    }

    #[test]
    fn golden_corpus_matches_fixture_files_on_disk() {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/python");
        let mut found = 0;
        for entry in fs::read_dir(&dir).expect("fixtures/python must exist") {
            let entry = entry.expect("readable fixture dir entry");
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("py") {
                continue;
            }
            let src = fs::read_to_string(&path).expect("readable fixture file");
            let id = path.file_name().unwrap().to_string_lossy().to_string();
            let output = parse_python(&input(&id, &src));
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
    fn import_statement_structure_is_as_expected() {
        let output = parse_python(&input("imports.py", IMPORTS));
        let ast = match output {
            ParseOutput::Parsed { ast, .. } => ast,
            other => panic!("expected Parsed, got {other:?}"),
        };
        let plain_import = &ast.children[0];
        assert_eq!(plain_import.kind, "Import");
        assert_eq!(plain_import.children[0].kind, "ImportAlias");
        assert_eq!(plain_import.children[0].text, "os");

        let aliased_import = &ast.children[1];
        assert_eq!(aliased_import.children[0].text, "os.path");
        assert_eq!(aliased_import.children[0].children[0].kind, "Alias");
        assert_eq!(aliased_import.children[0].children[0].text, "ospath");

        let from_import = &ast.children[2];
        assert_eq!(from_import.kind, "ImportFrom");
        assert_eq!(from_import.text, "collections");
        assert_eq!(from_import.children.len(), 2);
        assert_eq!(from_import.children[0].text, "OrderedDict");

        let relative = &ast.children[3];
        assert_eq!(relative.text, ".");

        let relative_up = &ast.children[4];
        assert_eq!(relative_up.text, "..pkg");
        assert_eq!(relative_up.children[0].children[0].text, "renamed");

        let star_import = &ast.children[6];
        assert_eq!(star_import.children[0].text, "*");
    }

    #[test]
    fn function_def_structure_is_as_expected() {
        let output = parse_python(&input("function_def.py", FUNCTION_DEF));
        let ast = match output {
            ParseOutput::Parsed { ast, .. } => ast,
            other => panic!("expected Parsed, got {other:?}"),
        };
        let func = &ast.children[0];
        assert_eq!(func.kind, "FunctionDef");
        assert_eq!(func.text, "greet");
        let params = func
            .children
            .iter()
            .find(|c| c.kind == "Params")
            .expect("Params present");
        assert_eq!(params.children[0].kind, "Param");
        assert_eq!(params.children[0].text, "name");
        assert_eq!(params.children[0].children[0].kind, "Annotation");
        assert_eq!(params.children[1].text, "greeting");
        assert!(params.children[1]
            .children
            .iter()
            .any(|c| c.kind == "Default"));
        assert_eq!(params.children[2].kind, "VarArgs");
        assert_eq!(params.children[2].text, "args");
        assert_eq!(params.children[3].kind, "KwArgs");
        assert_eq!(params.children[3].text, "kwargs");
        assert!(func.children.iter().any(|c| c.kind == "ReturnAnnotation"));
        let body = func.children.iter().find(|c| c.kind == "Body").unwrap();
        assert_eq!(body.children[0].kind, "Assign");
        assert_eq!(body.children[1].kind, "Return");
    }

    #[test]
    fn class_def_and_nested_methods_are_as_expected() {
        let output = parse_python(&input("class_def.py", CLASS_DEF));
        let ast = match output {
            ParseOutput::Parsed { ast, .. } => ast,
            other => panic!("expected Parsed, got {other:?}"),
        };
        let class = &ast.children[0];
        assert_eq!(class.kind, "ClassDef");
        assert_eq!(class.text, "Widget");
        let bases = class.children.iter().find(|c| c.kind == "Bases").unwrap();
        assert_eq!(bases.children[0].kind, "Traversal");
        assert_eq!(bases.children[0].text, "Base");
        assert_eq!(bases.children[1].kind, "KeywordArg");
        assert_eq!(bases.children[1].text, "metaclass");
        let body = class.children.iter().find(|c| c.kind == "Body").unwrap();
        assert_eq!(body.children[0].kind, "ExprStmt"); // docstring
        assert_eq!(body.children[1].kind, "AnnAssign");
        let methods: Vec<_> = body
            .children
            .iter()
            .filter(|c| c.kind == "FunctionDef")
            .collect();
        assert_eq!(methods.len(), 2);
        assert_eq!(methods[0].text, "__init__");
        assert_eq!(methods[1].text, "describe");
    }

    #[test]
    fn assignments_and_calls_structure_is_as_expected() {
        let output = parse_python(&input("assignments_and_calls.py", ASSIGNMENTS_AND_CALLS));
        let ast = match output {
            ParseOutput::Parsed { ast, .. } => ast,
            other => panic!("expected Parsed, got {other:?}"),
        };
        assert_eq!(ast.children[0].kind, "Assign");
        assert_eq!(ast.children[0].text, "x");
        assert_eq!(ast.children[2].children[0].kind, "List");
        assert_eq!(ast.children[3].children[0].kind, "Dict");
        assert_eq!(ast.children[4].children[0].kind, "Tuple");
        let call_assign = &ast.children[5];
        assert_eq!(call_assign.kind, "Assign");
        let call = &call_assign.children[0];
        assert_eq!(call.kind, "Call");
        assert_eq!(call.text, "compute");
        assert!(call.children.iter().any(|c| c.kind == "KeywordArg"));
        assert!(call.children.iter().any(|c| c.kind == "Starred"));
        assert!(call.children.iter().any(|c| c.kind == "DoubleStarred"));
        let attr_assign = &ast.children[6];
        assert_eq!(attr_assign.kind, "Assign");
        assert_eq!(attr_assign.text, "obj.attr.nested");
        let bare_call = &ast.children[7];
        assert_eq!(bare_call.kind, "ExprStmt");
        assert_eq!(bare_call.children[0].kind, "Call");
    }

    #[test]
    fn decorators_are_captured_in_declaration_order() {
        let output = parse_python(&input("decorated_function.py", DECORATED_FUNCTION));
        let ast = match output {
            ParseOutput::Parsed { ast, .. } => ast,
            other => panic!("expected Parsed, got {other:?}"),
        };
        let func = &ast.children[0];
        assert_eq!(func.kind, "FunctionDef");
        let decorators = func
            .children
            .iter()
            .find(|c| c.kind == "Decorators")
            .expect("Decorators present");
        assert_eq!(decorators.children.len(), 2);
        assert_eq!(decorators.children[0].children[0].text, "staticmethod");
        assert_eq!(decorators.children[1].children[0].text, "app.route");
    }

    // -- Determinism: same input parsed twice -> byte-identical serialization --

    #[test]
    fn parsing_is_deterministic_across_repeated_runs() {
        for (name, src) in golden_fixtures() {
            let first = parse_python(&input(name, src));
            let second = parse_python(&input(name, src));
            let first_json = serde_json::to_string(&first).unwrap();
            let second_json = serde_json::to_string(&second).unwrap();
            assert_eq!(first_json, second_json, "{name}: non-deterministic output");
        }
    }

    // -- Deliberate break (required, step 3 of the brief) --------------------
    // Each case feeds a construct outside the declared pilot subset and
    // asserts an explicit Unsupported/ParseError -- never a silently wrong
    // partial parse.

    #[test]
    fn fstring_is_reported_as_unsupported_not_a_silent_partial_parse() {
        let src = "name = \"world\"\ngreeting = f\"hello {name}\"\n";
        let output = parse_python(&input("fstring.py", src));
        match output {
            ParseOutput::Unsupported { reason, .. } => {
                assert!(
                    reason.to_lowercase().contains("f-string"),
                    "reason should name the f-string problem: {reason}"
                );
            }
            other => panic!(
                "expected ParseOutput::Unsupported for an f-string, got {other:?} \
                 (a partial/guessed parse would be a failure here)"
            ),
        }
    }

    #[test]
    fn walrus_operator_is_rejected_not_silently_parsed() {
        // The walrus operator (`:=`) is outside the pilot's expression
        // grammar anywhere it can appear; it is never treated as plain `:`.
        let src = "if (n := 10) > 5:\n    pass\n";
        let output = parse_python(&input("walrus.py", src));
        // `if` is itself an excluded statement keyword, so this already
        // reports Unsupported before the walrus token is even reached --
        // still an explicit, honest result, never a partial parse.
        assert!(
            matches!(
                output,
                ParseOutput::Unsupported { .. } | ParseOutput::Error { .. }
            ),
            "expected an explicit Unsupported/Error, got {output:?}"
        );

        // A walrus used somewhere our grammar does reach (inside a plain
        // expression statement) surfaces as an explicit Error: `:=` is never
        // read as plain `:` and never silently dropped.
        let src2 = "value = (n := compute())\n";
        let output2 = parse_python(&input("walrus2.py", src2));
        match output2 {
            ParseOutput::Error { error, .. } => {
                assert!(
                    error.reason.contains(":=") || error.reason.to_lowercase().contains("walrus"),
                    "reason should name the walrus token: {}",
                    error.reason
                );
            }
            other => panic!(
                "expected ParseOutput::Error for a walrus operator, got {other:?} \
                 (never a silent partial parse)"
            ),
        }
    }

    #[test]
    fn match_statement_surfaces_as_an_explicit_error_not_a_silent_parse() {
        // `match`/`case` are soft keywords in real Python; this pilot does
        // not special-case them. A `match` statement is not representable by
        // this grammar and must surface as an explicit error, never as if it
        // had been understood.
        let src = "match command:\n    case \"start\":\n        pass\n";
        let output = parse_python(&input("match_stmt.py", src));
        assert!(
            matches!(
                output,
                ParseOutput::Error { .. } | ParseOutput::Unsupported { .. }
            ),
            "expected an explicit Error/Unsupported for a match statement, got {output:?}"
        );
    }

    #[test]
    fn excluded_statement_keywords_are_reported_as_unsupported() {
        let cases = [
            "if True:\n    pass\n",
            "for x in y:\n    pass\n",
            "while True:\n    pass\n",
            "try:\n    pass\nexcept Exception:\n    pass\n",
            "with open('f') as fh:\n    pass\n",
            "async def f():\n    pass\n",
            "raise ValueError('x')\n",
            "assert True\n",
            "del x\n",
            "global x\n",
        ];
        for src in cases {
            let output = parse_python(&input("excluded.py", src));
            assert!(
                matches!(output, ParseOutput::Unsupported { .. }),
                "expected Unsupported for {src:?}, got {output:?}"
            );
        }
    }

    #[test]
    fn deliberately_broken_inputs_never_panic() {
        let inputs = [
            "def f(:\n    pass\n",
            "class C(:\n    pass\n",
            "x = [1, 2,\n",
            "x = {1: 2,\n",
            "x = (1,\n",
            "x = \"unterminated\n",
            "def f():\npass\n", // missing indent
            "import \n",
            "from import x\n",
            "x = \n",
            "    x = 1\n",                    // unexpected indent at module start
            "def f():\n    x = 1\n  y = 2\n", // inconsistent dedent
        ];
        for src in inputs {
            let output = parse_python(&input("broken.py", src));
            assert!(
                matches!(
                    output,
                    ParseOutput::Error { .. } | ParseOutput::Unsupported { .. }
                ),
                "expected an explicit Error/Unsupported (never a panic, never a silently wrong \
                 partial parse) for input {src:?}, got {output:?}"
            );
        }
    }

    #[test]
    fn tuple_unpacking_assignment_target_is_rejected() {
        // `a, b = 1, 2` is valid Python but outside the pilot's assignment
        // grammar (no tuple-unpacking targets); it must not be silently
        // accepted as if `a` alone were assigned.
        let output = parse_python(&input("unpack.py", "a, b = 1, 2\n"));
        assert!(
            matches!(output, ParseOutput::Error { .. }),
            "expected an explicit Error, got {output:?}"
        );
    }

    #[test]
    fn subscript_assignment_target_is_rejected() {
        // Subscript expressions aren't in the pilot's expression grammar at
        // all (documented out of scope), so `d[0] = 1` surfaces as an
        // explicit Error (unexpected `[` after the `d` name) rather than a
        // silently accepted assignment to `d`.
        let output = parse_python(&input("subscript_assign.py", "d[0] = 1\n"));
        assert!(
            matches!(output, ParseOutput::Error { .. }),
            "expected an explicit Error, got {output:?}"
        );
    }

    #[test]
    fn tabs_in_indentation_are_rejected() {
        let output = parse_python(&input("tabs.py", "def f():\n\tpass\n"));
        assert!(
            matches!(output, ParseOutput::Error { .. }),
            "expected an explicit Error for tab indentation, got {output:?}"
        );
    }

    // -- Construction-proof: no network access anywhere in this crate --------
    // (covered by `tests::no_network_imports_in_parser_source`, which scans
    // every .rs file under src/, python.rs included.)
}
