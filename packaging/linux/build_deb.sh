#!/bin/sh
# Build ColorHide-<tag>-linux-x64.deb from dist/ColorHide: app in /opt/ColorHide, launcher, menu entry, icon.
#   packaging/linux/build_deb.sh v1.2.3
set -eu
TAG="$1"
VERSION="${TAG#v}"
ROOT="$(mktemp -d)/colorhide"
mkdir -p "$ROOT/DEBIAN" "$ROOT/opt" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/pixmaps" "$ROOT/usr/share/doc/colorhide"
cp -a dist/ColorHide "$ROOT/opt/ColorHide"
ln -s /opt/ColorHide/ColorHide "$ROOT/usr/bin/colorhide"
cp assets/icon.png "$ROOT/usr/share/pixmaps/colorhide.png"
cp LICENSE "$ROOT/usr/share/doc/colorhide/copyright"
cat > "$ROOT/usr/share/applications/colorhide.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=ColorHide
Comment=Print color photos as plain black-and-white; scan them back to color
Exec=/opt/ColorHide/ColorHide %F
Icon=colorhide
Terminal=false
Categories=Graphics;Photography;
MimeType=image/png;image/jpeg;image/tiff;application/pdf;
DESKTOP
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: colorhide
Version: $VERSION
Architecture: amd64
Maintainer: ColorHide contributors <https://github.com/TonyD365/ColorHide>
Homepage: https://github.com/TonyD365/ColorHide
Section: graphics
Priority: optional
Depends: libegl1, libxkbcommon-x11-0, libxcb-cursor0, libfontconfig1
Recommends: cups-client, sane-utils
Installed-Size: $(du -sk "$ROOT/opt" | cut -f1)
Description: Hide a photo's color in a black-and-white print
 ColorHide prints a color photo as a plain-looking black-and-white page and
 recovers the color from a scan of it.
CONTROL
OUT="ColorHide-$TAG-linux-x64.deb"
dpkg-deb --build --root-owner-group "$ROOT" "$OUT"
rm -rf "$(dirname "$ROOT")"
echo "$OUT"
