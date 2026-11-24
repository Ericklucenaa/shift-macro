"""Funções do Windows via ctypes: DPI, janelas e atalhos globais."""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
else:  # pragma: no cover - o app é só para Windows
    user32 = kernel32 = dwmapi = None


def ensure_dpi_aware() -> None:
    """Coordenadas físicas em todos os monitores (Per-Monitor V2)."""
    if not IS_WINDOWS:
        return
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


# ---------------------------------------------------------------- janelas
@dataclass
class WindowInfo:
    hwnd: int
    title: str


if IS_WINDOWS:
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def list_windows() -> list[WindowInfo]:
    """Janelas visíveis com título, na ordem Z (da frente para trás)."""
    if not IS_WINDOWS:
        return []
    out: list[WindowInfo] = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip():
                    out.append(WindowInfo(int(hwnd), buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def find_window(title: str, exact: bool = False) -> WindowInfo | None:
    t = (title or "").strip().lower()
    if not t:
        return None
    for w in list_windows():
        name = w.title.lower()
        if (name == t) if exact else (t in name):
            return w
    return None


def window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) visíveis da janela, sem a sombra do Windows 10/11."""
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    res = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
    )
    if res != 0:
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9


def show_window(hwnd: int, mode: str) -> None:
    cmd = {"minimize": SW_MINIMIZE, "maximize": SW_MAXIMIZE, "restore": SW_RESTORE}[mode]
    user32.ShowWindow(wintypes.HWND(hwnd), cmd)


def activate_window(hwnd: int) -> bool:
    """Traz a janela para a frente. O Windows bloqueia SetForegroundWindow de
    processos em segundo plano; anexar a entrada à thread da janela da frente
    contorna isso de forma suportada."""
    h = wintypes.HWND(hwnd)
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    cur_thread = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    attached = False
    if fg_thread and fg_thread != cur_thread:
        attached = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
    try:
        user32.BringWindowToTop(h)
        ok = bool(user32.SetForegroundWindow(h))
    finally:
        if attached:
            user32.AttachThreadInput(cur_thread, fg_thread, False)
    return ok or user32.GetForegroundWindow() == hwnd


def foreground_window() -> WindowInfo | None:
    h = user32.GetForegroundWindow()
    return WindowInfo(int(h), window_title(h)) if h else None


# ---------------------------------------------------------------- atalhos globais
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT, WM_APP = 0x0312, 0x0012, 0x8000

_VK_NAMES = {
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "enter": 0x0D, "tab": 0x09, "backspace": 0x08,
    "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdown": 0x22, "pause": 0x13,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "printscreen": 0x2C, "print": 0x2C,
    "scrolllock": 0x91, "numlock": 0x90,
    **{f"num{d}": 0x60 + d for d in range(10)},
}
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "alt": MOD_ALT, "win": MOD_WIN, "meta": MOD_WIN}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Shift+F11' -> (modificadores, vk). Lança ValueError se inválido."""
    parts = [p.strip() for p in (text or "").replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("Atalho vazio")
    mods = 0
    vk = None
    for p in parts:
        low = p.lower()
        if low in _MODS:
            mods |= _MODS[low]
            continue
        key = p.upper() if len(p) == 1 else low
        if key not in _VK_NAMES:
            raise ValueError(f"Tecla não suportada em atalho: {p}")
        if vk is not None:
            raise ValueError("Use só uma tecla além dos modificadores")
        vk = _VK_NAMES[key]
    if vk is None:
        raise ValueError("Falta a tecla principal do atalho")
    return mods, vk


class GlobalHotkeys:
    """Registra atalhos com RegisterHotKey numa thread com loop de mensagens.

    Funciona com o app minimizado e independe do motor de execução estar
    ocupado: o callback roda nesta thread (deve ser rápido e thread-safe).
    """

    def __init__(self, on_hotkey: Callable[[str], None]):
        self._on = on_hotkey
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._wanted: dict[str, str] = {}
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self.errors: dict[str, str] = {}

    def start(self, bindings: dict[str, str]) -> dict[str, str]:
        self.stop()
        self._wanted = dict(bindings)
        self.errors = {}
        if not IS_WINDOWS:
            return self.errors
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self.errors

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None
        self._tid = 0

    def _loop(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        for i, (action, combo) in enumerate(self._wanted.items(), start=1):
            if not combo:
                continue
            try:
                mods, vk = parse_hotkey(combo)
            except ValueError as e:
                self.errors[action] = str(e)
                continue
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = action
            else:
                self.errors[action] = f"{combo} já está em uso por outro programa"
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                try:
                    self._on(ids[msg.wParam])
                except Exception:  # nunca derrubar a thread de atalhos
                    pass
        for i in ids:
            user32.UnregisterHotKey(None, i)
