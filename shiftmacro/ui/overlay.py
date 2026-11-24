"""Seleção sobre a tela: recortar uma região ou escolher um ponto.

A tela é congelada (captura MSS em pixels físicos) e mostrada numa janela por
monitor. A posição do mouse em cada janela é convertida para coordenadas
físicas proporcionalmente, o que funciona com escalas de DPI diferentes entre
monitores.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..vision import capture
from ..vision.capture import Rect
from . import theme


def to_qimage(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_BGR888).copy()


def _match_screens() -> list[tuple[object, Rect]]:
    """Associa cada QScreen ao monitor físico do MSS (mesmo tamanho em pixels,
    origem mais próxima)."""
    mons = capture.monitors()
    used: set[int] = set()
    out = []
    for s in QGuiApplication.screens():
        g = s.geometry()
        dpr = s.devicePixelRatio()
        pw, ph = round(g.width() * dpr), round(g.height() * dpr)
        best, best_d = None, None
        for i, m in enumerate(mons):
            if i in used:
                continue
            size_d = abs(m.w - pw) + abs(m.h - ph)
            pos_d = abs(m.x - g.x()) + abs(m.y - g.y())
            d = size_d * 10 + pos_d
            if best_d is None or d < best_d:
                best, best_d = i, d
        if best is not None:
            used.add(best)
            out.append((s, mons[best]))
    return out


class _Overlay(QWidget):
    def __init__(self, picker: "ScreenPicker", screen, mon: Rect, shot: np.ndarray):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.picker = picker
        self.mon = mon
        self.shot = shot
        self.pix = QPixmap.fromImage(to_qimage(shot))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.origin: QPoint | None = None
        self.current: QPoint | None = None

    # conversões lógico <-> físico
    def phys(self, p: QPoint) -> tuple[int, int]:
        sx = self.mon.w / max(1, self.width())
        sy = self.mon.h / max(1, self.height())
        return self.mon.x + int(p.x() * sx), self.mon.y + int(p.y() * sy)

    def local_px(self, p: QPoint) -> tuple[int, int]:
        x, y = self.phys(p)
        return min(max(0, x - self.mon.x), self.mon.w - 1), min(max(0, y - self.mon.y), self.mon.h - 1)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.picker.done(None)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.picker.done(None)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.picker.mode == "point":
            x, y = self.phys(e.position().toPoint())
            lx, ly = self.local_px(e.position().toPoint())
            b, g, r = (int(v) for v in self.shot[ly, lx])
            self.picker.done((x, y, (r, g, b)))
            return
        self.origin = e.position().toPoint()
        self.current = self.origin
        self.update()

    def mouseMoveEvent(self, e):
        self.current = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.picker.mode != "region" or self.origin is None or e.button() != Qt.MouseButton.LeftButton:
            return
        a = self.phys(self.origin)
        b = self.phys(e.position().toPoint())
        x1, y1 = min(a[0], b[0]), min(a[1], b[1])
        x2, y2 = max(a[0], b[0]), max(a[1], b[1])
        self.origin = None
        if x2 - x1 < 4 or y2 - y1 < 4:
            self.update()
            return  # clique sem arrastar: ignora
        m = self.mon
        x1, y1 = max(x1, m.x), max(y1, m.y)
        x2, y2 = min(x2, m.right), min(y2, m.bottom)
        self.picker.crop = self.shot[y1 - m.y:y2 - m.y, x1 - m.x:x2 - m.x].copy()
        self.picker.done(Rect(x1, y1, x2 - x1, y2 - y1))

    def paintEvent(self, _):
        t = theme.current()
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        accent = QColor(t.accent)
        cur = self.current or self.mapFromGlobal(QCursor.pos())
        if self.picker.mode == "region" and self.origin is not None and self.current is not None:
            sel = QRect(self.origin, self.current).normalized()
            src = QRect(
                int(sel.x() * self.pix.width() / self.width()), int(sel.y() * self.pix.height() / self.height()),
                int(sel.width() * self.pix.width() / self.width()), int(sel.height() * self.pix.height() / self.height()),
            )
            p.drawPixmap(sel, self.pix, src)
            p.setPen(QPen(accent, 1.5))
            p.drawRect(sel)
            a, b = self.phys(sel.topLeft()), self.phys(sel.bottomRight())
            self._tag(p, sel.bottomRight() + QPoint(8, 8), f"{b[0] - a[0]} × {b[1] - a[1]}  ·  x {a[0]}, y {a[1]}")
        # mira
        p.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DashLine))
        p.drawLine(0, cur.y(), self.width(), cur.y())
        p.drawLine(cur.x(), 0, cur.x(), self.height())
        if self.picker.mode == "point" and self.rect().contains(cur):
            self._magnifier(p, cur)
        self._hint(p)
        p.end()

    def _hint(self, p: QPainter):
        text = ("Arraste para selecionar a área" if self.picker.mode == "region" else "Clique no ponto desejado") + "   ·   Esc cancela"
        f = QFont(self.font())
        f.setPointSizeF(10.5)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 28
        r = QRect((self.width() - w) // 2, 24, w, 34)
        p.fillRect(r, QColor(20, 22, 25, 230))
        p.setPen(QColor(theme.current().accent))
        p.drawRect(r.adjusted(0, 0, -1, -1))
        p.setPen(QColor("#E4E6E9"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _tag(self, p: QPainter, at: QPoint, text: str):
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 8
        x = min(at.x(), self.width() - w - 4)
        y = min(at.y(), self.height() - h - 4)
        p.fillRect(QRect(x, y, w, h), QColor(20, 22, 25, 235))
        p.setPen(QColor("#E4E6E9"))
        p.drawText(QRect(x, y, w, h), Qt.AlignmentFlag.AlignCenter, text)

    def _magnifier(self, p: QPainter, cur: QPoint):
        lx, ly = self.local_px(cur)
        n, z = 11, 10
        x0, y0 = max(0, lx - n // 2), max(0, ly - n // 2)
        crop = self.shot[y0:y0 + n, x0:x0 + n]
        if crop.size == 0:
            return
        img = QPixmap.fromImage(to_qimage(crop)).scaled(crop.shape[1] * z, crop.shape[0] * z)
        box = QRect(cur.x() + 18, cur.y() + 18, n * z, n * z)
        if box.right() > self.width():
            box.moveRight(cur.x() - 18)
        if box.bottom() + 40 > self.height():
            box.moveBottom(cur.y() - 18 - 40)
        p.drawPixmap(box.topLeft(), img)
        p.setPen(QPen(QColor(theme.current().accent), 1))
        p.drawRect(box)
        cx = box.left() + (lx - x0) * z
        cy = box.top() + (ly - y0) * z
        p.setPen(QPen(QColor("#FFFFFF"), 1))
        p.drawRect(QRect(cx, cy, z, z))
        b, g, r = (int(v) for v in self.shot[ly, lx])
        x, y = self.phys(cur)
        self._tag(p, QPoint(box.left(), box.bottom() + 6), f"x {x}, y {y}   #{r:02X}{g:02X}{b:02X}")


class ScreenPicker:
    def __init__(self, mode: str):
        self.mode = mode  # region | point
        self.result = None
        self.crop: np.ndarray | None = None
        self.overlays: list[_Overlay] = []
        self.loop = QEventLoop()

    def done(self, result) -> None:
        self.result = result
        for o in self.overlays:
            o.close()
        self.overlays = []
        self.loop.quit()

    def run(self):
        for screen, mon in _match_screens():
            shot = capture.grab(mon)
            o = _Overlay(self, screen, mon, shot)
            self.overlays.append(o)
        if not self.overlays:
            return None
        for o in self.overlays:
            o.showFullScreen()
            o.raise_()
            o.activateWindow()
        # foco no monitor onde está o mouse, para o Esc funcionar de primeira
        pos = QCursor.pos()
        for o in self.overlays:
            if o.geometry().contains(pos):
                o.activateWindow()
                o.setFocus()
        self.loop.exec()
        return self.result


def _with_hidden(window, fn):
    """Torna invisíveis as janelas do app enquanto o usuário escolhe na tela.

    Usa opacidade em vez de hide(): esconder um diálogo modal encerraria o
    diálogo, e esconder a janela principal esconderia os diálogos filhos.
    """
    from PySide6.QtWidgets import QApplication

    hidden = [w for w in QApplication.topLevelWidgets()
              if w.isVisible() and not w.isMinimized() and not isinstance(w, _Overlay) and w.windowOpacity() > 0]
    for w in hidden:
        w.setWindowOpacity(0.0)
    if hidden:
        loop = QEventLoop()
        QTimer.singleShot(220, loop.quit)  # tempo para o Windows redesenhar o que estava atrás
        loop.exec()
    try:
        return fn()
    finally:
        for w in hidden:
            w.setWindowOpacity(1.0)
        if window is not None and window.isVisible():
            window.raise_()
            window.activateWindow()


def pick_region(window=None) -> Rect | None:
    return _with_hidden(window, lambda: ScreenPicker("region").run())


def pick_point(window=None) -> tuple[int, int, tuple[int, int, int]] | None:
    return _with_hidden(window, lambda: ScreenPicker("point").run())


def capture_image(window=None) -> tuple[np.ndarray, Rect] | None:
    """Recorta uma região e devolve (imagem BGR, região)."""
    def go():
        sp = ScreenPicker("region")
        rect = sp.run()
        if rect is None or sp.crop is None:
            return None
        # recorte da tela congelada: exatamente o que o usuário viu
        return sp.crop, rect

    return _with_hidden(window, go)
