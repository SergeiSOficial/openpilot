param([string]$Serial = 'emulator-5556', [string]$TestClass = '',
    [ValidateSet('ai.comma.openpilot.sim','ai.comma.openpilot.acceleration')]
    [string]$Package = 'ai.comma.openpilot.sim', [string]$ApkRoot = '')
$ErrorActionPreference = 'Stop'
if ($Serial -notmatch '^emulator-[0-9]+$') { throw 'This test script requires an Android emulator serial.' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$adb = Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe'
if (-not $ApkRoot) { $ApkRoot = Join-Path $repo 'android\app\build\outputs\apk' }
$application = Join-Path $ApkRoot 'debug\app-x86_64-debug.apk'
$tests = Join-Path $ApkRoot 'androidTest\debug\app-debug-androidTest.apk'
$report = Join-Path $PSScriptRoot '.cache\emulator-tests.txt'
$bootDeadline = [DateTime]::UtcNow.AddMinutes(2)
do {
    $boot = & $adb -s $Serial shell getprop sys.boot_completed 2>$null
    if ($LASTEXITCODE -eq 0 -and ([string]$boot).Trim() -eq '1') { break }
    if ([DateTime]::UtcNow -ge $bootDeadline) { throw 'Dedicated emulator did not boot within two minutes.' }
    Start-Sleep -Milliseconds 500
} while ($true)
& $adb -s $Serial install -r $application
if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
& $adb -s $Serial install -r $tests
if ($LASTEXITCODE -ne 0) { throw 'Test installation failed.' }
$arguments = @('-s', $Serial, 'shell', 'am', 'instrument', '-w')
if ($TestClass) { $arguments += @('-e', 'class', $TestClass) }
$arguments += "${Package}.test/androidx.test.runner.AndroidJUnitRunner"
$errors = Join-Path $PSScriptRoot '.cache\instrument-stderr.txt'
& $adb -s $Serial shell run-as $Package rm -f files/fold-request.json
$instrumentation = Start-Process -FilePath $adb -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $report -RedirectStandardError $errors
$handled = @{}
$testDeadline = [DateTime]::UtcNow.AddMinutes(30)
$initialSize = & $adb -s $Serial shell wm size
$initialOverride = $null
if (($initialSize -join "`n") -match 'Override size: ([0-9]+x[0-9]+)') { $initialOverride = $Matches[1] }
try {
    while (-not $instrumentation.HasExited) {
        if ([DateTime]::UtcNow -ge $testDeadline) { throw 'Android emulator test exceeded thirty minutes.' }
        $requestText = & $adb -s $Serial shell run-as $Package cat files/fold-request.json 2>$null
        if ($LASTEXITCODE -eq 0) {
            try { $request = $requestText | ConvertFrom-Json } catch { $request = $null }
            if ($request -and $request.session -match '^[a-f0-9]{16}$' -and $request.phase -in @('fold', 'unfold')) {
                $key = "$($request.session)-$($request.phase)"
                if (-not $handled.ContainsKey($key)) {
                    & $adb -s $Serial emu $request.phase
                    if ($LASTEXITCODE -ne 0) { throw 'Emulator console fold command failed.' }
                    if ($request.phase -eq 'fold') {
                        $area = & $adb -s $Serial shell wm folded-area
                        if (($area -join '') -notmatch 'Folded area: ([0-9]+),([0-9]+),([0-9]+),([0-9]+)') { throw 'Folded viewport is not configured.' }
                        $foldWidth = [int]$Matches[3] - [int]$Matches[1]
                        $foldHeight = [int]$Matches[4] - [int]$Matches[2]
                        if ($foldWidth -le 0 -or $foldHeight -le 0) { throw 'Invalid folded viewport.' }
                        # This API 36 image reports CLOSED=1 but config_foldedDeviceStates=0,
                        # so the legacy fold profile needs an explicit viewport transition.
                        & $adb -s $Serial shell wm size "${foldWidth}x${foldHeight}"
                        if ($LASTEXITCODE -ne 0) { throw 'Cannot apply the folded test viewport.' }
                        & $adb -s $Serial shell run-as $Package touch "files/fold-viewport-workaround-$($request.session)"
                    } else {
                        $restoreSize = if ($initialOverride) { $initialOverride } else { 'reset' }
                        & $adb -s $Serial shell wm size $restoreSize
                    }
                    & $adb -s $Serial shell run-as $Package touch "files/fold-ack-$key"
                    if ($LASTEXITCODE -ne 0) { throw 'Cannot acknowledge fold command.' }
                    $handled[$key] = $true
                }
            }
        }
        Start-Sleep -Milliseconds 200
        $instrumentation.Refresh()
    }
} finally {
    $instrumentation.Refresh()
    if (-not $instrumentation.HasExited) {
        & $adb -s $Serial shell am force-stop $Package | Out-Null
        Stop-Process -Id $instrumentation.Id -ErrorAction SilentlyContinue
    }
    & $adb -s $Serial emu unfold | Out-Null
    $restoreSize = if ($initialOverride) { $initialOverride } else { 'reset' }
    & $adb -s $Serial shell wm size $restoreSize | Out-Null
}
$result = Get-Content -LiteralPath $report -Raw
Write-Output (($result -split "`n" | Where-Object { $_ -match '^ai\.comma|^Error in|^Time:|^OK \(|^FAILURES|^Tests run:' }) -join "`n")
# am instrument can return exit code zero even when JUnit failed.
if ($instrumentation.ExitCode -ne 0 -or $result -notmatch 'OK \([0-9]+ tests?\)' -or $result -match 'FAILURES|INSTRUMENTATION_FAILED|Process crashed') {
    & $adb -s $Serial logcat -d -b crash -t 150 > (Join-Path $PSScriptRoot '.cache\emulator-crash.txt')
    throw "Android instrumentation did not pass. See $report"
}
if (-not $TestClass) {
    Copy-Item -LiteralPath $report -Destination (Join-Path $PSScriptRoot '.cache\final-suite-tests.txt')
}
