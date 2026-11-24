"""Reconhecimento de imagem com OpenCV Template Matching.

Usa TM_CCOEFF_NORMED (similaridade de 0 a 1) em várias escalas e devolve o
resultado de maior confiança. Escalas cobrem diferenças de DPI/zoom entre a
captura e a execução (ex.: imagem capturada a 100% e tela a 125%).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Match:
    score: float  # 0..1
    x: int  # canto superior esquerdo, relativo à imagem pesquisada
    y: int
    w: int
    h: int
    scale: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def decode_png(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Imagem inválida ou corrompida.")
    return img


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Não foi possível gerar o PNG.")
    return buf.tobytes()


def scales_for(multiscale: bool, min_scale: float = 0.75, max_scale: float = 1.5, steps: int = 13) -> list[float]:
    if not multiscale:
        return [1.0]
    vals = set(np.round(np.linspace(min_scale, max_scale, max(2, steps)), 3).tolist())
    vals.add(1.0)
    # 1.0 primeiro: é o caso mais comum e permite parar cedo
    return sorted(vals, key=lambda s: abs(s - 1.0))


def _match_one(hay: np.ndarray, tpl: np.ndarray) -> tuple[float, tuple[int, int]]:
    if float(tpl.std()) < 1e-6:
        # modelo de cor única: CCOEFF fica indefinido; usa diferença quadrática
        res = cv2.matchTemplate(hay, tpl, cv2.TM_SQDIFF_NORMED)
        min_v, _, min_loc, _ = cv2.minMaxLoc(res)
        return 1.0 - float(min_v), min_loc
    res = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
    res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
    _, max_v, _, max_loc = cv2.minMaxLoc(res)
    return float(max_v), max_loc


def find(
    haystack: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = 0.8,
    scales: list[float] | None = None,
    grayscale: bool = True,
) -> Match | None:
    """Melhor ocorrência de `template` em `haystack` (ambos BGR).

    Devolve o Match de maior score entre as escalas, mesmo abaixo do limiar
    (o chamador decide com `score >= threshold`); None se o modelo não cabe.
    """
    if haystack is None or template is None or template.size == 0:
        return None
    hay = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY) if grayscale else haystack
    base = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if grayscale else template
    best: Match | None = None
    for s in scales or [1.0]:
        if s == 1.0:
            tpl = base
        else:
            w = max(1, int(round(base.shape[1] * s)))
            h = max(1, int(round(base.shape[0] * s)))
            tpl = cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        th, tw = tpl.shape[:2]
        if th > hay.shape[0] or tw > hay.shape[1] or th < 3 or tw < 3:
            continue
        score, (x, y) = _match_one(hay, tpl)
        if best is None or score > best.score:
            best = Match(score=score, x=int(x), y=int(y), w=tw, h=th, scale=s)
        if best.score >= 0.995:
            break  # correspondência praticamente exata
    return best


def find_color(
    haystack: np.ndarray, rgb: tuple[int, int, int], tolerance: int = 0
) -> tuple[int, int] | None:
    """Primeiro pixel (de cima para baixo, da esquerda para a direita) com a cor
    dentro da tolerância por canal. Coordenadas relativas à imagem."""
    r, g, b = rgb
    target = np.array([b, g, r], dtype=np.int16)
    diff = np.abs(haystack.astype(np.int16) - target)
    mask = np.all(diff <= int(tolerance), axis=2)
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    return int(xs[0]), int(ys[0])


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def parse_color(text: str | tuple | list) -> tuple[int, int, int]:
    if isinstance(text, (tuple, list)) and len(text) == 3:
        return int(text[0]), int(text[1]), int(text[2])
    t = str(text).strip().lstrip("#")
    if len(t) == 6:
        try:
            return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
        except ValueError:
            pass
    parts = [p for p in t.replace(";", ",").split(",") if p.strip()]
    if len(parts) == 3:
        return tuple(max(0, min(255, int(p))) for p in parts)  # type: ignore[return-value]
    raise ValueError(f"Cor inválida: '{text}'. Use #RRGGBB ou R,G,B.")


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)
