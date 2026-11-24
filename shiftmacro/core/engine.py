"""Motor de execução de macros, independente da interface.

Roda numa thread própria. A interface acompanha por um Listener (callbacks
chamados na thread do motor — quem usa Qt deve repassar via sinais).
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..actions import commands as _commands  # noqa: F401  (registra os comandos)
from ..actions import conditions, registry
from .context import LogEntry, MacroError, RunContext, StopRequested
from .model import Macro, RunSettings
from .structure import Structure, analyze, resolve_target

MAX_CALL_DEPTH = 200
MAX_MACRO_DEPTH = 8


class Listener:
    """Callbacks do motor. Todos opcionais; chamados na thread do motor."""

    def on_state(self, state: str) -> None: ...  # running | paused | step | stopped
    def on_step(self, row: int) -> None: ...
    def on_status(self, row: int, text: str, level: str) -> None: ...  # ok | warn | error | skip
    def on_log(self, entry: LogEntry) -> None: ...
    def on_repetition(self, current: int, total: int | None) -> None: ...
    def on_finished(self, result: "RunResult") -> None: ...


@dataclass
class RunResult:
    completed: bool  # terminou normalmente
    stopped: bool  # parada pelo usuário
    error: str | None
    repetitions: int
    elapsed: float
    error_row: int | None = None


@dataclass
class _Frame:
    start: int
    end: int
    count: int = 0  # 0 = infinito (loop) / não se aplica (while)
    done: int = 0
    counter: str = ""


class _StopMacro(Exception):
    pass


class Engine:
    def __init__(
        self,
        macro: Macro,
        inputs,
        vision=None,
        listener: Listener | None = None,
        *,
        base_dir: Path | None = None,
        notify: Callable[[str, str], None] | None = None,
        macro_loader: Callable[[Path], Macro] | None = None,
    ):
        self.macro = macro
        self.inputs = inputs
        if vision is None:
            from ..vision.service import VisionService

            vision = VisionService(macro.images)
        self.vision = vision
        self.listener = listener or Listener()
        self.base_dir = base_dir
        self.notify = notify
        self.macro_loader = macro_loader
        self.stop_event = threading.Event()
        self.run_event = threading.Event()
        self.run_event.set()
        self.step_mode = False
        self._thread: threading.Thread | None = None
        self.ctx: RunContext | None = None

    # ------------------------------------------------------------ controle
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def paused(self) -> bool:
        return not self.run_event.is_set()

    def stop(self) -> None:
        self.stop_event.set()
        self.run_event.set()  # destrava quem estiver pausado

    def pause(self) -> None:
        if not self.stop_event.is_set():
            self.run_event.clear()
            self.listener.on_state("paused")

    def resume(self) -> None:
        self.step_mode = False
        self.run_event.set()
        self.listener.on_state("running")

    def toggle_pause(self) -> None:
        if self.paused:
            self.resume()
        else:
            self.pause()

    def next_step(self) -> None:
        """No modo passo a passo, executa a próxima etapa."""
        self.step_mode = True
        self.run_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------ validação
    @staticmethod
    def check_structure(commands) -> Structure:
        return analyze(commands)

    # ------------------------------------------------------------ execução
    def start(self, **kw: Any) -> None:
        if self.running:
            raise RuntimeError("A macro já está em execução.")

        def target():
            res = self.run(**kw)
            self.listener.on_finished(res)

        self._thread = threading.Thread(target=target, name="macro-engine", daemon=True)
        self._thread.start()

    def run(
        self,
        *,
        start_at: int = 0,
        only: list[int] | None = None,
        settings: RunSettings | None = None,
        step_mode: bool = False,
    ) -> RunResult:
        """Executa de forma bloqueante e devolve o resultado (nunca lança)."""
        s = settings or self.macro.settings
        self.stop_event.clear()
        self.run_event.set()
        self.step_mode = step_mode
        t0 = time.perf_counter()
        all_cmds = self.macro.commands
        if only:
            rows = sorted(set(i for i in only if 0 <= i < len(all_cmds)))
        else:
            rows = list(range(len(all_cmds)))
        cmds = [all_cmds[i] for i in rows]
        st = analyze(cmds)
        if st.errors:
            i, msg = st.errors[0]
            prefix = "A seleção corta um bloco ao meio. " if only else ""
            err = f"{prefix}Etapa {rows[i] + 1}: {msg}" if i < len(rows) else msg
            self._log(LogEntry(time.time(), "error", err, step=rows[i] if i < len(rows) else None))
            return RunResult(False, False, err, 0, 0.0, rows[i] if i < len(rows) else None)
        first = 0
        if not only and start_at:
            first = max(0, min(start_at, len(cmds)))
        ctx = RunContext(
            self.macro, self.inputs, self.vision,
            stop_event=self.stop_event, run_event=self.run_event, speed=s.speed,
            log=self._log, notify=self.notify, base_dir=self.base_dir,
        )
        self.ctx = ctx
        total = {"once": 1, "count": max(1, s.repeat_count)}.get(s.repeat_mode)
        rep = 0
        stopped = False
        error: str | None = None
        error_row: int | None = None
        self.listener.on_state("step" if step_mode else "running")
        ctx.log(f"Início: {self.macro.name}", "info")
        try:
            while True:
                rep += 1
                ctx.repetition = rep
                ctx.vars["repeticao"] = rep
                self.listener.on_repetition(rep, total)
                try:
                    self._run_list(ctx, cmds, rows, st, first if rep == 1 else 0)
                except _StopMacro:
                    break
                if s.repeat_mode == "once":
                    break
                if s.repeat_mode == "count" and rep >= max(1, s.repeat_count):
                    break
                if s.repeat_mode == "duration" and time.perf_counter() - t0 >= s.repeat_minutes * 60:
                    break
                ctx.check()
        except StopRequested:
            stopped = True
            ctx.log("Execução interrompida pelo usuário", "warn")
        except MacroError as e:
            error, error_row = str(e), ctx.step
        except Exception as e:  # erro inesperado: mostra a causa sem derrubar o app
            error, error_row = f"{type(e).__name__}: {e}", ctx.step
            self._log(LogEntry(time.time(), "error", traceback.format_exc(limit=6), step=ctx.step))
        finally:
            ctx.release_all()
            self.listener.on_state("stopped")
        elapsed = time.perf_counter() - t0
        ctx.step, ctx.command_label = (error_row, ctx.command_label) if error else (None, "")
        if error:
            ctx.log(f"Erro: {error}", "error")
        elif not stopped:
            ctx.log(f"Concluída: {rep} repetição(ões) em {elapsed:.1f} s", "ok", elapsed_ms=elapsed * 1000)
        return RunResult(not stopped and not error, stopped, error, rep, elapsed, error_row)

    # ------------------------------------------------------------ núcleo
    def _log(self, entry: LogEntry) -> None:
        self.listener.on_log(entry)

    def _status(self, row: int | None, text: str, level: str) -> None:
        if row is not None:
            self.listener.on_status(row, text, level)

    def _run_list(self, ctx: RunContext, cmds, rows: list[Any], st: Structure, pc: int = 0) -> None:
        n = len(cmds)
        loops: list[_Frame] = []
        calls: list[tuple[int, int]] = []
        pending: int | None = None  # ramo (else/else_if) que deve ser avaliado

        def false_branch(at: int, opener: int) -> int:
            nonlocal pending
            b = st.next_branch.get(at)
            if b is None:
                return st.end_of[opener] + 1
            pending = b
            return b

        def goto(target: str, here: int) -> int:
            nonlocal loops, pending
            idx = resolve_target(st, ctx.text(target), n)
            if idx is None:
                raise MacroError(f"Destino “{target}” não existe (use um rótulo ou o número da etapa).")
            loops = [f for f in loops if f.start < idx <= f.end]
            pending = None
            return idx

        while pc < n:
            ctx.check()
            cmd = cmds[pc]
            row = rows[pc]
            spec = registry.get(cmd.type)
            ctx.step = row
            ctx.command_label = spec.label
            ctx.status = ""
            ctx.last_similarity = None
            ctx.last_coords = None
            structural = spec.block in ("mid", "close")
            if not cmd.enabled and not structural:
                self._status(row, "Desativada", "skip")
                pc = st.end_of[pc] + 1 if pc in st.end_of else pc + 1
                continue
            if row is not None:
                self.listener.on_step(row)
                if self.step_mode:
                    self.run_event.clear()
                    self.listener.on_state("step")
                    ctx.check()  # espera "Próximo passo"
            t_cmd = time.perf_counter()
            nxt = pc + 1
            t = cmd.type
            try:
                if t == "if":
                    if conditions.evaluate(ctx, cmd.params):
                        ctx.status = "Verdadeiro"
                    else:
                        ctx.status = "Falso"
                        nxt = false_branch(pc, pc)
                elif t in ("else_if", "else"):
                    opener = st.owner[pc]
                    if pending == pc:
                        pending = None
                        if t == "else" or conditions.evaluate(ctx, cmd.params):
                            ctx.status = "Verdadeiro" if t == "else_if" else "Entrou"
                        else:
                            ctx.status = "Falso"
                            nxt = false_branch(pc, opener)
                    else:
                        ctx.status = "Pulado"
                        nxt = st.end_of[opener] + 1
                elif t in ("end_if", "label", "comment"):
                    pass
                elif t == "loop":
                    raw = str(cmd.params.get("count") if cmd.params.get("count") is not None else "0").strip()
                    count = 0 if raw in ("", "0") else ctx.integer(raw)
                    if raw not in ("", "0") and count <= 0:
                        ctx.status = "0 voltas"
                        nxt = st.end_of[pc] + 1
                    else:
                        fr = _Frame(pc, st.end_of[pc], count, 0, str(cmd.params.get("counter") or "").strip())
                        loops.append(fr)
                        if fr.counter:
                            ctx.set_var(fr.counter, 1)
                        ctx.status = "Volta 1" + (f"/{count}" if count else "")
                elif t == "end_loop":
                    fr = loops[-1] if loops and loops[-1].end == pc else None
                    if fr is None:
                        raise MacroError("End Loop sem Loop ativo")
                    fr.done += 1
                    if fr.count == 0 or fr.done < fr.count:
                        if fr.counter:
                            ctx.set_var(fr.counter, fr.done + 1)
                        nxt = fr.start + 1
                        ctx.status = f"Volta {fr.done + 1}" + (f"/{fr.count}" if fr.count else "")
                    else:
                        loops.pop()
                        ctx.status = f"{fr.done} voltas"
                elif t == "while":
                    mine = loops[-1] if loops and loops[-1].start == pc else None
                    if conditions.evaluate(ctx, cmd.params):
                        if mine is None:
                            loops.append(_Frame(pc, st.end_of[pc]))
                        else:
                            mine.done += 1
                        ctx.status = "Verdadeiro"
                    else:
                        if mine is not None:
                            loops.pop()
                        ctx.status = "Falso"
                        nxt = st.end_of[pc] + 1
                elif t == "end_while":
                    nxt = st.start_of[pc]
                elif t == "break":
                    if not loops:
                        raise MacroError("Break fora de um loop")
                    fr = loops.pop()
                    nxt = fr.end + 1
                elif t == "continue":
                    if not loops:
                        raise MacroError("Continue fora de um loop")
                    nxt = loops[-1].end
                elif t == "goto":
                    nxt = goto(str(cmd.params.get("target") or ""), pc)
                elif t == "function":
                    nxt = st.end_of[pc] + 1
                elif t == "call_function":
                    name = str(cmd.params.get("name") or "").strip()
                    if name not in st.functions:
                        raise MacroError(f"Função '{name}' não existe")
                    if len(calls) >= MAX_CALL_DEPTH:
                        raise MacroError("Chamadas de função demais (recursão sem fim?)")
                    calls.append((pc + 1, len(loops)))
                    nxt = st.functions[name] + 1
                elif t in ("end_function", "return"):
                    if calls:
                        ret, depth = calls.pop()
                        loops = loops[:depth]
                        nxt = ret
                    elif t == "return":
                        raise MacroError("Retornar fora de uma função")
                elif t == "stop_macro":
                    self._status(row, "Encerrada", "ok")
                    ctx.log("Encerrada pelo comando Encerrar execução", "info")
                    raise _StopMacro()
                elif t == "run_macro":
                    self._run_sub_macro(ctx, cmd)
                else:
                    if spec.run is None:
                        raise MacroError(f"O comando {spec.label} não tem execução")
                    flow = spec.run(ctx, cmd)
                    if flow is not None:
                        if flow.stop:
                            self._status(row, ctx.status or "Parou", "warn")
                            raise _StopMacro()
                        if flow.goto is not None:
                            nxt = goto(flow.goto, pc)
                        elif flow.branch is False and pc in st.end_of:
                            nxt = false_branch(pc, pc)
                        if flow.pause:
                            ctx.log("Macro pausada pela etapa (F7 ou Continuar para seguir)", "warn")
                            self.pause()
            except StopRequested:
                self._status(row, "Interrompida", "warn")
                raise
            except _StopMacro:
                raise
            except MacroError:
                self._status(row, "Erro", "error")
                raise
            except Exception as e:
                self._status(row, "Erro", "error")
                raise MacroError(f"{spec.label}: {e}") from e
            elapsed = (time.perf_counter() - t_cmd) * 1000
            level = "warn" if ctx.status.startswith(("Não", "Falso", "Ainda")) else "ok"
            self._status(row, ctx.status or "OK", level)
            if t not in ("comment", "label"):
                ctx.log(
                    spec.describe(cmd.params) or spec.label,
                    "info",
                    similarity=ctx.last_similarity,
                    coords=ctx.last_coords,
                    elapsed_ms=round(elapsed, 1),
                )
            if cmd.delay_ms:
                ctx.sleep(cmd.delay_ms / 1000)
            pc = nxt

    def _run_sub_macro(self, ctx: RunContext, cmd) -> None:
        if ctx.depth >= MAX_MACRO_DEPTH:
            raise MacroError("Macros chamando macros demais (ciclo?)")
        path = ctx.resolve_path(str(cmd.params.get("path") or ""))
        if not path.is_file():
            raise MacroError(f"Macro não encontrada: {path}")
        loader = self.macro_loader
        if loader is None:
            from ..storage.project import load_macro

            loader = load_macro
        try:
            sub = loader(path)
        except Exception as e:
            raise MacroError(f"Não foi possível abrir {path.name}: {e}") from e
        st = analyze(sub.commands)
        if st.errors:
            i, msg = st.errors[0]
            raise MacroError(f"{path.name}, etapa {i + 1}: {msg}")
        from ..vision.service import VisionService

        sub_ctx = RunContext(
            sub, ctx.inputs, VisionService(sub.images),
            stop_event=ctx.stop_event, run_event=ctx.run_event, speed=ctx.speed,
            log=self._log, notify=ctx.notify, base_dir=path.parent,
        )
        sub_ctx.depth = ctx.depth + 1
        sub_ctx.repetition = ctx.repetition
        ctx.log(f"Executando {path.name}", "info")
        try:
            self._run_list(sub_ctx, sub.commands, [None] * len(sub.commands), st)
        except _StopMacro:
            pass
        finally:
            sub_ctx.release_all()
        ctx.status = f"{path.name} concluída"
