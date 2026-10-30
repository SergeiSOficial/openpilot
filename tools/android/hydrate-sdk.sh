#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SDK="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}/sdk"
WINDOWS_SDK="${1:?Pass the mounted Windows Android SDK path}"
mkdir -p "$SDK/build-tools" "$SDK/platforms"
if [[ ! -d "$SDK/build-tools/36.0.0" ]]; then
  unzip -q "$ROOT/tools/android/.cache/build-tools_r36_linux.zip" -d "$SDK/build-tools/.unpack"
  mv "$SDK/build-tools/.unpack/android-16" "$SDK/build-tools/36.0.0"
fi
if [[ ! -d "$SDK/platforms/android-36" ]]; then
  cp -a "$WINDOWS_SDK/platforms/android-36" "$SDK/platforms/"
fi
if [[ ! -d "$SDK/licenses" ]]; then cp -a "$WINDOWS_SDK/licenses" "$SDK/"; fi
# Gradle distributions are portable. Reuse a complete existing download when available.
WINDOWS_USER="$(dirname "$(dirname "$(dirname "$(dirname "$WINDOWS_SDK")")")")"
GRADLE_DIST=.gradle/wrapper/dists/gradle-9.1.0-bin/9agqghryom9wkf8r80qlhnts3
if [[ -d "$WINDOWS_USER/$GRADLE_DIST/gradle-9.1.0" && ! -d "$HOME/$GRADLE_DIST/gradle-9.1.0" ]]; then
  mkdir -p "$HOME/$GRADLE_DIST"
  cp -a "$WINDOWS_USER/$GRADLE_DIST/gradle-9.1.0" "$HOME/$GRADLE_DIST/"
  touch "$HOME/$GRADLE_DIST/gradle-9.1.0-bin.zip.ok"
fi
echo "Linux Android SDK prepared at $SDK"
