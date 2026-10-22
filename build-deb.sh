#!/bin/sh
# Build the Folio Draw .deb (amd64). Usage: ./build-deb.sh
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' folio_draw/__init__.py)
( cd engine && cargo build --release )
ROOT=build/folio-draw_${VERSION}_amd64
rm -rf "$ROOT"
install -d "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/folio-draw" "$ROOT/usr/lib/python3/dist-packages/folio_draw" \
  "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/doc/folio-draw"
install -m 644 engine/target/release/libfolio_draw_engine.so "$ROOT/usr/lib/folio-draw/"
strip --strip-unneeded "$ROOT/usr/lib/folio-draw/libfolio_draw_engine.so"
install -m 644 folio_draw/*.py "$ROOT/usr/lib/python3/dist-packages/folio_draw/"
install -m 644 folio-draw.desktop "$ROOT/usr/share/applications/folio-draw.desktop"
install -m 644 data/icons/hicolor/scalable/apps/folio-draw.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
for s in 16 24 32 48 64 128 256; do
  install -d "$ROOT/usr/share/icons/hicolor/${s}x${s}/apps"
  install -m 644 "data/icons/png/${s}.png" "$ROOT/usr/share/icons/hicolor/${s}x${s}/apps/folio-draw.png"
done
cat > "$ROOT/usr/bin/folio-draw" <<'PY'
#!/usr/bin/python3
import sys
from folio_draw.app import main
sys.exit(main())
PY
chmod 755 "$ROOT/usr/bin/folio-draw"
cat > "$ROOT/usr/share/doc/folio-draw/copyright" <<'TXT'
Folio Draw — part of the Folio suite.
All code (engine, codecs, interface) written from scratch for this project.
License: MIT
TXT
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTL
Package: folio-draw
Version: ${VERSION}
Architecture: amd64
Maintainer: Ron Shillings <ron.shillings@gmail.com>
Installed-Size: ${SIZE}
Depends: python3 (>= 3.8), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, libc6 (>= 2.34), libgcc-s1
Section: graphics
Priority: optional
Homepage: https://folio.local/draw
Description: Simple drawing program with layers and real transparency
 Folio Draw is a quick, uncluttered picture editor in the spirit of the classic
 desktop paint program: pencil, brushes, shapes, text, fill, selection, crop,
 resize and rotate — plus layers, blend modes and true alpha transparency.
 Opens and saves PNG, JPEG, BMP, GIF (animated GIFs open with one frame per
 layer) and OpenRaster (.ora, keeps layers) using
 its own native engine. Part of the Folio suite.
CTL
cat > "$ROOT/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
fi
exit 0
SH
cp "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"
sed -i 's/= "configure"/= "remove"/' "$ROOT/DEBIAN/postrm"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"
find "$ROOT" -name __pycache__ -prune -exec rm -rf {} +
dpkg-deb --root-owner-group --build "$ROOT" "build/folio-draw_${VERSION}_amd64.deb"
echo "built build/folio-draw_${VERSION}_amd64.deb"
