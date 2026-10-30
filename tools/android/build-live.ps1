param()
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$sdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk'
$cmake = Join-Path $sdk 'cmake/3.22.1/bin/cmake.exe'
$ninja = Join-Path $sdk 'cmake/3.22.1/bin/ninja.exe'
$build = Join-Path $repo 'tools/android/.cache/native-live-arm64'
$ort = Join-Path $repo 'tools/android/.cache/live-deps/onnxruntime-android-1.23.2.aar'
if (-not (Test-Path -LiteralPath $ort)) {
    New-Item -ItemType Directory -Force (Split-Path $ort) | Out-Null
    Invoke-WebRequest -Uri 'https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/1.23.2/onnxruntime-android-1.23.2.aar' -OutFile $ort
}
if ((Get-FileHash -LiteralPath $ort -Algorithm SHA256).Hash -ne '82048D1F462218ADAE4BA76477089AB0BA76093D84F733540066DB1A8BA6B827') {
    throw 'Official ONNX Runtime AAR checksum differs; retained for inspection.'
}
# This is an Android cross build. Never configure a native host test/helper target.
& $cmake -S (Join-Path $repo 'android/app/src/main/cpp') -B $build -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$ninja" "-DCMAKE_TOOLCHAIN_FILE=$sdk/ndk/28.2.13676358/build/cmake/android.toolchain.cmake" `
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-30 -DANDROID_STL=c++_shared -DCMAKE_BUILD_TYPE=RelWithDebInfo
if ($LASTEXITCODE -ne 0) { throw 'Android native configuration failed.' }
& $cmake --build $build --target openpilot_ipc --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Android ARM64 capture build failed.' }
Copy-Item -LiteralPath (Join-Path $build 'libopenpilot_ipc.so') -Destination (Join-Path $repo 'android/app/src/main/jniLibs/arm64-v8a/libopenpilot_ipc.so')
Push-Location $repo
try {
    python tools/android/stage_live.py
    if ($LASTEXITCODE -ne 0) { throw 'Live asset staging failed.' }
    wsl -d Ubuntu-24.04 -- bash tools/android/build-wsl.sh -PwithModel -PprebuiltNative -PliveShadow --offline :app:assembleDebug :app:assembleDebugAndroidTest
    if ($LASTEXITCODE -ne 0) { throw 'Live APK build failed.' }
} finally { Pop-Location }
