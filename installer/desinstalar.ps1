<#
  Remove o Shift Macro instalado por instalar.ps1.
  Suas macros (.shiftmacro) não são tocadas. Configurações e recuperação automática
  ficam em %APPDATA%\ShiftMacro; use -RemoverDados para apagá-las também.
#>
param([switch]$RemoverDados, [switch]$Silencioso)
$ErrorActionPreference = "Continue"
$pasta = $PSScriptRoot

if (-not $Silencioso) {
    Add-Type -AssemblyName System.Windows.Forms
    $r = [System.Windows.Forms.MessageBox]::Show("Remover o Shift Macro deste computador?`n`nSuas macros salvas não serão apagadas.", "Shift Macro", "YesNo", "Question")
    if ($r -ne "Yes") { exit 0 }
}

Get-Process -Name ShiftMacro -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$pasta*" } | Stop-Process -Force

foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Programs")) "Shift Macro.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Desktop")) "Shift Macro.lnk"))) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}
$cls = "HKCU:\Software\Classes"
if ((Get-ItemProperty "$cls\.shiftmacro" -ErrorAction SilentlyContinue)."(default)" -eq "ShiftMacro.Macro") {
    Remove-Item "$cls\.shiftmacro" -Recurse -Force
}
Remove-Item "$cls\ShiftMacro.Macro" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ShiftMacro" -Recurse -Force -ErrorAction SilentlyContinue
if ($RemoverDados) { Remove-Item (Join-Path $env:APPDATA "ShiftMacro") -Recurse -Force -ErrorAction SilentlyContinue }

# a pasta contém este script: apaga depois que o PowerShell terminar
if ($pasta -like "*Shift Macro*" -and (Test-Path (Join-Path $pasta "ShiftMacro.exe"))) {
    Start-Process cmd.exe -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$pasta`"" -WindowStyle Hidden
}
if (-not $Silencioso) {
    [System.Windows.Forms.MessageBox]::Show("Shift Macro removido.", "Shift Macro") | Out-Null
}
