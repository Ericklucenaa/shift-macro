"""Catálogo de comandos. Importar este módulo registra todos os tipos."""
from __future__ import annotations

import datetime as _dt
import os
import random
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

from ..core import expr
from ..core.context import MacroError, RunContext
from ..utils import winapi
from ..vision import matcher
from ..vision.service import Found
from . import common as C
from . import conditions
from .inputs import normalize_key, parse_combo
from .registry import CommandSpec, Field as F, Flow, register

M, K, IMG, FLOW, VAR, SYS = "Mouse", "Teclado", "Imagem e tela", "Controle de fluxo", "Variáveis e funções", "Sistema"


def _ms(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return f"{v} ms"
    return f"{f / 1000:g} s" if f >= 1000 else f"{f:g} ms"


def _xy(p: dict, kx: str = "x", ky: str = "y") -> str:
    return f"({p.get(kx)}, {p.get(ky)})"


def _point(ctx: RunContext, p: dict, kx: str = "x", ky: str = "y") -> tuple[int, int]:
    return ctx.integer(p.get(kx)), ctx.integer(p.get(ky))


# ================================================================== MOUSE
AT_OPTS = [("coords", "Nas coordenadas"), ("current", "Na posição atual do mouse")]


def _at_fields(default_at: str = "coords") -> list[F]:
    return [
        F("at", "Onde", "choice", default_at, options=AT_OPTS),
        F("pos", "Posição (x, y)", "point", (0, 0), keys=("x", "y"), show_if=("at", ("coords",))),
    ]


def _go(ctx: RunContext, p: dict) -> None:
    if (p.get("at") or "coords") == "coords":
        ctx.inputs.move(*_point(ctx, p))


def run_move(ctx: RunContext, cmd) -> None:
    p = cmd.params
    x, y = _point(ctx, p)
    if p.get("relative"):
        cx, cy = ctx.inputs.position()
        x, y = cx + x, cy + y
    C.smooth_move(ctx, x, y, ctx.number(p.get("duration_ms"), 0) / 1000)


register(CommandSpec(
    "mouse_move", "Mover mouse", M, "mouse",
    [F("pos", "Posição (x, y)", "point", (0, 0), keys=("x", "y")),
     F("relative", "Relativo à posição atual", "bool", False),
     F("duration_ms", "Duração do movimento (ms)", "int", 0, min=0, max=60_000)],
    lambda p: f"{'Deslocar' if p.get('relative') else 'Mover para'} {_xy(p)}" + (f" em {_ms(p.get('duration_ms'))}" if p.get("duration_ms") else ""),
    run_move,
))


def _click_spec(type_: str, label: str, button: str, clicks: int) -> None:
    def run(ctx: RunContext, cmd) -> None:
        _go(ctx, cmd.params)
        ctx.inputs.click(button, clicks)

    def desc(p):
        where = _xy(p) if (p.get("at") or "coords") == "coords" else "na posição atual"
        return f"{label} {where}"

    register(CommandSpec(type_, label, M, "mouse", _at_fields(), desc, run))


_click_spec("left_click", "Clique esquerdo", "left", 1)
_click_spec("right_click", "Clique direito", "right", 1)
_click_spec("double_click", "Clique duplo", "left", 2)
_click_spec("middle_click", "Clique do meio", "middle", 1)


def run_mouse_down(ctx: RunContext, cmd) -> None:
    _go(ctx, cmd.params)
    b = cmd.params.get("button") or "left"
    ctx.inputs.down(b)
    ctx.held_buttons.add(b)


def run_mouse_up(ctx: RunContext, cmd) -> None:
    _go(ctx, cmd.params)
    b = cmd.params.get("button") or "left"
    ctx.inputs.up(b)
    ctx.held_buttons.discard(b)


for _t, _l, _r in (("mouse_down", "Pressionar botão", run_mouse_down), ("mouse_up", "Soltar botão", run_mouse_up)):
    register(CommandSpec(
        _t, _l, M, "mouse",
        [F("button", "Botão", "choice", "left", options=C.BUTTON_OPTS), *_at_fields("current")],
        (lambda l: lambda p: f"{l} {C.BUTTON_NAME.get(p.get('button'), '').lower()}"
         + (f" em {_xy(p)}" if p.get("at") == "coords" else ""))(_l),
        _r,
    ))


def run_drag(ctx: RunContext, cmd) -> None:
    p = cmd.params
    b = p.get("button") or "left"
    ctx.inputs.move(*_point(ctx, p, "x1", "y1"))
    ctx.sleep(0.05)
    ctx.inputs.down(b)
    ctx.held_buttons.add(b)
    try:
        x2, y2 = _point(ctx, p, "x2", "y2")
        C.smooth_move(ctx, x2, y2, max(0.05, ctx.number(p.get("duration_ms"), 400) / 1000))
        ctx.sleep(0.05)
    finally:
        ctx.inputs.up(b)
        ctx.held_buttons.discard(b)


register(CommandSpec(
    "drag", "Arrastar e soltar", M, "mouse",
    [F("from", "De (x, y)", "point", (0, 0), keys=("x1", "y1")),
     F("to", "Para (x, y)", "point", (100, 100), keys=("x2", "y2")),
     F("button", "Botão", "choice", "left", options=C.BUTTON_OPTS),
     F("duration_ms", "Duração (ms)", "int", 400, min=50, max=60_000)],
    lambda p: f"Arrastar de {_xy(p, 'x1', 'y1')} até {_xy(p, 'x2', 'y2')}",
    run_drag,
))


def run_scroll(ctx: RunContext, cmd) -> None:
    p = cmd.params
    _go(ctx, p)
    ctx.inputs.scroll(ctx.integer(p.get("vertical"), 0), ctx.integer(p.get("horizontal"), 0))


def _desc_scroll(p):
    parts = []
    v, h = int(p.get("vertical") or 0), int(p.get("horizontal") or 0)
    if v:
        parts.append(f"{abs(v)} para {'cima' if v > 0 else 'baixo'}")
    if h:
        parts.append(f"{abs(h)} para a {'direita' if h > 0 else 'esquerda'}")
    where = f" em {_xy(p)}" if p.get("at") == "coords" else ""
    return f"Rolar {' e '.join(parts) or '0'}{where}"


register(CommandSpec(
    "scroll", "Rolar (scroll)", M, "mouse",
    [F("vertical", "Vertical (+ cima, − baixo)", "int", -3, min=-100, max=100),
     F("horizontal", "Horizontal (+ direita, − esquerda)", "int", 0, min=-100, max=100),
     *_at_fields("current")],
    _desc_scroll, run_scroll,
))


# ================================================================== TECLADO
def _key(ctx: RunContext, v: Any) -> str:
    try:
        return normalize_key(ctx.text(v))
    except ValueError as e:
        raise MacroError(str(e)) from e


def run_key_press(ctx: RunContext, cmd) -> None:
    k = _key(ctx, cmd.params.get("key"))
    for i in range(max(1, ctx.integer(cmd.params.get("times"), 1))):
        if i:
            ctx.sleep(0.03)
        ctx.inputs.key_down(k)
        ctx.inputs.key_up(k)


def run_key_down(ctx: RunContext, cmd) -> None:
    k = _key(ctx, cmd.params.get("key"))
    ctx.inputs.key_down(k)
    ctx.held_keys.add(k)


def run_key_up(ctx: RunContext, cmd) -> None:
    k = _key(ctx, cmd.params.get("key"))
    ctx.inputs.key_up(k)
    ctx.held_keys.discard(k)


register(CommandSpec(
    "key_press", "Pressionar tecla", K, "keyboard",
    [F("key", "Tecla", "key", "enter"), F("times", "Vezes", "int", 1, min=1, max=1000)],
    lambda p: f"Tecla {str(p.get('key')).upper()}" + (f" ×{p.get('times')}" if int(p.get("times") or 1) > 1 else ""),
    run_key_press,
))
register(CommandSpec("key_down", "Manter tecla pressionada", K, "keyboard", [F("key", "Tecla", "key", "shift")],
                     lambda p: f"Pressionar {str(p.get('key')).upper()} (sem soltar)", run_key_down))
register(CommandSpec("key_up", "Soltar tecla", K, "keyboard", [F("key", "Tecla", "key", "shift")],
                     lambda p: f"Soltar {str(p.get('key')).upper()}", run_key_up))


def run_type(ctx: RunContext, cmd) -> None:
    text = ctx.text(cmd.params.get("text") or "")
    interval = max(0.0, ctx.number(cmd.params.get("interval_ms"), 10) / 1000)
    for i, ch in enumerate(text):
        ctx.check()
        ctx.inputs.type_char(ch)
        if interval and i < len(text) - 1:
            ctx.sleep(interval)


register(CommandSpec(
    "type_text", "Digitar texto", K, "keyboard",
    [F("text", "Texto", "multiline", "", help="Use {variavel} para inserir o valor de uma variável."),
     F("interval_ms", "Intervalo entre teclas (ms)", "int", 10, min=0, max=5000)],
    lambda p: "Digitar “" + (str(p.get("text") or "")[:60].replace("\n", "⏎")) + ("…" if len(str(p.get("text") or "")) > 60 else "") + "”",
    run_type,
))


def run_hotkey(ctx: RunContext, cmd) -> None:
    try:
        keys = parse_combo(ctx.text(cmd.params.get("keys")))
    except ValueError as e:
        raise MacroError(str(e)) from e
    pressed = []
    try:
        for k in keys:
            ctx.inputs.key_down(k)
            pressed.append(k)
            time.sleep(0.01)
    finally:
        for k in reversed(pressed):
            ctx.inputs.key_up(k)


register(CommandSpec(
    "hotkey", "Combinação de teclas", K, "keyboard",
    [F("keys", "Combinação", "hotkey", "ctrl+c", help="Ex.: ctrl+shift+s, alt+tab, win+d")],
    lambda p: f"Teclas {str(p.get('keys')).upper()}",
    run_hotkey,
))


def run_hold(ctx: RunContext, cmd) -> None:
    k = _key(ctx, cmd.params.get("key"))
    ctx.inputs.key_down(k)
    ctx.held_keys.add(k)
    try:
        ctx.sleep(ctx.number(cmd.params.get("duration_ms"), 1000) / 1000)
    finally:
        ctx.inputs.key_up(k)
        ctx.held_keys.discard(k)


register(CommandSpec(
    "hold_key", "Segurar tecla por um tempo", K, "keyboard",
    [F("key", "Tecla", "key", "w"), F("duration_ms", "Duração (ms)", "int", 1000, min=1, max=3_600_000)],
    lambda p: f"Segurar {str(p.get('key')).upper()} por {_ms(p.get('duration_ms'))}",
    run_hold,
))


# ================================================================== IMAGEM E TELA
def run_image(ctx: RunContext, cmd) -> Flow | None:
    p = cmd.params
    name = p.get("image") or ""
    f = C.search_loop(ctx, p, lambda: ctx.vision.find_image(name, p, ctx.integer))
    return C.finish(ctx, p, f)


def _desc_image(verb: str):
    def d(p):
        out = f"{verb} “{p.get('image') or '?'}” {C.describe_search(p)} (≥{p.get('threshold')}%, {C.describe_wait(p)})"
        tail = C.describe_outcome(p)
        return f"{out} → {tail}" if tail else out
    return d


def _image_spec(type_: str, label: str, verb: str, on_found: str, timeout: int, on_nf: str = "continue", infinite=False):
    fields = C.image_match_fields() + C.search_area_fields() + C.wait_fields(timeout) + C.found_fields(on_found) + C.not_found_fields(on_nf)
    for f in fields:
        if f.key == "infinite":
            f.default = infinite
    register(CommandSpec(type_, label, IMG, "image", fields, _desc_image(verb), run_image,
                         opens_block_when=C.opens_block))


_image_spec("smart_click", "Smart Click", "Smart Click em", "left", 5000)
_image_spec("find_image", "Procurar imagem", "Procurar", "none", 0)
_image_spec("wait_image", "Aguardar imagem aparecer", "Aguardar", "none", 30000, "stop")
_image_spec("click_image", "Clicar em imagem", "Clicar em", "left", 5000, "stop")


def run_wait_vanish(ctx: RunContext, cmd) -> Flow | None:
    p = cmd.params
    name = p.get("image") or ""
    f = C.search_loop(ctx, p, lambda: ctx.vision.find_image(name, p, ctx.integer), want=False)
    ctx.last_similarity = f.score
    if not f.found:
        ctx.status = "Sumiu"
        ctx.log("Imagem não está mais na tela", "ok", similarity=f.score)
        return None
    ctx.status = f"Ainda visível {f.score:.0%}"
    ctx.log("Tempo esgotado: a imagem continua na tela", "warn", similarity=f.score, coords=(f.x, f.y))
    return C.apply_not_found(ctx, {**p, "on_not_found": p.get("on_timeout")})


register(CommandSpec(
    "wait_image_vanish", "Aguardar imagem desaparecer", IMG, "image",
    C.image_match_fields() + C.search_area_fields() + C.wait_fields(30000) + [
        F("on_timeout", "Se continuar na tela", "choice", "stop",
          options=[o for o in C.ON_NOT_FOUND if o[0] in ("continue", "stop", "pause", "goto")]),
        F("goto_not_found", "Ir para (rótulo ou nº da etapa)", "label", "", show_if=("on_timeout", ("goto",))),
    ],
    lambda p: f"Aguardar “{p.get('image') or '?'}” sumir {C.describe_search(p)} ({C.describe_wait(p)})",
    run_wait_vanish,
))


def run_pixel(ctx: RunContext, cmd) -> Flow | None:
    p = cmd.params
    x, y = _point(ctx, p)
    try:
        want = matcher.parse_color(ctx.text(p.get("color")))
    except ValueError as e:
        raise MacroError(str(e)) from e
    tol = ctx.integer(p.get("tolerance"), 10)
    state: dict[str, Any] = {}

    def probe() -> Found:
        got = ctx.vision.pixel(x, y)
        state["got"] = got
        dist = matcher.color_distance(got, want)
        return Found(dist <= tol, 1 - dist / 255, x, y)

    f = C.search_loop(ctx, p, probe)
    got = state.get("got")
    if got:
        ctx.vars["cor_pixel"] = matcher.to_hex(got)
    flow = C.finish(ctx, p, f, "Cor")
    ctx.status = ("Cor confere" if f.found else f"Cor {matcher.to_hex(got) if got else '?'}")
    return flow


register(CommandSpec(
    "pixel_color", "Verificar cor de pixel", IMG, "image",
    [F("pos", "Pixel (x, y)", "point", (0, 0), keys=("x", "y")),
     F("color", "Cor esperada", "color", "#FFFFFF"),
     F("tolerance", "Tolerância por canal (0–255)", "int", 10, min=0, max=255),
     *C.wait_fields(0), *C.found_fields("none"), *C.not_found_fields("continue")],
    lambda p: f"Pixel {_xy(p)} = {p.get('color')} ±{p.get('tolerance')}" + (f" → {C.describe_outcome(p)}" if C.describe_outcome(p) else ""),
    run_pixel, opens_block_when=C.opens_block,
))


def run_find_color(ctx: RunContext, cmd) -> Flow | None:
    p = cmd.params
    try:
        want = matcher.parse_color(ctx.text(p.get("color")))
    except ValueError as e:
        raise MacroError(str(e)) from e
    tol = ctx.integer(p.get("tolerance"), 10)
    f = C.search_loop(ctx, p, lambda: ctx.vision.find_color(want, tol, p, ctx.integer))
    return C.finish(ctx, p, f, "Cor")


register(CommandSpec(
    "find_color", "Procurar cor", IMG, "image",
    [F("color", "Cor", "color", "#FF0000"),
     F("tolerance", "Tolerância por canal (0–255)", "int", 10, min=0, max=255),
     *C.search_area_fields(), *C.wait_fields(0), *C.found_fields("move"), *C.not_found_fields("continue")],
    lambda p: f"Procurar cor {p.get('color')} ±{p.get('tolerance')} {C.describe_search(p)}" + (f" → {C.describe_outcome(p)}" if C.describe_outcome(p) else ""),
    run_find_color, opens_block_when=C.opens_block,
))


def run_screenshot(ctx: RunContext, cmd) -> None:
    p = cmd.params
    try:
        area = ctx.vision.search_rect(p, ctx.integer)
        img, area = ctx.vision.grab(area)
    except Exception as e:
        raise MacroError(str(e)) from e
    folder = ctx.resolve_path(p.get("folder") or str(Path.home() / "Pictures" / "Shift Macro"))
    folder.mkdir(parents=True, exist_ok=True)
    now = _dt.datetime.now()
    name = ctx.text(p.get("filename") or "captura_{data}_{hora}").replace("{data}", now.strftime("%Y-%m-%d")).replace("{hora}", now.strftime("%H-%M-%S"))
    name = "".join(c for c in name if c not in '<>:"/\\|?*') or "captura"
    path = folder / f"{name}.png"
    i = 2
    while path.exists():
        path = folder / f"{name}_{i}.png"
        i += 1
    path.write_bytes(matcher.encode_png(img))
    ctx.vars["ultima_captura"] = str(path)
    ctx.status = path.name
    ctx.log(f"Captura salva em {path}", "ok")


register(CommandSpec(
    "screenshot", "Capturar screenshot", IMG, "image",
    [*C.search_area_fields(),
     F("folder", "Pasta", "folder", str(Path.home() / "Pictures" / "Shift Macro")),
     F("filename", "Nome do arquivo", "text", "captura_{data}_{hora}", help="{data}, {hora} e {variaveis} são substituídos.")],
    lambda p: f"Salvar captura {C.describe_search(p)} em {p.get('folder')}",
    run_screenshot,
))


# ================================================================== FLUXO (executados pelo motor)
def run_delay(ctx: RunContext, cmd) -> None:
    lo = ctx.number(cmd.params.get("ms"), 1000)
    hi = ctx.number(cmd.params.get("random_max_ms"), 0)
    ms = random.uniform(lo, hi) if hi > lo else lo
    ctx.sleep(ms / 1000)


register(CommandSpec(
    "delay", "Delay (esperar)", FLOW, "delay",
    [F("ms", "Esperar (ms)", "int", 1000, min=0, max=86_400_000),
     F("random_max_ms", "Até (ms, aleatório; 0 = fixo)", "int", 0, min=0, max=86_400_000)],
    lambda p: f"Esperar {_ms(p.get('ms'))}" + (f" a {_ms(p.get('random_max_ms'))}" if (p.get("random_max_ms") or 0) > (p.get("ms") or 0) else ""),
    run_delay,
))
register(CommandSpec("if", "If (se)", FLOW, "condition", conditions.condition_fields(),
                     lambda p: "Se " + conditions.describe(p), block="open", block_family="if"))
register(CommandSpec("else_if", "Else If (senão, se)", FLOW, "condition", conditions.condition_fields(),
                     lambda p: "Senão, se " + conditions.describe(p), block="mid", block_family="if"))
register(CommandSpec("else", "Else (senão)", FLOW, "condition", [], lambda p: "Senão", block="mid", block_family="if"))
register(CommandSpec("end_if", "End If", FLOW, "condition", [], lambda p: "Fim do Se", block="close", block_family="if"))
register(CommandSpec(
    "loop", "Loop (repetir)", FLOW, "loop",
    [F("count", "Repetições (0 = infinito)", "expr", "3"),
     F("counter", "Guardar a volta atual na variável", "var", "volta", help="Começa em 1. Deixe vazio para não guardar.")],
    lambda p: "Repetir " + ("para sempre" if str(p.get("count")).strip() in ("0", "") else f"{p.get('count')} vezes")
    + (f" (volta em {p.get('counter')})" if p.get("counter") else ""),
    block="open", block_family="loop",
))
register(CommandSpec("end_loop", "End Loop", FLOW, "loop", [], lambda p: "Fim do Repetir", block="close", block_family="loop"))
register(CommandSpec("while", "While (enquanto)", FLOW, "loop", conditions.condition_fields(),
                     lambda p: "Enquanto " + conditions.describe(p), block="open", block_family="while"))
register(CommandSpec("end_while", "End While", FLOW, "loop", [], lambda p: "Fim do Enquanto", block="close", block_family="while"))
register(CommandSpec("break", "Break (sair do loop)", FLOW, "flow", [], lambda p: "Sair do loop"))
register(CommandSpec("continue", "Continue (próxima volta)", FLOW, "flow", [], lambda p: "Pular para a próxima volta"))
register(CommandSpec("goto", "Go To (ir para)", FLOW, "flow", [F("target", "Rótulo ou nº da etapa", "label", "")],
                     lambda p: f"Ir para {p.get('target') or '?'}"))
register(CommandSpec("label", "Label (rótulo)", FLOW, "flow", [F("label", "Nome do rótulo", "text", "inicio")],
                     lambda p: f"Rótulo: {p.get('label')}"))
register(CommandSpec("stop_macro", "Encerrar execução", FLOW, "flow", [], lambda p: "Encerrar a macro"))
register(CommandSpec("comment", "Comentário", FLOW, "comment", [F("text", "Texto", "multiline", "")],
                     lambda p: str(p.get("text") or "").replace("\n", " ")))


# ================================================================== VARIÁVEIS E FUNÇÕES
SET_OPS = [("=", "= (definir)"), ("+=", "+= (somar)"), ("-=", "−= (subtrair)"), ("*=", "×= (multiplicar)"), ("/=", "÷= (dividir)")]


def run_set_var(ctx: RunContext, cmd) -> None:
    p = cmd.params
    name = (p.get("name") or "").strip()
    raw = p.get("value")
    if isinstance(raw, str):
        try:
            val = expr.evaluate(raw, ctx.vars)
        except expr.ExprError as e:
            # texto simples sem aspas é aceito (ex.: Ana); algo com cara de
            # conta que falhou é erro, para não guardar "y + 1" por engano
            if any(ch in raw for ch in "+-*/<>=()%"):
                raise MacroError(f"Valor de '{name}': {e}") from e
            val = ctx.text(raw)
    else:
        val = raw
    op = p.get("op") or "="
    if op != "=":
        cur = ctx.vars.get(name, 0)
        try:
            cur_n = float(cur) if not isinstance(cur, (int, float)) else cur
            val_n = float(val) if not isinstance(val, (int, float)) else val
        except (TypeError, ValueError):
            if op == "+=":
                ctx.set_var(name, f"{cur}{val}")
                ctx.status = f"{name} = {ctx.vars[name]}"
                return
            raise MacroError(f"'{name}' não é número para {op}") from None
        if op == "+=":
            val = cur_n + val_n
        elif op == "-=":
            val = cur_n - val_n
        elif op == "*=":
            val = cur_n * val_n
        else:
            if val_n == 0:
                raise MacroError("Divisão por zero")
            val = cur_n / val_n
        if isinstance(val, float) and val.is_integer():
            val = int(val)
    ctx.set_var(name, val)
    ctx.status = f"{name} = {val!r}" if isinstance(val, str) else f"{name} = {val}"


register(CommandSpec(
    "set_var", "Definir variável", VAR, "variable",
    [F("name", "Variável", "var", "contador"), F("op", "Operação", "choice", "=", options=SET_OPS),
     F("value", "Valor ou expressão", "expr", "0", help="Ex.: 10, contador + 1, \"texto\", random(1, 6)")],
    lambda p: f"{p.get('name')} {p.get('op') or '='} {p.get('value')}",
    run_set_var,
))
register(CommandSpec("function", "Função (definir)", VAR, "flow", [F("name", "Nome da função", "text", "minha_funcao")],
                     lambda p: f"Função {p.get('name')}()", block="open", block_family="function"))
register(CommandSpec("end_function", "Fim da função", VAR, "flow", [], lambda p: "Fim da função", block="close", block_family="function"))
register(CommandSpec("call_function", "Chamar função", VAR, "flow", [F("name", "Função", "function", "")],
                     lambda p: f"Chamar {p.get('name') or '?'}()"))
register(CommandSpec("return", "Retornar da função", VAR, "flow", [], lambda p: "Retornar"))
register(CommandSpec("run_macro", "Executar outra macro", VAR, "flow",
                     [F("path", "Arquivo .shiftmacro", "macro", "")],
                     lambda p: f"Executar {Path(str(p.get('path') or '?')).name}"))


# ================================================================== SISTEMA
def run_open_program(ctx: RunContext, cmd) -> None:
    p = cmd.params
    path = ctx.text(p.get("path") or "").strip().strip('"')
    if not path:
        raise MacroError("Informe o programa.")
    args = ctx.text(p.get("args") or "")
    try:
        cmdline = f'"{path}" {args}'.strip()
        proc = subprocess.Popen(cmdline, shell=False, cwd=str(Path(path).parent) if Path(path).parent.is_dir() else None)
    except OSError as e:
        raise MacroError(f"Não foi possível abrir {path}: {e.strerror or e}") from e
    if p.get("wait"):
        while proc.poll() is None:
            ctx.sleep(0.1, scale=False)
        ctx.status = f"Encerrou ({proc.returncode})"


def _startfile(target: str) -> None:
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except OSError as e:
        raise MacroError(f"Não foi possível abrir {target}: {e.strerror or e}") from e


def run_open_file(ctx: RunContext, cmd) -> None:
    path = ctx.resolve_path(cmd.params.get("path") or "")
    if not path.exists():
        raise MacroError(f"Arquivo não encontrado: {path}")
    _startfile(str(path))


def run_open_folder(ctx: RunContext, cmd) -> None:
    path = ctx.resolve_path(cmd.params.get("path") or "")
    if not path.is_dir():
        raise MacroError(f"Pasta não encontrada: {path}")
    _startfile(str(path))


def run_open_url(ctx: RunContext, cmd) -> None:
    url = ctx.text(cmd.params.get("url") or "").strip()
    if not url:
        raise MacroError("Informe o endereço.")
    if "://" not in url:
        url = "https://" + url
    webbrowser.open(url)


register(CommandSpec("open_program", "Abrir programa", SYS, "system",
                     [F("path", "Programa", "file", "notepad.exe"), F("args", "Argumentos", "text", ""),
                      F("wait", "Esperar o programa fechar", "bool", False)],
                     lambda p: f"Abrir {p.get('path')} {p.get('args') or ''}".strip(), run_open_program))
register(CommandSpec("open_file", "Abrir arquivo", SYS, "system", [F("path", "Arquivo", "file", "")],
                     lambda p: f"Abrir arquivo {p.get('path')}", run_open_file))
register(CommandSpec("open_folder", "Abrir pasta", SYS, "system", [F("path", "Pasta", "folder", "")],
                     lambda p: f"Abrir pasta {p.get('path')}", run_open_folder))
register(CommandSpec("open_url", "Abrir URL", SYS, "system", [F("url", "Endereço", "text", "https://")],
                     lambda p: f"Abrir {p.get('url')}", run_open_url))


def run_wait_window(ctx: RunContext, cmd) -> Flow | None:
    p = cmd.params
    title = ctx.text(p.get("window"))

    def probe() -> Found:
        w = winapi.find_window(title)
        if not w:
            return Found(False, 0.0)
        if p.get("activate"):
            winapi.activate_window(w.hwnd)
        return Found(True, 1.0)

    f = C.search_loop(ctx, p, probe)
    if f.found:
        ctx.status = "Janela apareceu"
        ctx.log(f"Janela “{title}” encontrada", "ok")
        return None
    ctx.status = "Não apareceu"
    ctx.log(f"Janela “{title}” não apareceu", "warn")
    return C.apply_not_found(ctx, p)


register(CommandSpec(
    "wait_window", "Aguardar janela", SYS, "system",
    [F("window", "Título da janela (parte do nome)", "window", ""),
     F("activate", "Ativar quando aparecer", "bool", True),
     *C.wait_fields(30000),
     F("on_not_found", "Se não aparecer", "choice", "stop",
       options=[o for o in C.ON_NOT_FOUND if o[0] in ("continue", "stop", "pause", "goto")]),
     F("goto_not_found", "Ir para (rótulo ou nº da etapa)", "label", "", show_if=("on_not_found", ("goto",)))],
    lambda p: f"Aguardar janela “{p.get('window')}” ({C.describe_wait(p)})",
    run_wait_window,
))


def _window_or_fail(ctx: RunContext, p: dict) -> winapi.WindowInfo:
    title = ctx.text(p.get("window"))
    w = winapi.find_window(title)
    if not w:
        raise MacroError(f"Janela “{title}” não encontrada.")
    return w


def run_activate(ctx: RunContext, cmd) -> None:
    w = _window_or_fail(ctx, cmd.params)
    if not winapi.activate_window(w.hwnd):
        ctx.log("O Windows não deixou trazer a janela para a frente; ela foi destacada na barra de tarefas.", "warn")
    ctx.status = w.title[:40]


def run_window_state(ctx: RunContext, cmd) -> None:
    w = _window_or_fail(ctx, cmd.params)
    winapi.show_window(w.hwnd, cmd.params.get("state") or "minimize")


STATES = [("minimize", "Minimizar"), ("maximize", "Maximizar"), ("restore", "Restaurar")]
register(CommandSpec("activate_window", "Ativar janela", SYS, "system",
                     [F("window", "Título da janela (parte do nome)", "window", "")],
                     lambda p: f"Ativar janela “{p.get('window')}”", run_activate))
register(CommandSpec("window_state", "Minimizar/maximizar janela", SYS, "system",
                     [F("window", "Título da janela (parte do nome)", "window", ""),
                      F("state", "Ação", "choice", "minimize", options=STATES)],
                     lambda p: f"{dict(STATES).get(p.get('state'), '')} janela “{p.get('window')}”", run_window_state))


def run_notify(ctx: RunContext, cmd) -> None:
    ctx.notify(ctx.text(cmd.params.get("title") or "Shift Macro"), ctx.text(cmd.params.get("message") or ""))


def run_beep(ctx: RunContext, cmd) -> None:
    import winsound

    p = cmd.params
    kind = p.get("sound") or "alert"
    if kind == "tone":
        winsound.Beep(max(37, min(32767, ctx.integer(p.get("frequency"), 880))), max(10, ctx.integer(p.get("duration_ms"), 300)))
    else:
        flag = {"alert": winsound.MB_ICONEXCLAMATION, "error": winsound.MB_ICONHAND, "info": winsound.MB_ICONASTERISK}.get(kind, winsound.MB_OK)
        winsound.MessageBeep(flag)


register(CommandSpec("notify", "Exibir notificação", SYS, "system",
                     [F("title", "Título", "text", "Shift Macro"), F("message", "Mensagem", "multiline", "Etapa concluída")],
                     lambda p: f"Notificar: {p.get('title')} — {str(p.get('message') or '')[:50]}", run_notify))
register(CommandSpec("beep", "Alerta sonoro", SYS, "system",
                     [F("sound", "Som", "choice", "alert", options=[("alert", "Alerta do Windows"), ("info", "Informação"), ("error", "Erro"), ("tone", "Tom")]),
                      F("frequency", "Frequência (Hz)", "int", 880, min=37, max=32767, show_if=("sound", ("tone",))),
                      F("duration_ms", "Duração (ms)", "int", 300, min=10, max=10_000, show_if=("sound", ("tone",)))],
                     lambda p: "Alerta sonoro" + (f" {p.get('frequency')} Hz" if p.get("sound") == "tone" else ""), run_beep))

# tipos executados diretamente pelo motor
ENGINE_TYPES = {
    "if", "else_if", "else", "end_if", "loop", "end_loop", "while", "end_while", "break", "continue",
    "goto", "label", "stop_macro", "comment", "function", "end_function", "call_function", "return", "run_macro",
}
