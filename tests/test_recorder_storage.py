"""Gravação (conversão de eventos), arquivos .shiftmacro, configurações e expressões."""
from __future__ import annotations

import zipfile

import pytest

from shiftmacro.actions.registry import make
from shiftmacro.core import expr
from shiftmacro.core.engine import Engine
from shiftmacro.core.model import Macro, RunSettings
from shiftmacro.recorder.convert import RawEvent as E
from shiftmacro.recorder.convert import convert
from shiftmacro.recorder.recorder import _drop_dangling
from shiftmacro.storage import appdata
from shiftmacro.storage.project import ProjectError, load_macro, save_macro
from shiftmacro.utils.winapi import parse_hotkey

from .fakes import FakeInputs, FakeScreen


def types(cmds):
    return [c.type for c in cmds]


def test_clique_simples_duplo_e_direito():
    ev = [
        E(0.00, "down", 100, 100, button="left"), E(0.08, "up", 101, 100, button="left"),
        E(1.00, "down", 200, 200, button="left"), E(1.05, "up", 200, 200, button="left"),
        E(1.20, "down", 201, 200, button="left"), E(1.25, "up", 201, 200, button="left"),
        E(2.00, "down", 50, 60, button="right"), E(2.05, "up", 50, 60, button="right"),
    ]
    cmds = convert(ev, mode="clicks")
    assert types(cmds) == ["left_click", "double_click", "right_click"]
    assert (cmds[0].params["x"], cmds[0].params["y"]) == (100, 100)
    assert cmds[0].delay_ms == 920  # 1.00 - 0.08


def test_arrastar_sem_movimentos_e_com_movimentos():
    ev = [E(0, "down", 10, 10, button="left"), E(0.2, "move", 50, 50), E(0.4, "up", 100, 120, button="left")]
    d = convert(ev, mode="clicks")
    assert types(d) == ["drag"]
    assert (d[0].params["x2"], d[0].params["y2"]) == (100, 120)
    m = convert(ev, mode="all", record_moves=True)
    assert types(m) == ["mouse_down", "mouse_move", "mouse_up"]


def test_texto_combinacoes_e_teclas_especiais():
    ev = [
        E(0.0, "kdown", key="shift"), E(0.01, "kdown", key="o", char="O"), E(0.05, "kup", key="o"), E(0.06, "kup", key="shift"),
        E(0.1, "kdown", key="i", char="i"), E(0.12, "kup", key="i"),
        E(0.3, "kdown", key="ctrl"), E(0.32, "kdown", key="s", char="\x13"), E(0.34, "kup", key="s"), E(0.36, "kup", key="ctrl"),
        E(0.5, "kdown", key="enter"), E(0.52, "kup", key="enter"),
        E(0.6, "kdown", key="enter"), E(0.62, "kup", key="enter"),
    ]
    cmds = convert(ev, mode="keyboard")
    assert types(cmds) == ["type_text", "hotkey", "key_press"]
    assert cmds[0].params["text"] == "Oi"
    assert cmds[1].params["keys"] == "ctrl+s"
    assert cmds[2].params["times"] == 2


def test_tecla_segurada_vira_manter_e_soltar():
    ev = [E(0, "kdown", key="w", char="w")] + [E(0.1 * i, "kdown", key="w", char="w") for i in range(1, 10)] + [
        E(0.5, "kdown", key="space", char=" "), E(0.55, "kup", key="space"), E(1.0, "kup", key="w")]
    cmds = convert(ev, mode="keyboard")
    assert types(cmds) == ["key_down", "type_text", "key_up"]
    assert cmds[1].params["text"] == " "


def test_rolagem_somada_e_modo_so_teclado_ignora_mouse():
    ev = [E(0, "scroll", 10, 10, dy=-1), E(0.1, "scroll", 10, 10, dy=-1), E(0.2, "scroll", 10, 10, dy=-1),
          E(0.3, "kdown", key="a", char="a"), E(0.31, "kup", key="a")]
    cmds = convert(ev, mode="clicks")
    assert types(cmds) == ["scroll"] and cmds[0].params["vertical"] == -3
    assert types(convert(ev, mode="keyboard")) == ["type_text"]


def test_movimentos_amostrados():
    ev = [E(i * 0.005, "move", i, i) for i in range(200)]
    cmds = convert(ev, mode="all", min_move_ms=50)
    assert 15 <= len(cmds) <= 25


def test_soltar_orfao_e_descartado():
    ev = [E(0, "up", 1, 1, button="left"), E(0.1, "kup", key="f9"), E(0.2, "down", 5, 5, button="left"), E(0.3, "up", 5, 5, button="left")]
    assert [e.kind for e in _drop_dangling(ev)] == ["down", "up"]


def test_gravacao_convertida_executa():
    ev = [E(0, "down", 10, 20, button="left"), E(0.05, "up", 10, 20, button="left"),
          E(0.1, "kdown", key="a", char="a"), E(0.12, "kup", key="a")]
    cmds = convert(ev, mode="all", keep_delays=False)
    inp = FakeInputs()
    res = Engine(Macro(commands=cmds), inp, FakeScreen().vision({})).run()
    assert res.completed
    assert inp.of("click") == [("click", "left", 1, 10, 20)] and inp.typed() == "a"


# ------------------------------------------------------------ armazenamento
def test_salvar_e_abrir_shiftmacro(tmp_path):
    m = Macro(name="Teste", description="desc", variables={"n": 1}, settings=RunSettings(repeat_mode="count", repeat_count=4, speed=2),
              hotkeys={"run": "F2"}, images={"botao": b"\x89PNG fake"})
    c = make("smart_click", image="botao")
    c.name, c.comment, c.delay_ms, c.enabled = "Clicar", "nota", 120, False
    m.commands = [c, make("type_text", text="ção")]
    p = save_macro(m, tmp_path / "x")
    assert p.suffix == ".shiftmacro"
    with zipfile.ZipFile(p) as z:
        assert set(z.namelist()) == {"macro.json", "images/botao.png"}
    m2 = load_macro(p)
    assert m2.name == "Teste" and m2.variables == {"n": 1}
    assert m2.settings.repeat_count == 4 and m2.settings.speed == 2
    assert m2.hotkeys == {"run": "F2"}
    assert m2.images == {"botao": b"\x89PNG fake"}
    c2 = m2.commands[0]
    assert (c2.name, c2.comment, c2.delay_ms, c2.enabled) == ("Clicar", "nota", 120, False)
    assert m2.commands[1].params["text"] == "ção"


def test_arquivo_invalido_e_caminho_malicioso(tmp_path):
    bad = tmp_path / "ruim.shiftmacro"
    bad.write_text("não é zip")
    with pytest.raises(ProjectError):
        load_macro(bad)
    evil = tmp_path / "evil.shiftmacro"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("macro.json", '{"name": "x", "commands": []}')
        z.writestr("images/../../fora.png", b"x")
    assert load_macro(evil).images == {}


def test_configuracoes_recentes_e_autosave(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTMACRO_HOME", str(tmp_path))
    s = appdata.AppSettings.load()
    assert s.hotkeys["stop"] == "F8"
    f = tmp_path / "a.shiftmacro"
    f.write_bytes(b"x")
    s.add_recent(f)
    s.add_recent(f)
    s.theme = "light"
    s.hotkeys["run"] = "Ctrl+F6"
    s.save()
    s2 = appdata.AppSettings.load()
    assert s2.theme == "light" and len(s2.recent) == 1 and s2.hotkeys["run"] == "Ctrl+F6"
    a = appdata.Autosave()
    assert a.pending() is None
    a.write(Macro(name="Recuperar", commands=[make("delay")]), str(f))
    assert a.pending()["original"] == str(f)
    assert a.recover().name == "Recuperar"
    a.mark_clean()
    assert a.pending() is None


# ------------------------------------------------------------ expressões e atalhos
def test_expressoes():
    v = {"n": 3, "nome": "Ana"}
    assert expr.evaluate("n * 2 + 1", v) == 7
    assert expr.evaluate("n > 2 e nome = \"Ana\"", v) is True
    assert expr.evaluate("nao (n < 2)", v) is True
    assert expr.evaluate("\"x\" + n", v) == "x3"
    assert expr.value_of("Olá {nome}!", v) == "Olá Ana!"
    assert 1 <= expr.evaluate("random(1, 6)", v) <= 6
    for bad in ("__import__('os')", "n.__class__", "open('x')", "2 ** 1000", "1/0"):
        with pytest.raises(expr.ExprError):
            expr.evaluate(bad, v)


def test_atalhos():
    assert parse_hotkey("F6") == (0, 0x75)
    assert parse_hotkey("Shift+F11") == (0x4, 0x7A)
    assert parse_hotkey("ctrl+alt+K") == (0x3, ord("K"))
    for bad in ("", "Ctrl", "F6+F7", "Ctrl+Ç"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)
