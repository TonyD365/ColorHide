#!/bin/sh
# Build Inkhue-<tag>-macos-<arch>.pkg from dist/Inkhue.app. Installs into /Applications.
#   packaging/macos/build_pkg.sh v1.2.3 arm64
set -eu
TAG="$1"; ARCH="$2"
VERSION="${TAG#v}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
mkdir -p "$WORK/root"
ditto dist/Inkhue.app "$WORK/root/Inkhue.app"

# never "relocate" the install to wherever another copy of the bundle happens to be
pkgbuild --analyze --root "$WORK/root" "$WORK/component.plist"
/usr/libexec/PlistBuddy -c "Set :0:BundleIsRelocatable false" "$WORK/component.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :0:BundleIsRelocatable bool false" "$WORK/component.plist"

pkgbuild --root "$WORK/root" --component-plist "$WORK/component.plist" \
    --install-location /Applications --scripts "$HERE/scripts" \
    --identifier io.github.tonyd365.inkhue --version "$VERSION" "$WORK/Inkhue.pkg"

cat > "$WORK/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>Inkhue $VERSION</title>
    <welcome mime-type="text/html"><![CDATA[<html><body style="font-family:-apple-system">
        <h2>Inkhue $VERSION</h2>
        <p>Print a color photo as a plain-looking black-and-white page. Scan it, and the color comes back.</p>
        <p>Inkhue will be installed in your <b>Applications</b> folder and keeps itself up to date.</p>
        </body></html>]]></welcome>
    <license file="LICENSE.txt"/>
    <options customize="never" require-scripts="false" hostArchitectures="$( [ "$ARCH" = arm64 ] && echo arm64 || echo x86_64 )"/>
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
    <choices-outline><line choice="default"><line choice="app"/></line></choices-outline>
    <choice id="default"/>
    <choice id="app" visible="false"><pkg-ref id="io.github.tonyd365.inkhue"/></choice>
    <pkg-ref id="io.github.tonyd365.inkhue" version="$VERSION" onConclusion="none">Inkhue.pkg</pkg-ref>
</installer-gui-script>
XML
mkdir -p "$WORK/resources"
cp LICENSE "$WORK/resources/LICENSE.txt"
OUT="Inkhue-$TAG-macos-$ARCH.pkg"
productbuild --distribution "$WORK/distribution.xml" --package-path "$WORK" --resources "$WORK/resources" "$OUT"
rm -rf "$WORK"
echo "$OUT"
