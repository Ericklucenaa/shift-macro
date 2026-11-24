<#
  Instala o Shift Macro para o usuário atual (sem precisar de administrador).
  Rode a partir da pasta do aplicativo (a que contém ShiftMacro.exe):

    powershell -ExecutionPolicy Bypass -File instalar.ps1 [-AtalhoAreaDeTrabalho] [-Destino <pasta>]

  O que faz:
    - copia o aplicativo para %LOCALAPPDATA%\Programs\Shift Macro (ou -Destino);
    - cria atalho no Menu Iniciar (e na Área de Trabalho, se pedido);
    - associa arquivos .shiftmacro ao Shift Macro (duplo clique abre);
    - registra em Configurações > Aplicativos para desinstalar.
  Opções de teste: -SemAtalhos, -SemRegistro.
#>
param(
    [string]$Destino = (Join-Path $env:LOCALAPPDATA "Programs\Shift Macro"),
    [switch]$AtalhoAreaDeTrabalho,
    [switch]$SemAtalhos,
    [switch]$SemRegistro
)
$ErrorActionPreference = "Stop"
$origem = $PSScriptRoot
$exeOrigem = Join-Path $origem "ShiftMacro.exe"
if (-not (Test-Path $exeOrigem)) {
    Write-Host "ShiftMacro.exe não está nesta pasta. Rode o instalador de dentro da pasta do aplicativo." -ForegroundColor Red
    exit 1
}
$versao = (Get-Item $exeOrigem).VersionInfo.ProductVersion
if (-not $versao) { $versao = "1.0.0" }

$rodando = Get-Process -Name ShiftMacro -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Destino*" }
if ($rodando) {
    Write-Host "Feche o Shift Macro antes de instalar (está aberto a partir de $Destino)." -ForegroundColor Yellow
    exit 1
}

Write-Host "Instalando Shift Macro $versao em $Destino..."
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
if ((Resolve-Path $origem).Path -ne (Resolve-Path $Destino).Path) {
    # /MIR deixa o destino igual à origem (remove arquivos de versões antigas)
    robocopy $origem $Destino /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { Write-Host "Falha ao copiar os arquivos (robocopy $LASTEXITCODE)." -ForegroundColor Red; exit 1 }
}
$exe = Join-Path $Destino "ShiftMacro.exe"

if (-not $SemAtalhos) {
    $shell = New-Object -ComObject WScript.Shell
    $menu = Join-Path ([Environment]::GetFolderPath("Programs")) "Shift Macro.lnk"
    $lnk = $shell.CreateShortcut($menu)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $Destino
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = "Gravar, editar e executar macros"
    $lnk.Save()
    if ($AtalhoAreaDeTrabalho) {
        $desk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Shift Macro.lnk"
        $l2 = $shell.CreateShortcut($desk)
        $l2.TargetPath = $exe
        $l2.WorkingDirectory = $Destino
        $l2.IconLocation = "$exe,0"
        $l2.Save()
    }
}

if (-not $SemRegistro) {
    $cls = "HKCU:\Software\Classes"
    New-Item -Force "$cls\.shiftmacro" | Out-Null
    Set-ItemProperty "$cls\.shiftmacro" -Name "(default)" -Value "ShiftMacro.Macro"
    New-Item -Force "$cls\ShiftMacro.Macro\DefaultIcon" | Out-Null
    New-Item -Force "$cls\ShiftMacro.Macro\shell\open\command" | Out-Null
    Set-ItemProperty "$cls\ShiftMacro.Macro" -Name "(default)" -Value "Macro do Shift Macro"
    Set-ItemProperty "$cls\ShiftMacro.Macro\DefaultIcon" -Name "(default)" -Value "`"$exe`",0"
    Set-ItemProperty "$cls\ShiftMacro.Macro\shell\open\command" -Name "(default)" -Value "`"$exe`" `"%1`""

    $un = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ShiftMacro"
    New-Item -Force $un | Out-Null
    $tam = [int]((Get-ChildItem $Destino -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
    $props = @{
        DisplayName = "Shift Macro"; DisplayVersion = $versao; Publisher = "Shift"; InstallLocation = $Destino
        DisplayIcon = "$exe,0"; EstimatedSize = $tam; NoModify = 1; NoRepair = 1
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Destino\desinstalar.ps1`""
    }
    foreach ($k in $props.Keys) {
        $type = if ($props[$k] -is [int]) { "DWord" } else { "String" }
        New-ItemProperty -Path $un -Name $k -Value $props[$k] -PropertyType $type -Force | Out-Null
    }
    # avisa o Explorer sobre a nova associação de arquivo
    Add-Type -Namespace Win32 -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, uint f, IntPtr a, IntPtr b);' -ErrorAction SilentlyContinue
    [Win32.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
}

if ($SemAtalhos) {
    Write-Host "Instalado em $exe" -ForegroundColor Green
} else {
    Write-Host "Instalado. Abra pelo Menu Iniciar: Shift Macro." -ForegroundColor Green
}
