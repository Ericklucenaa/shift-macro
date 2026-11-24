"""Atualização automática pelas releases públicas do GitHub.

Fluxo: consulta a última release -> compara versões -> baixa o zip do
aplicativo -> confere o SHA-256 publicado junto -> gera um script que espera o
Shift Macro fechar, troca os arquivos da pasta do aplicativo e o abre de novo.
Nada é enviado: só leitura da API pública do GitHub.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = "Ericklucenaa/shift-macro"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = "ShiftMacro-Updater"
ASSET_RE = re.compile(r"^ShiftMacro-(\d+\.\d+\.\d+)-win64\.zip$")
TIMEOUT = 15


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    url: str  # página da release
    asset_url: str
    asset_name: str
    asset_size: int
    sha256_url: str | None


def parse_version(v: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v or "")
    if not m:
        raise ValueError(f"versão inválida: {v}")
    return tuple(int(x) for x in m.groups())


def is_newer(remote: str, local: str) -> bool:
    try:
        return parse_version(remote) > parse_version(local)
    except ValueError:
        return False


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Nenhuma versão publicada ainda.") from e
        if e.code == 403:
            raise UpdateError("O GitHub limitou as consultas; tente de novo mais tarde.") from e
        raise UpdateError(f"O GitHub respondeu {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("Sem conexão com o GitHub.") from e


def parse_release(data: dict) -> Release:
    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") or []
    zip_asset = next((a for a in assets if ASSET_RE.match(str(a.get("name") or ""))), None)
    if zip_asset is None:
        raise UpdateError(f"A versão {tag} não tem o pacote para Windows.")
    sha = next((a for a in assets if str(a.get("name")) == f"{zip_asset['name']}.sha256"), None)
    return Release(
        version=ASSET_RE.match(zip_asset["name"]).group(1),
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        url=str(data.get("html_url") or RELEASES_PAGE),
        asset_url=str(zip_asset["browser_download_url"]),
        asset_name=str(zip_asset["name"]),
        asset_size=int(zip_asset.get("size") or 0),
        sha256_url=str(sha["browser_download_url"]) if sha else None,
    )


def latest_release(fetch: Callable[[str], bytes] = _get) -> Release:
    try:
        data = json.loads(fetch(API_LATEST).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise UpdateError("Resposta inválida do GitHub.") from e
    return parse_release(data)


def check(current: str, fetch: Callable[[str], bytes] = _get) -> Release | None:
    """A release mais nova que `current`, ou None se já está atualizado."""
    rel = latest_release(fetch)
    return rel if is_newer(rel.version, current) else None


def download(rel: Release, dest_dir: Path, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None, opener=urllib.request.urlopen,
             fetch: Callable[..., bytes] = _get) -> Path:
    """Baixa o zip, confere o SHA-256 (quando publicado) e devolve o caminho."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / rel.asset_name
    req = urllib.request.Request(rel.asset_url, headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256()
    try:
        with opener(req, timeout=TIMEOUT) as r, open(target, "wb") as f:
            total = int(r.headers.get("Content-Length") or rel.asset_size or 0)
            done = 0
            while True:
                if cancelled and cancelled():
                    raise UpdateError("Download cancelado.")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Falha no download: {e}") from e
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    if rel.sha256_url:
        raw = fetch(rel.sha256_url, accept="application/octet-stream").decode("ascii", "ignore").split()
        if not raw:
            target.unlink(missing_ok=True)
            raise UpdateError("A assinatura SHA-256 publicada está vazia.")
        expected = raw[0].lower()
        if h.hexdigest().lower() != expected:
            target.unlink(missing_ok=True)
            raise UpdateError("O arquivo baixado não confere com a assinatura SHA-256 publicada.")
    try:
        with zipfile.ZipFile(target) as z:
            names = z.namelist()
    except zipfile.BadZipFile as e:
        target.unlink(missing_ok=True)
        raise UpdateError("O pacote baixado está corrompido.") from e
    if not any(n.replace("\\", "/").endswith("ShiftMacro/ShiftMacro.exe") for n in names):
        target.unlink(missing_ok=True)
        raise UpdateError("O pacote baixado não contém o ShiftMacro.exe.")
    return target


def app_dir() -> Path | None:
    """Pasta do aplicativo, se estiver rodando como executável."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def updater_script(zip_path: Path, target_dir: Path, pid: int, exe_name: str = "ShiftMacro.exe",
                   relaunch: bool = True) -> str:
    """Script PowerShell que aplica a atualização depois que o app fecha."""
    z = str(zip_path).replace("'", "''")
    t = str(target_dir).replace("'", "''")
    log = str(zip_path.with_suffix(".log")).replace("'", "''")
    return f"""$ErrorActionPreference = 'Stop'
$log = '{log}'
function Log($m) {{ Add-Content -LiteralPath $log -Value ("{{0}} {{1}}" -f (Get-Date -Format s), $m) }}
try {{
  $p = Get-Process -Id {pid} -ErrorAction SilentlyContinue
  if ($p) {{ $p.WaitForExit(60000) | Out-Null }}
  Start-Sleep -Milliseconds 500
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ('shiftmacro-update-' + [guid]::NewGuid())
  Expand-Archive -LiteralPath '{z}' -DestinationPath $tmp -Force
  $src = Join-Path $tmp 'ShiftMacro'
  if (-not (Test-Path (Join-Path $src '{exe_name}'))) {{ throw 'pacote sem {exe_name}' }}
  robocopy $src '{t}' /MIR /NFL /NDL /NJH /NJS /NP /R:5 /W:1 | Out-Null
  if ($LASTEXITCODE -ge 8) {{ throw "robocopy $LASTEXITCODE" }}
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath '{z}' -Force -ErrorAction SilentlyContinue
  Log 'atualizado'
}} catch {{
  Log ("falhou: " + $_)
}}
{"Start-Process -FilePath (Join-Path '" + t + "' '" + exe_name + "')" if relaunch else ""}
"""


def apply_update(zip_path: Path, target_dir: Path | None = None) -> None:
    """Dispara o script de troca e retorna; o chamador deve fechar o app em seguida."""
    target = target_dir or app_dir()
    if target is None:
        raise UpdateError("A atualização automática só funciona no executável (ShiftMacro.exe).")
    script = Path(tempfile.gettempdir()) / "shiftmacro-atualizar.ps1"
    # BOM: o PowerShell 5.1 lê scripts sem BOM como ANSI (quebra caminhos com acento)
    script.write_text(updater_script(zip_path, target, os.getpid()), encoding="utf-8-sig")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
        creationflags=flags, close_fds=True,
    )
