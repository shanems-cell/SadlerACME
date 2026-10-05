#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
BUILD="$ROOT/.build"
DIST="$ROOT/dist"
VERSION=$(sed -n 's/^version="\([^"]*\)"$/\1/p' "$ROOT/pkg/INFO")
[ -n "$VERSION" ] || exit 1
grep -Fq "VERSION=\"$VERSION\"" "$ROOT/src/ui/index.cgi" || { echo "UI/package versions differ" >&2; exit 1; }
rm -rf "$BUILD"
mkdir -p "$BUILD/payload/share/sadleracme" "$BUILD/spk" "$DIST"
cp -R "$ROOT/src/." "$BUILD/payload/"
rm -rf "$BUILD/payload/lib"
rm -f "$BUILD/payload/ui/workflow-api.sh"
cp -R "$ROOT/vendor/acme.sh-3.1.5" "$BUILD/payload/share/"
cp "$ROOT/LICENSE" "$BUILD/payload/ui/LICENSE.txt"
cp "$ROOT/NOTICE.txt" "$BUILD/payload/share/sadleracme/NOTICE.txt"
cp -R "$ROOT/pkg/." "$BUILD/spk/"
python3 "$ROOT/tools/assemble_worker.py" "$ROOT" "$BUILD/payload/bin/sadleracme-root"
python3 "$ROOT/tools/assemble_worker.py" "$ROOT" "$BUILD/payload/bin/sadleracme-emergency-remove" emergency
python3 "$ROOT/tools/assemble_worker.py" "$ROOT" "$BUILD/payload/ui/index.cgi" cgi
python3 "$ROOT/tools/build_help.py" "$ROOT" "$BUILD/payload/ui"
cp "$BUILD/payload/bin/sadleracme-emergency-remove" "$BUILD/payload/ui/sadleracme-emergency-remove.txt"
python3 "$ROOT/tools/build_units.py" "$BUILD"
find "$BUILD/payload" "$BUILD/spk" -type d -exec chmod 755 {} \; -exec chmod g-s {} \;
find "$BUILD/payload" "$BUILD/spk" -type f -exec chmod 644 {} \;
chmod 755 "$BUILD/spk/scripts/"* "$BUILD/payload/bin/"* "$BUILD/payload/ui/index.cgi"
(
  cd "$BUILD/payload"
  tar --format=ustar --owner=0 --group=0 --numeric-owner -czf "$BUILD/spk/package.tgz" bin ui share
)
(
  cd "$BUILD/spk"
  tar --format=ustar --owner=0 --group=0 --numeric-owner -cf "$DIST/SadlerACME-$VERSION.spk" INFO package.tgz scripts conf PACKAGE_ICON.PNG PACKAGE_ICON_256.PNG
)
printf '%s\n' "$DIST/SadlerACME-$VERSION.spk"
