"""Janela principal do Shift Macro."""
from __future__ import annotations

import base64
import copy
import json
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QItemSelectionModel, QMimeData, QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QDialog, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStatusBar, QSystemTrayIcon, QTableView, QTableWidget,
    QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, DONATE_URL, __version__
from ..actions import registry
from ..core.engine import Engine, RunResult
from ..core.model import Command, Macro
from ..core.structure import family_of
from ..recorder.convert import convert
from ..recorder.recorder import Recorder
from ..storage import appdata
from ..storage.project import EXTENSION, ProjectError, load_macro, save_macro
from ..utils import winapi
from ..vision import matcher
from . import dialogs, icons, overlay, theme, update_dialog
from .bridge import EngineBridge
from .delegates import StepDelegate
from .flow import FlowLayout
from .forms import CommandEditor
from .models import ACTION, DELAY, DESC, MIME_TYPE, STATUS, STEP, CommandTableModel, LogFilter, LogModel

MIME_CMDS = "application/x-shiftmacro-commands"
SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0]
CLOSER = {"if": "end_if", "loop": "end_loop", "while": "end_while", "function": "end_function"}
MAX_UNDO = 100


class CommandTree(QTreeWidget):
    """Barra lateral: comandos por categoria; arrastar para a tabela insere."""

    def mimeData(self, items):
        md = QMimeData()
        it = items[0] if items else None
        t = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        if t:
            md.setData(MIME_TYPE, t.encode())
        return md

    def mimeTypes(self):
        return [MIME_TYPE]


class PropertiesPanel(QWidget):
    edited = Signal()

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.editor: CommandEditor | None = None
        self.row: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        title = QLabel("Propriedades")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.scroll, 1)
        self.show_hint("Selecione uma etapa para ver e editar os detalhes.\n\nDuplo clique abre o editor completo.")

    def show_hint(self, text: str) -> None:
        self.editor = None
        self.row = None
        w = QLabel(text)
        w.setObjectName("hint")
        w.setWordWrap(True)
        w.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        w.setContentsMargins(0, 8, 0, 0)
        self.scroll.setWidget(w)

    def show_command(self, row: int, cmd: Command) -> None:
        self.row = row
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 6, 6, 6)
        self.editor = CommandEditor(cmd, self.host)
        self.editor.changed.connect(self.edited.emit)
        lay.addWidget(self.editor)
        if cmd.type in dialogs.IMAGE_TYPES:
            b = QPushButton(icons.icon("search", theme.current().text, 16), "Abrir Smart Click e testar…")
            b.clicked.connect(lambda: self.host.edit_row(row))
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        self.scroll.setWidget(holder)


class MainWindow(QMainWindow):
    hotkey_pressed = Signal(str)

    def __init__(self, settings: appdata.AppSettings, open_path: str | None = None):
        super().__init__()
        self.settings = settings
        self.macro = Macro()
        self.path: str | None = None
        self.dirty = False
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.engine: Engine | None = None
        self.run_rows: list[int] | None = None
        self.run_started = 0.0
        self.run_rep = (0, None)
        self.current_step: int | None = None
        self._inputs = None
        self.recorder: Recorder | None = None
        self.autosave = appdata.Autosave()
        self._props_snapshot_taken = False
        self._last_autosave_sig = None

        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(980, 620)
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks | QMainWindow.DockOption.AllowTabbedDocks)

        self.model = CommandTableModel(self.macro)
        self.model.toggled.connect(self.toggle_rows)
        self.model.move_requested.connect(self.move_rows)
        self.model.insert_type_requested.connect(lambda t, row: self.insert_type(t, at=row))
        self.model.delay_edited.connect(self._delay_edited)

        self.bridge = EngineBridge(self)
        self.bridge.flushed.connect(self._on_flush)
        self.bridge.state_changed.connect(self._on_engine_state)
        self.bridge.repetition.connect(self._on_repetition)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.notify.connect(self._show_notification)

        self.hotkeys = winapi.GlobalHotkeys(self._hotkey_thread)
        self.hotkey_pressed.connect(self._on_hotkey)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_central()
        self._build_docks()
        self._build_statusbar()
        self._build_tray()

        self.props_timer = QTimer(self, singleShot=True, interval=300, timeout=self._apply_properties)
        self.autosave_timer = QTimer(self, timeout=self._do_autosave)
        self._restart_autosave()
        self.run_clock = QTimer(self, interval=200, timeout=self._update_run_info)

        self._restore_geometry()
        self._register_hotkeys()
        self._refresh_all()
        QTimer.singleShot(0, lambda: self._startup(open_path))

    # ================================================================ construção
    def _act(self, text, slot, shortcut=None, icon=None, tip=None, checkable=False) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(icons.icon(icon, theme.current().text))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        if slot:
            a.triggered.connect(slot)
        return a

    def _build_actions(self):
        A = self._act
        self.a_new = A("Nova macro", self.new_macro, QKeySequence.StandardKey.New, "new", "Começar uma macro vazia (Ctrl+N)")
        self.a_open = A("Abrir…", self.open_dialog, QKeySequence.StandardKey.Open, "open", "Abrir um arquivo .shiftmacro (Ctrl+O)")
        self.a_save = A("Salvar", self.save, QKeySequence.StandardKey.Save, "save", "Salvar (Ctrl+S)")
        self.a_save_as = A("Salvar como…", self.save_as, "Ctrl+Shift+S")
        self.a_props = A("Propriedades da macro…", self.macro_properties)
        self.a_export_log = A("Exportar log…", self.export_log)
        self.a_quit = A("Sair", self.close, "Alt+F4")

        self.a_undo = A("Desfazer", self.undo, QKeySequence.StandardKey.Undo, "undo")
        self.a_redo = A("Refazer", self.redo, QKeySequence.StandardKey.Redo, "redo")
        self.a_cut = A("Recortar", self.cut, QKeySequence.StandardKey.Cut, "cut")
        self.a_copy = A("Copiar", self.copy, QKeySequence.StandardKey.Copy, "copy")
        self.a_paste = A("Colar", self.paste, QKeySequence.StandardKey.Paste, "paste")
        self.a_dup = A("Duplicar", self.duplicate, "Ctrl+D", "duplicate", "Duplicar as etapas selecionadas (Ctrl+D)")
        self.a_del = A("Excluir", self.delete_selected, QKeySequence.StandardKey.Delete, "delete", "Excluir as etapas selecionadas (Del)")
        self.a_up = A("Mover para cima", lambda: self.move_selected(-1), "Ctrl+Up", "up", "Mover para cima (Ctrl+↑)")
        self.a_down = A("Mover para baixo", lambda: self.move_selected(1), "Ctrl+Down", "down", "Mover para baixo (Ctrl+↓)")
        self.a_toggle = A("Ativar/desativar", self.toggle_selected, "Ctrl+E", "toggle", "Ativar ou desativar as etapas (Ctrl+E)")
        self.a_edit = A("Editar etapa…", lambda: self.edit_row(self.current_row()), "Return", "edit")
        self.a_select_all = A("Selecionar tudo", lambda: self.table.selectAll(), QKeySequence.StandardKey.SelectAll)

        self.a_record = A("Gravar", self.toggle_record, None, "record", "Gravar mouse e teclado (F9)", checkable=True)
        self.a_smart = A("Smart Click", self.smart_click_capture, None, "smart", "Recortar uma imagem da tela e criar um Smart Click (Shift+F11)")
        self.a_run = A("Executar", lambda: self.run(), None, "play", "Executar a macro (F6)")
        self.a_run_from = A("Executar a partir da etapa selecionada", self.run_from_selected)
        self.a_run_sel = A("Executar somente as selecionadas", self.run_selected)
        self.a_step = A("Passo a passo", self.step, "F10", "step", "Executar uma etapa por vez (F10)")
        self.a_pause = A("Pausar", self.toggle_pause, None, "pause", "Pausar ou continuar (F7)")
        self.a_stop = A("Parar", self.stop, None, "stop", "Parar imediatamente (F8)")
        self.a_pick = A("Pegar coordenadas e cor…", self.pick_coords, None, "crosshair")
        self.a_vars = A("Variáveis iniciais…", self.edit_variables, None, "variable")
        self.a_images = A("Imagens da macro…", self.manage_images, None, "image")
        self.a_check = A("Verificar estrutura", self.check_structure, None, "check")

        self.a_prefs = A("Preferências…", lambda: self.preferences(0), "Ctrl+,", "settings")
        self.a_hotkeys = A("Atalhos globais…", lambda: self.preferences(1))
        self.a_rec_opts = A("Opções de gravação…", lambda: self.preferences(2))
        self.a_help = A("Guia rápido", self.show_help, "F1", "help")
        self.a_update = A("Verificar atualizações…", lambda: update_dialog.run_check(self, manual=True), None, "update")
        self.a_donate = A("Apoiar o projeto", self.donate, None, "heart",
                          "O Shift Macro é gratuito. Se ele te poupa tempo, considere apoiar no Ko-fi.")
        self.a_about = A("Sobre o Shift Macro", lambda: dialogs.about(self))

        self.rec_mode_group = QActionGroup(self)
        self.rec_mode_actions = {}
        for key, label in (("all", "Mouse e teclado"), ("clicks", "Somente cliques"), ("keyboard", "Somente teclado")):
            a = QAction(label, self, checkable=True)
            a.setData(key)
            a.setChecked(self.settings.record_mode == key)
            a.triggered.connect(lambda _=False, k=key: self._set_record_mode(k))
            self.rec_mode_group.addAction(a)
            self.rec_mode_actions[key] = a
        self.a_rec_moves = QAction("Gravar movimentos do mouse", self, checkable=True)
        self.a_rec_moves.setChecked(self.settings.record_moves)
        self.a_rec_moves.toggled.connect(self._set_record_moves)

        self.for_edit = [self.a_undo, self.a_redo, self.a_cut, self.a_paste, self.a_dup, self.a_del, self.a_up,
                         self.a_down, self.a_toggle, self.a_edit, self.a_new, self.a_open, self.a_record, self.a_smart,
                         self.a_vars, self.a_images, self.a_props]
        # atalhos de edição de etapas só valem com o foco na tabela: Del, Enter ou
        # Ctrl+C num campo do painel de propriedades editam o campo, não a macro
        self.table_scoped = [self.a_edit, self.a_del, self.a_cut, self.a_copy, self.a_paste, self.a_select_all,
                             self.a_up, self.a_down, self.a_dup, self.a_toggle]
        for a in self.findChildren(QAction):
            if a in self.table_scoped:
                a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            else:
                self.addAction(a)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Arquivo")
        m.addActions([self.a_new, self.a_open])
        self.recent_menu = m.addMenu("Abrir recente")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        m.addActions([self.a_save, self.a_save_as])
        m.addSeparator()
        m.addActions([self.a_props, self.a_export_log])
        m.addSeparator()
        m.addAction(self.a_quit)

        m = mb.addMenu("&Editar")
        m.addActions([self.a_undo, self.a_redo])
        m.addSeparator()
        m.addActions([self.a_cut, self.a_copy, self.a_paste, self.a_dup, self.a_del])
        m.addSeparator()
        m.addActions([self.a_edit, self.a_toggle, self.a_up, self.a_down])
        m.addSeparator()
        m.addAction(self.a_select_all)

        self.insert_menu = mb.addMenu("&Inserir")
        self._fill_insert_menu(self.insert_menu)

        m = mb.addMenu("&Ferramentas")
        m.addAction(self.a_record)
        rm = m.addMenu("Modo de gravação")
        rm.addActions(list(self.rec_mode_actions.values()))
        rm.addSeparator()
        rm.addAction(self.a_rec_moves)
        m.addAction(self.a_smart)
        m.addAction(self.a_pick)
        m.addSeparator()
        m.addActions([self.a_run, self.a_run_from, self.a_run_sel, self.a_step, self.a_pause, self.a_stop])
        m.addSeparator()
        m.addActions([self.a_vars, self.a_images, self.a_check])

        self.view_menu = mb.addMenu("&Visualização")
        tg = QActionGroup(self)
        self.a_dark = QAction("Tema escuro", self, checkable=True)
        self.a_light = QAction("Tema claro", self, checkable=True)
        for a, name in ((self.a_dark, "dark"), (self.a_light, "light")):
            tg.addAction(a)
            a.setChecked(self.settings.theme == name)
            a.triggered.connect(lambda _=False, n=name: self.set_theme(n))
        self.view_menu.addActions([self.a_dark, self.a_light])
        self.view_menu.addSeparator()

        m = mb.addMenu("&Configurações")
        m.addActions([self.a_prefs, self.a_hotkeys, self.a_rec_opts])

        m = mb.addMenu("Aj&uda")
        m.addActions([self.a_help, self.a_update])
        m.addSeparator()
        m.addActions([self.a_donate, self.a_about])

    def _fill_insert_menu(self, menu: QMenu):
        menu.clear()
        for cat, specs in registry.by_category().items():
            sub = menu.addMenu(cat)
            for s in specs:
                a = sub.addAction(icons.icon(s.kind, theme.current().kinds.get(s.kind), 16), s.label)
                a.triggered.connect(lambda _=False, t=s.type: self.insert_type(t))

    def _build_toolbar(self):
        tb = QToolBar("Ferramentas")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.addSeparator()

        rec_menu = QMenu(self)
        rec_menu.addActions(list(self.rec_mode_actions.values()))
        rec_menu.addSeparator()
        rec_menu.addAction(self.a_rec_moves)
        rec_menu.addAction(self.a_rec_opts)
        self.rec_btn = QToolButton()
        self.rec_btn.setObjectName("recordButton")
        self.rec_btn.setDefaultAction(self.a_record)
        self.rec_btn.setMenu(rec_menu)
        self.rec_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.rec_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_record.setIcon(icons.icon("record", theme.current().record))
        tb.addWidget(self.rec_btn)
        tb.addAction(self.a_smart)
        tb.addSeparator()

        run_menu = QMenu(self)
        run_menu.addActions([self.a_run, self.a_run_from, self.a_run_sel, self.a_step])
        self.run_btn = QToolButton()
        self.run_btn.setObjectName("runButton")
        self.run_btn.setDefaultAction(self.a_run)
        self.run_btn.setMenu(run_menu)
        self.run_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.run_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_run.setIcon(icons.icon("play", theme.current().run))
        tb.addWidget(self.run_btn)
        tb.addAction(self.a_pause)
        tb.addAction(self.a_stop)
        self.a_stop.setIcon(icons.icon("stop", theme.current().record))
        tb.addAction(self.a_step)
        tb.widgetForAction(self.a_step).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.addSeparator()
        for a in (self.a_dup, self.a_up, self.a_down, self.a_del):
            tb.addAction(a)
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.macro_label = QLabel()
        self.macro_label.setObjectName("muted")
        self.macro_label.setContentsMargins(0, 0, 8, 0)
        tb.addWidget(self.macro_label)
        tb.addSeparator()
        self.donate_btn = QToolButton()
        self.donate_btn.setObjectName("donateButton")
        self.donate_btn.setDefaultAction(self.a_donate)
        self.donate_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.a_donate.setIconText("Apoiar")  # texto curto no botão; o menu mostra o nome completo
        self.a_donate.setIcon(icons.icon("heart", theme.current().record))
        tb.addWidget(self.donate_btn)
        self.toolbar = tb

    def _build_central(self):
        t = theme.current()
        # barra lateral
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(8, 8, 0, 8)
        sl.setSpacing(6)
        st = QLabel("Comandos")
        st.setObjectName("sectionTitle")
        sl.addWidget(st)
        self.cmd_search = QLineEdit()
        self.cmd_search.setPlaceholderText("Procurar comando…")
        self.cmd_search.setClearButtonEnabled(True)
        self.cmd_search.textChanged.connect(self._filter_tree)
        sl.addWidget(self.cmd_search)
        self.tree = CommandTree()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.itemActivated.connect(self._tree_activated)
        self.tree.setToolTip("Duplo clique ou arraste para a tabela")
        sl.addWidget(self.tree, 1)
        self._fill_tree()
        side.setMinimumWidth(190)

        # tabela
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 8, 0, 0)
        ml.setSpacing(0)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(StepDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.table.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.table.setDragDropOverwriteMode(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.doubleClicked.connect(lambda idx: self.edit_row(idx.row()) if idx.column() != DELAY else None)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(STEP, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(ACTION, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(DESC, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(DELAY, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(STATUS, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(STEP, 66)
        self.table.setColumnWidth(ACTION, 200)
        self.table.setColumnWidth(DELAY, 78)
        self.table.setColumnWidth(STATUS, 150)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.addActions(self.table_scoped)
        ml.addWidget(self.table, 1)
        self.empty_hint = QLabel(
            "A macro está vazia.\n\nGrave com F9, recorte um Smart Click com Shift+F11\n"
            "ou dê duplo clique num comando à esquerda.")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setParent(self.table.viewport())
        self.empty_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # propriedades
        self.props = PropertiesPanel(self)
        self.props.edited.connect(self._props_edited)
        self.props.setMinimumWidth(280)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(side)
        self.splitter.addWidget(mid)
        self.splitter.addWidget(self.props)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 760, 340])
        self.splitter.setChildrenCollapsible(False)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.splitter, 1)
        cl.addWidget(self._build_run_panel())
        self.setCentralWidget(central)

    def _build_run_panel(self) -> QWidget:
        f = QFrame()
        f.setObjectName("runPanel")
        flow = FlowLayout(f, hspacing=18, vspacing=6)
        flow.setContentsMargins(12, 8, 12, 8)

        def group(*widgets, spacing=8) -> QWidget:
            g = QWidget()
            h = QHBoxLayout(g)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(spacing)
            for w in widgets:
                h.addWidget(w)
            return g

        def title(text):
            lab = QLabel(text)
            lab.setObjectName("sectionTitle")
            return lab

        def muted(text):
            lab = QLabel(text)
            lab.setObjectName("muted")
            return lab

        self.rep_group = QButtonGroup(self)
        self.r_once = QRadioButton("Uma vez")
        self.r_count = QRadioButton("")
        self.r_count.setToolTip("Repetir um número de vezes")
        self.s_count = QSpinBox()
        self.s_count.setRange(1, 1_000_000)
        self.s_count.setFixedWidth(72)
        self.r_duration = QRadioButton("Por")
        self.s_minutes = QDoubleSpinBox()
        self.s_minutes.setRange(0.05, 100_000)
        self.s_minutes.setDecimals(1)
        self.s_minutes.setFixedWidth(72)
        self.r_infinite = QRadioButton("Sem parar")
        for i, (r, key) in enumerate(((self.r_once, "once"), (self.r_count, "count"), (self.r_duration, "duration"), (self.r_infinite, "infinite"))):
            self.rep_group.addButton(r, i)
            r.setProperty("mode", key)
        self.rep_group.buttonToggled.connect(lambda *_: self._run_settings_changed())
        self.s_count.valueChanged.connect(lambda *_: (self.r_count.setChecked(True), self._run_settings_changed()))
        self.s_minutes.valueChanged.connect(lambda *_: (self.r_duration.setChecked(True), self._run_settings_changed()))
        flow.addWidget(group(
            title("Repetir"), self.r_once,
            group(self.r_count, self.s_count, muted("vezes"), spacing=4),
            group(self.r_duration, self.s_minutes, muted("min"), spacing=4),
            self.r_infinite, spacing=14,
        ))

        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(0, len(SPEEDS) - 1)
        self.speed.setFixedWidth(100)
        self.speed.setPageStep(1)
        self.speed.setToolTip("Multiplica o ritmo dos delays. Tempo limite de busca de imagem não muda.")
        self.speed_label = QLabel("1×")
        self.speed_label.setMinimumWidth(40)
        self.speed_label.setFont(theme.mono_font(9))
        self.speed.valueChanged.connect(lambda *_: self._run_settings_changed())
        flow.addWidget(group(title("Velocidade"), self.speed, self.speed_label))

        self.c_minimize = QCheckBox("Minimizar ao executar")
        self.c_shutdown = QCheckBox("Desligar ao terminar")
        self.c_minimize.toggled.connect(lambda *_: self._run_settings_changed())
        self.c_shutdown.clicked.connect(self._shutdown_toggled)
        flow.addWidget(group(self.c_minimize, self.c_shutdown, spacing=16))

        self.run_info = QLabel("Pronto")
        self.run_info.setObjectName("counter")
        self.run_info.setFont(theme.mono_font(9))
        self.run_info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.run_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.run_info.setMinimumWidth(230)
        flow.addWidget(self.run_info)
        return f

    def _build_docks(self):
        # log
        logw = QWidget()
        ll = QVBoxLayout(logw)
        ll.setContentsMargins(8, 6, 8, 6)
        ll.setSpacing(6)
        bar = QHBoxLayout()
        self.log_problems = QCheckBox("Só avisos e erros")
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Filtrar…")
        self.log_search.setClearButtonEnabled(True)
        self.log_search.setMaximumWidth(240)
        b_clear = QPushButton("Limpar")
        b_clear.setProperty("flat", True)
        b_export = QPushButton("Exportar…")
        b_export.setProperty("flat", True)
        b_clear.clicked.connect(lambda: self.log_model.clear())
        b_export.clicked.connect(self.export_log)
        bar.addWidget(self.log_problems)
        bar.addWidget(self.log_search)
        bar.addStretch(1)
        bar.addWidget(b_clear)
        bar.addWidget(b_export)
        ll.addLayout(bar)
        self.log_model = LogModel(self.settings.log_max)
        self.log_filter = LogFilter()
        self.log_filter.setSourceModel(self.log_model)
        self.log_problems.toggled.connect(lambda *_: self.log_filter.set_filter(self.log_problems.isChecked(), self.log_search.text()))
        self.log_search.textChanged.connect(lambda *_: self.log_filter.set_filter(self.log_problems.isChecked(), self.log_search.text()))
        self.log_view = QTableView()
        self.log_view.setModel(self.log_filter)
        self.log_view.verticalHeader().hide()
        self.log_view.verticalHeader().setDefaultSectionSize(22)
        self.log_view.setShowGrid(False)
        self.log_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_view.setWordWrap(False)
        lh = self.log_view.horizontalHeader()
        lh.setHighlightSections(False)
        for i, w in enumerate((104, 44, 52, 150, 0, 92, 96, 70)):
            if w:
                self.log_view.setColumnWidth(i, w)
        lh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.log_view.clicked.connect(self._log_clicked)
        ll.addWidget(self.log_view, 1)

        # variáveis
        self.vars_table = QTableWidget(0, 2)
        self.vars_table.setHorizontalHeaderLabels(["Variável", "Valor atual"])
        self.vars_table.verticalHeader().hide()
        self.vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.vars_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vars_table.setShowGrid(False)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(logw, "Log de execução")
        tabs.addTab(self.vars_table, "Variáveis")
        self.bottom_tabs = tabs
        dock = QDockWidget("Execução", self)
        dock.setObjectName("logDock")
        dock.setWidget(tabs)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [200], Qt.Orientation.Vertical)
        self.log_dock = dock

        a = dock.toggleViewAction()
        a.setText("Log e variáveis")
        a.setShortcut("Ctrl+L")
        self.view_menu.addAction(a)
        self.a_show_side = QAction("Barra de comandos", self, checkable=True, checked=True)
        self.a_show_side.toggled.connect(lambda v: self.splitter.widget(0).setVisible(v))
        self.a_show_props = QAction("Propriedades", self, checkable=True, checked=True)
        self.a_show_props.toggled.connect(self.props.setVisible)
        self.a_follow = QAction("Seguir a etapa em execução", self, checkable=True, checked=self.settings.follow_current)
        self.a_follow.toggled.connect(lambda v: setattr(self.settings, "follow_current", v))
        self.view_menu.addActions([self.a_show_side, self.a_show_props, self.a_follow])

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.rec_indicator = QLabel("")
        self.rec_indicator.setStyleSheet(f"color:{theme.current().record}; font-weight:600;")
        self.structure_label = QPushButton("")
        self.structure_label.setProperty("flat", True)
        self.structure_label.clicked.connect(self.check_structure)
        self.hotkey_label = QLabel("")
        self.hotkey_label.setObjectName("muted")
        sb.addPermanentWidget(self.rec_indicator)
        sb.addPermanentWidget(self.structure_label)
        sb.addPermanentWidget(self.hotkey_label)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        m.addAction("Mostrar janela", self._show_normal)
        m.addSeparator()
        m.addAction(self.a_run)
        m.addAction(self.a_pause)
        m.addAction(self.a_stop)
        m.addSeparator()
        m.addAction("Sair", self.close)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self._show_normal() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    # ================================================================ árvore de comandos
    def _fill_tree(self):
        self.tree.clear()
        t = theme.current()
        for cat, specs in registry.by_category().items():
            top = QTreeWidgetItem([cat])
            f = top.font(0)
            f.setWeight(f.Weight.DemiBold)
            top.setFont(0, f)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for s in specs:
                it = QTreeWidgetItem([s.label])
                it.setIcon(0, icons.icon(s.kind, t.kinds.get(s.kind), 16))
                it.setData(0, Qt.ItemDataRole.UserRole, s.type)
                it.setToolTip(0, f"{s.label} — duplo clique para inserir")
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                top.addChild(it)
            top.setExpanded(cat in ("Mouse", "Teclado", "Imagem e tela", "Controle de fluxo"))

    def _filter_tree(self, text: str):
        q = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            any_vis = False
            for j in range(top.childCount()):
                ch = top.child(j)
                vis = not q or q in ch.text(0).lower() or q in top.text(0).lower()
                ch.setHidden(not vis)
                any_vis = any_vis or vis
            top.setHidden(not any_vis)
            if q:
                top.setExpanded(True)

    def _tree_activated(self, item, _col):
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if t:
            self.insert_type(t)

    # ================================================================ estado / seleção
    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def current_row(self) -> int | None:
        rows = self.selected_rows()
        if rows:
            return rows[0]
        idx = self.table.currentIndex()
        return idx.row() if idx.isValid() else None

    def select_rows(self, rows: list[int], scroll: bool = True):
        sm = self.table.selectionModel()
        sm.clearSelection()
        n = self.model.rowCount()
        rows = [r for r in rows if 0 <= r < n]
        if rows:
            # define o item atual sem mexer na seleção (setCurrentIndex do
            # QTableView limparia as outras linhas selecionadas)
            sm.setCurrentIndex(self.model.index(rows[0], DESC), QItemSelectionModel.SelectionFlag.NoUpdate)
        for r in rows:
            sm.select(self.model.index(r, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        if rows:
            if scroll:
                self.table.scrollTo(self.model.index(rows[-1], 0))
                self.table.scrollTo(self.model.index(rows[0], 0))

    def _selection_changed(self, *_):
        self._flush_props()
        self._update_props()
        self._update_actions()

    def _update_props(self):
        rows = self.selected_rows()
        if self.is_running():
            self.props.setEnabled(False)
        else:
            self.props.setEnabled(True)
        self._props_snapshot_taken = False
        if len(rows) == 1 and rows[0] < len(self.macro.commands):
            self.props.show_command(rows[0], self.macro.commands[rows[0]])
        elif len(rows) > 1:
            self.props.show_hint(f"{len(rows)} etapas selecionadas.\n\nCtrl+D duplica, Ctrl+E ativa/desativa, "
                                 "Ctrl+↑/↓ move, Del exclui. Selecione duas ou mais etapas e insira um Loop ou If "
                                 "para envolvê-las no bloco.")
        else:
            self.props.show_hint("Selecione uma etapa para ver e editar os detalhes.\n\nDuplo clique abre o editor completo.")

    def _props_edited(self):
        self.props_timer.start()

    def _apply_properties(self):
        ed, row = self.props.editor, self.props.row
        if ed is None or row is None or row >= len(self.macro.commands) or self.is_running():
            return
        new = ed.result()
        old = self.macro.commands[row]
        if new.to_dict() == old.to_dict():
            return
        if not self._props_snapshot_taken:
            self.before_change()
            self._props_snapshot_taken = True
        self.macro.commands[row] = new
        ed.cmd = new
        self.model.refresh_rows([row])
        self._mark_dirty()
        self._refresh_status()

    def is_running(self) -> bool:
        return bool(self.engine and self.engine.running)

    def is_recording(self) -> bool:
        return bool(self.recorder and self.recorder.running)

    def _update_actions(self):
        running = self.is_running()
        recording = self.is_recording()
        busy = running or recording
        has_sel = bool(self.selected_rows())
        for a in self.for_edit:
            a.setEnabled(not running)
        self.a_record.setEnabled(not running)
        self.a_undo.setEnabled(not busy and bool(self.undo_stack))
        self.a_redo.setEnabled(not busy and bool(self.redo_stack))
        for a in (self.a_cut, self.a_copy, self.a_dup, self.a_del, self.a_up, self.a_down, self.a_toggle, self.a_edit, self.a_run_sel):
            a.setEnabled(has_sel and not busy)
        self.a_copy.setEnabled(has_sel)
        self.a_run_from.setEnabled(has_sel and not busy)
        self.a_run.setEnabled(not busy)
        self.a_step.setEnabled(not recording and (not running or self.engine.paused))
        self.a_pause.setEnabled(running)
        self.a_stop.setEnabled(running or recording)
        self.a_pause.setText("Continuar" if running and self.engine.paused else "Pausar")
        self.a_pause.setIcon(icons.icon("play" if running and self.engine.paused else "pause", theme.current().text))
        self.table.setDragEnabled(not busy)
        self.table.setAcceptDrops(not busy)
        self.tree.setEnabled(not running)
        self.insert_menu.setEnabled(not running)
        for w in (self.r_once, self.r_count, self.r_duration, self.r_infinite, self.s_count, self.s_minutes):
            w.setEnabled(not running)

    def _refresh_all(self):
        self.model.set_macro(self.macro)
        self._load_run_settings()
        self._update_title()
        self._refresh_status()
        self._update_props()
        self._update_actions()
        self._position_empty_hint()

    def _refresh_status(self):
        st = self.model.structure
        t = theme.current()
        if st.errors:
            n = len(st.errors)
            self.structure_label.setText(f"{n} problema{'s' if n > 1 else ''} na estrutura")
            self.structure_label.setStyleSheet(f"color:{t.error}; font-weight:600;")
            self.structure_label.setToolTip("\n".join(f"Etapa {i + 1}: {m}" for i, m in st.errors[:12]))
        else:
            n = len(self.macro.commands)
            self.structure_label.setText(f"{n} etapa{'s' if n != 1 else ''}")
            self.structure_label.setStyleSheet(f"color:{t.muted};")
            self.structure_label.setToolTip("Estrutura sem problemas")
        self.empty_hint.setVisible(not self.macro.commands)
        self._position_empty_hint()

    def _position_empty_hint(self):
        vp = self.table.viewport()
        self.empty_hint.setGeometry(0, 0, vp.width(), vp.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._position_empty_hint()

    def _update_title(self):
        name = self.macro.name or "Macro"
        file = Path(self.path).name if self.path else "não salva"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — {APP_NAME}")
        self.macro_label.setText(f"{name}  ·  {file}")

    def _mark_dirty(self):
        self.dirty = True
        self._update_title()
        self._update_actions()

    # ================================================================ desfazer
    def _snapshot(self) -> dict:
        return {
            "macro": self.macro.to_dict(),
            "images": dict(self.macro.images),
            "selection": self.selected_rows(),
        }

    def _flush_props(self):
        """Aplica uma edição do painel que ainda esperava o atraso de digitação."""
        if self.props_timer.isActive():
            self.props_timer.stop()
            self._apply_properties()

    def _restore(self, snap: dict):
        self.props.editor = None  # o painel antigo não pode reaplicar valores velhos
        m = Macro.from_dict(snap["macro"], snap["images"])
        self.macro.commands = m.commands
        self.macro.images = m.images
        self.macro.variables = m.variables
        self.macro.name, self.macro.description, self.macro.hotkeys = m.name, m.description, m.hotkeys
        self.macro.settings = m.settings
        self.model.refresh()
        self._load_run_settings()
        self.select_rows(snap.get("selection") or [])
        self._mark_dirty()
        self._refresh_status()

    def before_change(self):
        """Guarda o estado atual para Desfazer. Chamado antes de toda alteração."""
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()

    def undo(self):
        self._flush_props()
        if not self.undo_stack or self.is_running():
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())
        self.statusBar().showMessage("Desfeito", 2000)

    def redo(self):
        self._flush_props()
        if not self.redo_stack or self.is_running():
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())
        self.statusBar().showMessage("Refeito", 2000)

    def _after_edit(self, select: list[int]):
        self.model.refresh()
        self.select_rows(select)
        self._mark_dirty()
        self._refresh_status()
        self._update_props()

    # ================================================================ edição
    def _insert_at(self) -> int:
        rows = self.selected_rows()
        return (max(rows) + 1) if rows else len(self.macro.commands)

    def insert_commands(self, cmds: list[Command], at: int | None = None, snapshot: bool = True):
        if not cmds:
            return
        if snapshot:
            self.before_change()
        at = self._insert_at() if at is None else max(0, min(at, len(self.macro.commands)))
        self.macro.commands[at:at] = cmds
        self._after_edit(list(range(at, at + len(cmds))))

    def insert_type(self, type_: str, at: int | None = None):
        if self.is_running():
            return
        spec = registry.get(type_)
        cmd = registry.make(type_)
        sel = self.selected_rows()
        wrap = (at is None and spec.block == "open" and len(sel) >= 2 and sel == list(range(sel[0], sel[-1] + 1)))
        if spec.fields:
            d = dialogs.edit_dialog_for(cmd, self, self)
            if d.exec() != QDialog.DialogCode.Accepted:
                return
            cmd = d.result_command()
        closer = None
        fam = family_of(cmd)
        if fam:
            closer = registry.make(CLOSER[fam])
        self.before_change()
        if wrap and closer:
            self.macro.commands.insert(sel[-1] + 1, closer)
            self.macro.commands.insert(sel[0], cmd)
            self._after_edit([sel[0]])
            self.statusBar().showMessage(f"{len(sel)} etapas colocadas dentro de {spec.label}", 4000)
            return
        cmds = [cmd] + ([closer] if closer else [])
        if closer and fam == "if" and cmd.type != "if":
            # Smart Click com bloco: deixa um Else pronto quando "senão" usa bloco
            if cmd.params.get("on_not_found") == "else":
                cmds = [cmd, registry.make("else"), closer]
        self.insert_commands(cmds, at, snapshot=False)
        self.select_rows([self.macro.commands.index(cmd)])

    def edit_row(self, row: int | None):
        if row is None or row >= len(self.macro.commands) or self.is_running():
            return
        if self.props_timer.isActive():
            self.props_timer.stop()
            self._apply_properties()
        cmd = self.macro.commands[row]
        try:
            registry.get(cmd.type)
        except KeyError:
            QMessageBox.warning(self, APP_NAME, f"O tipo de comando “{cmd.type}” não existe nesta versão.")
            return
        d = dialogs.edit_dialog_for(cmd, self, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            # imagens recortadas no diálogo continuam na macro (Desfazer remove)
            self._update_props()
            return
        new = d.result_command()
        if new.to_dict() == cmd.to_dict():
            return
        self.before_change()
        self.macro.commands[row] = new
        self._after_edit([row])

    def delete_selected(self):
        rows = self.selected_rows()
        if not rows or self.is_running():
            return
        self.before_change()
        for r in reversed(rows):
            del self.macro.commands[r]
        nxt = min(rows[0], len(self.macro.commands) - 1)
        self._after_edit([nxt] if nxt >= 0 else [])
        self.statusBar().showMessage(f"{len(rows)} etapa(s) excluída(s) · Ctrl+Z desfaz", 4000)

    def duplicate(self):
        rows = self.selected_rows()
        if not rows:
            return
        self.before_change()
        clones = [self.macro.commands[r].clone() for r in rows]
        at = rows[-1] + 1
        self.macro.commands[at:at] = clones
        self._after_edit(list(range(at, at + len(clones))))

    def move_selected(self, delta: int):
        rows = self.selected_rows()
        if not rows:
            return
        n = len(self.macro.commands)
        if (delta < 0 and rows[0] == 0) or (delta > 0 and rows[-1] == n - 1):
            return
        self.before_change()
        cmds = self.macro.commands
        if delta < 0:
            for r in rows:
                cmds[r - 1], cmds[r] = cmds[r], cmds[r - 1]
        else:
            for r in reversed(rows):
                cmds[r + 1], cmds[r] = cmds[r], cmds[r + 1]
        self._after_edit([r + delta for r in rows])

    def move_rows(self, rows: list[int], dest: int):
        if self.is_running():
            return
        rows = sorted(r for r in set(rows) if 0 <= r < len(self.macro.commands))
        if not rows:
            return
        if rows == list(range(rows[0], rows[-1] + 1)) and rows[0] <= dest <= rows[-1] + 1:
            return  # soltou no mesmo lugar
        self.before_change()
        moving = [self.macro.commands[r] for r in rows]
        before = sum(1 for r in rows if r < dest)
        for r in reversed(rows):
            del self.macro.commands[r]
        at = dest - before
        self.macro.commands[at:at] = moving
        self._after_edit(list(range(at, at + len(moving))))

    def toggle_rows(self, row: int):
        if self.is_running():
            return
        rows = self.selected_rows()
        if row not in rows:
            rows = [row]
        self.before_change()
        target = not self.macro.commands[row].enabled
        for r in rows:
            self.macro.commands[r].enabled = target
        self.model.refresh_rows(rows)
        self._mark_dirty()
        self._update_props()

    def toggle_selected(self):
        rows = self.selected_rows()
        if rows:
            self.toggle_rows(rows[0])

    def _delay_edited(self, row: int, ms: int):
        if self.macro.commands[row].delay_ms == ms:
            return
        self.before_change()
        rows = self.selected_rows() if row in self.selected_rows() else [row]
        for r in rows:
            self.macro.commands[r].delay_ms = ms
        self.model.refresh_rows(rows)
        self._mark_dirty()
        self._update_props()

    # ---------- área de transferência
    def copy(self):
        rows = self.selected_rows()
        if not rows:
            return
        cmds = [self.macro.commands[r] for r in rows]
        imgs = {}
        for c in cmds:
            n = c.params.get("image")
            if n and n in self.macro.images:
                imgs[n] = base64.b64encode(self.macro.images[n]).decode()
        payload = json.dumps({"commands": [c.to_dict() for c in cmds], "images": imgs})
        md = QMimeData()
        md.setData(MIME_CMDS, QByteArray(payload.encode()))
        lines = []
        for i, c in zip(rows, cmds):
            s = registry.get(c.type)
            lines.append(f"{i + 1}\t{s.label}\t{s.describe(c.params)}")
        md.setText("\n".join(lines))
        QGuiApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage(f"{len(cmds)} etapa(s) copiada(s)", 2500)

    def cut(self):
        self.copy()
        self.delete_selected()

    def paste(self):
        md = QGuiApplication.clipboard().mimeData()
        if not md or not md.hasFormat(MIME_CMDS) or self.is_running():
            return
        try:
            data = json.loads(bytes(md.data(MIME_CMDS)).decode())
            cmds = [Command.from_dict(d).clone() for d in data.get("commands", [])]
            images = {k: base64.b64decode(v) for k, v in (data.get("images") or {}).items()}
        except (ValueError, KeyError):
            return
        self.before_change()
        rename = {}
        for name, png in images.items():
            if name in self.macro.images and self.macro.images[name] != png:
                new = self.macro.unique_image_name(name + "_")
                rename[name] = new
                self.macro.images[new] = png
            else:
                self.macro.images[name] = png
        for c in cmds:
            if c.params.get("image") in rename:
                c.params["image"] = rename[c.params["image"]]
        self.insert_commands(cmds, snapshot=False)

    def _table_menu(self, pos):
        idx = self.table.indexAt(pos)
        if idx.isValid() and idx.row() not in self.selected_rows():
            self.select_rows([idx.row()], scroll=False)
        m = QMenu(self)
        m.addAction(self.a_edit)
        m.addSeparator()
        m.addAction(self.a_run_from)
        m.addAction(self.a_run_sel)
        m.addSeparator()
        m.addActions([self.a_cut, self.a_copy, self.a_paste, self.a_dup])
        m.addSeparator()
        m.addActions([self.a_toggle, self.a_up, self.a_down, self.a_del])
        m.addSeparator()
        ins = m.addMenu("Inserir")
        self._fill_insert_menu(ins)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ================================================================ imagens (EditorHost)
    def top_window(self):
        return self

    def capture_image_from_screen(self, extra_hide=None) -> str | None:
        r = overlay.capture_image(self)
        if r is None:
            return None
        img, rect = r
        if img.shape[0] < 3 or img.shape[1] < 3:
            return None
        name = self.macro.unique_image_name("imagem")
        self.before_change()
        self.macro.images[name] = matcher.encode_png(img)
        self._mark_dirty()
        self.statusBar().showMessage(f"Imagem “{name}” recortada ({rect.w} × {rect.h} px em {rect.x}, {rect.y})", 5000)
        return name

    def import_image_file(self) -> str | None:
        p, _ = QFileDialog.getOpenFileName(self, "Importar imagem", self.settings.last_dir, "Imagens (*.png *.jpg *.jpeg *.bmp)")
        if not p:
            return None
        try:
            data = Path(p).read_bytes()
            img = matcher.decode_png(data)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Importar imagem", f"Não foi possível abrir a imagem: {e}")
            return None
        base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(p).stem)[:40] or "imagem"
        name = base if base not in self.macro.images else self.macro.unique_image_name(base + "_")
        self.before_change()
        self.macro.images[name] = matcher.encode_png(img)
        self._mark_dirty()
        return name

    def smart_click_capture(self):
        if self.is_running():
            return
        name = self.capture_image_from_screen()
        if not name:
            return
        cmd = registry.make("smart_click", image=name)
        d = dialogs.SmartClickDialog(cmd, self, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        cmd = d.result_command()
        cmds = [cmd]
        if family_of(cmd):
            cmds += ([registry.make("else")] if cmd.params.get("on_not_found") == "else" else []) + [registry.make("end_if")]
        self.insert_commands(cmds)

    def pick_coords(self):
        r = overlay.pick_point(self)
        if not r:
            return
        x, y, rgb = r
        QGuiApplication.clipboard().setText(f"{x}, {y}")
        self.statusBar().showMessage(f"Posição ({x}, {y}) · cor {matcher.to_hex(rgb)} — coordenadas copiadas", 8000)

    # ================================================================ arquivos
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"Salvar as alterações em “{self.macro.name}”?")
        save = box.addButton("Salvar", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Não salvar", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is cancel:
            return False
        if box.clickedButton() is save:
            return self.save()
        return True

    def new_macro(self):
        if self.is_running() or not self._confirm_discard():
            return
        self._set_macro(Macro(), None)

    def _set_macro(self, macro: Macro, path: str | None):
        self.macro = macro
        self.path = path
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._refresh_all()
        self._register_hotkeys()
        if macro.commands:
            self.select_rows([0])

    def open_dialog(self):
        if self.is_running() or not self._confirm_discard():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Abrir macro", self.settings.last_dir, f"Macros do Shift (*{EXTENSION});;JSON (*.json)")
        if p:
            self.open_path(p, confirm=False)

    def open_path(self, p: str, confirm: bool = True):
        if confirm and not self._confirm_discard():
            return
        try:
            m = load_macro(p)
        except (ProjectError, OSError) as e:
            QMessageBox.warning(self, "Abrir macro", str(e))
            return
        self._set_macro(m, str(Path(p).resolve()))
        self.settings.last_dir = str(Path(p).parent)
        self.settings.add_recent(p)
        self.settings.save()
        self.statusBar().showMessage(f"Aberta: {p}", 4000)

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        safe = "".join(ch for ch in self.macro.name if ch not in '<>:"/\\|?*').strip() or "macro"
        start = str(Path(self.settings.last_dir or Path.home() / "Documents") / f"{safe}{EXTENSION}")
        p, _ = QFileDialog.getSaveFileName(self, "Salvar macro", start, f"Macros do Shift (*{EXTENSION})")
        if not p:
            return False
        return self._write(p)

    def _write(self, p: str) -> bool:
        if self.props_timer.isActive():
            self.props_timer.stop()
            self._apply_properties()
        self._run_settings_changed()
        try:
            path = save_macro(self.macro, p)
        except OSError as e:
            QMessageBox.warning(self, "Salvar macro", f"Não foi possível salvar: {e.strerror or e}")
            return False
        self.path = str(path)
        self.dirty = False
        self.settings.last_dir = str(path.parent)
        self.settings.add_recent(path)
        self.settings.save()
        self._update_title()
        self.statusBar().showMessage(f"Salva em {path}", 4000)
        return True

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = self.settings.existing_recent()
        if not rec:
            a = self.recent_menu.addAction("Nenhum arquivo recente")
            a.setEnabled(False)
            return
        for p in rec:
            self.recent_menu.addAction(Path(p).name, lambda p=p: self.open_path(p)).setToolTip(p)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Limpar lista", lambda: (setattr(self.settings, "recent", []), self.settings.save()))

    def macro_properties(self):
        before = self._snapshot()
        d = dialogs.MacroPropertiesDialog(self.macro, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.undo_stack.append(before)
            self.redo_stack.clear()
            self._mark_dirty()
            self._register_hotkeys()

    def edit_variables(self):
        before = self._snapshot()
        if dialogs.VariablesDialog(self.macro, self).exec() == QDialog.DialogCode.Accepted:
            self.undo_stack.append(before)
            self.redo_stack.clear()
            self._mark_dirty()

    def manage_images(self):
        d = dialogs.ImagesDialog(self.macro, self, self)
        d.exec()
        if d.changed:
            self.model.refresh()
            self._mark_dirty()
            self._update_props()

    def _do_autosave(self):
        if not self.dirty or self.is_running():
            return
        sig = json.dumps(self.macro.to_dict(), sort_keys=True, default=str) + str(sorted(self.macro.images))
        if sig == self._last_autosave_sig:
            return
        try:
            self.autosave.write(self.macro, self.path)
            self._last_autosave_sig = sig
        except OSError:
            pass

    def _restart_autosave(self):
        self.autosave_timer.stop()
        if self.settings.autosave_seconds > 0:
            self.autosave_timer.start(self.settings.autosave_seconds * 1000)

    def _startup(self, open_path: str | None):
        pending = self.autosave.pending()
        if pending:
            when = time.strftime("%d/%m %H:%M", time.localtime(pending.get("time", 0)))
            orig = pending.get("original")
            msg = f"O Shift Macro fechou sem salvar uma macro ({when})."
            if orig:
                msg += f"\nArquivo original: {orig}"
            msg += "\n\nRecuperar as alterações?"
            if QMessageBox.question(self, "Recuperar macro", msg) == QMessageBox.StandardButton.Yes:
                try:
                    m = self.autosave.recover()
                    self._set_macro(m, orig)
                    self.dirty = True
                    self._update_title()
                    open_path = None
                except (ProjectError, OSError) as e:
                    QMessageBox.warning(self, "Recuperar macro", str(e))
            self.autosave.mark_clean()
        if open_path:
            self.open_path(open_path, confirm=False)
        QTimer.singleShot(4000, self._auto_update_check)

    def _auto_update_check(self):
        """No máximo uma consulta automática por dia; desligável nas Preferências."""
        s = self.settings
        if not s.auto_update or time.time() - s.update_last_check < 20 * 3600:
            return
        s.update_last_check = int(time.time())
        s.save()
        update_dialog.run_check(self, manual=False)

    def donate(self):
        QDesktopServices.openUrl(QUrl(DONATE_URL))

    # ================================================================ execução
    def _load_run_settings(self):
        s = self.macro.settings
        widgets = (self.rep_group, self.s_count, self.s_minutes, self.speed, self.c_minimize, self.c_shutdown)
        for w in widgets:
            w.blockSignals(True)
        {"once": self.r_once, "count": self.r_count, "duration": self.r_duration, "infinite": self.r_infinite}[s.repeat_mode].setChecked(True)
        self.s_count.setValue(max(1, s.repeat_count))
        self.s_minutes.setValue(max(0.05, s.repeat_minutes))
        self.speed.setValue(min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - s.speed)))
        self.c_minimize.setChecked(s.minimize_on_run)
        self.c_shutdown.setChecked(False)  # nunca vem ligado de um arquivo: exige confirmação a cada vez
        for w in widgets:
            w.blockSignals(False)
        self.speed_label.setText(_speed_text(SPEEDS[self.speed.value()]))

    def _run_settings_changed(self):
        s = self.macro.settings
        btn = self.rep_group.checkedButton()
        old = s.to_dict()
        s.repeat_mode = btn.property("mode") if btn else "once"
        s.repeat_count = self.s_count.value()
        s.repeat_minutes = self.s_minutes.value()
        s.speed = SPEEDS[self.speed.value()]
        s.minimize_on_run = self.c_minimize.isChecked()
        s.shutdown_when_done = self.c_shutdown.isChecked()
        self.speed_label.setText(_speed_text(s.speed))
        if self.engine and self.engine.ctx and self.is_running():
            self.engine.ctx.speed = s.speed  # velocidade muda na hora
        if {k: v for k, v in s.to_dict().items() if k != "shutdown_when_done"} != {k: v for k, v in old.items() if k != "shutdown_when_done"}:
            self._mark_dirty()

    def _shutdown_toggled(self, checked: bool):
        if checked:
            r = QMessageBox.question(
                self, "Desligar ao terminar",
                "Quando a macro terminar normalmente, o computador será desligado após 60 segundos de aviso "
                "(dá para cancelar). Se a macro for parada ou der erro, nada acontece.\n\nAtivar?")
            if r != QMessageBox.StandardButton.Yes:
                self.c_shutdown.setChecked(False)
        self._run_settings_changed()

    def _inputs_backend(self):
        if self._inputs is None or self._inputs.pg.FAILSAFE != self.settings.failsafe:
            from ..actions.inputs import PyAutoGuiBackend

            self._inputs = PyAutoGuiBackend(failsafe=self.settings.failsafe)
        return self._inputs

    def run(self, start_at: int = 0, only: list[int] | None = None, step: bool = False):
        if self.is_running() or self.is_recording():
            return
        if not self.macro.commands:
            self.statusBar().showMessage("A macro está vazia.", 3000)
            return
        if self.props_timer.isActive():
            self.props_timer.stop()
            self._apply_properties()
        self._run_settings_changed()
        st = self.model.structure
        if st.errors and not only:
            i, msg = st.errors[0]
            self.select_rows([i])
            QMessageBox.warning(self, "Não dá para executar", f"Etapa {i + 1}: {msg}\n\nCorrija a estrutura e tente de novo.")
            return
        macro = copy.copy(self.macro)  # comandos/imagens compartilhados, mas a edição fica bloqueada durante a execução
        macro.commands = [c for c in self.macro.commands]
        base_dir = Path(self.path).parent if self.path else None
        try:
            inputs = self._inputs_backend()
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Não foi possível iniciar o controle de mouse/teclado: {e}")
            return
        self.engine = Engine(macro, inputs, listener=self.bridge, base_dir=base_dir,
                             notify=self.bridge.send_notification)
        self.model.clear_run_state()
        self.current_step = None
        self.run_rep = (1, None)
        self.run_started = time.perf_counter()
        self.run_rows = only
        self.bottom_tabs.setCurrentIndex(0)
        self.log_model.add([])
        self.engine.start(start_at=start_at, only=only, step_mode=step)
        self.run_clock.start()
        self._update_actions()
        self._update_props()
        if macro.settings.minimize_on_run and not step:
            self.showMinimized()

    def run_from_selected(self):
        r = self.current_row()
        if r is not None:
            self.run(start_at=r)

    def run_selected(self):
        rows = self.selected_rows()
        if rows:
            self.run(only=rows)

    def step(self):
        if self.is_running():
            self.engine.next_step()
            return
        start = self.current_row() or 0
        self.run(start_at=start, step=True)

    def toggle_pause(self):
        if self.is_running():
            self.engine.toggle_pause()

    def stop(self):
        if self.is_recording():
            self.stop_recording()
        if self.engine:
            self.engine.stop()

    def _on_flush(self, step, statuses, logs):
        if statuses:
            self.model.set_statuses(statuses)
        if step is not ...:
            self.current_step = step
            self.model.set_current(step)
            if step is not None and self.settings.follow_current:
                self.table.scrollTo(self.model.index(step, 0), QAbstractItemView.ScrollHint.EnsureVisible)
        if logs:
            sb = self.log_view.verticalScrollBar()
            at_bottom = sb.value() >= sb.maximum() - 4
            self.log_model.add(logs)
            if at_bottom:
                self.log_view.scrollToBottom()
        if self.is_running() and self.bottom_tabs.currentIndex() == 1:
            self._refresh_vars()

    def _refresh_vars(self):
        ctx = self.engine.ctx if self.engine else None
        try:
            vars_ = dict(ctx.vars) if ctx else dict(self.macro.variables)
        except RuntimeError:
            return
        self.vars_table.setRowCount(len(vars_))
        for i, (k, v) in enumerate(sorted(vars_.items())):
            self.vars_table.setItem(i, 0, QTableWidgetItem(k))
            self.vars_table.setItem(i, 1, QTableWidgetItem(repr(v) if isinstance(v, str) else str(v)))

    def _on_engine_state(self, state: str):
        self._update_actions()
        t = theme.current()
        if state in ("paused", "step"):
            self.run_info.setStyleSheet(f"color:{t.warn};")
        elif state == "running":
            self.run_info.setStyleSheet(f"color:{t.run};")
        self.tray.setToolTip(f"{APP_NAME} — {'em execução' if state == 'running' else 'pausada' if state in ('paused', 'step') else 'parada'}")

    def _on_repetition(self, cur, total):
        self.run_rep = (cur, total)

    def _update_run_info(self):
        if not self.is_running():
            return
        el = time.perf_counter() - self.run_started
        cur, total = self.run_rep
        rep = f"Repetição {cur}" + (f" de {total}" if total else "")
        step = f"etapa {self.current_step + 1}" if self.current_step is not None else ""
        state = " · pausada" if self.engine and self.engine.paused else ""
        self.run_info.setText(f"{rep} · {step} · {_clock(el)}{state}")

    def _on_finished(self, res: RunResult):
        self.run_clock.stop()
        self.bridge.flush()
        self.model.set_current(None)
        t = theme.current()
        if res.error:
            self.run_info.setStyleSheet(f"color:{t.error};")
            self.run_info.setText(f"Erro na etapa {res.error_row + 1 if res.error_row is not None else '?'} · {_clock(res.elapsed)}")
            self.statusBar().showMessage(f"Erro: {res.error}", 15000)
        elif res.stopped:
            self.run_info.setStyleSheet(f"color:{t.warn};")
            self.run_info.setText(f"Parada · {res.repetitions} repetição(ões) · {_clock(res.elapsed)}")
        else:
            self.run_info.setStyleSheet(f"color:{t.ok};")
            self.run_info.setText(f"Concluída · {res.repetitions} repetição(ões) · {_clock(res.elapsed)}")
        self._refresh_vars()
        if self.isMinimized() and self.macro.settings.minimize_on_run:
            self._show_normal()
        if res.error and res.error_row is not None:
            self.select_rows([res.error_row])
            self.bottom_tabs.setCurrentIndex(0)
            if self.isMinimized() or not self.isActiveWindow():
                self._show_notification("Macro parou com erro", res.error)
        self._update_actions()
        self._update_props()
        if res.completed and self.c_shutdown.isChecked():
            d = dialogs.ShutdownDialog(self)
            self._show_normal()
            if d.exec() == QDialog.DialogCode.Accepted:
                if self.dirty:
                    self._do_autosave()
                dialogs.ShutdownDialog.shutdown_now()
            else:
                self.c_shutdown.setChecked(False)

    def _show_notification(self, title: str, message: str):
        if self.tray.isVisible():
            self.tray.showMessage(title, message, icons.app_icon(), 6000)
        else:
            self.statusBar().showMessage(f"{title}: {message}", 8000)

    def check_structure(self):
        st = self.model.structure
        if not st.errors:
            QMessageBox.information(self, "Estrutura", "Nenhum problema: todos os blocos estão fechados e os destinos existem.")
            return
        i, msg = st.errors[0]
        self.select_rows([i])
        more = "\n".join(f"Etapa {j + 1}: {m}" for j, m in st.errors[:10])
        QMessageBox.warning(self, "Estrutura", more)

    def _log_clicked(self, idx: QModelIndex):
        e = self.log_filter.data(idx, Qt.ItemDataRole.UserRole)
        if e is not None and e.step is not None and e.step < self.model.rowCount():
            self.select_rows([e.step])

    def export_log(self):
        if not self.log_model.rows:
            self.statusBar().showMessage("O log está vazio.", 3000)
            return
        p, _ = QFileDialog.getSaveFileName(self, "Exportar log", "log-shift-macro.csv", "CSV (*.csv);;Texto (*.txt)")
        if not p:
            return
        sep = ";" if p.lower().endswith(".csv") else "\t"
        from .models import LOG_HEADERS

        lines = [sep.join(LOG_HEADERS)]
        for e in self.log_model.rows:
            lines.append(sep.join(c.replace(sep, ",").replace("\n", " ") for c in LogModel.cells(e)))
        try:
            Path(p).write_text("\n".join(lines), encoding="utf-8-sig")
        except OSError as e:
            QMessageBox.warning(self, "Exportar log", str(e))
            return
        self.statusBar().showMessage(f"Log exportado para {p}", 4000)

    # ================================================================ gravação
    def _set_record_mode(self, mode: str):
        self.settings.record_mode = mode
        self.settings.save()

    def _set_record_moves(self, v: bool):
        self.settings.record_moves = v
        self.settings.save()

    def toggle_record(self):
        if self.is_recording():
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if self.is_running() or self.is_recording():
            self.a_record.setChecked(self.is_recording())
            return
        hk = self._effective_hotkeys()
        ignore = {combo.split("+")[-1].strip().lower() for combo in hk.values() if combo}
        own_hwnd = int(self.winId())

        def exclude(x, y):
            if self.isMinimized() or not self.isVisible():
                return False
            try:
                wx, wy, ww, wh = winapi.window_rect(own_hwnd)
            except Exception:
                return False
            return wx <= x < wx + ww and wy <= y < wy + wh

        self.recorder = Recorder(mode=self.settings.record_mode, ignore_keys=ignore, exclude_point=exclude)
        self.a_record.setChecked(True)
        self.rec_indicator.setText("● Gravando — F9 para parar")
        self.tray.setToolTip(f"{APP_NAME} — gravando (F9 para parar)")
        self._update_actions()
        rec = self.recorder
        if self.settings.record_minimize:
            self.showMinimized()
            # não grava a animação de minimizar; se a gravação já foi cancelada, não inicia
            QTimer.singleShot(350, lambda: rec.start() if self.recorder is rec else None)
        else:
            rec.start()
        self.statusBar().showMessage(f"Gravando ({self.rec_mode_actions[self.settings.record_mode].text().lower()}). "
                                     f"{hk.get('record') or 'F9'} para terminar.")

    def stop_recording(self):
        if not self.recorder:
            return
        events = self.recorder.stop()
        self.recorder = None
        self.a_record.setChecked(False)
        self.rec_indicator.setText("")
        self.tray.setToolTip(APP_NAME)
        cmds = convert(events, mode=self.settings.record_mode, record_moves=self.settings.record_moves,
                       min_move_ms=self.settings.record_min_move_ms, keep_delays=self.settings.record_delays)
        self._show_normal()
        if cmds:
            self.insert_commands(cmds)
            self.statusBar().showMessage(f"Gravação concluída: {len(cmds)} etapa(s) a partir de {len(events)} evento(s). Ctrl+Z desfaz.", 8000)
        else:
            self.statusBar().showMessage("Nada foi gravado.", 4000)
        self._update_actions()

    # ================================================================ atalhos globais
    def _effective_hotkeys(self) -> dict[str, str]:
        hk = dict(self.settings.hotkeys)
        hk.update({k: v for k, v in self.macro.hotkeys.items() if v})
        return hk

    def _register_hotkeys(self):
        hk = self._effective_hotkeys()
        errors = self.hotkeys.start(hk)
        parts = [f"{hk.get('run') or '—'} executa", f"{hk.get('stop') or '—'} para", f"{hk.get('record') or '—'} grava"]
        self.hotkey_label.setText("  ·  ".join(parts))
        self.hotkey_label.setToolTip("\n".join(f"{appdata.HOTKEY_LABELS[k]}: {v or 'desligado'}" for k, v in hk.items() if k in appdata.HOTKEY_LABELS))
        if errors:
            msg = "; ".join(f"{appdata.HOTKEY_LABELS.get(k, k)}: {v}" for k, v in errors.items())
            self.statusBar().showMessage(f"Atalhos indisponíveis — {msg}", 12000)

    def _hotkey_thread(self, action: str):
        # roda na thread dos atalhos: parar e pausar agem na hora, sem esperar a interface
        eng = self.engine
        if action == "stop" and eng is not None:
            eng.stop()
        elif action == "pause" and eng is not None and eng.running:
            eng.toggle_pause()
            return
        self.hotkey_pressed.emit(action)

    def _on_hotkey(self, action: str):
        if action == "run":
            if not self.is_running():
                self.run()
        elif action == "stop":
            if self.is_recording():
                self.stop_recording()
        elif action == "record":
            self.toggle_record()
        elif action == "capture":
            if not self.is_running():
                self.smart_click_capture() if not QApplication.activeModalWidget() else None
        self._update_actions()

    # ================================================================ preferências / tema
    def preferences(self, tab: int = 0):
        old_theme = self.settings.theme
        d = dialogs.PreferencesDialog(self.settings, self, tab)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.save()
        self._register_hotkeys()
        self._restart_autosave()
        self.log_model.max_rows = self.settings.log_max
        self.a_follow.setChecked(self.settings.follow_current)
        for k, a in self.rec_mode_actions.items():
            a.setChecked(k == self.settings.record_mode)
        self.a_rec_moves.setChecked(self.settings.record_moves)
        if self.settings.theme != old_theme:
            self.set_theme(self.settings.theme)

    def set_theme(self, name: str):
        self.settings.theme = name
        self.settings.save()
        theme.apply(QApplication.instance(), name)
        icons._pixmap.cache_clear()
        (self.a_dark if name == "dark" else self.a_light).setChecked(True)
        self._retint_icons()  # ícones são desenhados na cor do tema
        self._fill_tree()
        self._fill_insert_menu(self.insert_menu)
        self.rec_indicator.setStyleSheet(f"color:{theme.current().record}; font-weight:600;")
        self.model.refresh()
        self._refresh_status()
        self._update_props()

    def _retint_icons(self):
        t = theme.current()
        mapping = {
            self.a_new: "new", self.a_open: "open", self.a_save: "save", self.a_undo: "undo", self.a_redo: "redo",
            self.a_cut: "cut", self.a_copy: "copy", self.a_paste: "paste", self.a_dup: "duplicate", self.a_del: "delete",
            self.a_up: "up", self.a_down: "down", self.a_toggle: "toggle", self.a_edit: "edit", self.a_smart: "smart",
            self.a_step: "step", self.a_pick: "crosshair", self.a_vars: "variable", self.a_images: "image",
            self.a_check: "check", self.a_prefs: "settings", self.a_help: "help", self.a_update: "update",
        }
        self.a_donate.setIcon(icons.icon("heart", t.record))
        for a, n in mapping.items():
            a.setIcon(icons.icon(n, t.text))
        self.a_record.setIcon(icons.icon("record", t.record))
        self.a_run.setIcon(icons.icon("play", t.run))
        self.a_stop.setIcon(icons.icon("stop", t.record))
        self._update_actions()

    def show_help(self):
        dialogs.HelpDialog(self, self._effective_hotkeys()).exec()

    # ================================================================ janela
    def _show_normal(self):
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _restore_geometry(self):
        if self.settings.geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(self.settings.geometry.encode()))
            except Exception:
                pass
        else:
            self.resize(1360, 820)
        if self.settings.window_state:
            try:
                self.restoreState(QByteArray.fromBase64(self.settings.window_state.encode()))
            except Exception:
                pass

    def closeEvent(self, e: QCloseEvent):
        if self.is_recording():
            self.stop_recording()
        if self.is_running():
            r = QMessageBox.question(self, APP_NAME, "Uma macro está em execução. Parar e sair?")
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.engine.stop()
            self.engine.join(2)
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings.geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.window_state = bytes(self.saveState().toBase64()).decode()
        self.settings.save()
        self.hotkeys.stop()
        self.autosave.mark_clean()
        self.tray.hide()
        e.accept()
        QApplication.instance().quit()


def _speed_text(s: float) -> str:
    return (f"{s:g}×").replace(".", ",")


def _clock(sec: float) -> str:
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}".replace(".", ",") if h else f"{m:02d}:{s:04.1f}".replace(".", ",")
