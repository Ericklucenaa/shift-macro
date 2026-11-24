"""Formulários gerados a partir dos campos declarados em cada CommandSpec."""
from __future__ import annotations

import copy
from typing import Any, Protocol

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from ..actions import registry
from ..actions.inputs import SPECIAL_KEYS
from ..actions.registry import CommandSpec, Field
from ..core.model import Command, Macro
from ..utils import winapi
from ..vision import matcher
from . import icons, overlay, theme


class EditorHost(Protocol):
    """O que os formulários precisam do aplicativo."""

    macro: Macro
    def top_window(self) -> QWidget: ...
    def capture_image_from_screen(self) -> str | None: ...
    def import_image_file(self) -> str | None: ...


LABEL_W = 150  # largura comum dos rótulos: formulários empilhados ficam alinhados


def _tool(icon: str, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(icons.icon(icon, theme.current().muted, 16))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _num_or_text(text: str) -> Any:
    s = text.strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return s


# ------------------------------------------------------------------ editores
class FieldEditor(QWidget):
    changed = Signal()

    def __init__(self, field: Field, host: EditorHost):
        super().__init__()
        self.field = field
        self.host = host
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)

    def get(self, params: dict) -> None: ...
    def set(self, params: dict) -> None: ...


class LineEditor(FieldEditor):
    def __init__(self, field, host, placeholder=""):
        super().__init__(field, host)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textEdited.connect(lambda *_: self.changed.emit())
        self.lay.addWidget(self.edit)

    def get(self, params):
        params[self.field.key] = self.edit.text()

    def set(self, params):
        v = params.get(self.field.key)
        self.edit.setText("" if v is None else str(v))


class IntEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.spin = QSpinBox()
        self.spin.setRange(int(field.min if field.min is not None else -1_000_000_000),
                           int(field.max if field.max is not None else 1_000_000_000))
        self.spin.setAccelerated(True)
        self.spin.valueChanged.connect(lambda *_: self.changed.emit())
        self.spin.setMinimumWidth(110)
        self.lay.addWidget(self.spin)
        self.lay.addStretch(1)

    def get(self, params):
        params[self.field.key] = self.spin.value()

    def set(self, params):
        v = params.get(self.field.key, self.field.default)
        try:
            self.spin.setValue(int(float(v)))
        except (TypeError, ValueError):
            self.spin.setValue(int(self.field.default or 0))


class FloatEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(2)
        self.spin.setRange(field.min if field.min is not None else -1e9, field.max if field.max is not None else 1e9)
        self.spin.valueChanged.connect(lambda *_: self.changed.emit())
        self.lay.addWidget(self.spin)
        self.lay.addStretch(1)

    def get(self, params):
        params[self.field.key] = self.spin.value()

    def set(self, params):
        try:
            self.spin.setValue(float(params.get(self.field.key, self.field.default) or 0))
        except (TypeError, ValueError):
            pass


class BoolEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.box = QCheckBox(field.label)
        self.box.toggled.connect(lambda *_: self.changed.emit())
        self.lay.addWidget(self.box)

    def get(self, params):
        params[self.field.key] = self.box.isChecked()

    def set(self, params):
        self.box.setChecked(bool(params.get(self.field.key)))


class ChoiceEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.combo = QComboBox()
        for value, label in field.options:
            self.combo.addItem(label, value)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.lay.addWidget(self.combo, 1)

    def get(self, params):
        params[self.field.key] = self.combo.currentData()

    def set(self, params):
        i = self.combo.findData(params.get(self.field.key, self.field.default))
        self.combo.setCurrentIndex(max(0, i))


class MultilineEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.edit = QPlainTextEdit()
        self.edit.setFixedHeight(76)
        self.edit.textChanged.connect(self.changed.emit)
        self.lay.addWidget(self.edit)

    def get(self, params):
        params[self.field.key] = self.edit.toPlainText()

    def set(self, params):
        self.edit.blockSignals(True)
        self.edit.setPlainText(str(params.get(self.field.key) or ""))
        self.edit.blockSignals(False)


class ComboTextEditor(FieldEditor):
    """Texto livre com sugestões (janelas abertas, rótulos, funções, teclas)."""

    def __init__(self, field, host, source):
        super().__init__(field, host)
        self.source = source
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.lineEdit().textEdited.connect(lambda *_: self.changed.emit())
        self.combo.activated.connect(lambda *_: self.changed.emit())
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(14)
        self.lay.addWidget(self.combo, 1)
        self._fill()
        orig = self.combo.showPopup

        def show_popup():
            self._fill()
            orig()

        self.combo.showPopup = show_popup  # type: ignore[method-assign]

    def _fill(self):
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        for item in self.source():
            self.combo.addItem(item)
        self.combo.setEditText(cur)
        self.combo.blockSignals(False)

    def get(self, params):
        params[self.field.key] = self.combo.currentText().strip()

    def set(self, params):
        self.combo.setEditText(str(params.get(self.field.key) or ""))


class KeyEditor(ComboTextEditor):
    def __init__(self, field, host):
        keys = list(SPECIAL_KEYS) + [chr(c) for c in range(ord("a"), ord("z") + 1)] + [str(d) for d in range(10)]
        super().__init__(field, host, lambda: keys)
        b = _tool("keyboard", "Pressione a tecla desejada")
        b.clicked.connect(self._capture)
        self.lay.addWidget(b)

    def _capture(self):
        combo = KeyCaptureDialog.ask(self, combo=False)
        if combo:
            self.combo.setEditText(combo)
            self.changed.emit()


class HotkeyEditor(LineEditor):
    def __init__(self, field, host):
        super().__init__(field, host, "ex.: ctrl+shift+s")
        b = _tool("keyboard", "Pressione a combinação")
        b.clicked.connect(self._capture)
        self.lay.addWidget(b)

    def _capture(self):
        combo = KeyCaptureDialog.ask(self, combo=True)
        if combo:
            self.edit.setText(combo)
            self.changed.emit()


class PathEditor(LineEditor):
    def __init__(self, field, host, kind):
        super().__init__(field, host)
        self.kind = kind
        b = _tool("folder", "Procurar…")
        b.clicked.connect(self._browse)
        self.lay.addWidget(b)

    def _browse(self):
        cur = self.edit.text()
        if self.kind == "folder":
            p = QFileDialog.getExistingDirectory(self, "Escolher pasta", cur)
        elif self.kind == "macro":
            p, _ = QFileDialog.getOpenFileName(self, "Escolher macro", cur, "Macros (*.shiftmacro)")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", cur, "Todos os arquivos (*.*)")
        if p:
            self.edit.setText(p.replace("/", "\\"))
            self.changed.emit()


class PointEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.x = QLineEdit()
        self.y = QLineEdit()
        for e, ph in ((self.x, "x"), (self.y, "y")):
            e.setPlaceholderText(ph)
            e.setMaximumWidth(92)
            e.setToolTip("Número ou expressão com variáveis (ex.: found_x + 10)")
            e.textEdited.connect(lambda *_: self.changed.emit())
            self.lay.addWidget(e)
        b = _tool("crosshair", "Pegar posição na tela")
        b.clicked.connect(self._pick)
        self.lay.addWidget(b)
        self.lay.addStretch(1)

    def _pick(self):
        r = overlay.pick_point(self.host.top_window())
        if r:
            self.x.setText(str(r[0]))
            self.y.setText(str(r[1]))
            self.changed.emit()

    def get(self, params):
        kx, ky = self.field.keys
        params[kx] = _num_or_text(self.x.text() or "0")
        params[ky] = _num_or_text(self.y.text() or "0")

    def set(self, params):
        kx, ky = self.field.keys
        self.x.setText(str(params.get(kx, 0)))
        self.y.setText(str(params.get(ky, 0)))


class RegionEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        box = QVBoxLayout()
        box.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.spins = []
        for tip in ("x", "y", "largura", "altura"):
            s = QSpinBox()
            s.setRange(-100_000, 100_000)
            s.setToolTip(tip)
            s.setPrefix(f"{tip[0]} ")
            s.valueChanged.connect(lambda *_: self.changed.emit())
            row.addWidget(s)
            self.spins.append(s)
        box.addLayout(row)
        b = QPushButton(icons.icon("crosshair", theme.current().muted, 16), "Selecionar na tela")
        b.clicked.connect(self._pick)
        box.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.lay.addLayout(box)

    def _pick(self):
        r = overlay.pick_region(self.host.top_window())
        if r:
            for s, v in zip(self.spins, r.as_list()):
                s.setValue(v)
            self.changed.emit()

    def get(self, params):
        params[self.field.key] = [s.value() for s in self.spins]

    def set(self, params):
        vals = params.get(self.field.key) or [0, 0, 0, 0]
        for s, v in zip(self.spins, vals):
            s.blockSignals(True)
            try:
                s.setValue(int(v))
            except (TypeError, ValueError):
                s.setValue(0)
            s.blockSignals(False)


class ColorEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(26, 26)
        self.swatch.setToolTip("Escolher cor")
        self.swatch.clicked.connect(self._dialog)
        self.edit = QLineEdit()
        self.edit.setMaximumWidth(110)
        self.edit.setPlaceholderText("#RRGGBB")
        self.edit.textEdited.connect(self._typed)
        b = _tool("color", "Pegar cor da tela (conta-gotas)")
        b.clicked.connect(self._pick)
        self.lay.addWidget(self.swatch)
        self.lay.addWidget(self.edit)
        self.lay.addWidget(b)
        self.lay.addStretch(1)

    def _paint(self):
        try:
            rgb = matcher.parse_color(self.edit.text())
            c = matcher.to_hex(rgb)
        except ValueError:
            c = theme.current().raised
        self.swatch.setStyleSheet(f"background:{c}; border:1px solid {theme.current().line}; border-radius:4px;")

    def _typed(self, *_):
        self._paint()
        self.changed.emit()

    def _dialog(self):
        try:
            cur = QColor(matcher.to_hex(matcher.parse_color(self.edit.text())))
        except ValueError:
            cur = QColor("#ffffff")
        c = QColorDialog.getColor(cur, self, "Escolher cor")
        if c.isValid():
            self.edit.setText(c.name().upper())
            self._typed()

    def _pick(self):
        r = overlay.pick_point(self.host.top_window())
        if r:
            self.edit.setText(matcher.to_hex(r[2]))
            self._typed()
            # se houver um campo de posição junto, já preenche (pixel_color/if pixel)
            form = self.parent()
            while form is not None and not isinstance(form, ParamForm):
                form = form.parent()
            if form is not None:
                form.set_point_if_present(r[0], r[1])

    def get(self, params):
        params[self.field.key] = self.edit.text().strip()

    def set(self, params):
        self.edit.setText(str(params.get(self.field.key) or ""))
        self._paint()


class ImageEditor(FieldEditor):
    def __init__(self, field, host):
        super().__init__(field, host)
        col = QVBoxLayout()
        col.setSpacing(6)
        top = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(120, 72)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"background:{theme.current().bg}; border:1px solid {theme.current().line}; border-radius:4px;")
        top.addWidget(self.preview)
        right = QVBoxLayout()
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._sel)
        right.addWidget(self.combo)
        b1 = QPushButton(icons.icon("smart", theme.current().muted, 16), "Recortar da tela")
        b1.clicked.connect(self._capture)
        b2 = QPushButton(icons.icon("image", theme.current().muted, 16), "Importar…")
        b2.clicked.connect(self._import)
        right.addWidget(b1)
        right.addWidget(b2)
        right.addStretch(1)
        top.addLayout(right, 1)
        col.addLayout(top)
        self.lay.addLayout(col)
        self._fill()

    def _fill(self, select: str | None = None):
        cur = select if select is not None else self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("(nenhuma)", "")
        for name in sorted(self.host.macro.images):
            self.combo.addItem(name, name)
        i = self.combo.findData(cur or "")
        self.combo.setCurrentIndex(max(0, i))
        self.combo.blockSignals(False)
        self._show()

    def _show(self):
        name = self.combo.currentData()
        data = self.host.macro.images.get(name) if name else None
        if not data:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("sem imagem")
            return
        pm = QPixmap()
        pm.loadFromData(data, "PNG")
        self.preview.setPixmap(pm.scaled(QSize(116, 68), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.preview.setToolTip(f"{name} · {pm.width()} × {pm.height()} px")

    def _sel(self, *_):
        self._show()
        self.changed.emit()

    def _capture(self):
        name = self.host.capture_image_from_screen()
        if name:
            self._fill(name)
            self.changed.emit()

    def _import(self):
        name = self.host.import_image_file()
        if name:
            self._fill(name)
            self.changed.emit()

    def get(self, params):
        params[self.field.key] = self.combo.currentData() or ""

    def set(self, params):
        self._fill(str(params.get(self.field.key) or ""))


def make_editor(field: Field, host: EditorHost) -> FieldEditor:
    k = field.kind
    if k == "int":
        return IntEditor(field, host)
    if k == "float":
        return FloatEditor(field, host)
    if k == "bool":
        return BoolEditor(field, host)
    if k == "choice":
        return ChoiceEditor(field, host)
    if k == "multiline":
        return MultilineEditor(field, host)
    if k == "key":
        return KeyEditor(field, host)
    if k == "hotkey":
        return HotkeyEditor(field, host)
    if k in ("file", "folder", "macro"):
        return PathEditor(field, host, k)
    if k == "point":
        return PointEditor(field, host)
    if k == "region":
        return RegionEditor(field, host)
    if k == "color":
        return ColorEditor(field, host)
    if k == "image":
        return ImageEditor(field, host)
    if k == "window":
        return ComboTextEditor(field, host, lambda: [w.title for w in winapi.list_windows()][:60])
    if k == "label":
        return ComboTextEditor(field, host, lambda: sorted({str(c.params.get("label")) for c in host.macro.commands if c.type == "label" and c.params.get("label")}))
    if k == "function":
        return ComboTextEditor(field, host, lambda: sorted({str(c.params.get("name")) for c in host.macro.commands if c.type == "function" and c.params.get("name")}))
    placeholder = {"expr": "ex.: contador + 1", "var": "nome_da_variavel"}.get(k, "")
    return LineEditor(field, host, placeholder)


# ------------------------------------------------------------------ formulário
class ParamForm(QWidget):
    changed = Signal()

    def __init__(self, spec: CommandSpec, params: dict, host: EditorHost, exclude: set[str] | None = None):
        super().__init__()
        self.spec = spec
        self.params = copy.deepcopy(params)
        self.host = host
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(8)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.editors: list[FieldEditor] = []
        self.labels: dict[int, QLabel] = {}
        for f in spec.fields:
            if exclude and f.key in exclude:
                continue
            ed = make_editor(f, host)
            ed.set(self.params)
            ed.changed.connect(self._on_change)
            if f.help:
                ed.setToolTip(f.help)
            if f.kind == "bool":
                self.form.addRow(ed)  # caixa de seleção ocupa a linha inteira
                lbl = None
            else:
                lbl = QLabel(f.label)
                lbl.setMinimumWidth(LABEL_W)
                lbl.setWordWrap(True)
                if f.help:
                    lbl.setToolTip(f.help)
                self.form.addRow(lbl, ed)
            self.editors.append(ed)
            if lbl is not None:
                self.labels[id(ed)] = lbl
        self._apply_visibility()

    def _on_change(self):
        self.values()
        self._apply_visibility()
        self.changed.emit()

    def _apply_visibility(self):
        for ed in self.editors:
            vis = ed.field.visible(self.params)
            self.form.setRowVisible(ed, vis)

    def values(self) -> dict:
        for ed in self.editors:
            ed.get(self.params)
        return copy.deepcopy(self.params)

    def set_point_if_present(self, x: int, y: int):
        for ed in self.editors:
            if isinstance(ed, PointEditor) and ed.isVisible():
                ed.x.setText(str(x))
                ed.y.setText(str(y))
                self._on_change()
                return


class CommonFields(QWidget):
    """Nome da etapa, comentário, delay depois e ativa: comuns a todo comando."""

    changed = Signal()

    def __init__(self, cmd: Command):
        super().__init__()
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.name = QLineEdit(cmd.name)
        self.name.setPlaceholderText("opcional")
        self.comment = QLineEdit(cmd.comment)
        self.comment.setPlaceholderText("opcional")
        self.delay = QSpinBox()
        self.delay.setRange(0, 86_400_000)
        self.delay.setSuffix(" ms")
        self.delay.setValue(cmd.delay_ms)
        self.delay.setAccelerated(True)
        self.delay.setMinimumWidth(110)
        self.enabled = QCheckBox("Etapa ativa")
        self.enabled.setChecked(cmd.enabled)
        def lbl(text):
            w = QLabel(text)
            w.setMinimumWidth(LABEL_W)
            return w

        form.addRow(lbl("Nome da etapa"), self.name)
        form.addRow(lbl("Comentário"), self.comment)
        drow = QHBoxLayout()
        drow.addWidget(self.delay)
        drow.addStretch(1)
        form.addRow(lbl("Esperar depois"), drow)
        form.addRow(self.enabled)
        for w in (self.name, self.comment):
            w.textEdited.connect(lambda *_: self.changed.emit())
        self.delay.valueChanged.connect(lambda *_: self.changed.emit())
        self.enabled.toggled.connect(lambda *_: self.changed.emit())

    def apply_to(self, cmd: Command) -> None:
        cmd.name = self.name.text().strip()
        cmd.comment = self.comment.text().strip()
        cmd.delay_ms = self.delay.value()
        cmd.enabled = self.enabled.isChecked()


class CommandEditor(QWidget):
    """Cabeçalho + campos do comando + campos comuns."""

    changed = Signal()

    def __init__(self, cmd: Command, host: EditorHost, exclude: set[str] | None = None, show_header: bool = True):
        super().__init__()
        self.cmd = cmd
        self.spec = registry.get(cmd.type)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        if show_header:
            lay.addWidget(_header(self.spec))
        self.form = ParamForm(self.spec, cmd.params, host, exclude)
        self.form.changed.connect(self.changed.emit)
        if self.spec.fields:
            lay.addWidget(self.form)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{theme.current().line};")
        lay.addWidget(sep)
        self.common = CommonFields(cmd)
        self.common.changed.connect(self.changed.emit)
        lay.addWidget(self.common)

    def result(self) -> Command:
        c = self.cmd.clone()
        c.id = self.cmd.id
        c.params = self.form.values()
        self.common.apply_to(c)
        return c


def _header(spec: CommandSpec) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    color = theme.current().kinds.get(spec.kind, theme.current().muted)
    ic = QLabel()
    ic.setPixmap(icons.icon(spec.kind, color, 20).pixmap(20, 20))
    title = QLabel(spec.label)
    f = title.font()
    f.setPointSizeF(f.pointSizeF() + 2)
    f.setWeight(f.Weight.DemiBold)
    title.setFont(f)
    cat = QLabel(spec.category)
    cat.setObjectName("muted")
    h.addWidget(ic)
    h.addWidget(title)
    h.addStretch(1)
    h.addWidget(cat)
    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return w


# ------------------------------------------------------------------ captura de tecla
_QT_KEYS = {
    Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter", Qt.Key.Key_Escape: "esc", Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backtab: "tab", Qt.Key.Key_Space: "space", Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete", Qt.Key.Key_Insert: "insert", Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown", Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_NumLock: "numlock", Qt.Key.Key_ScrollLock: "scrolllock", Qt.Key.Key_Print: "printscreen",
    Qt.Key.Key_Pause: "pause", Qt.Key.Key_Menu: "apps", Qt.Key.Key_Control: "ctrl", Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Alt: "alt", Qt.Key.Key_Meta: "win",
}


def qt_key_name(e: QKeyEvent) -> str | None:
    k = e.key()
    if Qt.Key.Key_F1 <= k <= Qt.Key.Key_F24:
        return f"f{k - Qt.Key.Key_F1 + 1}"
    if Qt.Key.Key_A <= k <= Qt.Key.Key_Z:
        return chr(k).lower()
    if Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
        return chr(k)
    if k in _QT_KEYS:
        return _QT_KEYS[k]
    t = e.text()
    return t.lower() if t and t.isprintable() else None


class KeyCaptureDialog(QDialog):
    def __init__(self, parent, combo: bool, title: str = "Pressione a tecla"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.combo = combo
        self.result_text: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        msg = QLabel("Pressione a combinação de teclas." if combo else "Pressione a tecla desejada.")
        self.preview = QLabel("…")
        f = self.preview.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        f.setWeight(f.Weight.DemiBold)
        self.preview.setFont(f)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(48)
        hint = QLabel("Esc cancela (para gravar a tecla Esc, use a lista).")
        hint.setObjectName("hint")
        lay.addWidget(msg)
        lay.addWidget(self.preview)
        lay.addWidget(hint)
        self.setMinimumWidth(340)

    def keyPressEvent(self, e: QKeyEvent):
        name = qt_key_name(e)
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if not name:
            return
        mods = []
        m = e.modifiers()
        if self.combo:
            if m & Qt.KeyboardModifier.ControlModifier:
                mods.append("ctrl")
            if m & Qt.KeyboardModifier.AltModifier:
                mods.append("alt")
            if m & Qt.KeyboardModifier.ShiftModifier:
                mods.append("shift")
            if m & Qt.KeyboardModifier.MetaModifier:
                mods.append("win")
        if name in ("ctrl", "alt", "shift", "win") and self.combo:
            self.preview.setText("+".join(mods) + "+…")
            return
        self.result_text = "+".join(mods + [name])
        self.preview.setText(self.result_text.upper())
        QTimer.singleShot(250, self.accept)

    @classmethod
    def ask(cls, parent, combo: bool, title: str = "Pressione a tecla") -> str | None:
        d = cls(parent, combo, title)
        return d.result_text if d.exec() == QDialog.DialogCode.Accepted else None
