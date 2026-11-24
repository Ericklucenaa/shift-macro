<#
  Prepara o ambiente de desenvolvimento: cria .venv com Python 3.12 e instala as dependências.
  Uso:  powershell -ExecutionPolicy Bypass -File scripts\instalar-dependencias.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = @("py", "-3.12") }
}
if (-not $py -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $v = & python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
    if ($v -eq "3.12") { $py = @("python") }
}
if (-not $py) {
    Write-Host "Python 3.12 não encontrado. Instale em https://www.python.org/downloads/ e rode de novo." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Criando ambiente virtual (.venv)..."
    & $py[0] $py[1..9] -m venv .venv
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --quiet
Write-Host "Instalando dependências..."
& $venvPy -m pip install -r requirements-dev.txt --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar dependências." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Pronto. Para abrir:      .venv\Scripts\python.exe main.py" -ForegroundColor Green
Write-Host "Para testar:             .venv\Scripts\python.exe -m pytest"
Write-Host "Para gerar o executável: powershell -ExecutionPolicy Bypass -File scripts\compilar.ps1"
