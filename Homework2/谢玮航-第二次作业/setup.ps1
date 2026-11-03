$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.uv-cache'

Push-Location $projectRoot
try {
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'uv sync 失败' }
    uv pip install --python $python geedim
    if ($LASTEXITCODE -ne 0) { throw 'geedim 安装失败' }
} finally {
    Pop-Location
}

& $python (Join-Path $PSScriptRoot 'hangzhou_ndvi.py') @args
if ($LASTEXITCODE -ne 0) { throw 'NDVI 分析失败' }
