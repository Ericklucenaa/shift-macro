"""Condições usadas por If, Else If e While."""
from __future__ import annotations

from typing import Any

from ..core import expr
from ..core.context import MacroError, RunContext
from ..utils import winapi
from ..vision import matcher
from ..vision.service import VisionError
from .common import describe_search, image_match_fields, search_area_fields
from .registry import Field as F

COND_TYPES = [
    ("expr", "Expressão / variável"),
    ("image_found", "Imagem está na tela"),
    ("image_not_found", "Imagem NÃO está na tela"),
    ("pixel", "Pixel tem a cor"),
    ("window_exists", "Janela existe"),
    ("window_active", "Janela está ativa"),
]
COND_NAME = dict(COND_TYPES)


def _only(*kinds):
    return ("cond", kinds)


def condition_fields() -> list[F]:
    img = [_with_show(f, _only("image_found", "image_not_found")) for f in image_match_fields() + search_area_fields()]
    return [
        F("cond", "Condição", "choice", "expr", options=COND_TYPES),
        F("expr", "Expressão", "expr", "contador < 5", show_if=_only("expr"),
          help="Ex.: contador < 5, nome == \"Ana\", tentativas >= 3 e achou"),
        *img,
        F("pos", "Pixel (x, y)", "point", (0, 0), keys=("x", "y"), show_if=_only("pixel")),
        F("color", "Cor", "color", "#FFFFFF", show_if=_only("pixel")),
        F("tolerance", "Tolerância por canal (0–255)", "int", 10, min=0, max=255, show_if=_only("pixel")),
        F("window", "Título da janela (parte do nome)", "window", "", show_if=_only("window_exists", "window_active")),
        F("negate", "Inverter o resultado (NÃO)", "bool", False),
    ]


def _with_show(f: F, show) -> F:
    # campos de área já dependem de region_mode; a condição só aparece se cond for imagem
    if f.show_if is None:
        f.show_if = show
    else:
        f.show_if = ("__all__", (f.show_if, show))  # type: ignore[assignment]
    return f


def evaluate(ctx: RunContext, p: dict[str, Any]) -> bool:
    kind = p.get("cond") or "expr"
    try:
        if kind == "expr":
            try:
                result = bool(expr.evaluate(str(p.get("expr") or ""), ctx.vars))
            except expr.ExprError as e:
                raise MacroError(f"Condição inválida: {e}") from e
        elif kind in ("image_found", "image_not_found"):
            f = ctx.vision.find_image(p.get("image") or "", p, ctx.integer)
            ctx.last_similarity = f.score
            ctx.log(f"Imagem {'encontrada' if f.found else 'não encontrada'} ({f.score:.0%})",
                    "ok" if f.found else "info", similarity=f.score, coords=(f.x, f.y) if f.found else None)
            if f.found:
                ctx.vars["found_x"], ctx.vars["found_y"] = f.x, f.y
            result = f.found if kind == "image_found" else not f.found
        elif kind == "pixel":
            x, y = ctx.integer(p.get("x")), ctx.integer(p.get("y"))
            got = ctx.vision.pixel(x, y)
            want = matcher.parse_color(p.get("color") or "#FFFFFF")
            result = matcher.color_distance(got, want) <= int(p.get("tolerance") or 0)
            ctx.log(f"Pixel ({x}, {y}) = {matcher.to_hex(got)}", coords=(x, y))
        elif kind == "window_exists":
            result = winapi.find_window(ctx.text(p.get("window"))) is not None
        elif kind == "window_active":
            fg = winapi.foreground_window()
            t = ctx.text(p.get("window")).lower()
            result = bool(fg and t and t in fg.title.lower())
        else:
            raise MacroError(f"Tipo de condição desconhecido: {kind}")
    except (VisionError, ValueError) as e:
        raise MacroError(str(e)) from e
    return (not result) if p.get("negate") else result


def describe(p: dict[str, Any]) -> str:
    kind = p.get("cond") or "expr"
    neg = "NÃO " if p.get("negate") else ""
    if kind == "expr":
        return f"{neg}{p.get('expr')}"
    if kind in ("image_found", "image_not_found"):
        verb = "está" if kind == "image_found" else "não está"
        return f"{neg}imagem “{p.get('image') or '?'}” {verb} {describe_search(p)} (≥{p.get('threshold')}%)"
    if kind == "pixel":
        return f"{neg}pixel ({p.get('x')}, {p.get('y')}) = {p.get('color')} ±{p.get('tolerance')}"
    if kind == "window_exists":
        return f"{neg}janela “{p.get('window')}” existe"
    return f"{neg}janela “{p.get('window')}” está ativa"
