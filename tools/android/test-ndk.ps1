param(
  [Parameter(Mandatory = $true)][string]$Serial,
  [string]$NdkVersion = '28.2.13676358'
)

$ErrorActionPreference = 'Stop'
if (-not $env:ANDROID_HOME) { throw 'Set ANDROID_HOME to the Android SDK directory.' }
$bin = Join-Path $env:ANDROID_HOME "ndk\$NdkVersion\toolchains\llvm\prebuilt\windows-x86_64\bin"
$adb = Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe'
$source = Join-Path $PSScriptRoot 'ndk-probe.c'
$temp = Join-Path ([IO.Path]::GetTempPath()) ("openpilot-ndk-" + [guid]::NewGuid().ToString('N'))
$remote = '/data/local/tmp/' + [IO.Path]::GetFileName($temp)
New-Item -ItemType Directory -Path $temp | Out-Null
try {
  foreach ($target in @('x86_64', 'aarch64')) {
    $compiler = Join-Path $bin "$target-linux-android26-clang.cmd"
    & $compiler $source -o (Join-Path $temp $target)
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed for $target." }
  }
  $abi = (& $adb -s $Serial shell getprop ro.product.cpu.abi).Trim()
  if ($LASTEXITCODE -ne 0) { throw 'Unable to query the selected device.' }
  $target = switch ($abi) { 'x86_64' { 'x86_64' } 'arm64-v8a' { 'aarch64' } default { throw "Unsupported device ABI: $abi" } }
  & $adb -s $Serial push (Join-Path $temp $target) $remote
  if ($LASTEXITCODE -ne 0) { throw 'ADB push failed.' }
  & $adb -s $Serial shell chmod 755 $remote
  if ($LASTEXITCODE -ne 0) { throw 'ADB chmod failed.' }
  & $adb -s $Serial shell $remote
  if ($LASTEXITCODE -ne 0) { throw 'Android NDK probe failed.' }
  Write-Host "Both targets compiled; probe ran on $Serial ($abi)."
} finally {
  & $adb -s $Serial shell rm -f $remote 2>$null | Out-Null
  Remove-Item -LiteralPath $temp -Recurse -Force
}
