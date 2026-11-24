"""Configurações do aplicativo, arquivos recentes e salvamento automático.

Tudo fica em %APPDATA%\\ShiftMacro (ou em SHIFTMACRO_HOME, usado nos testes).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.model import Macro
from .project import load_macro, save_macro

DEFAULT_HOTKEYS = {
    "run": "F6",
    "pause": "F7",
    "stop": "F8",
    "record": "F9",
    "capture": "Shift+F11",
}
HOTKEY_LABELS = {
    "run": "Iniciar execução",
    "pause": "Pausar ou continuar",
    "stop": "Parar imediatamente",
    "record": "Iniciar ou finalizar gravação",
    "capture": "Capturar imagem (Smart Click)",
}
MAX_RECENT = 10


def data_dir() -> Path:
    base = os.environ.get("SHIFTMACRO_HOME")
    if base:
        p = Path(base)
    else:
        p = Path(os.environ.get("APPDATA") or Path.home()) / "ShiftMacro"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class AppSettings:
    theme: str = "dark"  # dark | light
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    recent: list[str] = field(default_factory=list)
    autosave_seconds: int = 60
    failsafe: bool = False
    record_mode: str = "all"  # all | clicks | keyboard
    record_moves: bool = True  # gravar movimentos (no modo all)
    record_min_move_ms: int = 30
    record_delays: bool = True
    record_minimize: bool = True  # minimizar a janela ao começar a gravar
    follow_current: bool = True  # rolar a tabela até a etapa em execução
    auto_update: bool = True  # procurar versão nova ao abrir (consulta a API pública do GitHub)
    update_last_check: int = 0  # epoch da última consulta automática
    update_skip: str = ""  # versão que o usuário pediu para pular
    last_dir: str = ""
    geometry: str = ""
    window_state: str = ""
    log_max: int = 5000

    @classmethod
    def load(cls) -> "AppSettings":
        s = cls()
        f = data_dir() / "settings.json"
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return s
        for k, v in raw.items():
            if hasattr(s, k):
                cur = getattr(s, k)
                if isinstance(cur, dict) and isinstance(v, dict):
                    cur.update({str(a): str(b) for a, b in v.items()})
                elif isinstance(cur, list) and isinstance(v, list):
                    setattr(s, k, [str(x) for x in v])
                elif isinstance(cur, bool):
                    setattr(s, k, bool(v))
                elif isinstance(cur, int):
                    try:
                        setattr(s, k, int(v))
                    except (TypeError, ValueError):
                        pass
                else:
                    setattr(s, k, str(v))
        if s.theme not in ("dark", "light"):
            s.theme = "dark"
        return s

    def save(self) -> None:
        f = data_dir() / "settings.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, f)

    def add_recent(self, path: Path | str) -> None:
        p = str(Path(path).resolve())
        self.recent = [p] + [r for r in self.recent if os.path.normcase(r) != os.path.normcase(p)]
        del self.recent[MAX_RECENT:]

    def existing_recent(self) -> list[str]:
        return [r for r in self.recent if Path(r).is_file()]


class Autosave:
    """Guarda a macro aberta periodicamente. Se o app fechar sem salvar (queda,
    erro, desligamento), a próxima abertura oferece recuperar."""

    def __init__(self):
        self.dir = data_dir() / "autosave"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "recuperacao.shiftmacro"
        self.meta = self.dir / "sessao.json"

    def write(self, macro: Macro, original: str | None) -> None:
        save_macro(macro, self.file)
        self.meta.write_text(json.dumps({"original": original, "time": time.time(), "clean": False}), encoding="utf-8")

    def mark_clean(self) -> None:
        try:
            self.meta.unlink(missing_ok=True)
            self.file.unlink(missing_ok=True)
        except OSError:
            pass

    def pending(self) -> dict[str, Any] | None:
        """Dados da sessão anterior não encerrada, se houver."""
        if not self.file.is_file() or not self.meta.is_file():
            return None
        try:
            meta = json.loads(self.meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if meta.get("clean"):
            return None
        return meta

    def recover(self) -> Macro:
        return load_macro(self.file)
