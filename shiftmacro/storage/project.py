"""Arquivos .shiftmacro: um ZIP com macro.json e as imagens em images/*.png."""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

from ..core.model import FORMAT_VERSION, Macro

EXTENSION = ".shiftmacro"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = 50 * 1024 * 1024


class ProjectError(Exception):
    pass


def save_macro(macro: Macro, path: Path | str) -> Path:
    """Salva de forma atômica (arquivo temporário + troca), sem corromper o
    original se faltar energia no meio."""
    path = Path(path)
    if path.suffix.lower() != EXTENSION:
        path = path.with_suffix(EXTENSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    used = macro.used_images()
    fd, tmp = tempfile.mkstemp(prefix=".salvando-", suffix=EXTENSION, dir=str(path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            data = macro.to_dict()
            # imagens não usadas por nenhuma etapa também são guardadas (podem
            # estar numa etapa desativada ou ser reaproveitadas depois)
            data["images"] = sorted(macro.images)
            data["unused_images"] = sorted(set(macro.images) - used)
            z.writestr("macro.json", json.dumps(data, ensure_ascii=False, indent=1))
            for name, png in macro.images.items():
                z.writestr(f"images/{name}.png", png, compress_type=zipfile.ZIP_STORED)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def load_macro(path: Path | str) -> Macro:
    path = Path(path)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        # aceita também um .json solto (exportação simples)
        if path.suffix.lower() == ".json":
            return Macro.from_dict(json.loads(path.read_text(encoding="utf-8")))
        raise ProjectError(f"{path.name} não é um arquivo de macro válido.") from e
    with z:
        try:
            info = z.getinfo("macro.json")
        except KeyError as e:
            raise ProjectError(f"{path.name} não contém macro.json.") from e
        if info.file_size > MAX_JSON_BYTES:
            raise ProjectError("macro.json grande demais.")
        try:
            data = json.loads(z.read(info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ProjectError(f"macro.json corrompido: {e}") from e
        if data.get("format") not in (None, "shiftmacro"):
            raise ProjectError("Formato de arquivo desconhecido.")
        if int(data.get("version") or 1) > FORMAT_VERSION:
            raise ProjectError("Esta macro foi criada por uma versão mais nova do Shift Macro.")
        images: dict[str, bytes] = {}
        for item in z.infolist():
            n = item.filename
            if not n.startswith("images/") or not n.lower().endswith(".png") or item.is_dir():
                continue
            name = n[len("images/"):-4]
            if "/" in name or ".." in name or not name:
                continue  # nunca seguir caminhos dentro do zip
            if item.file_size > MAX_IMAGE_BYTES:
                raise ProjectError(f"Imagem {name} grande demais.")
            images[name] = z.read(item)
    return Macro.from_dict(data, images)
