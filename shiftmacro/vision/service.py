"""Serviço de visão usado pelos comandos: região de busca, imagens da macro,
template matching, pixel e cor. A captura é injetável (testes usam uma tela
falsa em memória)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from . import capture, matcher
from .capture import Rect

REGION_MODES = [
    ("screen", "Tela inteira"),
    ("monitor", "Monitor específico"),
    ("region", "Região personalizada"),
    ("window", "Janela específica"),
    ("coords", "Área por coordenadas"),
]


class VisionError(Exception):
    pass


@dataclass
class Found:
    found: bool
    score: float
    x: int = 0  # centro, coordenadas absolutas da tela
    y: int = 0
    rect: Rect | None = None  # área encontrada (absoluta)
    search: Rect | None = None  # área pesquisada


class VisionService:
    def __init__(
        self,
        images: dict[str, bytes] | None = None,
        *,
        grabber: Callable[[Rect | None], np.ndarray] = capture.grab,
        monitors: Callable[[], list[Rect]] = capture.monitors,
        virtual: Callable[[], Rect] = capture.virtual_screen,
        window_rect: Callable[[str], Rect | None] | None = None,
    ):
        self.images = images if images is not None else {}
        self._grab = grabber
        self._monitors = monitors
        self._virtual = virtual
        self._window_rect = window_rect or _window_rect_by_title
        self._cache: dict[str, tuple[int, np.ndarray]] = {}

    # ---------- imagens ----------
    def template(self, name: str) -> np.ndarray:
        if not name:
            raise VisionError("Nenhuma imagem escolhida para esta etapa.")
        data = self.images.get(name)
        if data is None:
            raise VisionError(f"A imagem '{name}' não está na macro.")
        key = id(data)
        cached = self._cache.get(name)
        if cached and cached[0] == key:
            return cached[1]
        img = matcher.decode_png(data)
        self._cache[name] = (key, img)
        return img

    # ---------- região ----------
    def search_rect(self, params: dict[str, Any], resolve: Callable[[Any], int] = int) -> Rect:
        mode = params.get("region_mode") or "screen"
        if mode == "monitor":
            mons = self._monitors()
            idx = resolve(params.get("monitor") or 1)
            if not 1 <= idx <= len(mons):
                raise VisionError(f"Monitor {idx} não existe (há {len(mons)}).")
            return mons[idx - 1]
        if mode in ("region", "coords"):
            reg = params.get("region") or []
            if len(reg) != 4:
                raise VisionError("Defina a região de busca.")
            x, y, w, h = (resolve(v) for v in reg)
            if w <= 0 or h <= 0:
                raise VisionError("A região de busca tem tamanho zero.")
            return Rect(x, y, w, h)
        if mode == "window":
            title = str(params.get("window") or "").strip()
            r = self._window_rect(title)
            if r is None:
                raise VisionError(f"Janela '{title}' não encontrada.")
            return r
        return self._virtual()

    def grab(self, rect: Rect | None) -> tuple[np.ndarray, Rect]:
        """Captura a área (recortada aos limites da tela) e devolve (imagem, área real)."""
        vs = self._virtual()
        r = (rect or vs).intersect(vs)
        if r is None:
            raise VisionError("A área de busca está fora da tela.")
        return self._grab(r), r

    # ---------- buscas ----------
    def find_image(self, name: str, params: dict[str, Any], resolve: Callable[[Any], int] = int) -> Found:
        tpl = self.template(name)
        area = self.search_rect(params, resolve)
        hay, area = self.grab(area)
        threshold = max(1, min(100, int(params.get("threshold") or 80))) / 100
        scales = matcher.scales_for(bool(params.get("multiscale")))
        m = matcher.find(hay, tpl, threshold=threshold, scales=scales, grayscale=not params.get("color_match"))
        if m is None:
            return Found(False, 0.0, search=area)
        rect = Rect(area.x + m.x, area.y + m.y, m.w, m.h)
        cx, cy = m.center
        return Found(m.score >= threshold, m.score, area.x + cx, area.y + cy, rect, area)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        img = self._grab(Rect(int(x), int(y), 1, 1))
        b, g, r = (int(v) for v in img[0, 0])
        return r, g, b

    def find_color(self, rgb: tuple[int, int, int], tolerance: int, params: dict[str, Any], resolve=int) -> Found:
        area = self.search_rect(params, resolve)
        hay, area = self.grab(area)
        p = matcher.find_color(hay, rgb, tolerance)
        if p is None:
            return Found(False, 0.0, search=area)
        return Found(True, 1.0, area.x + p[0], area.y + p[1], Rect(area.x + p[0], area.y + p[1], 1, 1), area)


def _window_rect_by_title(title: str) -> Rect | None:
    from ..utils import winapi

    w = winapi.find_window(title)
    if not w:
        return None
    if winapi.is_minimized(w.hwnd):
        raise VisionError(f"A janela '{w.title}' está minimizada; não dá para procurar nela.")
    x, y, wd, ht = winapi.window_rect(w.hwnd)
    return Rect(x, y, wd, ht)
