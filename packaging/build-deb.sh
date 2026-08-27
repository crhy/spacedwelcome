#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
version=$(tr -d '[:space:]' < "$root/VERSION")
case "$version" in
    [0-9]*.[0-9]*.[0-9]*) ;;
    *) echo "Invalid VERSION: $version" >&2; exit 1 ;;
esac

output_dir=${SPACED_WELCOME_OUTPUT_DIR:-$root/dist}
artifact="$output_dir/spaced-welcome_${version}_all.deb"
stage=$(mktemp -d "${TMPDIR:-/tmp}/spaced-welcome-deb.XXXXXXXX")
cleanup() {
    rm -rf -- "$stage"
}
trap cleanup EXIT HUP INT TERM

install -d -m 0755 \
    "$stage/DEBIAN" \
    "$stage/etc/xdg/autostart" \
    "$stage/usr/bin" \
    "$stage/usr/lib/python3/dist-packages/spaced_welcome" \
    "$stage/usr/share/applications" \
    "$stage/usr/share/doc/spaced-welcome" \
    "$stage/usr/share/icons/hicolor/scalable/apps" \
    "$stage/usr/share/metainfo" \
    "$stage/usr/share/spaced-welcome"

sed "s/@VERSION@/$version/g" \
    "$root/packaging/debian/control.in" > "$stage/DEBIAN/control"
install -m 0755 "$root/packaging/debian/postinst" "$stage/DEBIAN/postinst"
install -m 0755 "$root/packaging/debian/prerm" "$stage/DEBIAN/prerm"
install -m 0755 "$root/bin/spaced-welcome" "$stage/usr/bin/spaced-welcome"
install -m 0755 "$root/bin/spaced-welcome-install" "$stage/usr/bin/spaced-welcome-install"
install -m 0644 "$root"/src/spaced_welcome/*.py \
    "$stage/usr/lib/python3/dist-packages/spaced_welcome/"
install -m 0644 "$root/data/catalog.json" "$stage/usr/share/spaced-welcome/catalog.json"
install -m 0644 "$root/data/spaced-welcome.desktop" \
    "$stage/usr/share/applications/spaced-welcome.desktop"
install -m 0644 "$root/data/spaced-welcome-autostart.desktop" \
    "$stage/etc/xdg/autostart/spaced-welcome.desktop"
install -m 0644 "$root/data/io.github.crhy.SpacedWelcome.metainfo.xml" \
    "$stage/usr/share/metainfo/io.github.crhy.SpacedWelcome.metainfo.xml"
install -m 0644 "$root/data/icons/hicolor/scalable/apps/io.github.crhy.SpacedBazaar.svg" \
    "$stage/usr/share/icons/hicolor/scalable/apps/io.github.crhy.SpacedBazaar.svg"
for size in 48 64 128 256 512; do
    install -Dm644 \
        "$root/data/icons/hicolor/${size}x${size}/apps/io.github.crhy.SpacedWelcome.png" \
        "$stage/usr/share/icons/hicolor/${size}x${size}/apps/io.github.crhy.SpacedWelcome.png"
done
install -m 0644 "$root/packaging/debian/copyright" \
    "$stage/usr/share/doc/spaced-welcome/copyright"
install -m 0644 "$root/README.md" "$stage/usr/share/doc/spaced-welcome/README.md"

find "$stage" -type d -exec chmod 0755 {} +
find "$stage" -type f ! -path "$stage/DEBIAN/postinst" \
    ! -path "$stage/DEBIAN/prerm" ! -path "$stage/usr/bin/spaced-welcome" \
    ! -path "$stage/usr/bin/spaced-welcome-install" -exec chmod 0644 {} +

mkdir -p "$output_dir"
rm -f -- "$artifact"
dpkg-deb --root-owner-group --build "$stage" "$artifact"
printf '%s\n' "$artifact"
