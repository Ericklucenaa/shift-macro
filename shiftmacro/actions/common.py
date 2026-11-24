"""Campos e rotinas compartilhados entre comandos de imagem, cor e condições."""
from __future__ import annotations

import time
from typing import Any, Callable

from ..core.context import MacroError, RunContext
from ..vision.service import REGION_MODES, Found, VisionError
from .registry import Field as F
from .registry import Flow

BUTTON_OPTS = [("left", "Esquerdo"), ("right", "Direito"), ("middle", "Meio")]
BUTTON_NAME = dict(BUTTON_OPTS)

ON_FOUND = [
    ("move", "Mover o mouse até ela"),
    ("left", "Clicar com o botão esquerdo"),
    ("right", "Clicar com o botão direito"),
    ("double", "Clique duplo"),
    ("offset", "Clicar com deslocamento X/Y"),
    ("none", "Apenas validar que existe"),
    ("block", "Executar o bloco de comandos (até End If)"),
    ("goto", "Ir para uma etapa"),
    ("store", "Guardar as coordenadas em variáveis"),
]
ON_NOT_FOUND = [
    ("continue", "Continuar na próxima etapa"),
    ("retry", "Tentar novamente"),
    ("stop", "Parar a macro"),
    ("pause", "Pausar a macro"),
    ("goto", "Ir para uma etapa"),
    ("else", "Executar o bloco Else"),
]
ON_FOUND_NAME = dict(ON_FOUND)
ON_NOT_FOUND_NAME = dict(ON_NOT_FOUND)
_OFFSET_ACTIONS = ("move", "left", "right", "double", "offset")


def search_area_fields() -> list[F]:
    return [
        F("region_mode", "Onde procurar", "choice", "screen", options=REGION_MODES),
        F("monitor", "Monitor", "int", 1, min=1, max=16, show_if=("region_mode", ("monitor",))),
        F("region", "Área (x, y, largura, altura)", "region", [0, 0, 400, 300], show_if=("region_mode", ("region", "coords"))),
        F("window", "Título da janela (parte do nome)", "window", "", show_if=("region_mode", ("window",))),
    ]


def image_match_fields() -> list[F]:
    return [
        F("image", "Imagem", "image", ""),
        F("threshold", "Similaridade mínima (%)", "int", 80, min=1, max=100,
          help="100% exige a imagem idêntica. Entre 75% e 90% tolera pequenas variações."),
        F("multiscale", "Tolerar mudança de tamanho (DPI/zoom)", "bool", False,
          help="Procura também a imagem de 75% a 150% do tamanho. Mais lento."),
        F("color_match", "Diferenciar cores", "bool", False,
          help="Desligado compara em tons de cinza (mais rápido). Ligue se só a cor muda, ex.: botão verde/cinza."),
    ]


def wait_fields(timeout_ms: int = 5000) -> list[F]:
    return [
        F("timeout_ms", "Tempo limite de procura (ms)", "int", timeout_ms, min=0, max=86_400_000),
        F("infinite", "Procurar sem limite de tempo", "bool", False),
        F("interval_ms", "Intervalo entre tentativas (ms)", "int", 250, min=10, max=600_000),
    ]


def found_fields(default: str = "left") -> list[F]:
    return [
        F("on_found", "Quando encontrar", "choice", default, options=ON_FOUND),
        F("button", "Botão", "choice", "left", options=BUTTON_OPTS, show_if=("on_found", ("offset",))),
        F("offset", "Deslocamento (x, y)", "point", (0, 0), keys=("offset_x", "offset_y"),
          show_if=("on_found", _OFFSET_ACTIONS)),
        F("goto_found", "Ir para (rótulo ou nº da etapa)", "label", "", show_if=("on_found", ("goto",))),
        F("var", "Prefixo das variáveis", "var", "img", show_if=("on_found", ("store",)),
          help="Cria <prefixo>_x e <prefixo>_y com o centro encontrado."),
    ]


def not_found_fields(default: str = "continue") -> list[F]:
    return [
        F("on_not_found", "Quando não encontrar", "choice", default, options=ON_NOT_FOUND),
        F("retries", "Tentativas extras", "int", 3, min=1, max=1000, show_if=("on_not_found", ("retry",)),
          help="Depois de esgotar as tentativas, a macro para."),
        F("goto_not_found", "Ir para (rótulo ou nº da etapa)", "label", "", show_if=("on_not_found", ("goto",))),
    ]


def opens_block(p: dict[str, Any]) -> bool:
    return p.get("on_found") == "block" or p.get("on_not_found") == "else"


def smooth_move(ctx: RunContext, x: int, y: int, duration_s: float) -> None:
    """Move em passos de ~10 ms, verificando parada a cada passo."""
    dur = ctx.scaled(duration_s)
    if dur <= 0.012:
        ctx.inputs.move(x, y)
        return
    sx, sy = ctx.inputs.position()
    steps = max(2, int(dur / 0.01))
    t0 = time.perf_counter()
    for i in range(1, steps + 1):
        ctx.check()
        t = i / steps
        e = t * t * (3 - 2 * t)  # suavização (smoothstep)
        ctx.inputs.move(round(sx + (x - sx) * e), round(sy + (y - sy) * e))
        target = t0 + dur * t
        left = target - time.perf_counter()
        if left > 0:
            ctx.sleep(left, scale=False)


def click_at(ctx: RunContext, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    ctx.inputs.move(x, y)
    ctx.inputs.click(button, clicks)


def search_loop(ctx: RunContext, p: dict[str, Any], probe: Callable[[], Found], want: bool = True) -> Found:
    """Repete `probe` até o resultado ser `want` (True = encontrar) ou acabar o
    tempo. Tempo limite e intervalo não mudam com a velocidade: são esperas pela
    tela, não ritmo da macro."""
    timeout = max(0.0, ctx.number(p.get("timeout_ms"), 0) / 1000)
    interval = max(0.01, ctx.number(p.get("interval_ms"), 250) / 1000)
    infinite = bool(p.get("infinite"))
    attempts = 1 + (ctx.integer(p.get("retries"), 3) if p.get("on_not_found") == "retry" else 0)
    last = Found(False, 0.0)
    for attempt in range(1, attempts + 1):
        start = time.perf_counter()
        while True:
            ctx.check()
            try:
                last = probe()
            except VisionError as e:
                raise MacroError(str(e)) from e
            if last.found == want:
                return last
            if not infinite and time.perf_counter() - start >= timeout:
                break
            ctx.sleep(interval, scale=False)
        if attempt < attempts:
            ctx.log(f"Não encontrada; tentando de novo ({attempt}/{attempts - 1})", "warn", similarity=last.score)
    return last


def apply_found(ctx: RunContext, p: dict[str, Any], f: Found) -> Flow | None:
    ctx.vars["found_x"], ctx.vars["found_y"] = f.x, f.y
    ctx.vars["similaridade"] = round(f.score * 100, 1)
    action = p.get("on_found") or "none"
    ox = ctx.integer(p.get("offset_x"), 0) if action in _OFFSET_ACTIONS else 0
    oy = ctx.integer(p.get("offset_y"), 0) if action in _OFFSET_ACTIONS else 0
    x, y = f.x + ox, f.y + oy
    if action == "move":
        ctx.inputs.move(x, y)
    elif action == "left":
        click_at(ctx, x, y, "left")
    elif action == "right":
        click_at(ctx, x, y, "right")
    elif action == "double":
        click_at(ctx, x, y, "left", 2)
    elif action == "offset":
        click_at(ctx, x, y, p.get("button") or "left")
    elif action == "goto":
        return Flow(goto=str(p.get("goto_found") or ""))
    elif action == "store":
        prefix = (p.get("var") or "img").strip()
        ctx.set_var(f"{prefix}_x", f.x)
        ctx.set_var(f"{prefix}_y", f.y)
    elif action == "block":
        return Flow(branch=True)
    return None


def apply_not_found(ctx: RunContext, p: dict[str, Any]) -> Flow | None:
    action = p.get("on_not_found") or "continue"
    if action in ("stop", "retry"):
        return Flow(stop=True)
    if action == "pause":
        return Flow(pause=True)
    if action == "goto":
        return Flow(goto=str(p.get("goto_not_found") or ""))
    if action == "else":
        return Flow(branch=False)
    return None


def finish(ctx: RunContext, p: dict[str, Any], f: Found, what: str = "Imagem") -> Flow | None:
    """Registra o resultado de uma busca e aplica a ação escolhida."""
    ctx.last_similarity = f.score
    if f.found:
        ctx.last_coords = (f.x, f.y)
        ctx.status = f"Encontrada {f.score:.0%}" if f.score < 1 or what == "Imagem" else "Encontrada"
        ctx.log(f"{what} encontrada em ({f.x}, {f.y})", "ok", similarity=f.score, coords=(f.x, f.y))
        flow = apply_found(ctx, p, f)
        if flow is None and opens_block(p):
            flow = Flow(branch=True)
        return flow
    ctx.last_coords = None
    best = f" (melhor {f.score:.0%})" if f.score > 0 and what == "Imagem" else ""
    ctx.status = f"Não encontrada{best}"
    ctx.log(f"{what} não encontrada{best}", "warn", similarity=f.score)
    flow = apply_not_found(ctx, p)
    if p.get("on_not_found") == "retry":
        ctx.log("Tentativas esgotadas; parando a macro.", "error")
    if opens_block(p) and (flow is None or flow.branch is None and not (flow.stop or flow.pause or flow.goto)):
        flow = Flow(branch=False)
    return flow


def describe_search(p: dict[str, Any]) -> str:
    mode = p.get("region_mode") or "screen"
    if mode == "monitor":
        where = f"no monitor {p.get('monitor')}"
    elif mode in ("region", "coords"):
        r = p.get("region") or []
        where = f"em ({', '.join(str(v) for v in r)})" if r else "na região"
    elif mode == "window":
        where = f"na janela “{p.get('window')}”"
    else:
        where = "na tela"
    return where


def describe_outcome(p: dict[str, Any]) -> str:
    a = p.get("on_found")
    parts = []
    if a in ("offset",) or (a in _OFFSET_ACTIONS and (p.get("offset_x") or p.get("offset_y"))):
        parts.append(f"{ON_FOUND_NAME.get(a, '').lower()} ({p.get('offset_x')}, {p.get('offset_y')})")
    elif a == "goto":
        parts.append(f"ir para {p.get('goto_found')}")
    elif a == "store":
        parts.append(f"guardar em {p.get('var')}_x/_y")
    elif a:
        parts.append(ON_FOUND_NAME.get(a, a).lower())
    nf = p.get("on_not_found")
    if nf and nf != "continue":
        txt = ON_NOT_FOUND_NAME.get(nf, nf).lower()
        if nf == "goto":
            txt = f"ir para {p.get('goto_not_found')}"
        parts.append(f"senão: {txt}")
    return "; ".join(parts)


def describe_wait(p: dict[str, Any]) -> str:
    if p.get("infinite"):
        return "sem limite"
    t = p.get("timeout_ms") or 0
    try:
        return f"até {float(t) / 1000:g} s"
    except (TypeError, ValueError):
        return f"até {t} ms"
