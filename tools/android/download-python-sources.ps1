$ErrorActionPreference = 'Stop'
foreach ($package in @(@{Name='numpy';Version='2.5.3'}, @{Name='pycapnp';Version='2.1.0'},
    @{Name='cffi';Version='2.1.1'}, @{Name='setproctitle';Version='1.3.7'}, @{Name='zstandard';Version='0.25.0'},
    @{Name='pycryptodome';Version='3.23.0'})) {
    $name = $package.Name
    $version = $package.Version
    $metadata = Invoke-RestMethod "https://pypi.org/pypi/$name/$version/json"
    $source = $metadata.urls | Where-Object {$_.packagetype -eq 'sdist'} | Select-Object -First 1
    if (-not $source) { throw "Missing source release for $name $version" }
    $directory = Join-Path $PSScriptRoot "recipes\$name\build\$version"
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $destination = Join-Path $directory $source.filename
    if ((Test-Path $destination) -and ((Get-FileHash $destination -Algorithm SHA256).Hash.ToLowerInvariant() -eq $source.digests.sha256)) { continue }
    $partial = $destination + '.download'
    Invoke-WebRequest $source.url -OutFile $partial
    if ((Get-FileHash $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $source.digests.sha256) { throw "Source checksum failed: $name" }
    Move-Item -LiteralPath $partial -Destination $destination -Force
    Write-Output "Verified $name $version source archive"
}
