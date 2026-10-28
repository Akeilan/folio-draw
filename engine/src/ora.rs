//! OpenRaster (.ora) — the open layered image format shared by GIMP, Krita and MyPaint.
//! A ZIP holding stack.xml, one PNG per layer, a merged image and a thumbnail.

use crate::doc::{resample, Doc, BLEND_ADD, BLEND_DARKEN, BLEND_DIFFERENCE, BLEND_LIGHTEN, BLEND_MULTIPLY, BLEND_NORMAL, BLEND_OVERLAY, BLEND_SCREEN};
use crate::png;
use crate::zip::{ZipReader, ZipWriter};

const OPS: [(u8, &str); 8] = [
    (BLEND_NORMAL, "svg:src-over"),
    (BLEND_MULTIPLY, "svg:multiply"),
    (BLEND_SCREEN, "svg:screen"),
    (BLEND_OVERLAY, "svg:overlay"),
    (BLEND_DARKEN, "svg:darken"),
    (BLEND_LIGHTEN, "svg:lighten"),
    (BLEND_DIFFERENCE, "svg:difference"),
    (BLEND_ADD, "svg:plus"),
];

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
        .replace('\n', "&#10;").replace('\r', "&#13;").replace('\t', "&#9;")
}

fn unesc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        let Some(j) = tail.find(';') else {
            out.push_str(tail);
            return out;
        };
        let ent = &tail[1..j];
        match ent {
            "amp" => out.push('&'),
            "lt" => out.push('<'),
            "gt" => out.push('>'),
            "quot" => out.push('"'),
            "apos" => out.push('\''),
            _ if ent.starts_with("#x") => {
                if let Some(c) = u32::from_str_radix(&ent[2..], 16).ok().and_then(char::from_u32) {
                    out.push(c)
                }
            }
            _ if ent.starts_with('#') => {
                if let Some(c) = ent[1..].parse::<u32>().ok().and_then(char::from_u32) {
                    out.push(c)
                }
            }
            _ => out.push_str(&tail[..=j]),
        }
        rest = &tail[j + 1..];
    }
    out.push_str(rest);
    out
}

pub fn save(doc: &Doc) -> Vec<u8> {
    let mut z = ZipWriter::new();
    z.add("mimetype", b"image/openraster", false);
    let mut xml = format!(
        "<?xml version='1.0' encoding='UTF-8'?>\n<image version=\"0.0.5\" w=\"{}\" h=\"{}\" xres=\"72\" yres=\"72\" xmlns:folio=\"https://folio.local/ns\" folio:loop=\"{}\" folio:frames-view=\"{}\"{}>\n <stack>\n",
        doc.w, doc.h, doc.gif_loop, doc.solo as u8,
        if doc.emb.is_empty() { String::new() } else { format!(" folio:embroidery=\"{}\"", esc(&doc.emb)) }
    );
    // stack.xml lists the topmost layer first
    let n = doc.layers.len();
    for (i, l) in doc.layers.iter().enumerate().rev() {
        let src = format!("data/layer{}.png", i);
        let op = OPS.iter().find(|o| o.0 == l.blend).map(|o| o.1).unwrap_or("svg:src-over");
        xml.push_str(&format!(
            "  <layer name=\"{}\" src=\"{}\" x=\"0\" y=\"0\" opacity=\"{:.3}\" visibility=\"{}\" composite-op=\"{}\"{}{}{} />\n",
            esc(&l.name),
            src,
            l.opacity,
            if l.visible { "visible" } else { "hidden" },
            op,
            if i == doc.active { " selected=\"true\"" } else { "" },
            if l.delay_ms > 0 { format!(" folio:delay=\"{}\"", l.delay_ms) } else { String::new() },
            if l.text.is_empty() { String::new() } else { format!(" folio:text=\"{}\"", esc(&l.text)) }
        ));
        z.add(&src, &png::encode(doc.w, doc.h, &l.px, 6), false);
    }
    let _ = n;
    xml.push_str(" </stack>\n</image>\n");
    z.add("stack.xml", xml.as_bytes(), true);
    let merged = doc.flatten_rgba();
    z.add("mergedimage.png", &png::encode(doc.w, doc.h, &merged, 6), false);
    let scale = (256.0 / doc.w.max(doc.h) as f32).min(1.0);
    let (tw, th) = (((doc.w as f32 * scale).round() as usize).max(1), ((doc.h as f32 * scale).round() as usize).max(1));
    let thumb = resample(&merged, doc.w, doc.h, tw, th, true);
    z.add("Thumbnails/thumbnail.png", &png::encode(tw, th, &thumb, 6), false);
    z.finish()
}

fn attr(tag: &str, key: &str) -> Option<String> {
    let mut search = 0;
    while let Some(i) = tag[search..].find(key) {
        let at = search + i;
        let before_ok = at == 0 || tag.as_bytes()[at - 1].is_ascii_whitespace();
        let after = &tag[at + key.len()..];
        let after_trim = after.trim_start();
        if before_ok && after_trim.starts_with('=') {
            let v = after_trim[1..].trim_start();
            let q = v.chars().next()?;
            if q == '"' || q == '\'' {
                let end = v[1..].find(q)?;
                return Some(unesc(&v[1..1 + end]));
            }
        }
        search = at + key.len();
    }
    None
}

pub fn load(data: &[u8]) -> Result<Doc, String> {
    let z = ZipReader::open(data)?;
    let xml_bytes = z.read("stack.xml")?;
    let xml = String::from_utf8_lossy(&xml_bytes).into_owned();
    let img_start = xml.find("<image").ok_or("OpenRaster: no <image> element")?;
    let img_end = xml[img_start..].find('>').ok_or("OpenRaster: bad <image>")? + img_start;
    let img_tag = &xml[img_start..img_end];
    let w: usize = attr(img_tag, "w").and_then(|v| v.parse().ok()).ok_or("OpenRaster: missing width")?;
    let h: usize = attr(img_tag, "h").and_then(|v| v.parse().ok()).ok_or("OpenRaster: missing height")?;
    if w == 0 || h == 0 || w > 32768 || h > 32768 {
        return Err("OpenRaster: bad image size".into());
    }
    let mut tags: Vec<String> = Vec::new();
    let mut pos = 0;
    while let Some(i) = xml[pos..].find("<layer") {
        let s = pos + i;
        let e = xml[s..].find('>').map(|e| s + e).ok_or("OpenRaster: bad <layer>")?;
        tags.push(xml[s..e].to_string());
        pos = e;
    }
    let mut doc = Doc::empty(w, h);
    let mut active = 0usize;
    // bottom layer last in XML → iterate reversed
    for tag in tags.iter().rev() {
        let src = match attr(tag, "src") {
            Some(s) => s,
            None => continue,
        };
        let bytes = match z.read(&src) {
            Ok(b) => b,
            Err(_) => continue,
        };
        let img = png::decode(&bytes)?;
        let x: i64 = attr(tag, "x").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) as i64;
        let y: i64 = attr(tag, "y").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) as i64;
        let px = place(&img.px, img.w, img.h, x, y, w, h);
        let name = attr(tag, "name").unwrap_or_else(|| format!("Layer {}", doc.layers.len() + 1));
        let opacity = attr(tag, "opacity").and_then(|v| v.parse::<f32>().ok()).unwrap_or(1.0);
        let visible = attr(tag, "visibility").map(|v| v != "hidden").unwrap_or(true);
        let blend = attr(tag, "composite-op")
            .and_then(|op| OPS.iter().find(|o| o.1 == op).map(|o| o.0))
            .unwrap_or(BLEND_NORMAL);
        if attr(tag, "selected").as_deref() == Some("true") {
            active = doc.layers.len();
        }
        doc.push_layer(&name, px, opacity, visible, blend);
        if let Some(dl) = attr(tag, "folio:delay").and_then(|v| v.parse::<u32>().ok()) {
            doc.layers.last_mut().unwrap().delay_ms = dl;
        }
        if let Some(t) = attr(tag, "folio:text") {
            doc.layers.last_mut().unwrap().text = t;
        }
    }
    if doc.layers.is_empty() {
        let merged = z.read("mergedimage.png").map_err(|_| "OpenRaster: no readable layers".to_string())?;
        let img = png::decode(&merged)?;
        doc.push_layer("Background", place(&img.px, img.w, img.h, 0, 0, w, h), 1.0, true, BLEND_NORMAL);
    }
    doc.active = active.min(doc.layers.len() - 1);
    if let Some(v) = attr(img_tag, "folio:loop").and_then(|v| v.parse::<i32>().ok()) {
        doc.gif_loop = v.clamp(-1, 65535);
    }
    doc.solo = attr(img_tag, "folio:frames-view").as_deref() == Some("1");
    if let Some(e) = attr(img_tag, "folio:embroidery") {
        doc.emb = e;
    }
    Ok(doc)
}

fn place(px: &[u8], pw: usize, ph: usize, x: i64, y: i64, w: usize, h: usize) -> Vec<u8> {
    if pw == w && ph == h && x == 0 && y == 0 {
        return px.to_vec();
    }
    crate::doc::crop_px(px, pw, ph, -x, -y, w, h)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip() {
        let mut d = Doc::new(20, 10, [255, 255, 255, 255]);
        d.layer_add("Ink & \"quotes\"");
        d.layer_set_props(1, None, 0.5, false, BLEND_MULTIPLY, 120, false);
        d.gif_loop = 3;
        d.emb = "{\"hoop\":\"4x4\"}".into();
        let bytes = save(&d);
        let back = load(&bytes).unwrap();
        assert_eq!(back.layers.len(), 2);
        assert_eq!(back.layers[1].name, "Ink & \"quotes\"");
        assert!(!back.layers[1].visible);
        assert_eq!(back.layers[1].blend, BLEND_MULTIPLY);
        assert!((back.layers[1].opacity - 0.5).abs() < 0.01);
        assert_eq!(back.layers[1].delay_ms, 120);
        assert_eq!(back.gif_loop, 3);
        assert_eq!(back.emb, d.emb);
        assert_eq!(back.layers[0].px, d.layers[0].px);
    }
}
