<#
  Gera o executável e os pacotes de distribuição.
  Uso:  powershell -ExecutionPolicy Bypass -File scripts\compilar.ps1 [-PularTestes]

  Resultado em dist\:
    ShiftMacro\ShiftMacro.exe        aplicativo (pasta completa)
    ShiftMacro-1.0.0-win64.zip       a pasta acima + exemplos + instalador, compactados
    ShiftMacro-1.0.0-setup.exe       instalador (só se o Inno Setup 6 estiver instalado)
#>
param([switch]$PularTestes)
# "Continue": o PyInstaller escreve INFO na saída de erro; o resultado é conferido pelo código de saída
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Rode antes scripts\instalar-dependencias.ps1" -ForegroundColor Red; exit 1 }
$version = (& $py -c "import shiftmacro; print(shiftmacro.__version__)").Trim()

if (-not $PularTestes) {
    Write-Host "Rodando os testes..."
    & $py -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { Write-Host "Testes falharam; executável não gerado." -ForegroundColor Red; exit 1 }
}

Write-Host "Gerando ícone e exemplos..."
& $py tools\make_icon.py
& $py tools\make_examples.py

Write-Host "Compilando com PyInstaller..."
& $py -m PyInstaller ShiftMacro.spec --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller falhou." -ForegroundColor Red; exit 1 }

$app = Join-Path $root "dist\ShiftMacro"
Copy-Item -Recurse -Force examples (Join-Path $app "Exemplos")
Copy-Item -Force installer\instalar.ps1, installer\desinstalar.ps1 $app
Copy-Item -Force README.md (Join-Path $app "LEIA-ME.md")

$zip = Join-Path $root "dist\ShiftMacro-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip
# o atualizador do app só instala o pacote se o hash bater com este arquivo
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$zip.sha256", "$hash  $(Split-Path $zip -Leaf)`n", (New-Object Text.UTF8Encoding($false)))
Write-Host "Pacote: $zip"
Write-Host "SHA-256: $hash"

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DAppVersion=$version" installer\ShiftMacro.iss
    if ($LASTEXITCODE -eq 0) { Write-Host "Instalador: dist\ShiftMacro-$version-setup.exe" }
} else {
    Write-Host "Inno Setup 6 não encontrado: setup.exe não gerado. O zip já inclui instalar.ps1." -ForegroundColor Yellow
}
Write-Host "Concluído: $app\ShiftMacro.exe" -ForegroundColor Green
