//! A from-scratch Terraform/HCL parser, built against public HCL grammar
//! documentation (the HashiCorp HCL native-syntax spec:
//! <https://github.com/hashicorp/hcl/blob/main/hclsyntax/spec.md>), not any
//! third-party HCL crate and not any reference-repository source (ADR-017).
//!
//! Scope (ADR-015, "R3 scope is Terraform/HCL and Python source"): the pilot's
//! common top-level constructs -- `resource`, `variable`, `module`, `locals`,
//! `provider`, `output`, `data`, and any other `identifier [labels] { body }`
//! block, plus their attributes -- and a deliberately bounded expression
//! grammar (string/number/bool/null literals, heredocs, dotted-identifier
//! traversals, tuples `[...]`, object constructors `{...}`, and parenthesized
//! expressions). This does not attempt to evaluate template interpolation
//! (`${...}`) or operators -- it is captured as text, which is a faithful
//! representation of what is on disk, not a guess at its value.
//!
//! Every failure path returns an explicit error with a reason; nothing here
//! panics on malformed input and nothing here returns a partial tree dressed
//! up as a complete one -- see `ParseOutput::Error` / `Unsupported`.

use cairn_transform_contract::{AstNode, ParseError, ParseInput, ParseOutput, Span};

/// Identifies this parser implementation and its version for the
/// transformation manifest (ADR-015).
pub const PARSER_VERSION: &str = "cairn-hcl-parser/0.1.0";

/// Parse one HCL source file into a [`ParseOutput`]. Never panics: any input,
/// however malformed, produces `ParseOutput::Error` with a reason rather than
/// an unwind.
pub fn parse_hcl(input: &ParseInput) -> ParseOutput {
    let source_file_id = input.source_file_id.clone();
    match parse_source(&input.source_text) {
        Ok(ast) => ParseOutput::Parsed {
            parser_version: PARSER_VERSION.to_string(),
            source_file_id,
            ast,
        },
        Err(err) => ParseOutput::Error {
            parser_version: PARSER_VERSION.to_string(),
            source_file_id,
            error: err,
        },
    }
}

fn parse_source(text: &str) -> Result<AstNode, ParseError> {
    let tokens = Lexer::new(text).tokenize()?;
    let mut parser = Parser::new(&tokens);
    let body = parser.parse_body(/* inside_braces */ false)?;
    Ok(body)
}

// ---------------------------------------------------------------------------
// Lexer
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
enum TokenKind {
    Ident(String),
    Str(String),     // raw text between quotes, escapes left intact
    Heredoc(String), // raw body lines, newline-joined, marker stripped
    Num(String),
    True,
    False,
    Null,
    LBrace,
    RBrace,
    LBrack,
    RBrack,
    LParen,
    RParen,
    Equals,
    Comma,
    Dot,
    Colon,
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
    byte_offsets: Vec<usize>, // byte_offsets[i] = byte offset of chars[i]; len == chars.len()+1
    lines: Vec<u32>,          // lines[i] = 1-indexed line number of chars[i]
    pos: usize,
    _src: &'a str,
}

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

    fn err(&self, start: usize, reason: impl Into<String>) -> ParseError {
        ParseError {
            reason: reason.into(),
            span: Some(self.span_from(start)),
        }
    }

    fn tokenize(mut self) -> Result<Vec<Token>, ParseError> {
        let mut out = Vec::new();
        loop {
            let tok = self.next_token()?;
            let is_eof = tok.kind == TokenKind::Eof;
            out.push(tok);
            if is_eof {
                break;
            }
        }
        Ok(out)
    }

    fn next_token(&mut self) -> Result<Token, ParseError> {
        loop {
            match self.peek_char() {
                None => {
                    return Ok(Token {
                        kind: TokenKind::Eof,
                        span: self.span_from(self.pos),
                    })
                }
                Some(' ') | Some('\t') | Some('\r') => {
                    self.pos += 1;
                }
                Some('#') => {
                    self.skip_line_comment();
                }
                Some('/') if self.peek_char_at(1) == Some('/') => {
                    self.skip_line_comment();
                }
                Some('/') if self.peek_char_at(1) == Some('*') => {
                    self.skip_block_comment()?;
                }
                _ => break,
            }
        }

        let start = self.pos;
        let c = match self.peek_char() {
            Some(c) => c,
            None => {
                return Ok(Token {
                    kind: TokenKind::Eof,
                    span: self.span_from(start),
                })
            }
        };

        if c == '\n' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::Newline,
                span: self.span_from(start),
            });
        }
        if c == '{' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::LBrace,
                span: self.span_from(start),
            });
        }
        if c == '}' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::RBrace,
                span: self.span_from(start),
            });
        }
        if c == '[' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::LBrack,
                span: self.span_from(start),
            });
        }
        if c == ']' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::RBrack,
                span: self.span_from(start),
            });
        }
        if c == '(' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::LParen,
                span: self.span_from(start),
            });
        }
        if c == ')' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::RParen,
                span: self.span_from(start),
            });
        }
        if c == '=' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::Equals,
                span: self.span_from(start),
            });
        }
        if c == ',' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::Comma,
                span: self.span_from(start),
            });
        }
        if c == ':' {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::Colon,
                span: self.span_from(start),
            });
        }
        if c == '.' && !self.peek_char_at(1).is_some_and(|n| n.is_ascii_digit()) {
            self.pos += 1;
            return Ok(Token {
                kind: TokenKind::Dot,
                span: self.span_from(start),
            });
        }
        if c == '"' {
            self.pos += 1;
            let content = self.scan_quoted_string(start)?;
            return Ok(Token {
                kind: TokenKind::Str(content),
                span: self.span_from(start),
            });
        }
        if c == '<' && self.peek_char_at(1) == Some('<') {
            return self.scan_heredoc(start);
        }
        if c.is_ascii_digit() {
            return Ok(self.scan_number(start));
        }
        if is_ident_start(c) {
            return Ok(self.scan_ident_or_keyword(start));
        }

        self.pos += 1;
        Err(self.err(start, format!("unexpected character '{c}'")))
    }

    fn skip_line_comment(&mut self) {
        while let Some(c) = self.peek_char() {
            if c == '\n' {
                break;
            }
            self.pos += 1;
        }
    }

    fn skip_block_comment(&mut self) -> Result<(), ParseError> {
        let start = self.pos;
        self.pos += 2; // consume "/*"
        loop {
            match self.peek_char() {
                None => {
                    return Err(self.err(start, "unterminated block comment: expected closing '*/'"))
                }
                Some('*') if self.peek_char_at(1) == Some('/') => {
                    self.pos += 2;
                    return Ok(());
                }
                Some(_) => self.pos += 1,
            }
        }
    }

    fn scan_quoted_string(&mut self, start: usize) -> Result<String, ParseError> {
        let mut buf = String::new();
        let mut interp_depth: i32 = 0;
        loop {
            match self.peek_char() {
                None => {
                    return Err(
                        self.err(start, "unterminated string literal: expected closing '\"'")
                    )
                }
                Some('\\') if interp_depth == 0 => {
                    buf.push('\\');
                    self.pos += 1;
                    if let Some(next) = self.peek_char() {
                        buf.push(next);
                        self.pos += 1;
                    } else {
                        return Err(self.err(start, "unterminated string literal: trailing escape"));
                    }
                }
                Some('"') if interp_depth == 0 => {
                    self.pos += 1;
                    return Ok(buf);
                }
                Some('$') if interp_depth == 0 && self.peek_char_at(1) == Some('{') => {
                    buf.push_str("${");
                    self.pos += 2;
                    interp_depth = 1;
                }
                Some('{') if interp_depth > 0 => {
                    interp_depth += 1;
                    buf.push('{');
                    self.pos += 1;
                }
                Some('}') if interp_depth > 0 => {
                    interp_depth -= 1;
                    buf.push('}');
                    self.pos += 1;
                }
                Some('"') if interp_depth > 0 => {
                    // A nested string literal inside ${...}. Scan it raw so an
                    // interpolated expression's own strings don't prematurely
                    // close the outer literal.
                    buf.push('"');
                    self.pos += 1;
                    loop {
                        match self.peek_char() {
                            None => {
                                return Err(self.err(
                                    start,
                                    "unterminated string literal: unterminated nested interpolation string",
                                ))
                            }
                            Some('\\') => {
                                buf.push('\\');
                                self.pos += 1;
                                if let Some(next) = self.peek_char() {
                                    buf.push(next);
                                    self.pos += 1;
                                } else {
                                    return Err(self
                                        .err(start, "unterminated string literal: trailing escape"));
                                }
                            }
                            Some('"') => {
                                buf.push('"');
                                self.pos += 1;
                                break;
                            }
                            Some(c) => {
                                buf.push(c);
                                self.pos += 1;
                            }
                        }
                    }
                }
                Some(c) => {
                    buf.push(c);
                    self.pos += 1;
                }
            }
        }
    }

    fn scan_heredoc(&mut self, start: usize) -> Result<Token, ParseError> {
        self.pos += 2; // consume "<<"
        let indented = self.peek_char() == Some('-');
        if indented {
            self.pos += 1;
        }
        let marker_start = self.pos;
        while self.peek_char().is_some_and(is_ident_continue) {
            self.pos += 1;
        }
        if self.pos == marker_start {
            return Err(self.err(start, "malformed heredoc: expected a marker after '<<'"));
        }
        let marker: String = self.chars[marker_start..self.pos].iter().collect();

        // Consume the rest of the introducer line (must reach end-of-line or EOF).
        while let Some(c) = self.peek_char() {
            if c == '\n' {
                break;
            }
            self.pos += 1;
        }
        if self.peek_char() == Some('\n') {
            self.pos += 1;
        }

        let mut lines: Vec<String> = Vec::new();
        loop {
            if self.peek_char().is_none() && lines.is_empty() {
                // EOF immediately after the introducer line, no body and no terminator.
                return Err(self.err(
                    start,
                    format!("unterminated heredoc: expected closing marker '{marker}'"),
                ));
            }
            let line_start = self.pos;
            while self.peek_char().is_some_and(|c| c != '\n') {
                self.pos += 1;
            }
            let line: String = self.chars[line_start..self.pos].iter().collect();
            let at_eof = self.peek_char().is_none();
            if !at_eof {
                self.pos += 1; // consume the newline
            }
            if line.trim() == marker {
                return Ok(Token {
                    kind: TokenKind::Heredoc(lines.join("\n")),
                    span: self.span_from(start),
                });
            }
            lines.push(line);
            if at_eof {
                return Err(self.err(
                    start,
                    format!("unterminated heredoc: expected closing marker '{marker}'"),
                ));
            }
        }
    }

    fn scan_number(&mut self, start: usize) -> Token {
        while self.peek_char().is_some_and(|c| c.is_ascii_digit()) {
            self.pos += 1;
        }
        if self.peek_char() == Some('.') && self.peek_char_at(1).is_some_and(|c| c.is_ascii_digit())
        {
            self.pos += 1;
            while self.peek_char().is_some_and(|c| c.is_ascii_digit()) {
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

    fn scan_ident_or_keyword(&mut self, start: usize) -> Token {
        while self.peek_char().is_some_and(is_ident_continue) {
            self.pos += 1;
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        let kind = match text.as_str() {
            "true" => TokenKind::True,
            "false" => TokenKind::False,
            "null" => TokenKind::Null,
            _ => TokenKind::Ident(text),
        };
        Token {
            kind,
            span: self.span_from(start),
        }
    }
}

fn is_ident_start(c: char) -> bool {
    c.is_alphabetic() || c == '_'
}

fn is_ident_continue(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '-'
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

    /// Parses a sequence of attributes/blocks. When `inside_braces` is true,
    /// stops at (and consumes) a matching `}`; reaching EOF first is an
    /// unterminated-block error. When false, stops at EOF.
    fn parse_body(&mut self, inside_braces: bool) -> Result<AstNode, ParseError> {
        let start_span = self.peek_span();
        let mut children = Vec::new();
        loop {
            self.skip_newlines();
            match self.peek() {
                TokenKind::Eof => {
                    if inside_braces {
                        return Err(ParseError {
                            reason: "unterminated block: expected closing '}' before end of file"
                                .to_string(),
                            span: Some(start_span),
                        });
                    }
                    break;
                }
                TokenKind::RBrace if inside_braces => {
                    self.advance();
                    break;
                }
                TokenKind::Ident(_) => {
                    children.push(self.parse_attribute_or_block()?);
                }
                other => {
                    return Err(ParseError {
                        reason: format!(
                            "expected an attribute or block, found {}",
                            describe(other)
                        ),
                        span: Some(self.peek_span()),
                    });
                }
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

    fn parse_attribute_or_block(&mut self) -> Result<AstNode, ParseError> {
        let name_tok = self.advance();
        let name = match &name_tok.kind {
            TokenKind::Ident(n) => n.clone(),
            other => {
                return Err(ParseError {
                    reason: format!("expected identifier, found {}", describe(other)),
                    span: Some(name_tok.span),
                })
            }
        };

        if matches!(self.peek(), TokenKind::Equals) {
            self.advance();
            let expr = self.parse_expr()?;
            let end_span = expr.span;
            // Consume a trailing terminator if present; don't require one.
            if matches!(self.peek(), TokenKind::Newline) {
                self.advance();
            }
            return Ok(AstNode {
                kind: "Attribute".to_string(),
                text: name,
                children: vec![expr],
                span: join_span(name_tok.span, end_span),
            });
        }

        // Otherwise this is a block: zero or more string/ident labels, then `{`.
        let mut labels = Vec::new();
        loop {
            match self.peek() {
                TokenKind::Str(s) => {
                    let span = self.peek_span();
                    labels.push(AstNode {
                        kind: "Label".to_string(),
                        text: s.clone(),
                        children: vec![],
                        span,
                    });
                    self.advance();
                }
                TokenKind::Ident(s) => {
                    let span = self.peek_span();
                    labels.push(AstNode {
                        kind: "Label".to_string(),
                        text: s.clone(),
                        children: vec![],
                        span,
                    });
                    self.advance();
                }
                TokenKind::LBrace => break,
                other => {
                    return Err(ParseError {
                        reason: format!(
                            "expected a block label or '{{', found {}",
                            describe(other)
                        ),
                        span: Some(self.peek_span()),
                    });
                }
            }
        }

        let lbrace_span = self.peek_span();
        self.advance(); // consume '{'
        let body = self.parse_body(true)?;
        let end_span = self
            .tokens
            .get(self.pos.saturating_sub(1))
            .map(|t| t.span)
            .unwrap_or(lbrace_span);

        let mut children = labels;
        children.push(body);
        Ok(AstNode {
            kind: "Block".to_string(),
            text: name,
            children,
            span: join_span(name_tok.span, end_span),
        })
    }

    fn parse_expr(&mut self) -> Result<AstNode, ParseError> {
        let tok = self.advance();
        match tok.kind {
            TokenKind::Str(ref s) => Ok(AstNode {
                kind: "StringLit".to_string(),
                text: format!("\"{s}\""),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::Heredoc(ref body) => Ok(AstNode {
                kind: "HeredocLit".to_string(),
                text: body.clone(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::Num(ref n) => Ok(AstNode {
                kind: "NumberLit".to_string(),
                text: n.clone(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::True => Ok(AstNode {
                kind: "BoolLit".to_string(),
                text: "true".to_string(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::False => Ok(AstNode {
                kind: "BoolLit".to_string(),
                text: "false".to_string(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::Null => Ok(AstNode {
                kind: "NullLit".to_string(),
                text: "null".to_string(),
                children: vec![],
                span: tok.span,
            }),
            TokenKind::Ident(ref first) => self.parse_traversal_or_call(first.clone(), tok.span),
            TokenKind::LBrack => self.parse_tuple(tok.span),
            TokenKind::LBrace => self.parse_object_cons(tok.span),
            TokenKind::LParen => {
                let inner = self.parse_expr()?;
                match self.peek() {
                    TokenKind::RParen => {
                        let end_span = self.peek_span();
                        self.advance();
                        Ok(AstNode {
                            kind: "Paren".to_string(),
                            text: String::new(),
                            children: vec![inner],
                            span: join_span(tok.span, end_span),
                        })
                    }
                    other => Err(ParseError {
                        reason: format!(
                            "unterminated parenthesized expression, found {}",
                            describe(other)
                        ),
                        span: Some(self.peek_span()),
                    }),
                }
            }
            other => Err(ParseError {
                reason: format!("unexpected token in expression: {}", describe(&other)),
                span: Some(tok.span),
            }),
        }
    }

    fn parse_traversal_or_call(
        &mut self,
        first: String,
        start_span: Span,
    ) -> Result<AstNode, ParseError> {
        if matches!(self.peek(), TokenKind::LParen) {
            self.advance();
            let mut args = Vec::new();
            loop {
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::RParen) {
                    break;
                }
                args.push(self.parse_expr()?);
                self.skip_newlines();
                if matches!(self.peek(), TokenKind::Comma) {
                    self.advance();
                    continue;
                }
                break;
            }
            self.skip_newlines();
            match self.peek() {
                TokenKind::RParen => {
                    let end_span = self.peek_span();
                    self.advance();
                    Ok(AstNode {
                        kind: "FunctionCall".to_string(),
                        text: first,
                        children: args,
                        span: join_span(start_span, end_span),
                    })
                }
                other => Err(ParseError {
                    reason: format!(
                        "unterminated function call arguments, found {}",
                        describe(other)
                    ),
                    span: Some(self.peek_span()),
                }),
            }
        } else {
            let mut path = vec![first];
            let mut end_span = start_span;
            while matches!(self.peek(), TokenKind::Dot) {
                self.advance();
                match self.peek() {
                    TokenKind::Ident(s) => {
                        path.push(s.clone());
                        end_span = self.peek_span();
                        self.advance();
                    }
                    TokenKind::Num(s) => {
                        // Splat/index-like numeric traversal segment, e.g. foo.0.bar
                        path.push(s.clone());
                        end_span = self.peek_span();
                        self.advance();
                    }
                    other => {
                        return Err(ParseError {
                            reason: format!(
                                "expected attribute name after '.', found {}",
                                describe(other)
                            ),
                            span: Some(self.peek_span()),
                        })
                    }
                }
            }
            Ok(AstNode {
                kind: "Traversal".to_string(),
                text: path.join("."),
                children: vec![],
                span: join_span(start_span, end_span),
            })
        }
    }

    fn parse_tuple(&mut self, start_span: Span) -> Result<AstNode, ParseError> {
        let mut items = Vec::new();
        loop {
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::RBrack) {
                break;
            }
            if matches!(self.peek(), TokenKind::Eof) {
                return Err(ParseError {
                    reason: "unterminated tuple: expected closing ']'".to_string(),
                    span: Some(start_span),
                });
            }
            items.push(self.parse_expr()?);
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
                let end_span = self.peek_span();
                self.advance();
                Ok(AstNode {
                    kind: "Tuple".to_string(),
                    text: String::new(),
                    children: items,
                    span: join_span(start_span, end_span),
                })
            }
            _ => Err(ParseError {
                reason: "unterminated tuple: expected closing ']'".to_string(),
                span: Some(start_span),
            }),
        }
    }

    fn parse_object_cons(&mut self, start_span: Span) -> Result<AstNode, ParseError> {
        let mut entries = Vec::new();
        loop {
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::RBrace) {
                break;
            }
            if matches!(self.peek(), TokenKind::Eof) {
                return Err(ParseError {
                    reason: "unterminated object constructor: expected closing '}'".to_string(),
                    span: Some(start_span),
                });
            }
            let key_tok = self.advance();
            let key = match &key_tok.kind {
                TokenKind::Ident(s) => s.clone(),
                TokenKind::Str(s) => s.clone(),
                other => {
                    return Err(ParseError {
                        reason: format!("expected object key, found {}", describe(other)),
                        span: Some(key_tok.span),
                    })
                }
            };
            match self.peek() {
                TokenKind::Equals | TokenKind::Colon => {
                    self.advance();
                }
                other => {
                    return Err(ParseError {
                        reason: format!(
                            "expected '=' or ':' after object key, found {}",
                            describe(other)
                        ),
                        span: Some(self.peek_span()),
                    })
                }
            }
            let value = self.parse_expr()?;
            let entry_span = join_span(key_tok.span, value.span);
            entries.push(AstNode {
                kind: "ObjectEntry".to_string(),
                text: key,
                children: vec![value],
                span: entry_span,
            });
            self.skip_newlines();
            if matches!(self.peek(), TokenKind::Comma) {
                self.advance();
                continue;
            }
        }
        self.skip_newlines();
        match self.peek() {
            TokenKind::RBrace => {
                let end_span = self.peek_span();
                self.advance();
                Ok(AstNode {
                    kind: "ObjectCons".to_string(),
                    text: String::new(),
                    children: entries,
                    span: join_span(start_span, end_span),
                })
            }
            _ => Err(ParseError {
                reason: "unterminated object constructor: expected closing '}'".to_string(),
                span: Some(start_span),
            }),
        }
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
        TokenKind::Ident(s) => format!("identifier '{s}'"),
        TokenKind::Str(_) => "a string literal".to_string(),
        TokenKind::Heredoc(_) => "a heredoc literal".to_string(),
        TokenKind::Num(_) => "a number".to_string(),
        TokenKind::True | TokenKind::False => "a boolean".to_string(),
        TokenKind::Null => "null".to_string(),
        TokenKind::LBrace => "'{'".to_string(),
        TokenKind::RBrace => "'}'".to_string(),
        TokenKind::LBrack => "'['".to_string(),
        TokenKind::RBrack => "']'".to_string(),
        TokenKind::LParen => "'('".to_string(),
        TokenKind::RParen => "')'".to_string(),
        TokenKind::Equals => "'='".to_string(),
        TokenKind::Comma => "','".to_string(),
        TokenKind::Dot => "'.'".to_string(),
        TokenKind::Colon => "':'".to_string(),
        TokenKind::Newline => "a newline".to_string(),
        TokenKind::Eof => "end of file".to_string(),
    }
}
