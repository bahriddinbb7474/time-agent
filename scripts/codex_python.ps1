$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe"
$SitePackages = Join-Path $ProjectRoot ".venv\Lib\site-packages"
$SrcPath = Join-Path $ProjectRoot "src"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

$env:PYTHONPATH = "$SrcPath;$SitePackages"
& $PythonExe @args
exit $LASTEXITCODE
