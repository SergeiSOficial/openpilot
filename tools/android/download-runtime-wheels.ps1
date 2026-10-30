$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..\..')
try {
    py -3.12 tools\android\write_runtime_requirements.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not select locked runtime dependencies.' }
    py -3.12 -m pip download --timeout 120 --retries 3 --platform any --python-version 312 --implementation py `
        --abi none --only-binary=:all: -r tools\android\.cache\runtime-requirements.txt --dest tools\android\.cache\wheels
    if ($LASTEXITCODE -ne 0) { throw 'Runtime wheel download failed.' }
} finally { Pop-Location }
