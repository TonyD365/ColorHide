#!/bin/sh
# Build Inkhue-<tag>-linux-x64.deb from dist/Inkhue: app in /opt/Inkhue, launcher, menu entry, icon.
#   packaging/linux/build_deb.sh v1.2.3
set -eu
TAG="$1"
VERSION="${TAG#v}"
ROOT="$(mktemp -d)/inkhue"
mkdir -p "$ROOT/DEBIAN" "$ROOT/opt" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/pixmaps" "$ROOT/usr/share/doc/inkhue"
cp -a dist/Inkhue "$ROOT/opt/Inkhue"
ln -s /opt/Inkhue/Inkhue "$ROOT/usr/bin/inkhue"
cp assets/icon.png "$ROOT/usr/share/pixmaps/inkhue.png"
cp LICENSE "$ROOT/usr/share/doc/inkhue/copyright"
cat > "$ROOT/usr/share/applications/inkhue.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Inkhue
Comment=Print color photos as plain black-and-white; scan them back to color
Exec=/opt/Inkhue/Inkhue %F
Icon=inkhue
Terminal=false
Categories=Graphics;Photography;
MimeType=image/png;image/jpeg;image/tiff;application/pdf;
DESKTOP
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: inkhue
Version: $VERSION
Architecture: amd64
Maintainer: Inkhue contributors <https://github.com/TonyD365/Inkhue>
Homepage: https://github.com/TonyD365/Inkhue
Section: graphics
Priority: optional
Replaces: colorhide
Conflicts: colorhide
Provides: colorhide
Depends: libegl1, libxkbcommon-x11-0, libxcb-cursor0, libfontconfig1
Recommends: cups-client, sane-utils
Installed-Size: $(du -sk "$ROOT/opt" | cut -f1)
Description: Hide a photo's color in a black-and-white print
 Inkhue prints a color photo as a plain-looking black-and-white page and
 recovers the color from a scan of it.
CONTROL
OUT="Inkhue-$TAG-linux-x64.deb"
dpkg-deb --build --root-owner-group "$ROOT" "$OUT"
rm -rf "$(dirname "$ROOT")"
echo "$OUT"
