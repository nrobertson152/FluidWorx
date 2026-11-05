#!/usr/bin/env bash
# Package dist/FluidWorx as dist/FluidWorx-<version>-x86_64.AppImage. Same pinned, checksum-verified tool as OpenSchematix.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import fluidworx; print(fluidworx.VERSION)")
BUNDLE=dist/FluidWorx
[ -x "$BUNDLE/FluidWorx" ] || { echo "Build the bundle first (packaging/build_linux.sh)." >&2; exit 1; }

APPDIR=dist/FluidWorx.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/share/mime/packages"
cp -a "$BUNDLE" "$APPDIR/usr/lib/fluidworx"
rm -f "$APPDIR/usr/lib/fluidworx/install.sh"
sed "s|@EXEC@|FluidWorx|" packaging/linux/fluidworx.desktop > "$APPDIR/fluidworx.desktop"
cp "$APPDIR/fluidworx.desktop" "$APPDIR/usr/share/applications/fluidworx.desktop"
cp fluidworx/resources/fluidworx-256.png "$APPDIR/fluidworx.png"
cp fluidworx/resources/fluidworx-256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/fluidworx.png"
cp fluidworx/resources/fluidworx-256.png "$APPDIR/.DirIcon"
cp packaging/linux/fluidworx-mime.xml "$APPDIR/usr/share/mime/packages/"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/fluidworx/FluidWorx" "$@"
EOF
chmod +x "$APPDIR/AppRun"
chmod -R a+rX "$APPDIR"

APPIMAGETOOL_VERSION=1.9.1
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
TOOL="dist/appimagetool-${APPIMAGETOOL_VERSION}-x86_64.AppImage"
if [ ! -f "$TOOL" ]; then
    curl -fsSL --retry 3 -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
fi
echo "$APPIMAGETOOL_SHA256  $TOOL" | sha256sum -c -
chmod +x "$TOOL"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOL" --no-appstream "$APPDIR" "dist/FluidWorx-${VERSION}-x86_64.AppImage"
