param([Parameter(Mandatory=$true)][string]$Serial, [string]$TestClass = '')
$ErrorActionPreference = 'Stop'
if ($Serial -notmatch '^[A-Za-z0-9_-]+$' -or $Serial.StartsWith('emulator-')) { throw 'Select a physical Fold 3 serial explicitly.' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$adb = Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe'
$model = ((& $adb -s $Serial shell getprop ro.product.model) -join '').Trim()
if ($LASTEXITCODE -ne 0 -or $model -notlike 'SM-F926*') { throw "Selected device is not an authorized Fold 3: $model" }
$abi = ((& $adb -s $Serial shell getprop ro.product.cpu.abi) -join '').Trim()
if ($abi -ne 'arm64-v8a') { throw "Unexpected physical-device ABI: $abi" }
$initialState = ((& $adb -s $Serial shell cmd device_state print-state) -join '').Trim()
if ($initialState -ne '0') { throw 'This phone test requires the Fold 3 to remain closed.' }
$initialSize = ((& $adb -s $Serial shell wm size) -join "`n").Trim()
$application = Join-Path $repo 'android\app\build\outputs\apk\debug\app-arm64-v8a-debug.apk'
$tests = Join-Path $repo 'android\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk'
$output = Join-Path $PSScriptRoot '.cache\fold3'
New-Item -ItemType Directory -Path $output -Force | Out-Null
& $adb -s $Serial install -r $application
if ($LASTEXITCODE -ne 0) { throw 'ARM64 application installation failed.' }
& $adb -s $Serial install -r $tests
if ($LASTEXITCODE -ne 0) { throw 'Instrumentation APK installation failed.' }
$arguments = @('-s', $Serial, 'shell', 'am', 'instrument', '-w')
if ($TestClass) { $arguments += @('-e', 'class', $TestClass) }
$arguments += 'ai.comma.openpilot.sim.test/androidx.test.runner.AndroidJUnitRunner'
$report = Join-Path $output 'phone-tests.txt'
$instrumentation = Start-Process -FilePath $adb -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $report -RedirectStandardError (Join-Path $output 'instrument-stderr.txt')
$deadline = [DateTime]::UtcNow.AddMinutes(45)
while (-not $instrumentation.HasExited) {
    if ([DateTime]::UtcNow -ge $deadline) {
        Stop-Process -Id $instrumentation.Id
        & $adb -s $Serial shell am force-stop ai.comma.openpilot.sim
        throw 'Physical-phone instrumentation exceeded its 45-minute overall limit.'
    }
    Start-Sleep -Milliseconds 500
}
$result = Get-Content -LiteralPath $report -Raw
Write-Output (($result -split "`n" | Where-Object { $_ -match '^ai\.comma|^Error in|^Time:|^OK \(|^FAILURES|^Tests run:' }) -join "`n")
if ($instrumentation.ExitCode -ne 0 -or $result -notmatch 'OK \([0-9]+ tests?\)' -or $result -match 'FAILURES|INSTRUMENTATION_FAILED|Process crashed') {
    throw 'Physical-phone instrumentation failed; see .cache/fold3/phone-tests.txt.'
}
$finalState = ((& $adb -s $Serial shell cmd device_state print-state) -join '').Trim()
$finalSize = ((& $adb -s $Serial shell wm size) -join "`n").Trim()
if ($finalState -ne $initialState -or $finalSize -ne $initialSize) { throw 'Phone display state changed during the folded-only test.' }
