"""Liga o motor (thread própria) à interface (thread do Qt).

O motor chama os callbacks na thread dele; aqui eles são acumulados e entregues
à interface em lotes a cada 40 ms. Um loop sem espera pode gerar milhares de
etapas por segundo: sem esse agrupamento a fila de eventos do Qt travaria a tela.
"""
from __future__ import annotations

import threading
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.context import LogEntry
from ..core.engine import Listener, RunResult


class EngineBridge(QObject, Listener):
    state_changed = Signal(str)
    repetition = Signal(int, object)
    finished = Signal(object)
    flushed = Signal(object, dict, list)  # etapa atual, {linha: (texto, nível)}, [LogEntry]
    notify = Signal(str, str)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self._lock = threading.Lock()
        self._step: int | None = None
        self._step_dirty = False
        self._status: dict[int, tuple[str, str]] = {}
        self._logs: deque[LogEntry] = deque(maxlen=20000)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.flush)
        self._timer.start()

    # ---------- chamados na thread do motor
    def on_step(self, row: int) -> None:
        with self._lock:
            self._step = row
            self._step_dirty = True

    def on_status(self, row: int, text: str, level: str) -> None:
        with self._lock:
            self._status[row] = (text, level)

    def on_log(self, entry: LogEntry) -> None:
        with self._lock:
            self._logs.append(entry)

    def on_state(self, state: str) -> None:
        self.state_changed.emit(state)

    def on_repetition(self, current: int, total) -> None:
        self.repetition.emit(current, total)

    def on_finished(self, result: RunResult) -> None:
        self.finished.emit(result)

    def send_notification(self, title: str, message: str) -> None:
        self.notify.emit(title, message)

    # ---------- thread do Qt
    def flush(self) -> None:
        with self._lock:
            if not (self._step_dirty or self._status or self._logs):
                return
            step = self._step if self._step_dirty else ...
            self._step_dirty = False
            status, self._status = self._status, {}
            logs = list(self._logs)
            self._logs.clear()
        self.flushed.emit(step, status, logs)
