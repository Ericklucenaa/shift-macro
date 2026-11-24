"""Ícones vetoriais próprios (traço de 1,75 px em grade 24×24), coloridos pelo tema."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_P = {
    "new": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1"/><path d="M3 7v10a2 2 0 0 0 2 2h12.5a2 2 0 0 0 1.9-1.4L22 11H7.5a2 2 0 0 0-1.9 1.4L3 19"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "record": '<circle cx="12" cy="12" r="7" fill="currentColor" stroke="none"/>',
    "smart": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M10 9l6 3-2.6 1.1L12.3 16z" fill="currentColor"/>',
    "play": '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="5.5" y="5.5" width="13" height="13" rx="1.5" fill="currentColor" stroke="none"/>',
    "step": '<path d="M5 5v14l9-7z" fill="currentColor" stroke="none"/><path d="M18 5v14"/>',
    "duplicate": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "delete": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "crosshair": '<circle cx="12" cy="12" r="8"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "edit": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "toggle": '<rect x="2.5" y="7" width="19" height="10" rx="5"/><circle cx="16.5" cy="12" r="3" fill="currentColor"/>',
    "log": '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1" fill="currentColor"/><circle cx="4" cy="12" r="1" fill="currentColor"/><circle cx="4" cy="18" r="1" fill="currentColor"/>',
    "variable": '<path d="M7 4C5 4 5 6 5 8s-1 4-2 4c1 0 2 2 2 4s0 4 2 4M17 4c2 0 2 2 2 4s1 4 2 4c-1 0-2 2-2 4s0 4-2 4"/><path d="M9.5 9l5 6M14.5 9l-5 6"/>',
    "cut": '<circle cx="6" cy="18" r="3"/><circle cx="18" cy="18" r="3"/><path d="M8.2 16 18 4M15.8 16 6 4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "paste": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 10h6M9 14h6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.01"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "warning": '<path d="M12 3.5L2.5 20h19z"/><path d="M12 10v4.5M12 17.5v.01"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "window": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "color": '<path d="M12 3.5c3.5 4 6 7.2 6 10a6 6 0 0 1-12 0c0-2.8 2.5-6 6-10z"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "heart": '<path d="M12 20s-7.5-4.6-9-9.3C1.9 7.2 4 4 7.3 4c2 0 3.4 1.1 4.7 2.7C13.3 5.1 14.7 4 16.7 4 20 4 22.1 7.2 21 10.7 19.5 15.4 12 20 12 20z"/>',
    "update": '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4h-4"/><path d="M12 8v5l3 2"/>',
}
# ícones por tipo de etapa
KIND_ICON = {
    "mouse": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 3v6"/>',
    "keyboard": _P["keyboard"],
    "image": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><circle cx="12" cy="12" r="3"/>',
    "condition": '<path d="M6 4v6a4 4 0 0 0 4 4h8M14 10l4 4-4 4"/><path d="M6 20v-4"/>',
    "loop": '<path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/>',
    "flow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "variable": _P["variable"],
    "system": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "comment": '<path d="M4 5h16v11H9l-5 4z"/>',
    "delay": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5M9 2h6"/>',
}


def _svg(body: str, color: str) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" color="{color}">{body}</svg>'
    ).replace("currentColor", color).encode()


@lru_cache(maxsize=512)
def _pixmap(body: str, color: str, size: int, dpr: float) -> QPixmap:
    r = QSvgRenderer(QByteArray(_svg(body, color)))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    t = theme.current()
    body = _P.get(name) or KIND_ICON.get(name) or _P["help"]
    ic = QIcon()
    for dpr in (1.0, 1.25, 1.5, 2.0):
        ic.addPixmap(_pixmap(body, color or t.text, size, dpr), QIcon.Mode.Normal)
        ic.addPixmap(_pixmap(body, t.faint, size, dpr), QIcon.Mode.Disabled)
    return ic


def kind_pixmap(kind: str, color: str, size: int, dpr: float) -> QPixmap:
    return _pixmap(KIND_ICON.get(kind, KIND_ICON["flow"]), color, size, dpr)


def app_icon() -> QIcon:
    """Marca: um cursor sobre uma trilha de etapas, em âmbar."""
    body = (
        '<rect x="1.5" y="1.5" width="21" height="21" rx="5" fill="#1D2024" stroke="#F2A93B" stroke-width="1.5"/>'
        '<path d="M6 7h6M6 11h4M6 15h3" stroke="#959CA6" stroke-width="1.6"/>'
        '<path d="M12.5 9.5l7 3.2-3 1.1-1.3 3z" fill="#F2A93B" stroke="#F2A93B" stroke-width="1.2"/>'
    )
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        r = QSvgRenderer(QByteArray(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-linejoin="round" stroke-linecap="round">{body}</svg>'.encode()))
        pm = QPixmap(s, s)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p)
        p.end()
        ic.addPixmap(pm)
    return ic


def size(n: int = 18) -> QSize:
    return QSize(n, n)
