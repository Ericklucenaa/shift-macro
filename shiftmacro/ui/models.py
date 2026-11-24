"""Modelos Qt: tabela de etapas e registro de execução."""
from __future__ import annotations

import json
import time
from collections import deque

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont

from ..actions import registry
from ..core.context import LogEntry
from ..core.model import Macro
from ..core.structure import Structure, analyze
from . import theme

STEP, ACTION, DESC, DELAY, STATUS = range(5)
HEADERS = ["Etapa", "Ação", "Descrição", "Delay", "Status"]
MIME_ROWS = "application/x-shiftmacro-rows"
MIME_TYPE = "application/x-shiftmacro-type"
KIND_ROLE = Qt.ItemDataRole.UserRole + 1
DEPTH_ROLE = Qt.ItemDataRole.UserRole + 2
NAME_ROLE = Qt.ItemDataRole.UserRole + 3
CURRENT_ROLE = Qt.ItemDataRole.UserRole + 4


def fmt_delay(ms: int) -> str:
    if not ms:
        return ""
    return f"{ms / 1000:.2f} s".replace(".", ",") if ms >= 1000 else f"{ms} ms"


class CommandTableModel(QAbstractTableModel):
    toggled = Signal(int)  # linha teve "ativa" alterada pelo checkbox
    move_requested = Signal(list, int)  # linhas, destino
    insert_type_requested = Signal(str, int)
    delay_edited = Signal(int, int)

    def __init__(self, macro: Macro):
        super().__init__()
        self.macro = macro
        self.structure: Structure = analyze(macro.commands)
        self.errors: dict[int, str] = {}
        self.current_row: int | None = None
        self.statuses: dict[int, tuple[str, str]] = {}
        self._recompute()

    # ---------------------------------------------------------- dados
    def set_macro(self, macro: Macro) -> None:
        self.beginResetModel()
        self.macro = macro
        self.statuses.clear()
        self.current_row = None
        self._recompute()
        self.endResetModel()

    def refresh(self) -> None:
        self.beginResetModel()
        self._recompute()
        self.endResetModel()

    def refresh_rows(self, rows) -> None:
        self._recompute()
        for r in rows:
            self.dataChanged.emit(self.index(r, 0), self.index(r, STATUS))

    def _recompute(self) -> None:
        self.structure = analyze(self.macro.commands)
        self.errors = {}
        for i, msg in self.structure.errors:
            self.errors.setdefault(i, msg)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.macro.commands)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        cmd = self.macro.commands[r]
        try:
            spec = registry.get(cmd.type)
        except KeyError:
            spec = None
        t = theme.current()
        if role == Qt.ItemDataRole.DisplayRole:
            if c == STEP:
                return str(r + 1)
            if c == ACTION:
                return spec.label if spec else cmd.type
            if c == DESC:
                if not spec:
                    return "Comando desconhecido"
                d = spec.describe(cmd.params)
                return d
            if c == DELAY:
                return fmt_delay(cmd.delay_ms)
            if c == STATUS:
                if r in self.errors:
                    return "Estrutura"
                return self.statuses.get(r, ("", ""))[0]
        if role == Qt.ItemDataRole.EditRole and c == DELAY:
            return cmd.delay_ms
        if role == Qt.ItemDataRole.CheckStateRole and c == STEP:
            return Qt.CheckState.Checked if cmd.enabled else Qt.CheckState.Unchecked
        if role == KIND_ROLE:
            return spec.kind if spec else "comment"
        if role == DEPTH_ROLE:
            return self.structure.depth[r] if r < len(self.structure.depth) else 0
        if role == NAME_ROLE:
            return cmd.name
        if role == CURRENT_ROLE:
            return r == self.current_row
        if role == Qt.ItemDataRole.ForegroundRole:
            if not cmd.enabled:
                return QColor(t.faint)
            if c == STATUS:
                if r in self.errors:
                    return QColor(t.error)
                level = self.statuses.get(r, ("", ""))[1]
                return QColor({"ok": t.ok, "warn": t.warn, "error": t.error, "skip": t.faint}.get(level, t.muted))
            if c in (STEP, DELAY):
                return QColor(t.muted)
            if spec and spec.kind == "comment":
                return QColor(t.muted)
        if role == Qt.ItemDataRole.FontRole:
            if c in (STEP, DELAY):
                return theme.mono_font(8.5)
            if spec and spec.kind == "comment" and c == DESC:
                f = QFont()
                f.setItalic(True)
                return f
            if not cmd.enabled and c in (ACTION, DESC):
                f = QFont()
                f.setStrikeOut(True)
                return f
        if role == Qt.ItemDataRole.BackgroundRole:
            if r == self.current_row:
                return QColor(t.accent_soft)
            if r in self.errors:
                c_ = QColor(t.error)
                c_.setAlpha(28)
                return c_
        if role == Qt.ItemDataRole.ToolTipRole:
            if r in self.errors:
                return self.errors[r]
            parts = []
            if cmd.name:
                parts.append(cmd.name)
            if cmd.comment:
                parts.append(cmd.comment)
            if c == DESC and spec:
                parts.append(spec.describe(cmd.params))
            return "\n".join(parts) or None
        if role == Qt.ItemDataRole.TextAlignmentRole and c in (STEP, DELAY):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False
        r, c = index.row(), index.column()
        if role == Qt.ItemDataRole.CheckStateRole and c == STEP:
            self.toggled.emit(r)
            return True
        if role == Qt.ItemDataRole.EditRole and c == DELAY:
            try:
                ms = max(0, int(str(value).replace("ms", "").strip() or 0))
            except ValueError:
                return False
            self.delay_edited.emit(r, ms)
            return True
        return False

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsDropEnabled
        if not index.isValid():
            return base
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if index.column() == STEP:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == DELAY:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    # ---------------------------------------------------------- execução
    def set_current(self, row: int | None) -> None:
        old = self.current_row
        self.current_row = row
        for r in (old, row):
            if r is not None and 0 <= r < self.rowCount():
                self.dataChanged.emit(self.index(r, 0), self.index(r, STATUS))

    def set_statuses(self, updates: dict[int, tuple[str, str]]) -> None:
        if not updates:
            return
        self.statuses.update(updates)
        rows = [r for r in updates if 0 <= r < self.rowCount()]
        if rows:
            self.dataChanged.emit(self.index(min(rows), STATUS), self.index(max(rows), STATUS))

    def clear_run_state(self) -> None:
        self.statuses.clear()
        self.set_current(None)
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, STATUS))

    # ---------------------------------------------------------- arrastar e soltar
    def supportedDropActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def supportedDragActions(self):
        # CopyAction: o modelo move as linhas sozinho em dropMimeData e o Qt
        # não tenta apagar as originais depois
        return Qt.DropAction.CopyAction

    def mimeTypes(self):
        return [MIME_ROWS, MIME_TYPE]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes})
        md = QMimeData()
        md.setData(MIME_ROWS, json.dumps(rows).encode())
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(MIME_ROWS) or data.hasFormat(MIME_TYPE)

    def dropMimeData(self, data, action, row, column, parent):
        if row < 0:
            row = parent.row() if parent.isValid() else self.rowCount()
        if data.hasFormat(MIME_ROWS):
            rows = json.loads(bytes(data.data(MIME_ROWS)).decode())
            self.move_requested.emit(rows, row)
            return True
        if data.hasFormat(MIME_TYPE):
            self.insert_type_requested.emit(bytes(data.data(MIME_TYPE)).decode(), row)
            return True
        return False


# ================================================================== log
LOG_HEADERS = ["Hora", "Rep.", "Etapa", "Comando", "Mensagem", "Similaridade", "Coordenadas", "Tempo"]


class LogModel(QAbstractTableModel):
    def __init__(self, max_rows: int = 5000):
        super().__init__()
        self.rows: deque[LogEntry] = deque()
        self.max_rows = max_rows

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(LOG_HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return LOG_HEADERS[section]
        return None

    def add(self, entries: list[LogEntry]) -> None:
        if not entries:
            return
        overflow = len(self.rows) + len(entries) - self.max_rows
        if overflow > 0:
            drop = min(overflow, len(self.rows))
            if drop:
                self.beginRemoveRows(QModelIndex(), 0, drop - 1)
                for _ in range(drop):
                    self.rows.popleft()
                self.endRemoveRows()
            entries = entries[-self.max_rows:]
        start = len(self.rows)
        self.beginInsertRows(QModelIndex(), start, start + len(entries) - 1)
        self.rows.extend(entries)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.rows.clear()
        self.endResetModel()

    @staticmethod
    def cells(e: LogEntry) -> list[str]:
        return [
            time.strftime("%H:%M:%S", time.localtime(e.time)) + f",{int(e.time * 1000) % 1000:03d}",
            str(e.repetition or ""),
            str(e.step + 1) if e.step is not None else "",
            e.command,
            e.message,
            f"{e.similarity * 100:.1f}%" if e.similarity is not None else "",
            f"{e.coords[0]}, {e.coords[1]}" if e.coords else "",
            f"{e.elapsed_ms:.0f} ms" if e.elapsed_ms is not None else "",
        ]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.rows[index.row()]
        t = theme.current()
        if role == Qt.ItemDataRole.DisplayRole:
            return self.cells(e)[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole:
            if e.level == "error":
                return QColor(t.error)
            if e.level == "warn":
                return QColor(t.warn)
            if index.column() in (0, 1, 2, 5, 6, 7):
                return QColor(t.muted)
        if role == Qt.ItemDataRole.FontRole and index.column() in (0, 1, 2, 5, 6, 7):
            return theme.mono_font(8.5)
        if role == Qt.ItemDataRole.UserRole:
            return e
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 4:
            return e.message
        return None


class LogFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.only_problems = False
        self.text = ""

    def set_filter(self, only_problems: bool, text: str) -> None:
        self.only_problems = only_problems
        self.text = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        e: LogEntry = self.sourceModel().rows[row]
        if self.only_problems and e.level not in ("warn", "error"):
            return False
        if self.text and self.text not in (e.message + " " + e.command).lower():
            return False
        return True
