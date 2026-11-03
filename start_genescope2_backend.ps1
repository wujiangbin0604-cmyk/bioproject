param(
    [ValidateRange(1024,65535)][int]$Port=8000,
    [ValidateRange(1024,65535)][int]$FrontendPort=5173,
    [string]$PythonExe=''
)
$ErrorActionPreference='Stop'
$previousPythonPath=$env:PYTHONPATH
$previousOrigins=$env:GENESCOPE_ALLOWED_ORIGINS
$previousUtf8=$env:PYTHONUTF8
if (-not $PythonExe) {
    $candidate=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
    if (Test-Path -LiteralPath $candidate) { $PythonExe=$candidate } else { $PythonExe='python' }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    $version=& $PythonExe -c 'import sys; print(str(sys.version_info.major)+str(sys.version_info.minor))'
    $vendor=Join-Path $PSScriptRoot ('backend\.vendor'+$(if ($version -eq '314') {'314'} else {''}))
    if (Test-Path -LiteralPath $vendor) { $env:PYTHONPATH=$vendor+[IO.Path]::PathSeparator+$previousPythonPath }
    $env:PYTHONUTF8='1'
    if (-not $env:GENESCOPE_ALLOWED_ORIGINS) { $env:GENESCOPE_ALLOWED_ORIGINS="http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort" }
    & $PythonExe -c 'import fastapi, uvicorn, numpy, pandas, sklearn, psutil; print("GeneScope runtime: ready")'
    if ($LASTEXITCODE -ne 0) { throw '缺少后端依赖，请先安装 backend/requirements.txt。' }
    Write-Host "GeneScope 2.0 API: http://127.0.0.1:$Port/docs"
    Write-Host '后台工作进程由API自动启动；关闭服务会安全终止当前任务。'
    & $PythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --workers 1
    if ($LASTEXITCODE -ne 0) { throw 'API未正常启动，请检查端口是否被占用。' }
}
finally {
    $env:PYTHONPATH=$previousPythonPath
    $env:GENESCOPE_ALLOWED_ORIGINS=$previousOrigins
    $env:PYTHONUTF8=$previousUtf8
    Pop-Location
}
