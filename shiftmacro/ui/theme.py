"""Tema visual: tokens de cor, cores por tipo de etapa e folha de estilo Qt."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    name: str
    bg: str  # janela
    panel: str  # painéis e tabela
    raised: str  # campos, botões
    hover: str
    line: str
    text: str
    muted: str
    faint: str
    accent: str  # seleção, etapa atual (âmbar "gravando")
    accent_text: str
    accent_soft: str
    run: str
    record: str
    warn: str
    error: str
    ok: str
    kinds: dict


DARK = Tokens(
    name="dark",
    bg="#16181B", panel="#1D2024", raised="#262A2F", hover="#2E3339", line="#32373E",
    text="#E4E6E9", muted="#959CA6", faint="#6B727C",
    accent="#F2A93B", accent_text="#1A1407", accent_soft="#3A2E1A",
    run="#3DBE7A", record="#E5484D", warn="#E8B44C", error="#F0646A", ok="#4CC38A",
    kinds={
        "mouse": "#6FA8DC", "keyboard": "#9CC26B", "image": "#3FB8AF", "condition": "#E39B4A",
        "loop": "#B48ED8", "flow": "#D97BA4", "variable": "#CDB558", "system": "#8C9DB0",
        "comment": "#6B737C", "delay": "#7F8B98",
    },
)
LIGHT = Tokens(
    name="light",
    bg="#EEF0F2", panel="#FFFFFF", raised="#F6F7F8", hover="#E9ECEF", line="#D5D9DE",
    text="#1C2026", muted="#5B6470", faint="#8A939E",
    accent="#B86E0B", accent_text="#FFFFFF", accent_soft="#FBEBD3",
    run="#1F8F55", record="#CF2F35", warn="#A86F05", error="#C8333A", ok="#1F8F55",
    kinds={
        "mouse": "#2F6FAE", "keyboard": "#5B8A26", "image": "#13857D", "condition": "#B8661A",
        "loop": "#7D52AE", "flow": "#B2457A", "variable": "#8A7413", "system": "#56677A",
        "comment": "#7B838D", "delay": "#66717D",
    },
)

_current: Tokens = DARK


def current() -> Tokens:
    return _current


def kind_color(kind: str) -> QColor:
    return QColor(_current.kinds.get(kind, _current.muted))


def mono_font(size: float = 9.0) -> QFont:
    f = QFont("Cascadia Mono")
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSizeF(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def apply(app: QApplication, name: str) -> Tokens:
    global _current
    t = LIGHT if name == "light" else DARK
    _current = t
    app.setStyle("Fusion")
    f = QFont("Segoe UI Variable Text")
    if not f.exactMatch():
        f = QFont("Segoe UI")
    f.setPointSizeF(9.5)
    app.setFont(f)
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg, QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.panel, QPalette.ColorRole.AlternateBase: t.raised,
        QPalette.ColorRole.Text: t.text, QPalette.ColorRole.Button: t.raised,
        QPalette.ColorRole.ButtonText: t.text, QPalette.ColorRole.Highlight: t.accent_soft,
        QPalette.ColorRole.HighlightedText: t.text, QPalette.ColorRole.ToolTipBase: t.raised,
        QPalette.ColorRole.ToolTipText: t.text, QPalette.ColorRole.PlaceholderText: t.faint,
        QPalette.ColorRole.Link: t.accent, QPalette.ColorRole.Mid: t.line, QPalette.ColorRole.Dark: t.line,
    }
    for role, c in roles.items():
        pal.setColor(role, QColor(c))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.faint))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.faint))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t.faint))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t, *_indicator_svgs(t)))
    return t


def _indicator_svgs(t: Tokens) -> tuple[str, str]:
    """SVGs do "check" e do ponto do rádio, na cor do tema (o QSS só aceita arquivo)."""
    import tempfile
    from pathlib import Path

    d = Path(tempfile.gettempdir())
    check = d / f"shiftmacro-check-{t.name}.svg"
    check.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" '
        f'fill="none" stroke="{t.accent_text}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        encoding="utf-8",
    )
    dot = d / f"shiftmacro-radio-{t.name}.svg"
    dot.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="none" '
        f'stroke="{t.accent}" stroke-width="1.4"/><circle cx="8" cy="8" r="3.6" fill="{t.accent}"/></svg>',
        encoding="utf-8",
    )
    return check.as_posix(), dot.as_posix()


def stylesheet(t: Tokens, check_path: str = "", radio_path: str = "") -> str:
    return f"""
* {{ outline: none; }}
QMainWindow, QDialog {{ background: {t.bg}; }}
QToolTip {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.line}; padding: 4px 6px; }}
QMenuBar {{ background: {t.bg}; color: {t.text}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 9px; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {t.hover}; }}
QMenu {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.line}; padding: 4px; }}
QMenu::item {{ padding: 5px 26px 5px 24px; border-radius: 3px; }}
QMenu::item:selected {{ background: {t.hover}; }}
QMenu::item:disabled {{ color: {t.faint}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 6px; }}

QToolBar {{ background: {t.bg}; border: none; border-bottom: 1px solid {t.line}; padding: 4px 6px; spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {t.line}; margin: 5px 6px; }}
QToolButton {{ color: {t.text}; border: 1px solid transparent; border-radius: 4px; padding: 4px 7px; }}
QToolButton:hover {{ background: {t.hover}; }}
QToolButton:pressed, QToolButton:checked {{ background: {t.raised}; border-color: {t.line}; }}
QToolButton:disabled {{ color: {t.faint}; }}
QToolButton#recordButton:checked {{ background: {t.record}; color: white; border-color: {t.record}; }}
QToolButton#runButton {{ color: {t.run}; font-weight: 600; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[popupMode="1"] {{ padding-right: 16px; }}

QStatusBar {{ background: {t.bg}; color: {t.muted}; border-top: 1px solid {t.line}; }}
QStatusBar::item {{ border: none; }}

QDockWidget {{ color: {t.muted}; font-weight: 600; }}
QDockWidget::title {{ background: {t.bg}; padding: 6px 8px; border-bottom: 1px solid {t.line}; text-align: left; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {t.line}; background: {t.panel}; }}
QTabBar::tab {{ background: transparent; color: {t.muted}; padding: 6px 12px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom-color: {t.accent}; }}
QTabBar::tab:hover {{ color: {t.text}; }}

QTableView, QTreeWidget, QListWidget, QTreeView {{
  background: {t.panel}; color: {t.text}; border: 1px solid {t.line}; border-radius: 4px;
  gridline-color: transparent; selection-background-color: {t.accent_soft}; selection-color: {t.text};
}}
QTableView::item {{ padding: 0 6px; border: none; }}
QTreeWidget::item, QListWidget::item {{ padding: 4px 4px; border-radius: 3px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {t.hover}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QHeaderView::section {{
  background: {t.panel}; color: {t.muted}; border: none; border-bottom: 1px solid {t.line};
  padding: 5px 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {t.panel}; border: none; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {t.raised}; color: {t.text}; border: 1px solid {t.line}; border-radius: 4px;
  padding: 4px 6px; selection-background-color: {t.accent}; selection-color: {t.accent_text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {t.faint}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {t.panel}; border: 1px solid {t.line}; selection-background-color: {t.hover}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}

QPushButton {{
  background: {t.raised}; color: {t.text}; border: 1px solid {t.line}; border-radius: 4px; padding: 5px 12px;
}}
QPushButton:hover {{ background: {t.hover}; }}
QPushButton:pressed {{ background: {t.line}; }}
QPushButton:disabled {{ color: {t.faint}; }}
QPushButton:default, QPushButton[primary="true"] {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
QPushButton[danger="true"] {{ color: {t.error}; }}
QPushButton[flat="true"] {{ background: transparent; border-color: transparent; }}
QPushButton[flat="true"]:hover {{ background: {t.hover}; }}

QCheckBox, QRadioButton {{ color: {t.text}; spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator {{ border: 1px solid {t.faint}; border-radius: 3px; background: {t.raised}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check_path}"); }}
QRadioButton::indicator {{ border: 1px solid {t.faint}; border-radius: 7px; background: {t.raised}; }}
QRadioButton::indicator:checked {{ border: none; background: transparent; image: url("{radio_path}"); }}
QToolButton::menu-button {{ width: 14px; border: none; border-left: 1px solid {t.line}; margin: 3px 0; }}
QToolButton::menu-arrow {{ width: 8px; height: 8px; }}

QSlider::groove:horizontal {{ height: 4px; background: {t.line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t.text}; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.line}; border-radius: 4px; min-height: 24px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t.faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {t.line}; border-radius: 4px; min-width: 24px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QGroupBox {{ color: {t.muted}; border: 1px solid {t.line}; border-radius: 4px; margin-top: 14px; padding: 10px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QSplitter::handle {{ background: {t.bg}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QFrame#panel {{ background: {t.panel}; border: 1px solid {t.line}; border-radius: 4px; }}
QFrame#runPanel {{ background: {t.panel}; border-top: 1px solid {t.line}; }}
QLabel#sectionTitle {{ color: {t.muted}; font-weight: 600; }}
QLabel#muted {{ color: {t.muted}; }}
QLabel#hint {{ color: {t.faint}; }}
QLabel#error {{ color: {t.error}; }}
QLabel#counter {{ color: {t.text}; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""
