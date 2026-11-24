"""Contexto de execução: estado compartilhado entre o motor e os comandos."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import expr


class StopRequested(Exception):
    """Parada pedida pelo usuário (F8, botão Parar ou comando Encerrar)."""


class MacroError(Exception):
    """Erro de execução com mensagem pronta para o usuário."""


@dataclass
class LogEntry:
    time: float
    level: str  # info | ok | warn | error
    message: str
    step: int | None = None  # índice da linha na tabela (0-based)
    command: str = ""
    similarity: float | None = None
    coords: tuple[int, int] | None = None
    elapsed_ms: float | None = None
    repetition: int | None = None


class RunContext:
    """Passado a cada comando. Toda espera passa por `sleep`, que respeita
    parada e pausa a cada 10 ms — é isso que garante a parada de emergência
    dentro de delays, loops e buscas infinitas."""

    TICK = 0.01

    def __init__(
        self,
        macro,
        inputs,
        vision,
        *,
        stop_event: threading.Event | None = None,
        run_event: threading.Event | None = None,
        speed: float = 1.0,
        log: Callable[[LogEntry], None] | None = None,
        notify: Callable[[str, str], None] | None = None,
        base_dir: Path | None = None,
        variables: dict[str, Any] | None = None,
    ):
        self.macro = macro
        self.inputs = inputs
        self.vision = vision
        self.stop_event = stop_event or threading.Event()
        self.run_event = run_event or threading.Event()  # set = rodando; clear = pausado
        self.run_event.set()
        self.speed = max(0.1, float(speed))
        self._log = log or (lambda e: None)
        self.notify = notify or (lambda title, msg: None)
        self.base_dir = base_dir
        self.vars: dict[str, Any] = dict(variables if variables is not None else macro.variables)
        self.step: int | None = None
        self.command_label = ""
        self.repetition = 1
        self.status = ""  # texto da coluna Status para a etapa atual
        self.last_similarity: float | None = None
        self.last_coords: tuple[int, int] | None = None
        self.depth = 0  # macros chamadas dentro de macros
        # teclas/botões pressionados por comandos e ainda não soltos: o motor
        # solta todos ao terminar ou ao parar, para nada ficar "preso"
        self.held_keys: set[str] = set()
        self.held_buttons: set[str] = set()

    def release_all(self) -> None:
        for k in list(self.held_keys):
            try:
                self.inputs.key_up(k)
            except Exception:
                pass
        for b in list(self.held_buttons):
            try:
                self.inputs.up(b)
            except Exception:
                pass
        self.held_keys.clear()
        self.held_buttons.clear()

    # ---------- controle ----------
    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def check(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested()
        if not self.run_event.is_set():
            while not self.run_event.wait(self.TICK * 5):
                if self.stop_event.is_set():
                    raise StopRequested()
            if self.stop_event.is_set():
                raise StopRequested()

    def scaled(self, seconds: float) -> float:
        return max(0.0, seconds) / self.speed

    def sleep(self, seconds: float, scale: bool = True) -> None:
        """Espera interrompível. `scale` aplica a velocidade de execução."""
        total = self.scaled(seconds) if scale else max(0.0, seconds)
        end = time.perf_counter() + total
        self.check()
        while True:
            left = end - time.perf_counter()
            if left <= 0:
                return
            if self.stop_event.wait(min(self.TICK, left)):
                raise StopRequested()
            if not self.run_event.is_set():
                paused_at = time.perf_counter()
                self.check()
                end += time.perf_counter() - paused_at  # pausa não consome a espera

    # ---------- valores ----------
    def value(self, v: Any) -> Any:
        return expr.value_of(v, self.vars)

    def number(self, v: Any, default: float = 0) -> float:
        try:
            return expr.number(v, self.vars, default)
        except expr.ExprError as e:
            raise MacroError(str(e)) from e

    def integer(self, v: Any, default: int = 0) -> int:
        return int(round(self.number(v, default)))

    def text(self, v: Any) -> str:
        return expr.interpolate(str(v if v is not None else ""), self.vars)

    def set_var(self, name: str, value: Any) -> None:
        name = (name or "").strip()
        if not expr.VAR_NAME.match(name):
            raise MacroError(f"Nome de variável inválido: '{name}'")
        self.vars[name] = value

    # ---------- registro ----------
    def log(self, message: str, level: str = "info", **extra: Any) -> None:
        self._log(
            LogEntry(
                time=time.time(),
                level=level,
                message=message,
                step=self.step,
                command=self.command_label,
                repetition=self.repetition,
                **extra,
            )
        )

    def resolve_path(self, p: str) -> Path:
        path = Path(self.text(p)).expanduser()
        if not path.is_absolute() and self.base_dir:
            path = self.base_dir / path
        return path
