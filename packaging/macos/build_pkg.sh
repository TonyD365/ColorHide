#!/bin/sh
# Build ColorHide-<tag>-macos-<arch>.pkg from dist/ColorHide.app. Installs into /Applications.
#   packaging/macos/build_pkg.sh v1.2.3 arm64
set -eu
TAG="$1"; ARCH="$2"
VERSION="${TAG#v}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
mkdir -p "$WORK/root"
ditto dist/ColorHide.app "$WORK/root/ColorHide.app"

# never "relocate" the install to wherever another copy of the bundle happens to be
pkgbuild --analyze --root "$WORK/root" "$WORK/component.plist"
/usr/libexec/PlistBuddy -c "Add :0:BundleIsRelocatable bool false" "$WORK/component.plist"

pkgbuild --root "$WORK/root" --component-plist "$WORK/component.plist" \
    --install-location /Applications --scripts "$HERE/scripts" \
    --identifier io.github.tonyd365.colorhide --version "$VERSION" "$WORK/ColorHide.pkg"

cat > "$WORK/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>ColorHide $VERSION</title>
    <welcome mime-type="text/html"><![CDATA[<html><body style="font-family:-apple-system">
        <h2>ColorHide $VERSION</h2>
        <p>Print a color photo as a plain-looking black-and-white page. Scan it, and the color comes back.</p>
        <p>ColorHide will be installed in your <b>Applications</b> folder and keeps itself up to date.</p>
        </body></html>]]></welcome>
    <license file="LICENSE.txt"/>
    <options customize="never" require-scripts="false" hostArchitectures="$( [ "$ARCH" = arm64 ] && echo arm64 || echo x86_64 )"/>
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
    <choices-outline><line choice="default"><line choice="app"/></line></choices-outline>
    <choice id="default"/>
    <choice id="app" visible="false"><pkg-ref id="io.github.tonyd365.colorhide"/></choice>
    <pkg-ref id="io.github.tonyd365.colorhide" version="$VERSION" onConclusion="none">ColorHide.pkg</pkg-ref>
</installer-gui-script>
XML
mkdir -p "$WORK/resources"
cp LICENSE "$WORK/resources/LICENSE.txt"
OUT="ColorHide-$TAG-macos-$ARCH.pkg"
productbuild --distribution "$WORK/distribution.xml" --package-path "$WORK" --resources "$WORK/resources" "$OUT"
rm -rf "$WORK"
echo "$OUT"
