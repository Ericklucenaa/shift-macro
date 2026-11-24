"""Converte eventos brutos de mouse/teclado em comandos editáveis.

Regras:
- pressionar e soltar no mesmo lugar (≤ 6 px, < 0,6 s) vira clique; dois cliques
  próximos e rápidos viram clique duplo;
- pressionar, mover e soltar vira "Arrastar" (ou Pressionar/Mover/Soltar se os
  movimentos estiverem sendo gravados);
- letras digitadas em sequência viram um único "Digitar texto";
- tecla com Ctrl/Alt/Win vira "Combinação de teclas";
- tecla segurada por mais de 0,6 s vira Manter pressionada + Soltar (preserva
  teclas sobrepostas, como andar e pular em jogos);
- rolagens seguidas são somadas;
- o tempo entre eventos vira o Delay de cada etapa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..actions.registry import make
from ..core.model import Command

CLICK_DIST = 6
CLICK_TIME = 0.6
DOUBLE_TIME = 0.45
HOLD_TIME = 0.6
SCROLL_MERGE = 0.35
MODIFIERS = {"ctrl", "ctrlleft", "ctrlright", "alt", "altleft", "altright", "shift", "shiftleft", "shiftright", "win", "winleft", "winright"}
_MOD_BASE = {m: m.replace("left", "").replace("right", "") for m in MODIFIERS}


@dataclass
class RawEvent:
    t: float
    kind: str  # move down up scroll kdown kup
    x: int = 0
    y: int = 0
    button: str = ""
    dx: int = 0
    dy: int = 0
    key: str = ""
    char: str | None = None  # caractere produzido (teclas de texto)


@dataclass
class _Item:
    t0: float
    t1: float
    cmd: Command
    meta: dict[str, Any] = field(default_factory=dict)


def _dist(a: RawEvent, b: RawEvent) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _printable(ch: str | None) -> bool:
    return bool(ch) and len(ch) == 1 and (ch.isprintable() or ch == " ")


def convert(
    events: list[RawEvent],
    *,
    mode: str = "all",  # all | clicks | keyboard
    record_moves: bool = True,
    min_move_ms: int = 30,
    keep_delays: bool = True,
) -> list[Command]:
    events = sorted(events, key=lambda e: e.t)
    use_mouse = mode in ("all", "clicks")
    use_keys = mode in ("all", "keyboard")
    moves = use_mouse and mode == "all" and record_moves
    items: list[_Item] = []

    # pré-cálculo: quando cada tecla foi solta (para detectar tecla segurada)
    release_at: dict[int, float] = {}
    down_since: dict[str, int] = {}
    for i, e in enumerate(events):
        if e.kind == "kdown" and e.key not in down_since:
            down_since[e.key] = i
        elif e.kind == "kup" and e.key in down_since:
            release_at[down_since.pop(e.key)] = e.t
    first_down: set[int] = set()
    held: set[str] = set()
    for i, e in enumerate(events):
        if e.kind == "kdown" and e.key not in held:
            held.add(e.key)
            first_down.add(i)
        elif e.kind == "kup":
            held.discard(e.key)

    mods_down: list[str] = []
    mods_used: set[str] = set()
    long_held: set[str] = set()
    text: _Item | None = None
    last_key: _Item | None = None
    pending_down: dict[str, tuple[RawEvent, int]] = {}  # botão -> (evento, índice no items)
    last_move_t = -1e9
    last_move: RawEvent | None = None

    def flush_text():
        nonlocal text
        text = None

    def add(t0: float, cmd: Command, t1: float | None = None, **meta) -> _Item:
        it = _Item(t0, t0 if t1 is None else t1, cmd, meta)
        items.append(it)
        return it

    for i, e in enumerate(events):
        k = e.kind
        if k in ("move", "down", "up", "scroll") and not use_mouse:
            continue
        if k in ("kdown", "kup") and not use_keys:
            continue
        if k == "move":
            if not moves:
                continue
            if (e.t - last_move_t) * 1000 < min_move_ms or (last_move and _dist(e, last_move) < 2):
                continue
            last_move_t, last_move = e.t, e
            flush_text()
            last_key = None
            add(e.t, make("mouse_move", x=e.x, y=e.y))
            continue
        if k == "down":
            flush_text()
            last_key = None
            # a ação é decidida no "up"; guarda a posição na lista
            ph_new = _Item(e.t, e.t, make("mouse_down", button=e.button, at="coords", x=e.x, y=e.y), {"placeholder": e.button})
            items.append(ph_new)
            pending_down[e.button] = (e, ph_new)
            continue
        if k == "up":
            if e.button not in pending_down:
                continue
            d, ph = pending_down.pop(e.button)
            idx = next((n for n in range(len(items) - 1, -1, -1) if items[n] is ph), None)
            if idx is None:
                continue
            if _dist(d, e) <= CLICK_DIST and e.t - d.t < CLICK_TIME:
                # clique; remove movimentos gravados entre pressionar e soltar
                del items[idx + 1:]
                j = _previous_click(items, idx, d) if d.button == "left" else None
                if j is not None:
                    prev = items[j]
                    prev.cmd = make("double_click", at="coords", x=prev.cmd.params["x"], y=prev.cmd.params["y"])
                    prev.t1 = e.t
                    prev.meta["double"] = True
                    del items[j + 1:]  # movimentos entre os cliques e o segundo clique
                else:
                    type_ = {"left": "left_click", "right": "right_click", "middle": "middle_click"}.get(d.button, "left_click")
                    ph.cmd = make(type_, at="coords", x=d.x, y=d.y)
                    ph.t1 = e.t
                    ph.meta = {"click": d.button, "x": d.x, "y": d.y}
            elif _dist(d, e) > CLICK_DIST and not moves:
                ph.cmd = make("drag", x1=d.x, y1=d.y, x2=e.x, y2=e.y, button=d.button,
                              duration_ms=int(max(50, (e.t - d.t) * 1000)))
                ph.t1 = e.t
                ph.meta = {}
            else:
                # pressionado longo ou arrasto com movimentos gravados: mantém
                # Pressionar ... Soltar para reproduzir fielmente
                ph.meta = {}
                add(e.t, make("mouse_up", button=e.button, at="coords", x=e.x, y=e.y))
            continue
        if k == "scroll":
            flush_text()
            last_key = None
            prev = items[-1] if items else None
            if prev and prev.cmd.type == "scroll" and e.t - prev.t1 < SCROLL_MERGE and abs(prev.cmd.params["x"] - e.x) < 20:
                prev.cmd.params["vertical"] += e.dy
                prev.cmd.params["horizontal"] += e.dx
                prev.t1 = e.t
            else:
                add(e.t, make("scroll", vertical=e.dy, horizontal=e.dx, at="coords", x=e.x, y=e.y))
            continue
        if k == "kdown":
            key = e.key
            if key in MODIFIERS:
                if i in first_down:
                    base = _MOD_BASE[key]
                    if base not in mods_down:
                        mods_down.append(base)
                continue
            combo_mods = [m for m in mods_down if m != "shift"]
            if i in first_down and not combo_mods and release_at.get(i, e.t) - e.t >= HOLD_TIME:
                # tecla segurada: Manter pressionada ... Soltar
                flush_text()
                last_key = None
                long_held.add(key)
                add(e.t, make("key_down", key=key))
                continue
            if key in long_held:
                continue  # repetição automática de tecla segurada
            if combo_mods:
                flush_text()
                last_key = None
                keys = combo_mods + (["shift"] if "shift" in mods_down else []) + [key]
                mods_used.update(mods_down)
                add(e.t, make("hotkey", keys="+".join(keys)))
                continue
            if _printable(e.char):
                last_key = None
                if text is None:
                    text = add(e.t, make("type_text", text=""))
                text.cmd.params["text"] += e.char
                text.t1 = e.t
                if "shift" in mods_down:
                    mods_used.add("shift")
                continue
            flush_text()
            if last_key and last_key.cmd.params.get("key") == key and e.t - last_key.t1 < 0.6:
                last_key.cmd.params["times"] = int(last_key.cmd.params.get("times") or 1) + 1
                last_key.t1 = e.t
            else:
                last_key = add(e.t, make("key_press", key=key))
            continue
        if k == "kup":
            key = e.key
            if key in long_held:
                long_held.discard(key)
                add(e.t, make("key_up", key=key))
                continue
            if key in MODIFIERS:
                base = _MOD_BASE[key]
                if base in mods_down:
                    mods_down.remove(base)
                    if base not in mods_used and base in ("win", "alt"):
                        flush_text()
                        last_key = None
                        add(e.t, make("key_press", key=base))
                    mods_used.discard(base)
            continue

    # botões ainda pressionados no fim: vira Pressionar sem Soltar
    for it in items:
        it.meta.pop("placeholder", None)

    cmds = [it.cmd for it in items]
    for a, b in zip(items, items[1:]):
        a.cmd.delay_ms = int(round(max(0.0, b.t0 - a.t1) * 1000)) if keep_delays else 0
    return cmds


def _previous_click(items: list[_Item], idx: int, d: RawEvent) -> int | None:
    """Índice do clique esquerdo imediatamente anterior, perto e recente (clique duplo)."""
    j = idx - 1
    while j >= 0 and items[j].cmd.type == "mouse_move":
        j -= 1
    if j < 0:
        return None
    prev = items[j]
    if prev.meta.get("click") != "left" or prev.meta.get("double"):
        return None
    if abs(prev.meta["x"] - d.x) > CLICK_DIST or abs(prev.meta["y"] - d.y) > CLICK_DIST:
        return None
    if d.t - prev.t1 > DOUBLE_TIME:
        return None
    return j
