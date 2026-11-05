#!/bin/sh
# Adds FluidWorx to this user's menu and file types, like OpenSchematix's installer. --uninstall removes it.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
BIN=$HOME/.local/bin
if [ "$1" = "--uninstall" ]; then
    rm -f "$DATA/applications/fluidworx.desktop" "$DATA/mime/packages/fluidworx-mime.xml" \
          "$DATA/icons/hicolor/256x256/apps/fluidworx.png" "$BIN/fluidworx"
else
    mkdir -p "$DATA/applications" "$DATA/mime/packages" "$DATA/icons/hicolor/256x256/apps" "$BIN"
    sed "s|@EXEC@|$HERE/FluidWorx|" "$HERE/fluidworx.desktop" > "$DATA/applications/fluidworx.desktop"
    cp "$HERE/fluidworx-mime.xml" "$DATA/mime/packages/"
    cp "$HERE/fluidworx-256.png" "$DATA/icons/hicolor/256x256/apps/fluidworx.png"
    ln -sf "$HERE/FluidWorx" "$BIN/fluidworx"
fi
command -v update-mime-database >/dev/null && update-mime-database "$DATA/mime" || true
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA/applications" || true
