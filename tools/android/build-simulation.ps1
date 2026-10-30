param([switch]$Bootstrap, [switch]$Test, [string]$Distribution = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$previousJavaHome = $env:JAVA_HOME
if (-not $env:JAVA_HOME -or -not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
    $taskJava = Get-ChildItem -LiteralPath 'C:\Program Files\Microsoft' -Directory -Filter 'jdk-17*' -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\java.exe') } |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $taskJava) { throw 'Install a Windows Java 17 JDK or set JAVA_HOME to its directory for APK signature verification.' }
    $env:JAVA_HOME = $taskJava.FullName
}
Push-Location $repo
try {
    function WslScript([string]$Script, [string[]]$Arguments = @()) {
        & wsl -d $Distribution -- bash "tools/android/$Script" @Arguments
        if ($LASTEXITCODE -ne 0) { throw "WSL step failed: $Script" }
    }
    function HostPython([string]$Script, [string[]]$Arguments = @()) {
        & wsl -d $Distribution -- bash tools/android/host-python.sh "tools/android/$Script" @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Host generation failed: $Script" }
    }
    function WindowsPython([string]$Script) {
        & py -3.12 "tools/android/$Script"
        if ($LASTEXITCODE -ne 0) { throw "Staging failed: $Script" }
    }
    if ($Bootstrap) {
        & wsl -d $Distribution -u root -- bash tools/android/bootstrap-wsl.sh --install-system-deps
        if ($LASTEXITCODE -ne 0) { throw 'WSL system prerequisites failed.' }
        WslScript 'bootstrap-wsl.sh'
        WslScript 'bootstrap-host.sh'
    }
    WindowsPython 'stage_msgq.py'
    HostPython 'prepare_native.py'
    WslScript 'build-host-params.sh'
    HostPython 'prepare_codegen.py'
    & tools/android/download-python-sources.ps1
    WslScript 'build-wheels.sh' @('chaquopy-libcxx', 'chaquopy-libffi', 'numpy', 'pycapnp', 'msgq', 'cffi', 'setproctitle', 'rednose', 'zstandard', 'pycryptodome')
    WslScript 'collect-wheels.sh'
    WindowsPython 'write_runtime_requirements.py'
    & tools/android/download-runtime-wheels.ps1
    HostPython 'prepare_mpc_extension.py'
    WslScript 'fetch-acados.sh'
    WslScript 'build-acados.sh'
    WslScript 'collect-acados.sh'
    WslScript 'build-host-reference.sh'
    HostPython 'capture_model_aot.py'
    HostPython 'capture_warp_aot.py'
    WindowsPython 'make_schema_patch.py'
    WindowsPython 'stage_model.py'
    WindowsPython 'stage_stack.py'
    WslScript 'run-reference.sh' @('--capture-kernels')
    HostPython 'capture_aot.py' @('--output', 'tools/android/.cache/model-aot/kernels')
    & tools/android/build-native.ps1
    WindowsPython 'stage_model.py'
    WindowsPython 'stage_stack.py'
    HostPython 'certify_model.py'
    HostPython 'prepare_fixture.py'
    HostPython 'prepare_log_fixture.py'
    HostPython 'prepare_fixture.py' @('--prepare')
    WslScript 'run-reference.sh'
    WindowsPython 'stage_fixture.py'
    WindowsPython 'validate_bundle.py'
    WslScript 'build-wsl.sh' @('-PwithModel', '-PprebuiltNative', ':app:assembleDebug', ':app:assembleDebugAndroidTest')
    $signer = Join-Path $env:ANDROID_HOME 'build-tools\36.0.0\apksigner.bat'
    foreach ($abi in @('x86_64', 'arm64-v8a')) {
        & $signer verify --verbose "android/app/build/outputs/apk/debug/app-$abi-debug.apk" *> "tools/android/.cache/signature-$abi.txt"
        if ($LASTEXITCODE -ne 0) { throw "APK signature verification failed: $abi" }
    }
    if ($Test) {
        & wsl -d $Distribution -- bash tools/android/host-python.sh -m unittest discover -s tools/android/tests -v *> tools/android/.cache/host-tests.txt
        if ($LASTEXITCODE -ne 0) { throw 'Host-side Android adapter tests failed.' }
        & tools/android/create-emulator.ps1 -Launch
        & tools/android/test-emulator.ps1
        $adb = Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe'
        $session = (& $adb -s emulator-5556 shell run-as ai.comma.openpilot.sim cat files/last-lifecycle-session.txt).Trim()
        & py -3.12 tools/android/collect_emulator.py --session $session
        if ($LASTEXITCODE -ne 0) { throw 'Emulator evidence collection failed.' }
        & py -3.12 tools/android/package_delivery.py --session $session
        if ($LASTEXITCODE -ne 0) { throw 'Simulation acceptance packaging failed.' }
    }
} finally { Pop-Location; $env:JAVA_HOME = $previousJavaHome }
