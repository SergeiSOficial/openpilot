param([switch]$Launch)
$ErrorActionPreference = 'Stop'
$sdk = $env:ANDROID_HOME
if (-not $sdk) { throw 'ANDROID_HOME is required.' }
$name = 'Openpilot_Fold3_API36'
$avdmanager = Join-Path $sdk 'cmdline-tools\latest\bin\avdmanager.bat'
$emulator = Join-Path $sdk 'emulator\emulator.exe'
$names = & $emulator -list-avds
if ($LASTEXITCODE -ne 0) { throw 'Cannot list Android virtual devices.' }
if ($names -notcontains $name) {
    'no' | & $avdmanager create avd --name $name --package 'system-images;android-36;google_apis;x86_64' --device '7.6in Foldable'
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the dedicated foldable AVD.' }
}
$configuration = Join-Path $env:USERPROFILE ".android\avd\$name.avd\config.ini"
if (-not (Test-Path -LiteralPath $configuration)) { throw 'Dedicated AVD configuration was not found.' }
$settings = Get-Content -LiteralPath $configuration -Raw
$settings = [regex]::Replace($settings, '(?m)^hw\.ramSize\s*=.*$', 'hw.ramSize = 6144')
[IO.File]::WriteAllText($configuration, $settings, [Text.UTF8Encoding]::new($false))
if ($Launch) {
    $adb = Join-Path $sdk 'platform-tools\adb.exe'
    $state = & $adb -s emulator-5556 get-state 2>$null
    if ($LASTEXITCODE -eq 0 -and $state -eq 'device') {
        $activeName = & $adb -s emulator-5556 emu avd name
        if ($activeName -notcontains $name) { throw 'Port 5556 belongs to a different AVD.' }
        Write-Output 'Dedicated foldable emulator is already running.'
    } else {
        Start-Process -FilePath $emulator -ArgumentList '-avd',$name,'-port','5556','-memory','6144','-cores','4',
            '-no-window','-no-audio','-no-snapshot' -WindowStyle Hidden -PassThru | Select-Object Id,ProcessName
    }
}
