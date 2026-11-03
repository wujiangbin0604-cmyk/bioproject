param([ValidateRange(1024,65535)][int]$Port=5173,[ValidateRange(1024,65535)][int]$ApiPort=8000)
$ErrorActionPreference='Stop'
$previousApi=$env:GENESCOPE_API_URL
Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
try {
    $env:GENESCOPE_API_URL="http://127.0.0.1:$ApiPort"
    & npm run dev -- --port $Port --strictPort
    if ($LASTEXITCODE -ne 0) { throw '前端未正常启动，请检查依赖及端口。' }
}
finally { $env:GENESCOPE_API_URL=$previousApi; Pop-Location }
