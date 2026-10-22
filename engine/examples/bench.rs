use folio_draw_engine::doc::Doc;
use std::time::Instant;
fn main() {
    let mut d = Doc::new(4000, 3000, [255, 255, 255, 255]);
    d.layer_add("a");
    d.layer_add("b");
    d.comp_update();
    for _ in 0..3 {
        d.mark_all();
        let t = Instant::now();
        d.comp_update();
        println!("comp_update {:?}", t.elapsed());
    }
    let t = Instant::now();
    let v = vec![0u8; 4000 * 3000 * 4];
    let s: u64 = v.iter().map(|&x| x as u64).sum();
    println!("touch 48MB {:?} {}", t.elapsed(), s);
}
