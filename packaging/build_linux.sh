#!/bin/sh
# Builds dist/FluidWorx and FluidWorx-<version>-linux-x86_64.tar.gz
set -e
cd "$(dirname "$0")/.."
python -m PyInstaller packaging/fluidworx.spec --noconfirm --distpath dist --workpath build
cp packaging/linux/install.sh packaging/linux/fluidworx.desktop packaging/linux/fluidworx-mime.xml dist/FluidWorx/
cp fluidworx/resources/fluidworx-256.png dist/FluidWorx/
cp LICENSE dist/FluidWorx/
VERSION=$(python -c "import fluidworx; print(fluidworx.VERSION)")
tar -C dist -czf "dist/FluidWorx-$VERSION-linux-x86_64.tar.gz" FluidWorx
