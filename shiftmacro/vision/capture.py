"""Captura de tela com MSS (coordenadas físicas, todos os monitores)."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

_local = threading.local()


def _sct():
    # MSS guarda handles de GDI por thread: uma instância por thread.
    s = getattr(_local, "sct", None)
    if s is None:
        import mss

        factory = getattr(mss, "MSS", None) or mss.mss
        s = factory()
        _local.sct = s
    return s


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersect(self, other: "Rect") -> "Rect | None":
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2, y2 = min(self.right, other.right), min(self.bottom, other.bottom)
        if x2 <= x1 or y2 <= y1:
            return None
        return Rect(x1, y1, x2 - x1, y2 - y1)

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


def monitors() -> list[Rect]:
    """Monitores individuais (índice 0 = monitor 1)."""
    return [Rect(m["left"], m["top"], m["width"], m["height"]) for m in _sct().monitors[1:]]


def virtual_screen() -> Rect:
    m = _sct().monitors[0]
    return Rect(m["left"], m["top"], m["width"], m["height"])


def grab(rect: Rect | None = None) -> np.ndarray:
    """Imagem BGR (uint8) da área pedida; a tela virtual inteira se rect=None."""
    r = rect or virtual_screen()
    vs = virtual_screen()
    clip = r.intersect(vs)
    if clip is None:
        raise ValueError("A área de busca está fora da tela.")
    shot = _sct().grab({"left": clip.x, "top": clip.y, "width": clip.w, "height": clip.h})
    arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
    return np.ascontiguousarray(arr[:, :, :3])


def pixel(x: int, y: int) -> tuple[int, int, int]:
    """Cor RGB de um pixel."""
    img = grab(Rect(int(x), int(y), 1, 1))
    b, g, r = (int(v) for v in img[0, 0])
    return r, g, b
