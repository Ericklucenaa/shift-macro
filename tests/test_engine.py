"""Motor: fluxo, condições, repetições, variáveis, funções e parada de emergência."""
from __future__ import annotations

import threading
import time

import pytest

from shiftmacro.actions.registry import make
from shiftmacro.core.engine import Engine, Listener
from shiftmacro.core.model import Macro, RunSettings
from shiftmacro.core.structure import analyze

from .fakes import FakeInputs, FakeScreen


class Rec(Listener):
    def __init__(self):
        self.steps, self.status, self.logs, self.reps, self.states = [], {}, [], [], []

    def on_step(self, row):
        self.steps.append(row)

    def on_status(self, row, text, level):
        self.status[row] = (text, level)

    def on_log(self, e):
        self.logs.append(e)

    def on_repetition(self, cur, total):
        self.reps.append((cur, total))

    def on_state(self, s):
        self.states.append(s)


def run(cmds, settings=None, **kw):
    m = Macro(commands=cmds, settings=settings or RunSettings())
    inp = FakeInputs()
    lst = Rec()
    eng = Engine(m, inp, FakeScreen().vision({}), lst)
    res = eng.run(**kw)
    return res, inp, lst, eng


def setv(name, value, op="="):
    return make("set_var", name=name, value=value, op=op)


def type_(text):
    return make("type_text", text=text, interval_ms=0)


def test_sequencia_simples_mouse_e_teclado():
    res, inp, lst, _ = run([
        make("left_click", x=10, y=20),
        make("double_click", x=30, y=40),
        make("right_click", at="current"),
        make("hotkey", keys="ctrl+shift+s"),
        type_("Olá, ção!"),
        make("scroll", vertical=-3, horizontal=2, at="current"),
    ])
    assert res.completed, res.error
    assert ("click", "left", 1, 10, 20) in inp.calls
    assert ("click", "left", 2, 30, 40) in inp.calls
    assert ("click", "right", 1, 30, 40) in inp.calls  # posição atual
    assert inp.of("kdown")[:3] == [("kdown", "ctrl"), ("kdown", "shift"), ("kdown", "s")]
    assert inp.of("kup")[:3] == [("kup", "s"), ("kup", "shift"), ("kup", "ctrl")]
    assert inp.typed() == "Olá, ção!"
    assert ("scroll", -3, 2) in inp.calls
    assert lst.steps == [0, 1, 2, 3, 4, 5]


def test_if_else_if_else():
    def prog(v):
        return [
            setv("x", v),
            make("if", cond="expr", expr="x > 10"),
            type_("A"),
            make("else_if", cond="expr", expr="x > 5"),
            type_("B"),
            make("else"),
            type_("C"),
            make("end_if"),
            type_("!"),
        ]

    assert run(prog(20))[1].typed() == "A!"
    assert run(prog(7))[1].typed() == "B!"
    assert run(prog(1))[1].typed() == "C!"


def test_ifs_aninhados():
    cmds = [
        setv("a", 1), setv("b", 0),
        make("if", cond="expr", expr="a == 1"),
        make("if", cond="expr", expr="b == 1"), type_("x"), make("else"), type_("y"), make("end_if"),
        type_("z"),
        make("else"), type_("w"),
        make("end_if"),
    ]
    assert run(cmds)[1].typed() == "yz"


def test_loop_com_contador_break_continue():
    cmds = [
        make("loop", count="10", counter="i"),
        make("if", cond="expr", expr="i == 2"), make("continue"), make("end_if"),
        make("if", cond="expr", expr="i == 5"), make("break"), make("end_if"),
        type_("{i}"),
        make("end_loop"),
        type_("."),
    ]
    res, inp, *_ = run(cmds)
    assert res.completed, res.error
    assert inp.typed() == "134."


def test_loops_aninhados():
    cmds = [
        make("loop", count="2", counter="a"),
        make("loop", count="3", counter="b"),
        type_("{a}{b} "),
        make("end_loop"),
        make("end_loop"),
    ]
    assert run(cmds)[1].typed() == "11 12 13 21 22 23 "


def test_while_e_variaveis():
    cmds = [
        setv("n", 0),
        make("while", cond="expr", expr="n < 4"),
        setv("n", 1, "+="),
        type_("{n}"),
        make("end_while"),
    ]
    res, inp, *_ = run(cmds)
    assert inp.typed() == "1234"
    assert res.completed


def test_goto_e_rotulo_e_numero_de_etapa():
    cmds = [
        setv("n", 0),
        make("label", label="topo"),
        setv("n", 1, "+="),
        make("if", cond="expr", expr="n < 3"), make("goto", target="topo"), make("end_if"),
        make("goto", target="9"),
        type_("pulado"),
        type_("fim{n}"),
    ]
    assert run(cmds)[1].typed() == "fim3"


def test_funcoes_e_retorno():
    cmds = [
        make("call_function", name="saudar"),
        make("call_function", name="saudar"),
        type_("."),
        make("stop_macro"),
        make("function", name="saudar"),
        type_("oi"),
        make("if", cond="expr", expr="True"), make("return"), make("end_if"),
        type_("nunca"),
        make("end_function"),
    ]
    res, inp, *_ = run(cmds)
    assert res.completed, res.error
    assert inp.typed() == "oioi."


def test_funcao_nao_roda_sozinha():
    cmds = [make("function", name="f"), type_("x"), make("end_function"), type_("y")]
    assert run(cmds)[1].typed() == "y"


def test_comando_desativado_e_bloco_desativado():
    a = type_("a")
    a.enabled = False
    loop = make("loop", count="3")
    loop.enabled = False
    cmds = [a, loop, type_("L"), make("end_loop"), type_("b")]
    res, inp, lst, _ = run(cmds)
    assert inp.typed() == "b"
    assert lst.status[0][0] == "Desativada"


def test_repeticoes_contagem_e_variavel_repeticao():
    res, inp, lst, _ = run([type_("{repeticao}")], RunSettings(repeat_mode="count", repeat_count=3))
    assert inp.typed() == "123"
    assert res.repetitions == 3
    assert lst.reps == [(1, 3), (2, 3), (3, 3)]


def test_repetir_por_tempo():
    t = time.perf_counter()
    res, *_ = run([make("delay", ms=50)], RunSettings(repeat_mode="duration", repeat_minutes=0.004))
    assert res.completed
    assert 0.2 < time.perf_counter() - t < 1.5
    assert res.repetitions >= 3


def test_velocidade_acelera_delays():
    t = time.perf_counter()
    run([make("delay", ms=400)], RunSettings(speed=4.0))
    assert time.perf_counter() - t < 0.3


def test_delay_por_etapa():
    c = type_("a")
    c.delay_ms = 200
    t = time.perf_counter()
    run([c, type_("b")])
    assert time.perf_counter() - t >= 0.19


def test_executar_a_partir_da_etapa_e_so_selecionados():
    cmds = [type_("a"), type_("b"), type_("c"), type_("d")]
    assert run(cmds, start_at=2)[1].typed() == "cd"
    assert run(cmds, only=[0, 3])[1].typed() == "ad"


def test_selecao_que_corta_bloco_e_recusada():
    cmds = [make("loop", count="2"), type_("a"), make("end_loop")]
    res, inp, *_ = run(cmds, only=[0, 1])
    assert not res.completed and "corta um bloco" in res.error
    assert inp.calls == []


def test_estrutura_invalida_mostra_etapa():
    st = analyze([make("if", cond="expr", expr="1"), type_("x")])
    assert not st.ok and "não foi fechado" in st.errors[0][1]
    st = analyze([make("end_loop")])
    assert "sem abertura" in st.errors[0][1]
    st = analyze([make("break")])
    assert "fora de um loop" in st.errors[0][1]
    st = analyze([make("loop"), make("if", cond="expr", expr="1"), make("end_loop"), make("end_if")])
    assert not st.ok
    res, *_ = run([make("goto", target="nada")])
    assert "não existe" in res.error


def test_erro_de_expressao_aponta_etapa():
    res, *_ = run([type_("a"), setv("x", "y + 1")])
    assert not res.completed
    assert res.error_row == 1
    assert "y" in res.error


def test_stop_macro_encerra_repeticoes():
    res, inp, *_ = run([type_("a"), make("stop_macro"), type_("b")], RunSettings(repeat_mode="infinite"))
    assert inp.typed() == "a"
    assert res.completed


# ------------------------------------------------------------ parada de emergência
def _start(cmds, settings=None, vision=None, **run_kw):
    m = Macro(commands=cmds, settings=settings or RunSettings())
    inp = FakeInputs()
    eng = Engine(m, inp, vision or FakeScreen().vision({}), Rec())
    done = threading.Event()
    out = {}

    class L(Rec):
        def on_finished(self, r):
            out["r"] = r
            done.set()

    eng.listener = L()
    eng.start(**run_kw)
    return eng, inp, done, out


@pytest.mark.parametrize("cmds", [
    [make("delay", ms=60_000)],
    [make("loop", count="0"), setv("x", 1, "+="), make("end_loop")],
    [make("while", cond="expr", expr="True"), make("end_while")],
    [make("hold_key", key="w", duration_ms=60_000)],
])
def test_parada_imediata(cmds):
    eng, inp, done, out = _start(cmds, RunSettings(repeat_mode="infinite"))
    time.sleep(0.15)
    t = time.perf_counter()
    eng.stop()
    assert done.wait(1.0), "o motor não parou"
    assert time.perf_counter() - t < 0.3
    assert out["r"].stopped
    # tecla segurada foi solta
    assert len(inp.of("kdown")) == len(inp.of("kup"))


def test_parada_durante_busca_infinita_de_imagem():
    from shiftmacro.vision import matcher

    from .fakes import pattern

    scr = FakeScreen()
    img = {"botao": matcher.encode_png(pattern())}
    eng, inp, done, out = _start([make("smart_click", image="botao", infinite=True, interval_ms=20)], vision=scr.vision(img))
    time.sleep(0.3)
    assert scr.grabs >= 3
    t = time.perf_counter()
    eng.stop()
    assert done.wait(1.0)
    assert time.perf_counter() - t < 0.3
    assert out["r"].stopped


def test_pausar_e_continuar():
    eng, inp, done, out = _start([make("loop", count="0"), type_("x"), make("delay", ms=5), make("end_loop")])
    time.sleep(0.1)
    eng.pause()
    time.sleep(0.05)
    n = len(inp.calls)
    time.sleep(0.2)
    assert len(inp.calls) == n, "continuou executando em pausa"
    eng.resume()
    time.sleep(0.1)
    assert len(inp.calls) > n
    eng.stop()
    assert done.wait(1)


def test_passo_a_passo():
    eng, inp, done, out = _start([type_("a"), type_("b"), type_("c")], step_mode=True)
    time.sleep(0.1)
    assert inp.typed() == ""  # espera o primeiro "Próximo passo"
    for expected in ("a", "ab"):
        eng.next_step()
        time.sleep(0.1)
        assert inp.typed() == expected
    eng.resume()
    assert done.wait(1)
    assert inp.typed() == "abc"


def test_mouse_down_preso_e_solto_ao_parar():
    eng, inp, done, out = _start([make("mouse_down", button="left"), make("delay", ms=60_000)])
    time.sleep(0.1)
    eng.stop()
    assert done.wait(1)
    assert inp.of("down") == [("down", "left")]
    assert inp.of("up") == [("up", "left")]
