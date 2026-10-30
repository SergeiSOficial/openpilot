param([string[]]$Abis = @('x86_64', 'arm64-v8a'))
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$sdk = $env:ANDROID_HOME
if (-not $sdk) { throw 'ANDROID_HOME is required.' }
$cmake = Join-Path $sdk 'cmake\3.22.1\bin\cmake.exe'
foreach ($abi in $Abis) {
    if ($abi -notin @('x86_64', 'arm64-v8a')) { throw "Unsupported ABI: $abi" }
    $build = Join-Path $PSScriptRoot ".cache\native-$abi"
    & $cmake -S (Join-Path $repo 'android\app\src\main\cpp') -B $build -G Ninja `
        "-DCMAKE_TOOLCHAIN_FILE=$sdk\ndk\28.2.13676358\build\cmake\android.toolchain.cmake" `
        "-DANDROID_ABI=$abi" '-DANDROID_PLATFORM=android-30' `
        "-DCMAKE_MAKE_PROGRAM=$sdk\cmake\3.22.1\bin\ninja.exe"
    if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed: $abi" }
    & $cmake --build $build -j 4
    if ($LASTEXITCODE -ne 0) { throw "Native compilation failed: $abi" }
    $destination = Join-Path $repo "android\app\src\main\jniLibs\$abi"
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Copy-Item -LiteralPath (Join-Path $build 'libopenpilot_ipc.so') -Destination $destination
    if (Test-Path (Join-Path $build 'libparams_c.so')) {
        Copy-Item -LiteralPath (Join-Path $build 'libparams_c.so') -Destination $destination
    }
    foreach ($model in @('pose', 'car', 'acados_ocp_solver_long', 'acados_ocp_solver_pyx')) {
        if (Test-Path (Join-Path $build "lib$model.so")) {
            Copy-Item -LiteralPath (Join-Path $build "lib$model.so") -Destination $destination
        }
    }
    if (Test-Path (Join-Path $build 'libopenpilot_kernels.so')) {
        Copy-Item -LiteralPath (Join-Path $build 'libopenpilot_kernels.so') -Destination $destination
    }
    $stl = Join-Path $sdk 'ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\sysroot\usr\lib'
    $triple = if ($abi -eq 'x86_64') { 'x86_64-linux-android' } else { 'aarch64-linux-android' }
    Copy-Item -LiteralPath (Join-Path $stl "$triple\libc++_shared.so") -Destination $destination
}
