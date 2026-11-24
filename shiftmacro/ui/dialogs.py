"""Diálogos: editar etapa, Smart Click, preferências, variáveis, imagens,
propriedades da macro, desligamento e ajuda."""
from __future__ import annotations

import subprocess
import time

import numpy as np
from PySide6.QtCore import QEventLoop, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from .. import DONATE_URL, REPO_URL, __version__
from ..actions import registry
from ..core import expr
from ..core.model import Command, Macro
from ..storage.appdata import DEFAULT_HOTKEYS, HOTKEY_LABELS, AppSettings
from ..utils.winapi import parse_hotkey
from ..vision.service import VisionError, VisionService
from . import icons, overlay, theme
from .forms import CommandEditor, CommonFields, KeyCaptureDialog, ParamForm, _header

IMAGE_TYPES = {"smart_click", "find_image", "wait_image", "click_image", "wait_image_vanish"}


def _buttons(dlg: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


def _scroll(w: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(w)
    s.setFrameShape(QFrame.Shape.NoFrame)
    return s


# ================================================================== editar etapa
class CommandDialog(QDialog):
    def __init__(self, cmd: Command, host, parent=None):
        super().__init__(parent)
        spec = registry.get(cmd.type)
        self.setWindowTitle(f"Editar etapa · {spec.label}")
        self.editor = CommandEditor(cmd, host)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.addWidget(self.editor)
        il.addStretch(1)
        lay.addWidget(_scroll(inner), 1)
        lay.addWidget(_buttons(self, "Aplicar"))
        self.resize(560, min(720, 220 + 44 * (len(spec.fields) + 4)))

    def result_command(self) -> Command:
        return self.editor.result()


# ================================================================== Smart Click
class _Preview(QLabel):
    """Área com fundo quadriculado (mostra transparência e bordas da imagem)."""

    def __init__(self, w: int, h: int):
        super().__init__()
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = theme.current()
        self.setStyleSheet(f"border:1px solid {t.line}; border-radius:4px; background:{t.bg}; color:{t.faint};")


class SmartClickDialog(QDialog):
    def __init__(self, cmd: Command, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.cmd = cmd
        self.spec = registry.get(cmd.type)
        self.setWindowTitle(f"{self.spec.label} · configurar")
        t = theme.current()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)
        root.addWidget(_header(self.spec))
        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        # ---------- coluna da imagem
        left = QVBoxLayout()
        left.setSpacing(8)
        cap = QLabel("Imagem de referência")
        cap.setObjectName("sectionTitle")
        left.addWidget(cap)
        self.preview = _Preview(360, 170)
        left.addWidget(self.preview)
        row = QHBoxLayout()
        self.image_combo = QComboBox()
        self.image_combo.currentIndexChanged.connect(self._image_changed)
        row.addWidget(self.image_combo, 1)
        left.addLayout(row)
        row2 = QHBoxLayout()
        b_cap = QPushButton(icons.icon("smart", t.text, 16), "Recortar da tela")
        b_cap.setToolTip("Esconde as janelas e deixa você arrastar sobre a área (atalho global: Shift+F11)")
        b_cap.clicked.connect(self._capture)
        b_imp = QPushButton(icons.icon("image", t.text, 16), "Importar…")
        b_imp.clicked.connect(self._import)
        row2.addWidget(b_cap)
        row2.addWidget(b_imp)
        row2.addStretch(1)
        left.addLayout(row2)

        sim = QLabel("Similaridade mínima")
        sim.setObjectName("sectionTitle")
        left.addSpacing(6)
        left.addWidget(sim)
        srow = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 100)
        self.spin = QSpinBox()
        self.spin.setRange(1, 100)
        self.spin.setSuffix(" %")
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.spin)
        left.addLayout(srow)
        hint = QLabel("100% exige a imagem idêntica. Entre 80% e 90% tolera antialiasing e pequenas mudanças.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        left.addWidget(hint)

        left.addSpacing(6)
        trow = QHBoxLayout()
        res_t = QLabel("Posição encontrada")
        res_t.setObjectName("sectionTitle")
        self.test_btn = QPushButton(icons.icon("search", t.text, 16), "Testar agora")
        self.test_btn.setToolTip("Procura na tela atual com as opções desta etapa (as janelas do app se escondem)")
        self.test_btn.clicked.connect(self._test)
        trow.addWidget(res_t)
        trow.addStretch(1)
        trow.addWidget(self.test_btn)
        left.addLayout(trow)
        self.result_view = _Preview(360, 200)
        self.result_view.setText("Use “Testar agora” para ver onde a imagem é encontrada.")
        self.result_view.setWordWrap(True)
        left.addWidget(self.result_view)
        self.result_text = QLabel("")
        self.result_text.setWordWrap(True)
        left.addWidget(self.result_text)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(372)
        body.addWidget(lw)

        # ---------- coluna de opções
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 8, 0)
        rl.setSpacing(12)
        self.form = ParamForm(self.spec, cmd.params, host, exclude={"image", "threshold"})
        rl.addWidget(self.form)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{t.line};")
        rl.addWidget(sep)
        self.common = CommonFields(cmd)
        rl.addWidget(self.common)
        rl.addStretch(1)
        body.addWidget(_scroll(right), 1)

        root.addWidget(_buttons(self, "Aplicar"))
        self._fill_images(str(cmd.params.get("image") or ""))
        self.spin.setValue(int(cmd.params.get("threshold") or 80))
        self.resize(940, 680)

    # ---------- imagem
    def _fill_images(self, select: str):
        self.image_combo.blockSignals(True)
        self.image_combo.clear()
        self.image_combo.addItem("(nenhuma imagem)", "")
        for n in sorted(self.host.macro.images):
            self.image_combo.addItem(n, n)
        self.image_combo.setCurrentIndex(max(0, self.image_combo.findData(select)))
        self.image_combo.blockSignals(False)
        self._image_changed()

    def _image_changed(self, *_):
        name = self.image_combo.currentData()
        data = self.host.macro.images.get(name) if name else None
        if not data:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Nenhuma imagem. Recorte da tela ou importe um arquivo.")
            return
        pm = QPixmap()
        pm.loadFromData(data, "PNG")
        scale = min(1.0 * 3, (self.preview.width() - 12) / max(1, pm.width()), (self.preview.height() - 12) / max(1, pm.height()))
        shown = pm.scaled(QSize(int(pm.width() * scale), int(pm.height() * scale)), Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.FastTransformation if scale > 1 else Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(shown)
        self.preview.setToolTip(f"{name} · {pm.width()} × {pm.height()} px")

    def _capture(self):
        name = self.host.capture_image_from_screen(extra_hide=self)
        if name:
            self._fill_images(name)

    def _import(self):
        name = self.host.import_image_file()
        if name:
            self._fill_images(name)

    def params(self) -> dict:
        p = self.form.values()
        p["image"] = self.image_combo.currentData() or ""
        p["threshold"] = self.spin.value()
        return p

    # ---------- teste
    def _test(self):
        p = self.params()
        if not p["image"]:
            self.result_text.setText("Escolha ou recorte uma imagem primeiro.")
            return
        vision = VisionService(self.host.macro.images)
        main = self.host.top_window()
        windows = [w for w in (self, main) if w is not None and w.isVisible()]
        for w in windows:
            w.setWindowOpacity(0.0)  # some da tela sem perder a posição
        loop = QEventLoop()
        QTimer.singleShot(250, loop.quit)
        loop.exec()
        try:
            t0 = time.perf_counter()
            found = vision.find_image(p["image"], p, int)
            ms = (time.perf_counter() - t0) * 1000
            area_img, area = vision.grab(found.search) if found.search else (None, None)
        except VisionError as e:
            found, area_img, ms = None, None, 0
            self.result_text.setText(str(e))
        finally:
            for w in windows:
                w.setWindowOpacity(1.0)
        if found is None:
            return
        t = theme.current()
        if area_img is not None and found.rect is not None:
            self._draw_result(area_img, area, found)
        if found.found:
            self.result_text.setText(
                f"<b style='color:{t.ok}'>Encontrada</b> · similaridade {found.score:.1%} · centro ({found.x}, {found.y}) · {ms:.0f} ms"
                .replace(".", ",", 1))
        elif found.rect is not None:
            self.result_text.setText(
                f"<b style='color:{t.warn}'>Não encontrada</b> com {p['threshold']}%. Melhor ponto: {found.score:.1%} em "
                f"({found.x}, {found.y}). Reduza a similaridade ou recorte de novo.")
        else:
            self.result_text.setText(f"<b style='color:{t.warn}'>Não encontrada</b>: a imagem é maior que a área de busca.")

    def _draw_result(self, img: np.ndarray, area, found):
        t = theme.current()
        pm = QPixmap.fromImage(overlay.to_qimage(img))
        W, H = self.result_view.width() - 8, self.result_view.height() - 8
        r = found.rect
        # aproxima na região encontrada quando a área de busca é grande
        cx, cy = r.x - area.x + r.w / 2, r.y - area.y + r.h / 2
        view_w = min(area.w, max(r.w * 6, 360))
        view_h = min(area.h, max(r.h * 6, 200))
        vx = int(min(max(0, cx - view_w / 2), area.w - view_w))
        vy = int(min(max(0, cy - view_h / 2), area.h - view_h))
        crop = pm.copy(vx, vy, int(view_w), int(view_h))
        s = min(W / crop.width(), H / crop.height())
        shown = crop.scaled(int(crop.width() * s), int(crop.height() * s), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        p = QPainter(shown)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(t.ok if found.found else t.warn), 2, Qt.PenStyle.SolidLine if found.found else Qt.PenStyle.DashLine)
        p.setPen(pen)
        rx, ry = (r.x - area.x - vx) * s, (r.y - area.y - vy) * s
        p.drawRect(int(rx), int(ry), int(r.w * s), int(r.h * s))
        p.drawLine(int(rx + r.w * s / 2) - 6, int(ry + r.h * s / 2), int(rx + r.w * s / 2) + 6, int(ry + r.h * s / 2))
        p.drawLine(int(rx + r.w * s / 2), int(ry + r.h * s / 2) - 6, int(rx + r.w * s / 2), int(ry + r.h * s / 2) + 6)
        p.end()
        self.result_view.setPixmap(shown)

    def result_command(self) -> Command:
        c = self.cmd.clone()
        c.id = self.cmd.id
        c.params = self.params()
        self.common.apply_to(c)
        return c


def edit_dialog_for(cmd: Command, host, parent=None):
    if cmd.type in IMAGE_TYPES:
        return SmartClickDialog(cmd, host, parent)
    return CommandDialog(cmd, host, parent)


# ================================================================== preferências
class HotkeyField(QWidget):
    def __init__(self, value: str):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText("desligado")
        b = QPushButton("Gravar…")
        b.clicked.connect(self._cap)
        h.addWidget(self.edit, 1)
        h.addWidget(b)

    def _cap(self):
        r = KeyCaptureDialog.ask(self, combo=True, title="Novo atalho")
        if r:
            self.edit.setText("+".join(p.capitalize() if len(p) > 1 else p.upper() for p in r.split("+")))

    def text(self) -> str:
        return self.edit.text().strip()


class PreferencesDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None, tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Preferências")
        self.s = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # Geral
        g = QWidget()
        gf = QFormLayout(g)
        gf.setContentsMargins(12, 14, 12, 12)
        gf.setVerticalSpacing(10)
        self.theme = QComboBox()
        self.theme.addItem("Escuro", "dark")
        self.theme.addItem("Claro", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 3600)
        self.autosave.setSuffix(" s")
        self.autosave.setSpecialValueText("desligado")
        self.autosave.setValue(settings.autosave_seconds)
        self.failsafe = QCheckBox("Levar o mouse ao canto superior esquerdo interrompe a macro")
        self.failsafe.setChecked(settings.failsafe)
        self.follow = QCheckBox("Rolar a tabela até a etapa em execução")
        self.follow.setChecked(settings.follow_current)
        self.logmax = QSpinBox()
        self.logmax.setRange(500, 200_000)
        self.logmax.setSingleStep(1000)
        self.logmax.setValue(settings.log_max)
        gf.addRow("Tema", self.theme)
        gf.addRow("Salvamento automático a cada", self.autosave)
        gf.addRow("Linhas guardadas no log", self.logmax)
        gf.addRow("", self.follow)
        gf.addRow("", self.failsafe)
        self.auto_update = QCheckBox("Procurar versão nova ao abrir (consulta o GitHub uma vez por dia)")
        self.auto_update.setChecked(settings.auto_update)
        gf.addRow("", self.auto_update)
        tabs.addTab(g, "Geral")

        # Atalhos
        a = QWidget()
        af = QFormLayout(a)
        af.setContentsMargins(12, 14, 12, 12)
        af.setVerticalSpacing(10)
        note = QLabel("Funcionam com o app minimizado. Combinações com Ctrl, Alt, Shift ou Win e uma tecla.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        af.addRow(note)
        self.hk: dict[str, HotkeyField] = {}
        for key, label in HOTKEY_LABELS.items():
            f = HotkeyField(settings.hotkeys.get(key, ""))
            self.hk[key] = f
            af.addRow(label, f)
        rst = QPushButton("Restaurar padrões")
        rst.clicked.connect(lambda: [self.hk[k].edit.setText(v) for k, v in DEFAULT_HOTKEYS.items()])
        af.addRow("", rst)
        self.hk_error = QLabel("")
        self.hk_error.setObjectName("error")
        self.hk_error.setWordWrap(True)
        af.addRow(self.hk_error)
        tabs.addTab(a, "Atalhos")

        # Gravação
        r = QWidget()
        rf = QFormLayout(r)
        rf.setContentsMargins(12, 14, 12, 12)
        rf.setVerticalSpacing(10)
        self.rmode = QComboBox()
        for v, l in (("all", "Mouse e teclado"), ("clicks", "Somente cliques do mouse"), ("keyboard", "Somente teclado")):
            self.rmode.addItem(l, v)
        self.rmode.setCurrentIndex(max(0, self.rmode.findData(settings.record_mode)))
        self.rmoves = QCheckBox("Gravar todos os movimentos do mouse")
        self.rmoves.setChecked(settings.record_moves)
        self.rmin = QSpinBox()
        self.rmin.setRange(5, 1000)
        self.rmin.setSuffix(" ms")
        self.rmin.setValue(settings.record_min_move_ms)
        self.rdelays = QCheckBox("Guardar o tempo entre as ações")
        self.rdelays.setChecked(settings.record_delays)
        self.rmin_win = QCheckBox("Minimizar o Shift Macro ao começar a gravar")
        self.rmin_win.setChecked(settings.record_minimize)
        rf.addRow("Gravar", self.rmode)
        rf.addRow("", self.rmoves)
        rf.addRow("Intervalo mínimo entre movimentos", self.rmin)
        rf.addRow("", self.rdelays)
        rf.addRow("", self.rmin_win)
        tabs.addTab(r, "Gravação")
        tabs.setCurrentIndex(tab)

        lay.addWidget(_buttons(self, "Salvar"))
        self.resize(560, 420)

    def accept(self):
        seen: dict[str, str] = {}
        for key, f in self.hk.items():
            v = f.text()
            if not v:
                continue
            try:
                norm = parse_hotkey(v)
            except ValueError as e:
                self.hk_error.setText(f"{HOTKEY_LABELS[key]}: {e}")
                return
            if norm in seen:
                self.hk_error.setText(f"{HOTKEY_LABELS[key]} usa o mesmo atalho de {HOTKEY_LABELS[seen[norm]]}.")
                return
            seen[norm] = key  # type: ignore[index]
        s = self.s
        s.theme = self.theme.currentData()
        s.autosave_seconds = self.autosave.value()
        s.failsafe = self.failsafe.isChecked()
        s.follow_current = self.follow.isChecked()
        s.auto_update = self.auto_update.isChecked()
        s.log_max = self.logmax.value()
        s.hotkeys = {k: f.text() for k, f in self.hk.items()}
        s.record_mode = self.rmode.currentData()
        s.record_moves = self.rmoves.isChecked()
        s.record_min_move_ms = self.rmin.value()
        s.record_delays = self.rdelays.isChecked()
        s.record_minimize = self.rmin_win.isChecked()
        super().accept()


# ================================================================== macro
class MacroPropertiesDialog(QDialog):
    def __init__(self, macro: Macro, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Propriedades da macro")
        self.macro = macro
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        f = QFormLayout()
        f.setVerticalSpacing(10)
        self.name = QLineEdit(macro.name)
        self.desc = QPlainTextEdit(macro.description)
        self.desc.setFixedHeight(90)
        f.addRow("Nome", self.name)
        f.addRow("Descrição", self.desc)
        lay.addLayout(f)
        box = QLabel("Atalhos só desta macro")
        box.setObjectName("sectionTitle")
        lay.addSpacing(6)
        lay.addWidget(box)
        hint = QLabel("Ficam salvos no arquivo e valem enquanto ela estiver aberta. Vazio usa o atalho geral.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        hf = QFormLayout()
        self.hk: dict[str, HotkeyField] = {}
        for key, label in HOTKEY_LABELS.items():
            w = HotkeyField(macro.hotkeys.get(key, ""))
            self.hk[key] = w
            hf.addRow(label, w)
        lay.addLayout(hf)
        self.err = QLabel("")
        self.err.setObjectName("error")
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self))
        self.resize(520, 480)

    def accept(self):
        for key, w in self.hk.items():
            if w.text():
                try:
                    parse_hotkey(w.text())
                except ValueError as e:
                    self.err.setText(f"{HOTKEY_LABELS[key]}: {e}")
                    return
        self.macro.name = self.name.text().strip() or "Macro"
        self.macro.description = self.desc.toPlainText().strip()
        self.macro.hotkeys = {k: w.text() for k, w in self.hk.items() if w.text()}
        super().accept()


class VariablesDialog(QDialog):
    def __init__(self, macro: Macro, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Variáveis iniciais")
        self.macro = macro
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        hint = QLabel("Valores com que cada execução começa. Números viram números; o resto, texto. "
                      "Durante a execução, veja os valores atuais na aba Variáveis do painel inferior.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        lay.addWidget(hint)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Nome", "Valor inicial"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        for k, v in macro.variables.items():
            self._add(k, v)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Adicionar")
        add.clicked.connect(lambda: self._add("", ""))
        rem = QPushButton("Remover")
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)
        self.err = QLabel("")
        self.err.setObjectName("error")
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self))
        self.resize(480, 400)

    def _add(self, k, v):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(str(k)))
        self.table.setItem(r, 1, QTableWidgetItem("" if v is None else str(v)))
        if not k:
            self.table.editItem(self.table.item(r, 0))

    def accept(self):
        out = {}
        for r in range(self.table.rowCount()):
            k = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            v = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            if not k:
                continue
            if not expr.VAR_NAME.match(k):
                self.err.setText(f"Nome inválido: “{k}”. Use letras, números e _ (sem espaços, sem começar com número).")
                return
            val: object = v
            try:
                val = int(v)
            except ValueError:
                try:
                    val = float(v.replace(",", "."))
                except ValueError:
                    pass
            out[k] = val
        self.macro.variables = out
        super().accept()


class ImagesDialog(QDialog):
    def __init__(self, macro: Macro, host, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imagens da macro")
        self.macro = macro
        self.host = host
        self.changed = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        self.list = QListWidget()
        self.list.setIconSize(QSize(96, 54))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("Recortar da tela", self._capture), ("Importar…", self._import), ("Renomear", self._rename),
                         ("Exportar PNG…", self._export), ("Excluir", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill()
        self.resize(560, 460)

    def _uses(self, name: str) -> int:
        n = 0
        for c in self.macro.commands:
            if c.params.get("image") == name:
                n += 1
        return n

    def _fill(self, select: str | None = None):
        self.list.clear()
        for name in sorted(self.macro.images):
            pm = QPixmap()
            pm.loadFromData(self.macro.images[name], "PNG")
            uses = self._uses(name)
            it = QListWidgetItem(QIcon(pm),f"{name}\n{pm.width()} × {pm.height()} px · " +
                                 (f"usada em {uses} etapa(s)" if uses else "não usada"))
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(it)
            if name == select:
                self.list.setCurrentItem(it)

    def _cur(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _capture(self):
        n = self.host.capture_image_from_screen(extra_hide=self)
        if n:
            self.changed = True
            self._fill(n)

    def _import(self):
        n = self.host.import_image_file()
        if n:
            self.changed = True
            self._fill(n)

    def _rename(self):
        old = self._cur()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Renomear imagem", "Novo nome:", text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        if not expr.VAR_NAME.match(new.replace("-", "_")):
            QMessageBox.warning(self, "Nome inválido", "Use letras, números, - e _.")
            return
        if new in self.macro.images:
            QMessageBox.warning(self, "Nome em uso", f"Já existe uma imagem “{new}”.")
            return
        self.host.before_change()
        self.macro.images[new] = self.macro.images.pop(old)
        for c in self.macro.commands:
            if c.params.get("image") == old:
                c.params["image"] = new
        self.changed = True
        self._fill(new)

    def _export(self):
        n = self._cur()
        if not n:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Exportar imagem", f"{n}.png", "PNG (*.png)")
        if p:
            with open(p, "wb") as f:
                f.write(self.macro.images[n])

    def _delete(self):
        n = self._cur()
        if not n:
            return
        uses = self._uses(n)
        msg = f"Excluir a imagem “{n}”?"
        if uses:
            msg += f"\n\nEla é usada em {uses} etapa(s), que ficarão sem imagem."
        if QMessageBox.question(self, "Excluir imagem", msg) != QMessageBox.StandardButton.Yes:
            return
        self.host.before_change()
        del self.macro.images[n]
        for c in self.macro.commands:
            if c.params.get("image") == n:
                c.params["image"] = ""
        self.changed = True
        self._fill()


# ================================================================== desligar
class ShutdownDialog(QDialog):
    SECONDS = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Desligar o computador")
        self.left = self.SECONDS
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        f = self.msg.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        self.msg.setFont(f)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        now = QPushButton("Desligar agora")
        now.setProperty("danger", True)
        now.clicked.connect(self.accept)
        cancel = QPushButton("Cancelar desligamento")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(now)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.timer = QTimer(self, interval=1000, timeout=self._tick)
        self.timer.start()
        self._tick(first=True)
        self.setMinimumWidth(420)

    def _tick(self, first=False):
        if not first:
            self.left -= 1
        if self.left <= 0:
            self.timer.stop()
            self.accept()
            return
        self.msg.setText(f"A macro terminou. O computador será desligado em <b>{self.left} s</b>. Salve o que estiver aberto.")

    @staticmethod
    def shutdown_now() -> None:
        subprocess.Popen(["shutdown", "/s", "/t", "0"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# ================================================================== ajuda
HELP_HTML = """
<h2>Guia rápido</h2>
<h3>1. Gravar</h3>
<p>Clique em <b>Gravar</b> (ou F9), faça a tarefa e pressione F9 de novo. Os cliques, teclas, textos,
rolagens e tempos viram etapas editáveis. Em <i>Gravar ▸</i> escolha gravar só cliques, só teclado ou
também os movimentos do mouse.</p>
<h3>2. Smart Click</h3>
<p>Em vez de clicar em uma coordenada fixa, o Smart Click procura uma <b>imagem</b> na tela e clica onde
ela estiver. Use <b>Shift+F11</b> em qualquer momento para recortar uma área da tela e criar a etapa.
Ajuste a similaridade, a região de busca e o que fazer quando encontrar ou não, e use
<b>Testar agora</b> para ver o resultado.</p>
<h3>3. Editar</h3>
<p>Duplo clique abre a etapa; o painel <b>Propriedades</b> à direita edita a etapa selecionada na hora.
Arraste linhas para reordenar, use a caixa de seleção para desativar uma etapa sem apagar e
Ctrl+Z para desfazer. Campos de posição aceitam variáveis: <code>found_x + 10</code>.</p>
<h3>4. Fluxo</h3>
<p><b>If / Else If / Else / End If</b>, <b>Loop</b> (0 = infinito), <b>While</b>, <b>Break</b>, <b>Continue</b>,
<b>Go To</b> com <b>Label</b> ou número da etapa, <b>Funções</b> e <b>Executar outra macro</b>.
Blocos ficam recuados; um bloco aberto sem fim aparece em vermelho na coluna Status.</p>
<h3>5. Variáveis</h3>
<p><b>Definir variável</b> aceita contas (<code>contador + 1</code>), textos entre aspas e funções
(<code>random(1, 6)</code>, <code>len</code>, <code>upper</code>). Em textos, use <code>{nome}</code>.
Variáveis prontas: <code>repeticao</code>, <code>found_x</code>, <code>found_y</code>,
<code>similaridade</code>, <code>cor_pixel</code>, <code>ultima_captura</code>.</p>
<h3>6. Executar</h3>
<p>Escolha no painel inferior: uma vez, N vezes, por um tempo ou sem parar; ajuste a velocidade.
<b>F6</b> executa, <b>F7</b> pausa/continua e <b>F8</b> para na hora, mesmo dentro de esperas e buscas
sem limite. O modo <b>Passo a passo</b> executa uma etapa por clique, para achar problemas.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None, hotkeys: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ajuda · Shift Macro")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        tb = QTextBrowser()
        t = theme.current()
        tb.setStyleSheet(f"QTextBrowser {{ border:none; padding: 14px 20px; background:{t.panel}; }}")
        hk = hotkeys or DEFAULT_HOTKEYS
        rows = "".join(f"<tr><td style='padding:3px 14px 3px 0'>{HOTKEY_LABELS[k]}</td><td><b>{v or '—'}</b></td></tr>"
                       for k, v in hk.items() if k in HOTKEY_LABELS)
        tb.setHtml(f"<div style='color:{t.text}'>{HELP_HTML}<h3>Atalhos globais atuais</h3><table>{rows}</table></div>")
        tb.setOpenExternalLinks(True)
        lay.addWidget(tb, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(640, 640)


def about(parent):
    QMessageBox.about(
        parent, "Sobre o Shift Macro",
        f"<h3>Shift Macro {__version__}</h3>"
        "<p>Gravação, edição e execução de macros para Windows, com reconhecimento de imagem.</p>"
        "<p>Funciona offline, sem conta e sem assinatura. A única conexão é a busca opcional por "
        "atualizações nas releases do GitHub.</p>"
        f"<p><a href='{REPO_URL}'>Código e versões no GitHub</a> · "
        f"<a href='{DONATE_URL}'>Apoiar o projeto no Ko-fi</a></p>"
        "<p style='color:gray'>Python, PySide6, OpenCV, MSS, PyAutoGUI e pynput.</p>",
    )
