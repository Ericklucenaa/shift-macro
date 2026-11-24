"""Gravação de mouse e teclado com pynput (ganchos de baixo nível do Windows)."""
from __future__ import annotations

import threading
import time
from typing import Callable

from .convert import RawEvent

_SPECIAL = {
    "alt": "alt", "alt_l": "altleft", "alt_r": "altright", "alt_gr": "altright",
    "ctrl": "ctrl", "ctrl_l": "ctrlleft", "ctrl_r": "ctrlright",
    "shift": "shift", "shift_l": "shiftleft", "shift_r": "shiftright",
    "cmd": "win", "cmd_l": "winleft", "cmd_r": "winright",
    "enter": "enter", "esc": "esc", "tab": "tab", "space": "space", "backspace": "backspace",
    "delete": "delete", "insert": "insert", "home": "home", "end": "end",
    "page_up": "pageup", "page_down": "pagedown", "up": "up", "down": "down", "left": "left", "right": "right",
    "caps_lock": "capslock", "num_lock": "numlock", "scroll_lock": "scrolllock",
    "print_screen": "printscreen", "pause": "pause", "menu": "apps",
    "media_volume_up": "volumeup", "media_volume_down": "volumedown", "media_volume_mute": "volumemute",
    "media_play_pause": "playpause", "media_next": "nexttrack", "media_previous": "prevtrack",
    **{f"f{i}": f"f{i}" for i in range(1, 25)},
}
# modificadores que viram "shift" etc. ao gerar combinações
_NORMAL_MOD = {"altleft": "alt", "altright": "alt", "ctrlleft": "ctrl", "ctrlright": "ctrl",
               "shiftleft": "shift", "shiftright": "shift", "winleft": "win", "winright": "win"}


def key_name(key) -> tuple[str, str | None]:
    """(nome PyAutoGUI, caractere produzido) para uma tecla do pynput."""
    from pynput import keyboard

    if isinstance(key, keyboard.Key):
        name = _SPECIAL.get(key.name, key.name)
        name = _NORMAL_MOD.get(name, name)
        return name, (" " if name == "space" else None)
    vk = getattr(key, "vk", None)
    ch = getattr(key, "char", None)
    if vk is not None:
        if 65 <= vk <= 90:
            base = chr(vk).lower()
        elif 48 <= vk <= 57:
            base = chr(vk)
        elif 96 <= vk <= 105:
            base = f"num{vk - 96}"
        elif ch and len(ch) == 1 and ch.isprintable():
            base = ch.lower()
        else:
            base = {106: "multiply", 107: "add", 109: "subtract", 110: "decimal", 111: "divide"}.get(vk, f"vk{vk}")
    else:
        base = (ch or "").lower() or "?"
    printable = ch if ch and len(ch) == 1 and ch.isprintable() else None
    return base, printable


class Recorder:
    def __init__(
        self,
        *,
        mode: str = "all",
        ignore_keys: set[str] | None = None,
        exclude_point: Callable[[int, int], bool] | None = None,
    ):
        self.mode = mode
        self.ignore_keys = {k.lower() for k in (ignore_keys or set())}
        self.exclude_point = exclude_point
        self.events: list[RawEvent] = []
        self._lock = threading.Lock()
        self._mouse = None
        self._kb = None
        self._t0 = 0.0
        self._ignored_down: set[str] = set()

    @property
    def running(self) -> bool:
        return self._mouse is not None or self._kb is not None

    def _add(self, e: RawEvent) -> None:
        with self._lock:
            self.events.append(e)

    def start(self) -> None:
        from pynput import keyboard, mouse

        self.events = []
        self._t0 = time.perf_counter()
        now = lambda: time.perf_counter() - self._t0  # noqa: E731
        bmap = {mouse.Button.left: "left", mouse.Button.right: "right", mouse.Button.middle: "middle"}

        if self.mode in ("all", "clicks"):
            def on_move(x, y):
                self._add(RawEvent(now(), "move", int(x), int(y)))

            def on_click(x, y, button, pressed):
                b = bmap.get(button)
                if not b:
                    return
                if self.exclude_point and self.exclude_point(int(x), int(y)):
                    return
                self._add(RawEvent(now(), "down" if pressed else "up", int(x), int(y), button=b))

            def on_scroll(x, y, dx, dy):
                if self.exclude_point and self.exclude_point(int(x), int(y)):
                    return
                self._add(RawEvent(now(), "scroll", int(x), int(y), dx=int(dx), dy=int(dy)))

            self._mouse = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
            self._mouse.start()

        if self.mode in ("all", "keyboard"):
            def on_press(key):
                name, ch = key_name(key)
                if name in self.ignore_keys:
                    self._ignored_down.add(name)
                    return
                self._add(RawEvent(now(), "kdown", key=name, char=ch))

            def on_release(key):
                name, _ = key_name(key)
                if name in self._ignored_down or name in self.ignore_keys:
                    self._ignored_down.discard(name)
                    return
                self._add(RawEvent(now(), "kup", key=name))

            self._kb = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._kb.start()

    def stop(self) -> list[RawEvent]:
        for lst in (self._mouse, self._kb):
            if lst is not None:
                lst.stop()
        self._mouse = self._kb = None
        with self._lock:
            ev = list(self.events)
        return _drop_dangling(ev)


def _drop_dangling(events: list[RawEvent]) -> list[RawEvent]:
    """Remove o "soltar" de um clique que começou antes da gravação (ex.: o
    clique no próprio botão Gravar) e eventos de teclas soltas sem pressionar."""
    down_buttons: set[str] = set()
    down_keys: set[str] = set()
    out: list[RawEvent] = []
    for e in events:
        if e.kind == "down":
            down_buttons.add(e.button)
        elif e.kind == "up":
            if e.button not in down_buttons:
                continue
            down_buttons.discard(e.button)
        elif e.kind == "kdown":
            down_keys.add(e.key)
        elif e.kind == "kup":
            if e.key not in down_keys:
                continue
            down_keys.discard(e.key)
        out.append(e)
    return out
