param(
    [string]$PythonExe = '',
    [ValidateRange(1024, 65535)][int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$previousPythonUtf8 = $env:PYTHONUTF8
if (-not $PythonExe) {
    if ($env:GENESCOPE_PYTHON) { $PythonExe = $env:GENESCOPE_PYTHON }
    else {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
        if (Test-Path -LiteralPath $candidate) { $PythonExe = $candidate }
        else { $PythonExe = 'python' }
    }
}
Push-Location -LiteralPath $projectDirectory
try {
    $webVendor = Join-Path $projectDirectory 'backend\.vendor314'
    if (Test-Path -LiteralPath $webVendor) {
        $env:PYTHONPATH = $webVendor + [IO.Path]::PathSeparator + $env:PYTHONPATH
    }
    $env:PYTHONUTF8 = '1'
    & $PythonExe -c 'from deployment.lab_registry import check_environment; check_environment(); import fastapi, uvicorn, psutil; print("Frozen runtime and Web dependencies: OK")'
    if ($LASTEXITCODE -ne 0) { throw '环境检查失败。请按 LAB_GUIDE.md 安装冻结科学计算依赖及Web依赖；不会绕过版本检查。' }
    Write-Host "GeneScope API: http://127.0.0.1:$Port/docs"
    Write-Host '请保留此终端；现场实验采用单API worker，避免热重载中断任务。'
    & $PythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --workers 1
    if ($LASTEXITCODE -ne 0) { throw '后端未正常启动或已停止；检查上方日志（包括端口占用）。' }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONUTF8 = $previousPythonUtf8
    Pop-Location
}
