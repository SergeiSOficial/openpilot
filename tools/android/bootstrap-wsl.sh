#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == --install-system-deps ]]; then
  [[ "$(id -u)" == 0 ]] || { echo 'System dependency installation requires root.' >&2; exit 1; }
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openjdk-17-jdk-headless ninja-build cmake clang llvm-dev \
    libffi-dev libssl-dev pkg-config patch patchelf unzip zip curl build-essential rsync python3.12-venv
  exit
fi

TASK_CACHE="${OPENPILOT_ANDROID_CACHE:-$HOME/.cache/openpilot-android}"
SDK="$TASK_CACHE/sdk"
mkdir -p "$TASK_CACHE"
for command in java javac ninja cmake clang llvm-config patchelf unzip curl; do
  command -v "$command" >/dev/null || { echo "Missing $command. Run --install-system-deps as root first." >&2; exit 1; }
done
if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  archive="$TASK_CACHE/commandlinetools-linux-16111833_latest.zip"
  curl -fL --retry 3 -o "$archive" https://dl.google.com/android/repository/commandlinetools-linux-16111833_latest.zip
  echo "e025545c62a8e64c7559119566a569fb1dec5f60  $archive" | sha1sum -c -
  mkdir -p "$SDK/cmdline-tools"
  unzip -q -o "$archive" -d "$TASK_CACHE/cmdline-unpack"
  mv "$TASK_CACHE/cmdline-unpack/cmdline-tools" "$SDK/cmdline-tools/latest"
fi
# The caller requested the Android development tools. Keep acceptance and installs within this SDK.
(yes || true) | "$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" --licenses >/dev/null
"$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" \
  'platform-tools' 'platforms;android-36' 'build-tools;36.0.0' 'ndk;28.2.13676358' 'cmake;3.22.1'
printf 'Android SDK ready: %s\n' "$SDK"
