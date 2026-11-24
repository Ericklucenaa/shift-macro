"""Atualização automática: versões, release, download verificado e troca de arquivos."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import zipfile

import pytest

from shiftmacro.utils import updater


def release_json(version="1.2.0", with_sha=True):
    assets = [{"name": f"ShiftMacro-{version}-win64.zip", "browser_download_url": "https://x/zip", "size": 10}]
    if with_sha:
        assets.append({"name": f"ShiftMacro-{version}-win64.zip.sha256", "browser_download_url": "https://x/sha"})
    assets.append({"name": "outra-coisa.txt", "browser_download_url": "https://x/txt"})
    return {"tag_name": f"v{version}", "body": "## Novidades\n- tudo", "html_url": "https://x/rel", "assets": assets}


def test_comparacao_de_versoes():
    assert updater.is_newer("1.0.1", "1.0.0")
    assert updater.is_newer("v2.0.0", "1.9.9")
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("0.9.0", "1.0.0")
    assert not updater.is_newer("lixo", "1.0.0")


def test_check_encontra_pacote_e_ignora_se_atual():
    fetch = lambda url: json.dumps(release_json("1.2.0")).encode()  # noqa: E731
    rel = updater.check("1.0.0", fetch)
    assert rel.version == "1.2.0" and rel.asset_url == "https://x/zip" and rel.sha256_url == "https://x/sha"
    assert "Novidades" in rel.notes
    assert updater.check("1.2.0", fetch) is None


def test_release_sem_pacote_windows():
    data = release_json()
    data["assets"] = [{"name": "fonte.zip", "browser_download_url": "x"}]
    with pytest.raises(updater.UpdateError):
        updater.check("1.0.0", lambda url: json.dumps(data).encode())


def _pkg(exe=b"novo") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ShiftMacro/ShiftMacro.exe", exe)
        z.writestr("ShiftMacro/_internal/lib.dll", b"lib")
    return buf.getvalue()


class FakeResp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_confere_sha256(tmp_path):
    data = _pkg()
    rel = updater.parse_release(release_json())
    good = hashlib.sha256(data).hexdigest().encode() + b"  ShiftMacro-1.2.0-win64.zip"
    seen = []
    p = updater.download(rel, tmp_path, progress=lambda d, t: seen.append((d, t)),
                         opener=lambda req, timeout: FakeResp(data), fetch=lambda url, accept="": good)
    assert p.read_bytes() == data
    assert seen[-1] == (len(data), len(data))


def test_download_adulterado_e_recusado(tmp_path):
    rel = updater.parse_release(release_json())
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download(rel, tmp_path, opener=lambda req, timeout: FakeResp(_pkg()), fetch=lambda url, accept="": b"0" * 64)
    assert not list(tmp_path.iterdir())  # nada fica para trás


def test_pacote_sem_executavel_e_recusado(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("leia.txt", b"x")
    rel = updater.parse_release(release_json(with_sha=False))
    with pytest.raises(updater.UpdateError, match="ShiftMacro.exe"):
        updater.download(rel, tmp_path, opener=lambda req, timeout: FakeResp(buf.getvalue()))


@pytest.mark.skipif(os.name != "nt", reason="script PowerShell")
def test_script_de_troca_aplica_atualizacao(tmp_path):
    app = tmp_path / "Shift Macro ação"  # espaço e acento no caminho
    app.mkdir()
    (app / "ShiftMacro.exe").write_bytes(b"velho")
    (app / "sobra-antiga.dll").write_bytes(b"x")
    z = tmp_path / "pkg.zip"
    z.write_bytes(_pkg(b"novo"))
    script = tmp_path / "s.ps1"
    script.write_text(updater.updater_script(z, app, pid=999999, relaunch=False), encoding="utf-8-sig")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "ignore")
    assert (app / "ShiftMacro.exe").read_bytes() == b"novo"
    assert (app / "_internal" / "lib.dll").exists()
    assert not (app / "sobra-antiga.dll").exists()  # versão antiga não deixa lixo
    assert not z.exists()
    assert "atualizado" in z.with_suffix(".log").read_text(encoding="utf-8", errors="ignore")
