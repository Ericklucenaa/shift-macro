"""Dublês: entrada que só registra chamadas e uma tela em memória."""
from __future__ import annotations

import threading

import numpy as np

from shiftmacro.vision.capture import Rect
from shiftmacro.vision.service import VisionService


class FakeInputs:
    def __init__(self):
        self.calls: list[tuple] = []
        self.pos = (0, 0)
        self.lock = threading.Lock()

    def _rec(self, *c):
        with self.lock:
            self.calls.append(c)

    def position(self):
        return self.pos

    def move(self, x, y):
        self.pos = (x, y)
        self._rec("move", x, y)

    def down(self, b):
        self._rec("down", b)

    def up(self, b):
        self._rec("up", b)

    def click(self, b, clicks=1):
        self._rec("click", b, clicks, *self.pos)

    def scroll(self, v, h):
        self._rec("scroll", v, h)

    def key_down(self, k):
        self._rec("kdown", k)

    def key_up(self, k):
        self._rec("kup", k)

    def type_char(self, ch):
        self._rec("char", ch)

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]

    def typed(self):
        return "".join(c[1] for c in self.calls if c[0] == "char")


class FakeScreen:
    """Tela virtual de dois monitores, lado a lado, em memória (BGR)."""

    def __init__(self, w1=800, h1=600, w2=640, h2=480):
        self.mons = [Rect(0, 0, w1, h1), Rect(w1, 0, w2, h2)]
        self.virtual = Rect(0, 0, w1 + w2, max(h1, h2))
        rng = np.random.default_rng(7)
        # fundo com ruído leve: template matching precisa de textura
        self.img = rng.integers(30, 60, size=(self.virtual.h, self.virtual.w, 3), dtype=np.uint8)
        self.grabs = 0

    def paste(self, tile: np.ndarray, x: int, y: int):
        h, w = tile.shape[:2]
        self.img[y:y + h, x:x + w] = tile

    def clear(self, x, y, w, h):
        self.img[y:y + h, x:x + w] = 40

    def grab(self, rect: Rect | None):
        self.grabs += 1
        r = rect or self.virtual
        return self.img[r.y:r.y + r.h, r.x:r.x + r.w].copy()

    def vision(self, images: dict[str, bytes], windows: dict[str, Rect] | None = None) -> VisionService:
        win = windows or {}
        return VisionService(
            images,
            grabber=self.grab,
            monitors=lambda: list(self.mons),
            virtual=lambda: self.virtual,
            window_rect=lambda t: next((r for k, r in win.items() if t.lower() in k.lower()), None),
        )


def pattern(w=40, h=30, seed=1) -> np.ndarray:
    """Um "botão" com textura própria, fácil de distinguir do fundo."""
    rng = np.random.default_rng(seed)
    tile = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
    tile[:4, :] = 250
    tile[:, :4] = 10
    return tile
