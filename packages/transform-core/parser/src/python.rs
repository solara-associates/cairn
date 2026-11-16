//! A from-scratch Python parser for the R3-02 pilot subset, built against
//! public CPython grammar/tokenizer documentation (the CPython `ast` grammar:
//! <https://docs.python.org/3/library/ast.html>, and the tokenizer's
//! indentation rules: <https://docs.python.org/3/reference/lexical_analysis.html#indentation>),
//! not any third-party Python-parsing crate and not any reference-repository
//! source (ADR-017).
//!
//! # Pilot subset (what this parser covers)
//!
//! Scoped to what 724 (detector) and 725 (engine) actually need to act on --
//! not a full-fidelity Python parser:
//!
//! - Module-level and nested **imports**: `import a.b.c`, `import a.b as c`,
//!   `from a.b import c, d as e`, `from a.b import (c, d as e)` (parenthesized,
//!   possibly multi-line), `from . import x` / `from .. import x` (relative),
//!   `from a import *`.
//! - **Function definitions**: `def name(params) -> ReturnAnnotation: body`,
//!   with simple decorators (`@name` / `@name(args)`), positional/keyword
//!   parameters with optional `: annotation` and `= default`, a bare `*`
//!   keyword-only marker, `*args`, `**kwargs`.
//! - **Class definitions**: `class Name(Base1, Base2, keyword=expr): body`,
//!   with the same simple-decorator support.
//! - **Assignments**: `target = expr` and annotated `target: Annotation`
//!   / `target: Annotation = expr`, where `target` is a plain name or a
//!   dotted attribute access (`a.b.c`).
//! - **Calls** and other bare expression statements (including a leading
//!   string-literal "docstring" statement).
//! - `return expr` / bare `return`, `pass`.
//! - A bounded expression grammar: string/number/`True`/`False`/`None`
//!   literals, dotted-name traversals, calls (positional, keyword,
//!   `*args`-spread, `**kwargs`-spread arguments), list literals `[...]`,
//!   tuple literals `(...)`/parenthesized grouping, dict literals `{...}`
//!   (including `**expr` unpacking entries).
//!
//! # Deliberately out of scope (named explicitly so 724/725 don't assume
//! coverage that isn't there)
//!
//! Recognized-but-excluded **statement** keywords are reported as
//! [`ParseOutput::Unsupported`] (the input is valid Python; this pilot
//! declines to represent it), not [`ParseOutput::Error`]: `if`/`elif`/`else`,
//! `for`/`while`, `try`/`except`/`finally`, `with`, `lambda`, `yield`,
//! `async`/`await`, `global`/`nonlocal`, `del`, `raise`, `assert`.
//! `match`/`case` are not special-cased (they are soft keywords in real
//! Python) -- a `match` statement falls through the ordinary expression-
//! statement path and surfaces as an explicit `ParseOutput::Error` (unexpected
//! token after the `match` subject expression), never a silently wrong parse.
//!
//! Also out of scope, every one of them surfacing as an explicit error or
//! unsupported result rather than a guess:
//!
//! - **f-strings** (any `f"..."` / `F'''...'''` literal) -- `Unsupported`.
//! - The **walrus operator** (`:=`) -- surfaces as `Error` (it is not a valid
//!   expression-start token anywhere our grammar expects one).
//! - Binary and unary operators, comparisons, boolean `and`/`or`/`not`, the
//!   conditional (`... if ... else ...`) expression, comprehensions, `lambda`
//!   expressions, slicing (`a[1:2]`), subscript targets/expressions,
//!   f-strings' embedded expressions -- none of these appear in the golden
//!   corpus; using one is a parser *bug* to fix in a later unit if the pilot
//!   corpus needs it, not a silent partial parse today.
//! - Multiple-target assignment (`a = b = c`), tuple/list-unpacking targets
//!   (`a, b = ...`), starred targets, augmented assignment (`x += 1`),
//!   subscript assignment (`d[k] = v`).
//! - Semicolon-separated multiple statements on one physical line.
//! - Decorators that are themselves complex expressions beyond a dotted name
//!   or a call on one.
//! - Tabs used for indentation (a lexer limitation of this pilot, not a
//!   judgment about the Python program's validity) -- `Error`.
//!
//! Every failure path returns an explicit `Error` or `Unsupported` result with
//! a reason; nothing here panics on malformed input and nothing here returns
//! a partial tree dressed up as a complete one.

use cairn_transform_contract::{AstNode, ParseError, ParseInput, ParseOutput, Span};

/// Identifies this parser implementation and its version for the
/// transformation manifest (ADR-015).
pub const PARSER_VERSION: &str = "cairn-python-parser/0.1.0";

/// Statement keywords that are recognized but intentionally outside the pilot
/// subset. Reported as `Unsupported`, not `Error`: the input is valid Python,
/// this pilot just declines to represent it.
const EXCLUDED_STATEMENT_KEYWORDS: &[&str] = &[
    "if", "elif", "else", "for", "while", "try", "except", "finally", "with", "lambda", "yield",
    "async", "await", "global", "nonlocal", "del", "raise", "assert",
];

/// Parse one Python source file into a [`ParseOutput`]. Never panics: any
/// input, however malformed, produces `ParseOutput::Error` or
/// `ParseOutput::Unsupported` with a reason rather than an unwind.
pub fn parse_python(input: &ParseInput) -> ParseOutput {
    let source_file_id = input.source_file_id.clone();
    match parse_source(&input.source_text) {
        Ok(ast) => ParseOutput::Parsed {
            parser_version: PARSER_VERSION.to_string(),
            source_file_id,
            ast,
        },
        Err(PyError::Unsupported(reason, span)) => ParseOutput::Unsupported {
            parser_version: PARSER_VERSION.to_string(),
            source_file_id,
            reason: format_unsupported(&reason, span),
        },
        Err(PyError::Syntax(err)) => ParseOutput::Error {
            parser_version: PARSER_VERSION.to_string(),
            source_file_id,
            error: err,
        },
    }
}

fn format_unsupported(reason: &str, span: Option<Span>) -> String {
    match span {
        Some(s) => format!("{reason} (near line {})", s.start_line),
        None => reason.to_string(),
    }
}

fn parse_source(text: &str) -> Result<AstNode, PyError> {
    let tokens = Lexer::new(text).tokenize()?;
    let mut parser = Parser::new(&tokens);
    parser.parse_module()
}

/// Either a genuine syntax problem (malformed/un-parseable input) or an
/// explicit "this construct is real Python but outside the pilot subset"
/// result. Kept distinct internally so callers can tell the two apart; both
/// collapse to an explicit, non-partial [`ParseOutput`] variant at the top.
#[derive(Debug)]
enum PyError {
    Syntax(ParseError),
    Unsupported(String, Option<Span>),
}

impl From<ParseError> for PyError {
    fn from(e: ParseError) -> Self {
        PyError::Syntax(e)
    }
}

fn unsupported(reason: impl Into<String>, span: Span) -> PyError {
    PyError::Unsupported(reason.into(), Some(span))
}

// ---------------------------------------------------------------------------
// Lexer
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
enum TokenKind {
    Name(String),
    Str { text: String, is_fstring: bool }, // raw source slice, quotes/prefix included verbatim
    Num(String),
    True,
    False,
    NoneTok,
    LParen,
    RParen,
    LBrack,
    RBrack,
    LBrace,
    RBrace,
    Comma,
    Dot,
    Colon,
    ColonEqual, // walrus `:=` -- lexed explicitly so it never masquerades as plain `:`
    Equals,
    Arrow, // `->`
    Star,
    DoubleStar,
    At,
    Indent,
    Dedent,
    Newline,
    Eof,
}

#[derive(Debug, Clone)]
struct Token {
    kind: TokenKind,
    span: Span,
}

struct Lexer<'a> {
    chars: Vec<char>,
    byte_offsets: Vec<usize>,
    lines: Vec<u32>,
    pos: usize,
    _src: &'a str,
}

const STRING_PREFIX_CHARS: &str = "rRbBuUfF";

impl<'a> Lexer<'a> {
    fn new(src: &'a str) -> Self {
        let chars: Vec<char> = src.chars().collect();
        let mut byte_offsets = Vec::with_capacity(chars.len() + 1);
        let mut lines = Vec::with_capacity(chars.len() + 1);
        let mut byte = 0usize;
        let mut line = 1u32;
        for &c in &chars {
            byte_offsets.push(byte);
            lines.push(line);
            byte += c.len_utf8();
            if c == '\n' {
                line += 1;
            }
        }
        byte_offsets.push(byte);
        lines.push(line);
        Lexer {
            chars,
            byte_offsets,
            lines,
            pos: 0,
            _src: src,
        }
    }

    fn peek_char(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn peek_char_at(&self, offset: usize) -> Option<char> {
        self.chars.get(self.pos + offset).copied()
    }

    fn span_from(&self, start: usize) -> Span {
        let end = self.pos.min(self.chars.len());
        let start = start.min(self.chars.len());
        let end_line_idx = if end > start { end - 1 } else { start };
        Span {
            start_byte: self.byte_offsets[start],
            end_byte: self.byte_offsets[end],
            start_line: self.lines[start],
            end_line: self.lines[end_line_idx.min(self.lines.len() - 1)],
        }
    }

    fn err(&self, start: usize, reason: impl Into<String>) -> PyError {
        PyError::Syntax(ParseError {
            reason: reason.into(),
            span: Some(self.span_from(start)),
        })
    }

    fn tokenize(mut self) -> Result<Vec<Token>, PyError> {
        let mut out: Vec<Token> = Vec::new();
        let mut indent_stack: Vec<usize> = vec![0];
        let mut paren_depth: i32 = 0;
        let mut at_line_start = true;

        loop {
            if at_line_start && paren_depth == 0 {
                let line_begin = self.pos;
                let mut col = 0usize;
                loop {
                    match self.peek_char() {
                        Some(' ') => {
                            col += 1;
                            self.pos += 1;
                        }
                        Some('\t') => {
                            return Err(self.err(
                                self.pos,
                                "tabs are not supported in indentation by the pilot lexer",
                            ));
                        }
                        _ => break,
                    }
                }
                match self.peek_char() {
                    None => break,
                    Some('\n') => {
                        self.pos += 1;
                        continue;
                    }
                    Some('#') => {
                        self.skip_line_comment();
                        if self.peek_char() == Some('\n') {
                            self.pos += 1;
                        }
                        continue;
                    }
                    Some('\r') => {
                        self.pos += 1;
                        continue;
                    }
                    _ => {
                        let top = *indent_stack.last().unwrap();
                        if col > top {
                            indent_stack.push(col);
                            out.push(Token {
                                kind: TokenKind::Indent,
                                span: self.span_from(line_begin),
                            });
                        } else if col < top {
                            while *indent_stack.last().unwrap() > col {
                                indent_stack.pop();
                                out.push(Token {
                                    kind: TokenKind::Dedent,
                                    span: self.span_from(self.pos),
                                });
                            }
                            if *indent_stack.last().unwrap() != col {
                                return Err(self.err(
                                    line_begin,
                                    "inconsistent indentation: unindent does not match any outer indentation level",
                                ));
                            }
                        }
                        at_line_start = false;
                    }
                }
            }

            match self.peek_char() {
                None => break,
                Some(' ') | Some('\t') | Some('\r') => {
                    self.pos += 1;
                }
                Some('#') => {
                    self.skip_line_comment();
                }
                Some('\\') if self.peek_char_at(1) == Some('\n') => {
                    self.pos += 2; // explicit line continuation
                }
                Some('\\')
                    if self.peek_char_at(1) == Some('\r') && self.peek_char_at(2) == Some('\n') =>
                {
                    self.pos += 3;
                }
                Some('\n') => {
                    self.pos += 1;
                    if paren_depth == 0 {
                        out.push(Token {
                            kind: TokenKind::Newline,
                            span: self.span_from(self.pos.saturating_sub(1)),
                        });
                        at_line_start = true;
                    }
                }
                Some(c) => {
                    let start = self.pos;
                    let tok = self.scan_one(c, start, &mut paren_depth)?;
                    out.push(tok);
                }
            }
        }

        if !matches!(out.last().map(|t| &t.kind), Some(TokenKind::Newline) | None) {
            out.push(Token {
                kind: TokenKind::Newline,
                span: self.span_from(self.pos),
            });
        }
        if paren_depth != 0 {
            return Err(self.err(
                self.pos,
                "unterminated bracket: expected closing delimiter before end of file",
            ));
        }
        while indent_stack.len() > 1 {
            indent_stack.pop();
            out.push(Token {
                kind: TokenKind::Dedent,
                span: self.span_from(self.pos),
            });
        }
        out.push(Token {
            kind: TokenKind::Eof,
            span: self.span_from(self.pos),
        });
        Ok(out)
    }

    fn skip_line_comment(&mut self) {
        while let Some(c) = self.peek_char() {
            if c == '\n' {
                break;
            }
            self.pos += 1;
        }
    }

    fn scan_one(&mut self, c: char, start: usize, paren_depth: &mut i32) -> Result<Token, PyError> {
        macro_rules! single {
            ($kind:expr) => {{
                self.pos += 1;
                return Ok(Token {
                    kind: $kind,
                    span: self.span_from(start),
                });
            }};
        }
        match c {
            '(' => {
                *paren_depth += 1;
                single!(TokenKind::LParen)
            }
            ')' => {
                *paren_depth -= 1;
                single!(TokenKind::RParen)
            }
            '[' => {
                *paren_depth += 1;
                single!(TokenKind::LBrack)
            }
            ']' => {
                *paren_depth -= 1;
                single!(TokenKind::RBrack)
            }
            '{' => {
                *paren_depth += 1;
                single!(TokenKind::LBrace)
            }
            '}' => {
                *paren_depth -= 1;
                single!(TokenKind::RBrace)
            }
            ',' => single!(TokenKind::Comma),
            '.' if !self.peek_char_at(1).is_some_and(|n| n.is_ascii_digit()) => {
                single!(TokenKind::Dot)
            }
            ':' => {
                if self.peek_char_at(1) == Some('=') {
                    self.pos += 2;
                    return Ok(Token {
                        kind: TokenKind::ColonEqual,
                        span: self.span_from(start),
                    });
                }
                single!(TokenKind::Colon)
            }
            '=' => single!(TokenKind::Equals),
            '-' if self.peek_char_at(1) == Some('>') => {
                self.pos += 2;
                Ok(Token {
                    kind: TokenKind::Arrow,
                    span: self.span_from(start),
                })
            }
            '*' => {
                if self.peek_char_at(1) == Some('*') {
                    self.pos += 2;
                    return Ok(Token {
                        kind: TokenKind::DoubleStar,
                        span: self.span_from(start),
                    });
                }
                single!(TokenKind::Star)
            }
            '@' => single!(TokenKind::At),
            '"' | '\'' => {
                let (text, is_fstring) = self.scan_string(start, c, false)?;
                Ok(Token {
                    kind: TokenKind::Str { text, is_fstring },
                    span: self.span_from(start),
                })
            }
            _ if c.is_ascii_digit() => Ok(self.scan_number(start)),
            _ if is_ident_start(c) => Ok(self.scan_ident_or_string(start)?),
            _ => {
                self.pos += 1;
                Err(self.err(start, format!("unexpected character '{c}'")))
            }
        }
    }

    /// Scans an identifier. If it turns out to be a 0-2 letter string prefix
    /// (`r`, `b`, `u`, `f`, any case, any order/combo) immediately followed by
    /// a quote, re-dispatches into string scanning with that prefix recorded
    /// (`is_fstring` true iff the prefix contains `f`/`F`). Otherwise resolves
    /// keywords (`True`/`False`/`None`) or returns a plain `Name`.
    fn scan_ident_or_string(&mut self, start: usize) -> Result<Token, PyError> {
        while self.peek_char().is_some_and(is_ident_continue) {
            self.pos += 1;
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        if text.len() <= 2
            && !text.is_empty()
            && text.chars().all(|ch| STRING_PREFIX_CHARS.contains(ch))
            && matches!(self.peek_char(), Some('"') | Some('\''))
        {
            let is_fstring = text.contains('f') || text.contains('F');
            let quote = self.peek_char().unwrap();
            let (body, body_fstring) = self.scan_string(start, quote, is_fstring)?;
            return Ok(Token {
                kind: TokenKind::Str {
                    text: body,
                    is_fstring: body_fstring,
                },
                span: self.span_from(start),
            });
        }
        let kind = match text.as_str() {
            "True" => TokenKind::True,
            "False" => TokenKind::False,
            "None" => TokenKind::NoneTok,
            _ => TokenKind::Name(text),
        };
        Ok(Token {
            kind,
            span: self.span_from(start),
        })
    }

    /// Scans a (possibly triple-quoted) string literal starting at the quote
    /// character, returning the exact source slice (prefix + quotes +
    /// content, verbatim) and whether it is an f-string. `start` is the
    /// overall token start (covers any prefix already consumed).
    fn scan_string(
        &mut self,
        start: usize,
        quote: char,
        is_fstring: bool,
    ) -> Result<(String, bool), PyError> {
        self.pos += 1; // consume opening quote
        let triple = self.peek_char() == Some(quote) && self.peek_char_at(1) == Some(quote);
        if triple {
            self.pos += 2;
        }
        loop {
            match self.peek_char() {
                None => {
                    return Err(
                        self.err(start, "unterminated string literal: expected closing quote")
                    );
                }
                Some('\\') => {
                    self.pos += 1;
                    if self.peek_char().is_some() {
                        self.pos += 1;
                    } else {
                        return Err(self.err(start, "unterminated string literal: trailing escape"));
                    }
                }
                Some(c) if c == quote => {
                    if !triple {
                        self.pos += 1;
                        break;
                    }
                    if self.peek_char_at(1) == Some(quote) && self.peek_char_at(2) == Some(quote) {
                        self.pos += 3;
                        break;
                    }
                    self.pos += 1;
                }
                Some(_) => {
                    self.pos += 1;
                }
            }
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        Ok((text, is_fstring))
    }

    fn scan_number(&mut self, start: usize) -> Token {
        while self
            .peek_char()
            .is_some_and(|c| c.is_ascii_digit() || c == '_')
        {
            self.pos += 1;
        }
        if self.peek_char() == Some('.') && self.peek_char_at(1).is_some_and(|c| c.is_ascii_digit())
        {
            self.pos += 1;
            while self
                .peek_char()
                .is_some_and(|c| c.is_ascii_digit() || c == '_')
            {
                self.pos += 1;
            }
        }
        if matches!(self.peek_char(), Some('e') | Some('E')) {
            let save = self.pos;
            self.pos += 1;
            if matches!(self.peek_char(), Some('+') | Some('-')) {
                self.pos += 1;
            }
            if self.peek_char().is_some_and(|c| c.is_ascii_digit()) {
                while self.peek_char().is_some_and(|c| c.is_ascii_digit()) {
                    self.pos += 1;
                }
            } else {
                self.pos = save;
            }
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        Token {
            kind: TokenKind::Num(text),
            span: self.span_from(start),
        }
    }
}

fn is_ident_start(c: char) -> bool {
    c.is_alphabetic() || c == '_'
}

fn is_ident_continue(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

struct Parser<'t> {
    tokens: &'t [Token],
    pos: usize,
}

impl<'t> Parser<'t> {
    fn new(tokens: &'t [Token]) -> Self {
        Parser { tokens, pos: 0 }
    }

    fn peek(&self) -> &TokenKind {
        self.tokens
            .get(self.pos)
            .map(|t| &t.kind)
            .unwrap_or(&TokenKind::Eof)
    }

    fn peek_span(&self) -> Span {
        self.tokens
            .get(self.pos)
            .map(|t| t.span)
            .unwrap_or_else(|| {
                self.tokens.last().map(|t| t.span).unwrap_or(Span {
                    start_byte: 0,
                    end_byte: 0,
                    start_line: 1,
                    end_line: 1,
                })
            })
    }

    fn advance(&mut self) -> Token {
        let tok = self.tokens.get(self.pos).cloned().unwrap_or_else(|| Token {
            kind: TokenKind::Eof,
            span: self.peek_span(),
        });
        if self.pos < self.tokens.len() {
            self.pos += 1;
        }
        tok
    }

    fn skip_newlines(&mut self) {
        while matches!(self.peek(), TokenKind::Newline) {
            self.advance();
        }
    }

    fn expect_newline(&mut self) -> Result<(), PyError> {
        match self.peek() {
            TokenKind::Newline => {
                self.advance();
                Ok(())
            }
            other => Err(PyError::Syntax(ParseError {
                reason: format!("expected end of statement, found {}", describe(other)),
                span: Some(self.peek_span()),
            })),
        }
    }

    fn expect(&mut self, kind: &TokenKind, what: &str) -> Result<Token, PyError> {
        if self.peek() == kind {
            Ok(self.advance())
        } else {
            Err(PyError::Syntax(ParseError {
                reason: format!("expected {what}, found {}", describe(self.peek())),
                span: Some(self.peek_span()),
            }))
        }
    }

    fn expect_name(&mut self, what: &str) -> Result<(String, Span), PyError> {
        let tok = self.advance();
        match tok.kind {
            TokenKind::Name(n) => Ok((n, tok.span)),
            other => Err(PyError::Syntax(ParseError {
                reason: format!("expected {what}, found {}", describe(&other)),
                span: Some(tok.span),
            })),
        }
    }

    // -- Module / blocks -----------------------------------------------

    fn parse_module(&mut self) -> Result<AstNode, PyError> {
        let start_span = self.peek_span();
        let mut children = Vec::new();
        loop {
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::Eof) {
                break;
            }
            children.push(self.parse_statement()?);
        }
        let end_span = self.peek_span();
        Ok(AstNode {
            kind: "Module".to_string(),
            text: String::new(),
            children,
            span: join_span(start_span, end_span),
        })
    }

    /// Parses an indented block: expects `Indent`, statements until a
    /// matching `Dedent` (consumed).
    fn parse_indented_body(&mut self) -> Result<AstNode, PyError> {
        let start_span = self.peek_span();
        self.expect(&TokenKind::Indent, "an indented block")?;
        let mut children = Vec::new();
        loop {
            self.skip_newlines();
            match self.peek() {
                TokenKind::Dedent => {
                    self.advance();
                    break;
                }
                TokenKind::Eof => {
                    return Err(PyError::Syntax(ParseError {
                        reason: "unterminated block: expected a dedent before end of file"
                            .to_string(),
                        span: Some(start_span),
                    }));
                }
                _ => children.push(self.parse_statement()?),
            }
        }
        let end_span = self.peek_span();
        Ok(AstNode {
            kind: "Body".to_string(),
            text: String::new(),
            children,
            span: join_span(start_span, end_span),
        })
    }

    // -- Statements -------------------------------------------------------

    fn parse_statement(&mut self) -> Result<AstNode, PyError> {
        match self.peek() {
            TokenKind::At => self.parse_decorated(),
            TokenKind::Name(n) if n == "def" => self.parse_funcdef(Vec::new()),
            TokenKind::Name(n) if n == "class" => self.parse_classdef(Vec::new()),
            TokenKind::Name(n) if n == "import" => self.parse_import(),
            TokenKind::Name(n) if n == "from" => self.parse_from_import(),
            TokenKind::Name(n) if n == "return" => self.parse_return(),
            TokenKind::Name(n) if n == "pass" => self.parse_pass(),
            TokenKind::Name(n) if EXCLUDED_STATEMENT_KEYWORDS.contains(&n.as_str()) => {
                let span = self.peek_span();
                let kw = n.clone();
                Err(unsupported(
                    format!("statement type '{kw}' is outside the pilot subset"),
                    span,
                ))
            }
            TokenKind::Name(_)
            | TokenKind::Str { .. }
            | TokenKind::Num(_)
            | TokenKind::True
            | TokenKind::False
            | TokenKind::NoneTok
            | TokenKind::LParen
            | TokenKind::LBrack
            | TokenKind::LBrace => self.parse_expr_or_assign_stmt(),
            other => Err(PyError::Syntax(ParseError {
                reason: format!("expected a statement, found {}", describe(other)),
                span: Some(self.peek_span()),
            })),
        }
    }

    fn parse_pass(&mut self) -> Result<AstNode, PyError> {
        let tok = self.advance(); // "pass"
        self.expect_newline()?;
        Ok(AstNode {
            kind: "Pass".to_string(),
            text: String::new(),
            children: vec![],
            span: tok.span,
        })
    }

    fn parse_return(&mut self) -> Result<AstNode, PyError> {
        let tok = self.advance(); // "return"
        if matches!(self.peek(), TokenKind::Newline) {
            self.advance();
            return Ok(AstNode {
                kind: "Return".to_string(),
                text: String::new(),
                children: vec![],
                span: tok.span,
            });
        }
        let expr = self.parse_expr()?;
        let span = join_span(tok.span, expr.span);
        self.expect_newline()?;
        Ok(AstNode {
            kind: "Return".to_string(),
            text: String::new(),
            children: vec![expr],
            span,
        })
    }

    fn dotted_name(&mut self) -> Result<(String, Span), PyError> {
        let (first, mut span) = self.expect_name("a module name")?;
        let mut path = vec![first];
        while matches!(self.peek(), TokenKind::Dot) {
            self.advance();
            let (seg, seg_span) = self.expect_name("a name after '.'")?;
            path.push(seg);
            span = join_span(span, seg_span);
        }
        Ok((path.join("."), span))
    }

    fn parse_import_alias(&mut self, dotted: bool) -> Result<AstNode, PyError> {
        let (name, mut span) = if dotted {
            self.dotted_name()?
        } else {
            self.expect_name("a name")?
        };
        let mut children = Vec::new();
        if let TokenKind::Name(kw) = self.peek() {
            if kw == "as" {
                self.advance();
                let (alias, alias_span) = self.expect_name("an alias after 'as'")?;
                span = join_span(span, alias_span);
                children.push(AstNode {
                    kind: "Alias".to_string(),
                    text: alias,
                    children: vec![],
                    span: alias_span,
                });
            }
        }
        Ok(AstNode {
            kind: "ImportAlias".to_string(),
            text: name,
            children,
            span,
        })
    }

    fn parse_import(&mut self) -> Result<AstNode, PyError> {
        let start = self.advance().span; // "import"
        let mut children = vec![self.parse_import_alias(true)?];
        while matches!(self.peek(), TokenKind::Comma) {
            self.advance();
            children.push(self.parse_import_alias(true)?);
        }
        let end = children.last().map(|c| c.span).unwrap_or(start);
        self.expect_newline()?;
        Ok(AstNode {
            kind: "Import".to_string(),
            text: String::new(),
            children,
            span: join_span(start, end),
        })
    }

    fn parse_from_import(&mut self) -> Result<AstNode, PyError> {
        let start = self.advance().span; // "from"
        let mut dots = String::new();
        let mut last_span = start;
        while matches!(self.peek(), TokenKind::Dot) {
            dots.push('.');
            last_span = self.advance().span;
        }
        let mut module = dots.clone();
        if matches!(self.peek(), TokenKind::Name(n) if n != "import") {
            let (name, span) = self.dotted_name()?;
            module.push_str(&name);
            last_span = span;
        }
        if module.is_empty() {
            return Err(PyError::Syntax(ParseError {
                reason: "expected a module name or relative dots after 'from'".to_string(),
                span: Some(self.peek_span()),
            }));
        }
        match self.peek() {
            TokenKind::Name(n) if n == "import" => {
                self.advance();
            }
            other => {
                return Err(PyError::Syntax(ParseError {
                    reason: format!("expected 'import', found {}", describe(other)),
                    span: Some(self.peek_span()),
                }))
            }
        }

        let mut children = Vec::new();
        if matches!(self.peek(), TokenKind::Star) {
            let span = self.advance().span;
            children.push(AstNode {
                kind: "ImportAlias".to_string(),
                text: "*".to_string(),
                children: vec![],
                span,
            });
        } else if matches!(self.peek(), TokenKind::LParen) {
            self.advance();
            self.skip_newlines();
            loop {
                if matches!(self.peek(), TokenKind::RParen) {
                    break;
                }
                children.push(self.parse_import_alias(false)?);
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::Comma) {
                    self.advance();
                    self.skip_newlines();
                    continue;
                }
                break;
            }
            self.skip_newlines();
            self.expect(&TokenKind::RParen, "')'")?;
        } else {
            children.push(self.parse_import_alias(false)?);
            while matches!(self.peek(), TokenKind::Comma) {
                self.advance();
                children.push(self.parse_import_alias(false)?);
            }
        }
        let end = children.last().map(|c| c.span).unwrap_or(last_span);
        self.expect_newline()?;
        Ok(AstNode {
            kind: "ImportFrom".to_string(),
            text: module,
            children,
            span: join_span(start, end),
        })
    }

    fn parse_decorated(&mut self) -> Result<AstNode, PyError> {
        let mut decorators = Vec::new();
        while matches!(self.peek(), TokenKind::At) {
            let at_span = self.advance().span;
            let expr = self.parse_expr()?;
            let span = join_span(at_span, expr.span);
            self.expect_newline()?;
            decorators.push(AstNode {
                kind: "Decorator".to_string(),
                text: String::new(),
                children: vec![expr],
                span,
            });
        }
        match self.peek() {
            TokenKind::Name(n) if n == "def" => self.parse_funcdef(decorators),
            TokenKind::Name(n) if n == "class" => self.parse_classdef(decorators),
            other => Err(unsupported(
                format!(
                    "decorators are only supported immediately before a function or class \
                     definition in the pilot subset, found {}",
                    describe(other)
                ),
                self.peek_span(),
            )),
        }
    }

    fn wrap_decorators(decorators: Vec<AstNode>) -> Option<AstNode> {
        if decorators.is_empty() {
            return None;
        }
        let span = decorators
            .iter()
            .fold(decorators[0].span, |acc, d| join_span(acc, d.span));
        Some(AstNode {
            kind: "Decorators".to_string(),
            text: String::new(),
            children: decorators,
            span,
        })
    }

    fn parse_params(&mut self) -> Result<AstNode, PyError> {
        let start = self.expect(&TokenKind::LParen, "'('")?.span;
        let mut params = Vec::new();
        loop {
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::RParen) {
                break;
            }
            if matches!(self.peek(), TokenKind::Star)
                && !matches!(
                    self.tokens.get(self.pos + 1).map(|t| &t.kind),
                    Some(TokenKind::Star)
                )
            {
                let star_span = self.advance().span;
                if let TokenKind::Name(_) = self.peek() {
                    let (name, name_span) = self.expect_name("a parameter name")?;
                    params.push(AstNode {
                        kind: "VarArgs".to_string(),
                        text: name,
                        children: vec![],
                        span: join_span(star_span, name_span),
                    });
                } else {
                    params.push(AstNode {
                        kind: "KwOnlyMarker".to_string(),
                        text: String::new(),
                        children: vec![],
                        span: star_span,
                    });
                }
            } else if matches!(self.peek(), TokenKind::DoubleStar) {
                let star_span = self.advance().span;
                let (name, name_span) = self.expect_name("a parameter name")?;
                params.push(AstNode {
                    kind: "KwArgs".to_string(),
                    text: name,
                    children: vec![],
                    span: join_span(star_span, name_span),
                });
            } else {
                let (name, mut span) = self.expect_name("a parameter name")?;
                let mut children = Vec::new();
                if matches!(self.peek(), TokenKind::Colon) {
                    self.advance();
                    let ann = self.parse_expr()?;
                    span = join_span(span, ann.span);
                    children.push(AstNode {
                        kind: "Annotation".to_string(),
                        text: String::new(),
                        children: vec![ann],
                        span,
                    });
                }
                if matches!(self.peek(), TokenKind::Equals) {
                    self.advance();
                    let default = self.parse_expr()?;
                    span = join_span(span, default.span);
                    children.push(AstNode {
                        kind: "Default".to_string(),
                        text: String::new(),
                        children: vec![default],
                        span,
                    });
                }
                params.push(AstNode {
                    kind: "Param".to_string(),
                    text: name,
                    children,
                    span,
                });
            }
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::Comma) {
                self.advance();
                continue;
            }
            break;
        }
        self.skip_newlines();
        let end = self.expect(&TokenKind::RParen, "')'")?.span;
        Ok(AstNode {
            kind: "Params".to_string(),
            text: String::new(),
            children: params,
            span: join_span(start, end),
        })
    }

    fn parse_funcdef(&mut self, decorators: Vec<AstNode>) -> Result<AstNode, PyError> {
        let start = self.advance().span; // "def"
        let (name, _) = self.expect_name("a function name")?;
        let params = self.parse_params()?;
        let mut children = Vec::new();
        if let Some(d) = Self::wrap_decorators(decorators) {
            children.push(d);
        }
        children.push(params);
        if matches!(self.peek(), TokenKind::Arrow) {
            self.advance();
            let ann = self.parse_expr()?;
            children.push(AstNode {
                kind: "ReturnAnnotation".to_string(),
                text: String::new(),
                children: vec![ann],
                span: self.peek_span(),
            });
        }
        self.expect(&TokenKind::Colon, "':'")?;
        self.expect_newline()?;
        let body = self.parse_indented_body()?;
        let end_span = body.span;
        children.push(body);
        Ok(AstNode {
            kind: "FunctionDef".to_string(),
            text: name,
            children,
            span: join_span(start, end_span),
        })
    }

    fn parse_call_arg(&mut self) -> Result<AstNode, PyError> {
        if matches!(self.peek(), TokenKind::DoubleStar) {
            let star_span = self.advance().span;
            let inner = self.parse_expr()?;
            let span = join_span(star_span, inner.span);
            return Ok(AstNode {
                kind: "DoubleStarred".to_string(),
                text: String::new(),
                children: vec![inner],
                span,
            });
        }
        if matches!(self.peek(), TokenKind::Star) {
            let star_span = self.advance().span;
            let inner = self.parse_expr()?;
            let span = join_span(star_span, inner.span);
            return Ok(AstNode {
                kind: "Starred".to_string(),
                text: String::new(),
                children: vec![inner],
                span,
            });
        }
        // Lookahead: `Name '=' ...` (not `==`, which isn't lexed at all here)
        // is a keyword argument.
        if let TokenKind::Name(n) = self.peek() {
            if matches!(
                self.tokens.get(self.pos + 1).map(|t| &t.kind),
                Some(TokenKind::Equals)
            ) {
                let name = n.clone();
                let name_span = self.advance().span; // name
                self.advance(); // '='
                let value = self.parse_expr()?;
                let span = join_span(name_span, value.span);
                return Ok(AstNode {
                    kind: "KeywordArg".to_string(),
                    text: name,
                    children: vec![value],
                    span,
                });
            }
        }
        self.parse_expr()
    }

    fn parse_classdef(&mut self, decorators: Vec<AstNode>) -> Result<AstNode, PyError> {
        let start = self.advance().span; // "class"
        let (name, _) = self.expect_name("a class name")?;
        let mut children = Vec::new();
        if let Some(d) = Self::wrap_decorators(decorators) {
            children.push(d);
        }
        if matches!(self.peek(), TokenKind::LParen) {
            let lparen_span = self.advance().span;
            let mut bases = Vec::new();
            loop {
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::RParen) {
                    break;
                }
                bases.push(self.parse_call_arg()?);
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::Comma) {
                    self.advance();
                    continue;
                }
                break;
            }
            self.skip_newlines();
            let rparen_span = self.expect(&TokenKind::RParen, "')'")?.span;
            children.push(AstNode {
                kind: "Bases".to_string(),
                text: String::new(),
                children: bases,
                span: join_span(lparen_span, rparen_span),
            });
        }
        self.expect(&TokenKind::Colon, "':'")?;
        self.expect_newline()?;
        let body = self.parse_indented_body()?;
        let end_span = body.span;
        children.push(body);
        Ok(AstNode {
            kind: "ClassDef".to_string(),
            text: name,
            children,
            span: join_span(start, end_span),
        })
    }

    fn parse_expr_or_assign_stmt(&mut self) -> Result<AstNode, PyError> {
        let expr = self.parse_expr()?;
        match self.peek() {
            TokenKind::Colon => {
                let target = require_target(&expr)?;
                self.advance();
                let ann = self.parse_expr()?;
                let mut children = vec![ann];
                let mut span = join_span(expr.span, children[0].span);
                if matches!(self.peek(), TokenKind::Equals) {
                    self.advance();
                    let value = self.parse_expr()?;
                    span = join_span(span, value.span);
                    children.push(value);
                }
                self.expect_newline()?;
                Ok(AstNode {
                    kind: "AnnAssign".to_string(),
                    text: target,
                    children,
                    span,
                })
            }
            TokenKind::Equals => {
                let target = require_target(&expr)?;
                self.advance();
                let value = self.parse_expr()?;
                let span = join_span(expr.span, value.span);
                self.expect_newline()?;
                Ok(AstNode {
                    kind: "Assign".to_string(),
                    text: target,
                    children: vec![value],
                    span,
                })
            }
            _ => {
                self.expect_newline()?;
                let span = expr.span;
                Ok(AstNode {
                    kind: "ExprStmt".to_string(),
                    text: String::new(),
                    children: vec![expr],
                    span,
                })
            }
        }
    }

    // -- Expressions ------------------------------------------------------

    fn parse_expr(&mut self) -> Result<AstNode, PyError> {
        let tok = self.advance();
        match tok.kind {
            TokenKind::Str { text, is_fstring } => {
                if is_fstring {
                    return Err(unsupported(
                        "f-strings are outside the pilot subset",
                        tok.span,
                    ));
                }
                Ok(AstNode {
                    kind: "StringLit".to_string(),
                    text,
                    children: vec![],
                    span: tok.span,
                })
            }
            TokenKind::Num(n) => Ok(AstNode {
                kind: "NumberLit".to_string(),
                text: n,
                children: vec![],
                span: tok.span,
            }),
            TokenKind::True => Ok(AstNode {
                kind: "BoolLit".to_string(),
                text: "True".to_string(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::False => Ok(AstNode {
                kind: "BoolLit".to_string(),
                text: "False".to_string(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::NoneTok => Ok(AstNode {
                kind: "NoneLit".to_string(),
                text: "None".to_string(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::Name(first) => self.parse_traversal_or_call(first, tok.span),
            TokenKind::LBrack => self.parse_list(tok.span),
            TokenKind::LParen => self.parse_tuple_or_group(tok.span),
            TokenKind::LBrace => self.parse_dict(tok.span),
            other => Err(PyError::Syntax(ParseError {
                reason: format!("unexpected token in expression: {}", describe(&other)),
                span: Some(tok.span),
            })),
        }
    }

    fn parse_traversal_or_call(
        &mut self,
        first: String,
        start_span: Span,
    ) -> Result<AstNode, PyError> {
        let mut path = vec![first];
        let mut end_span = start_span;
        while matches!(self.peek(), TokenKind::Dot) {
            self.advance();
            let (seg, seg_span) = self.expect_name("a name after '.'")?;
            path.push(seg);
            end_span = seg_span;
        }
        let dotted = path.join(".");
        if matches!(self.peek(), TokenKind::LParen) {
            self.advance();
            let mut args = Vec::new();
            loop {
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::RParen) {
                    break;
                }
                args.push(self.parse_call_arg()?);
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::Comma) {
                    self.advance();
                    continue;
                }
                break;
            }
            self.skip_newlines();
            let rparen_span = self.expect(&TokenKind::RParen, "')'")?.span;
            Ok(AstNode {
                kind: "Call".to_string(),
                text: dotted,
                children: args,
                span: join_span(start_span, rparen_span),
            })
        } else {
            Ok(AstNode {
                kind: "Traversal".to_string(),
                text: dotted,
                children: vec![],
                span: join_span(start_span, end_span),
            })
        }
    }

    fn parse_list(&mut self, start_span: Span) -> Result<AstNode, PyError> {
        let mut items = Vec::new();
        loop {
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::RBrack) {
                break;
            }
            if matches!(self.peek(), TokenKind::Eof) {
                return Err(PyError::Syntax(ParseError {
                    reason: "unterminated list: expected closing ']'".to_string(),
                    span: Some(start_span),
                }));
            }
            items.push(self.parse_call_arg()?);
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::Comma) {
                self.advance();
                continue;
            }
            break;
        }
        self.skip_newlines();
        match self.peek() {
            TokenKind::RBrack => {
                let end_span = self.advance().span;
                Ok(AstNode {
                    kind: "List".to_string(),
                    text: String::new(),
                    children: items,
                    span: join_span(start_span, end_span),
                })
            }
            _ => Err(PyError::Syntax(ParseError {
                reason: "unterminated list: expected closing ']'".to_string(),
                span: Some(start_span),
            })),
        }
    }

    fn parse_tuple_or_group(&mut self, start_span: Span) -> Result<AstNode, PyError> {
        if matches!(self.peek(), TokenKind::RParen) {
            let end_span = self.advance().span;
            return Ok(AstNode {
                kind: "Tuple".to_string(),
                text: String::new(),
                children: vec![],
                span: join_span(start_span, end_span),
            });
        }
        let first = self.parse_call_arg()?;
        if matches!(self.peek(), TokenKind::Comma) {
            let mut items = vec![first];
            loop {
                self.skip_newlines();
                if !matches!(self.peek(), TokenKind::Comma) {
                    break;
                }
                self.advance();
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::RParen) {
                    break; // trailing comma
                }
                items.push(self.parse_call_arg()?);
            }
            self.skip_newlines();
            let end_span = self.expect(&TokenKind::RParen, "')'")?.span;
            return Ok(AstNode {
                kind: "Tuple".to_string(),
                text: String::new(),
                children: items,
                span: join_span(start_span, end_span),
            });
        }
        self.skip_newlines();
        match self.peek() {
            TokenKind::RParen => {
                let end_span = self.advance().span;
                Ok(AstNode {
                    kind: "Paren".to_string(),
                    text: String::new(),
                    children: vec![first],
                    span: join_span(start_span, end_span),
                })
            }
            other => Err(PyError::Syntax(ParseError {
                reason: format!(
                    "unterminated parenthesized expression, found {}",
                    describe(other)
                ),
                span: Some(self.peek_span()),
            })),
        }
    }

    fn parse_dict(&mut self, start_span: Span) -> Result<AstNode, PyError> {
        let mut entries = Vec::new();
        loop {
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::RBrace) {
                break;
            }
            if matches!(self.peek(), TokenKind::Eof) {
                return Err(PyError::Syntax(ParseError {
                    reason: "unterminated dict: expected closing '}'".to_string(),
                    span: Some(start_span),
                }));
            }
            if matches!(self.peek(), TokenKind::DoubleStar) {
                let star_span = self.advance().span;
                let inner = self.parse_expr()?;
                let span = join_span(star_span, inner.span);
                entries.push(AstNode {
                    kind: "DictUnpack".to_string(),
                    text: String::new(),
                    children: vec![inner],
                    span,
                });
            } else {
                let key = self.parse_expr()?;
                self.expect(&TokenKind::Colon, "':' after dict key")?;
                let value = self.parse_expr()?;
                let span = join_span(key.span, value.span);
                entries.push(AstNode {
                    kind: "DictEntry".to_string(),
                    text: String::new(),
                    children: vec![key, value],
                    span,
                });
            }
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::Comma) {
                self.advance();
                continue;
            }
            break;
        }
        self.skip_newlines();
        match self.peek() {
            TokenKind::RBrace => {
                let end_span = self.advance().span;
                Ok(AstNode {
                    kind: "Dict".to_string(),
                    text: String::new(),
                    children: entries,
                    span: join_span(start_span, end_span),
                })
            }
            _ => Err(PyError::Syntax(ParseError {
                reason: "unterminated dict: expected closing '}'".to_string(),
                span: Some(start_span),
            })),
        }
    }
}

/// An assignment/annotated-assignment target must be a plain name or a dotted
/// attribute path -- the pilot subset's deliberate restriction (no tuple
/// unpacking, no subscript targets, no starred targets).
fn require_target(expr: &AstNode) -> Result<String, PyError> {
    if expr.kind == "Traversal" {
        Ok(expr.text.clone())
    } else {
        Err(unsupported(
            "assignment targets must be a plain name or dotted attribute access in the pilot \
             subset (no tuple unpacking, subscripts, or starred targets)",
            expr.span,
        ))
    }
}

fn join_span(a: Span, b: Span) -> Span {
    Span {
        start_byte: a.start_byte.min(b.start_byte),
        end_byte: a.end_byte.max(b.end_byte),
        start_line: a.start_line.min(b.start_line),
        end_line: a.end_line.max(b.end_line),
    }
}

fn describe(kind: &TokenKind) -> String {
    match kind {
        TokenKind::Name(s) => format!("identifier '{s}'"),
        TokenKind::Str { .. } => "a string literal".to_string(),
        TokenKind::Num(_) => "a number".to_string(),
        TokenKind::True | TokenKind::False => "a boolean".to_string(),
        TokenKind::NoneTok => "'None'".to_string(),
        TokenKind::LParen => "'('".to_string(),
        TokenKind::RParen => "')'".to_string(),
        TokenKind::LBrack => "'['".to_string(),
        TokenKind::RBrack => "']'".to_string(),
        TokenKind::LBrace => "'{'".to_string(),
        TokenKind::RBrace => "'}'".to_string(),
        TokenKind::Comma => "','".to_string(),
        TokenKind::Dot => "'.'".to_string(),
        TokenKind::Colon => "':'".to_string(),
        TokenKind::ColonEqual => "':=' (walrus operator)".to_string(),
        TokenKind::Equals => "'='".to_string(),
        TokenKind::Arrow => "'->'".to_string(),
        TokenKind::Star => "'*'".to_string(),
        TokenKind::DoubleStar => "'**'".to_string(),
        TokenKind::At => "'@'".to_string(),
        TokenKind::Indent => "an indent".to_string(),
        TokenKind::Dedent => "a dedent".to_string(),
        TokenKind::Newline => "a newline".to_string(),
        TokenKind::Eof => "end of file".to_string(),
    }
}
