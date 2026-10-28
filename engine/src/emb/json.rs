//! A small JSON reader and writer: the embroidery calls take and give JSON across the C ABI.

use std::collections::BTreeMap;
use std::fmt::Write;

#[derive(Clone, Debug, PartialEq)]
pub enum J {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<J>),
    Obj(BTreeMap<String, J>),
}

impl J {
    pub fn get(&self, k: &str) -> &J {
        static NULL: J = J::Null;
        match self {
            J::Obj(m) => m.get(k).unwrap_or(&NULL),
            _ => &NULL,
        }
    }
    pub fn at(&self, i: usize) -> &J {
        static NULL: J = J::Null;
        match self {
            J::Arr(v) => v.get(i).unwrap_or(&NULL),
            _ => &NULL,
        }
    }
    pub fn arr(&self) -> &[J] {
        match self {
            J::Arr(v) => v,
            _ => &[],
        }
    }
    pub fn f(&self, default: f64) -> f64 {
        match self {
            J::Num(n) => *n,
            J::Bool(b) => *b as i32 as f64,
            J::Str(s) => s.parse().unwrap_or(default),
            _ => default,
        }
    }
    pub fn f32(&self, default: f32) -> f32 {
        self.f(default as f64) as f32
    }
    pub fn i(&self, default: i64) -> i64 {
        match self {
            J::Num(n) => *n as i64,
            J::Bool(b) => *b as i64,
            _ => default,
        }
    }
    pub fn b(&self, default: bool) -> bool {
        match self {
            J::Bool(b) => *b,
            J::Num(n) => *n != 0.0,
            _ => default,
        }
    }
    pub fn s(&self) -> &str {
        match self {
            J::Str(s) => s,
            _ => "",
        }
    }
    pub fn is_null(&self) -> bool {
        matches!(self, J::Null)
    }
    pub fn obj() -> J {
        J::Obj(BTreeMap::new())
    }
    pub fn set(&mut self, k: &str, v: J) {
        if let J::Obj(m) = self {
            m.insert(k.to_string(), v);
        }
    }
    pub fn push(&mut self, v: J) {
        if let J::Arr(a) = self {
            a.push(v);
        }
    }
    pub fn dump(&self) -> String {
        let mut s = String::new();
        write_j(self, &mut s);
        s
    }
}

impl From<f64> for J {
    fn from(v: f64) -> J {
        J::Num(v)
    }
}
impl From<f32> for J {
    fn from(v: f32) -> J {
        J::Num(v as f64)
    }
}
impl From<i64> for J {
    fn from(v: i64) -> J {
        J::Num(v as f64)
    }
}
impl From<usize> for J {
    fn from(v: usize) -> J {
        J::Num(v as f64)
    }
}
impl From<bool> for J {
    fn from(v: bool) -> J {
        J::Bool(v)
    }
}
impl From<&str> for J {
    fn from(v: &str) -> J {
        J::Str(v.to_string())
    }
}
impl From<String> for J {
    fn from(v: String) -> J {
        J::Str(v)
    }
}

fn write_num(n: f64, out: &mut String) {
    if !n.is_finite() {
        out.push('0');
    } else if n == n.trunc() && n.abs() < 1e15 {
        let _ = write!(out, "{}", n as i64);
    } else {
        // four decimals is 0.1 µm for millimetres: plenty, and keeps files small
        let v = (n * 10000.0).round() / 10000.0;
        let _ = write!(out, "{}", v);
    }
}

fn write_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_j(j: &J, out: &mut String) {
    match j {
        J::Null => out.push_str("null"),
        J::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        J::Num(n) => write_num(*n, out),
        J::Str(s) => write_str(s, out),
        J::Arr(a) => {
            out.push('[');
            for (i, v) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_j(v, out);
            }
            out.push(']');
        }
        J::Obj(m) => {
            out.push('{');
            for (i, (k, v)) in m.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_str(k, out);
                out.push(':');
                write_j(v, out);
            }
            out.push('}');
        }
    }
}

pub fn parse(s: &str) -> Result<J, String> {
    let mut p = Parser { b: s.as_bytes(), i: 0 };
    p.ws();
    if p.i >= p.b.len() {
        return Ok(J::Null);
    }
    let v = p.value(0)?;
    p.ws();
    if p.i != p.b.len() {
        return Err(format!("JSON: trailing data at {}", p.i));
    }
    Ok(v)
}

struct Parser<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn ws(&mut self) {
        while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\n' | b'\r' | b'\t') {
            self.i += 1;
        }
    }
    fn err<T>(&self, what: &str) -> Result<T, String> {
        Err(format!("JSON: {} at {}", what, self.i))
    }
    fn value(&mut self, depth: usize) -> Result<J, String> {
        if depth > 200 {
            return self.err("too deep");
        }
        self.ws();
        let Some(&c) = self.b.get(self.i) else { return self.err("unexpected end") };
        match c {
            b'{' => {
                self.i += 1;
                let mut m = BTreeMap::new();
                self.ws();
                if self.b.get(self.i) == Some(&b'}') {
                    self.i += 1;
                    return Ok(J::Obj(m));
                }
                loop {
                    self.ws();
                    let k = match self.value(depth + 1)? {
                        J::Str(s) => s,
                        _ => return self.err("object key"),
                    };
                    self.ws();
                    if self.b.get(self.i) != Some(&b':') {
                        return self.err("expected ':'");
                    }
                    self.i += 1;
                    let v = self.value(depth + 1)?;
                    m.insert(k, v);
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(b'}') => {
                            self.i += 1;
                            return Ok(J::Obj(m));
                        }
                        _ => return self.err("expected ',' or '}'"),
                    }
                }
            }
            b'[' => {
                self.i += 1;
                let mut a = Vec::new();
                self.ws();
                if self.b.get(self.i) == Some(&b']') {
                    self.i += 1;
                    return Ok(J::Arr(a));
                }
                loop {
                    a.push(self.value(depth + 1)?);
                    self.ws();
                    match self.b.get(self.i) {
                        Some(b',') => self.i += 1,
                        Some(b']') => {
                            self.i += 1;
                            return Ok(J::Arr(a));
                        }
                        _ => return self.err("expected ',' or ']'"),
                    }
                }
            }
            b'"' => {
                self.i += 1;
                let mut out: Vec<u8> = Vec::new();
                loop {
                    let Some(&c) = self.b.get(self.i) else { return self.err("unterminated string") };
                    self.i += 1;
                    match c {
                        b'"' => break,
                        b'\\' => {
                            let Some(&e) = self.b.get(self.i) else { return self.err("bad escape") };
                            self.i += 1;
                            match e {
                                b'n' => out.push(b'\n'),
                                b't' => out.push(b'\t'),
                                b'r' => out.push(b'\r'),
                                b'b' => out.push(8),
                                b'f' => out.push(12),
                                b'u' => {
                                    let mut cp = self.hex4()?;
                                    if (0xD800..0xDC00).contains(&cp) && self.b.get(self.i) == Some(&b'\\') && self.b.get(self.i + 1) == Some(&b'u') {
                                        self.i += 2;
                                        let lo = self.hex4()?;
                                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo.wrapping_sub(0xDC00) & 0x3FF);
                                    }
                                    let ch = char::from_u32(cp).unwrap_or('\u{FFFD}');
                                    let mut buf = [0u8; 4];
                                    out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                                }
                                other => out.push(other),
                            }
                        }
                        c => out.push(c),
                    }
                }
                Ok(J::Str(String::from_utf8_lossy(&out).into_owned()))
            }
            b't' if self.b[self.i..].starts_with(b"true") => {
                self.i += 4;
                Ok(J::Bool(true))
            }
            b'f' if self.b[self.i..].starts_with(b"false") => {
                self.i += 5;
                Ok(J::Bool(false))
            }
            b'n' if self.b[self.i..].starts_with(b"null") => {
                self.i += 4;
                Ok(J::Null)
            }
            _ => {
                let s = self.i;
                while self.i < self.b.len() && matches!(self.b[self.i], b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') {
                    self.i += 1;
                }
                if s == self.i {
                    return self.err("unexpected character");
                }
                let t = std::str::from_utf8(&self.b[s..self.i]).unwrap_or("");
                t.parse::<f64>().map(J::Num).or_else(|_| self.err("bad number"))
            }
        }
    }
    fn hex4(&mut self) -> Result<u32, String> {
        if self.i + 4 > self.b.len() {
            return self.err("bad \\u");
        }
        let t = std::str::from_utf8(&self.b[self.i..self.i + 4]).unwrap_or("");
        self.i += 4;
        u32::from_str_radix(t, 16).or_else(|_| self.err("bad \\u"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip() {
        let src = r#"{"a":[1,2.5,-3e2,true,null,"x\"yé"],"b":{"c":"d"}}"#;
        let j = parse(src).unwrap();
        assert_eq!(j.get("a").at(1).f(0.0), 2.5);
        assert_eq!(j.get("a").at(2).f(0.0), -300.0);
        assert_eq!(j.get("a").at(5).s(), "x\"yé");
        let back = parse(&j.dump()).unwrap();
        assert_eq!(back, j);
    }
}
