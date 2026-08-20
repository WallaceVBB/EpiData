#!/usr/bin/env bash  
# packaging/make_appimage.sh  
set -euo pipefail  
  
APP=EpiData  
VERSION="${APP_VERSION:-0.0.0}"  
ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # racine du repo  
DIST="$ROOT/dist/$APP"  
APPDIR="$ROOT/$APP.AppDir"  
  
# 1. Nettoyer / recréer l'AppDir  
rm -rf "$APPDIR"  
mkdir -p "$APPDIR/usr/bin"  
mkdir -p "$APPDIR/usr/share/applications"  
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"  
  
# 2. Copier le build PyInstaller (onedir)  
cp -r "$DIST/"* "$APPDIR/usr/bin/"  
  
# 3. Copier le .desktop et l'icône  
cp "$ROOT/packaging/$APP.desktop" "$APPDIR/usr/share/applications/"  
cp "$ROOT/packaging/epidata.png"  "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APP.png"  
  
# 4. AppRun -> lance l'exécutable EpiData  
cat > "$APPDIR/AppRun" <<'EOF'  
#!/bin/bash  
HERE="$(dirname "$(readlink -f "${0}")")"  
exec "$HERE/usr/bin/EpiData" "$@"  
EOF  
chmod +x "$APPDIR/AppRun"  
  
# le .desktop et l'icône doivent aussi être à la racine de l'AppDir  
cp "$ROOT/packaging/$APP.desktop" "$APPDIR/$APP.desktop"  
cp "$ROOT/packaging/epidata.png"  "$APPDIR/epidata.png"  
  
# 5. Générer l'AppImage  
wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O appimagetool  
chmod +x appimagetool  
ARCH=x86_64 ./appimagetool "$APPDIR" "$ROOT/$APP-$VERSION-x86_64.AppImage"