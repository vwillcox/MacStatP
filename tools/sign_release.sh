#!/usr/bin/env bash
# Sign, notarise and staple a release disk image.
#
# Needs a paid Apple Developer account: a "Developer ID Application"
# certificate is the only identity Gatekeeper accepts for an app
# distributed outside the App Store. Without it, users have to
# right-click > Open the first time.
#
# One-time setup
# --------------
#   1. Enrol at https://developer.apple.com/programs/  (yearly fee)
#   2. Xcode > Settings > Accounts > Manage Certificates > +
#      "Developer ID Application"   (or create it on developer.apple.com)
#   3. Make an app-specific password at https://appleid.apple.com
#      > Sign-In and Security > App-Specific Passwords
#   4. Store it once, so it is not in your shell history:
#
#      xcrun notarytool store-credentials macstatp \
#        --apple-id you@example.com --team-id ABCDE12345 \
#        --password xxxx-xxxx-xxxx-xxxx
#
# Then
# ----
#   security find-identity -v -p codesigning     # copy the full name
#   IDENTITY="Developer ID Application: Your Name (ABCDE12345)" \
#     tools/sign_release.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PROFILE="${NOTARY_PROFILE:-macstatp}"

if [[ -z "${IDENTITY:-}" ]]; then
  echo "Set IDENTITY to your Developer ID. Available identities:" >&2
  security find-identity -v -p codesigning >&2 || true
  exit 1
fi

"$HERE/build_app.sh"

sign_app() {
  local app="$1"
  echo "signing $(basename "$app")"
  # Sign the executable first, then the bundle. --deep is deprecated and
  # gets nested code wrong; these bundles have no frameworks, so the
  # main binary plus the wrapper is the whole story.
  codesign --force --options runtime --timestamp \
    --sign "$IDENTITY" "$app/Contents/MacOS/"* 
  codesign --force --options runtime --timestamp \
    --sign "$IDENTITY" "$app"
  codesign --verify --strict --verbose=2 "$app"
}

sign_app "$ROOT/build/MacStatP.app"
sign_app "$ROOT/build/MacStatP Control.app"

echo "building the disk image"
SKIP_BUILD=1 "$HERE/make_dmg.sh"
DMG="$(ls -t "$ROOT"/build/MacStatP-*.dmg | head -1)"

echo "signing $DMG"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

echo "submitting to Apple for notarisation (this usually takes a minute)"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait

echo "stapling the ticket so it works offline"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo
echo "checking it the way Gatekeeper will"
spctl -a -t open --context context:primary-signature -v "$DMG"
echo
echo "done: $DMG"
echo "Anyone can now open this without the right-click dance."
