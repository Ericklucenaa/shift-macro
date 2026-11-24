"""Reconhecimento de imagem, cor e regiões de busca (tela em memória)."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from shiftmacro.actions.registry import make
from shiftmacro.core.engine import Engine
from shiftmacro.core.model import Macro
from shiftmacro.vision import matcher
from shiftmacro.vision.capture import Rect
from shiftmacro.vision.service import VisionError

from .fakes import FakeInputs, FakeScreen, pattern


def test_match_exato_e_coordenadas():
    scr = FakeScreen()
    tile = pattern()
    scr.paste(tile, 300, 200)
    m = matcher.find(scr.img, tile)
    assert m.score > 0.99
    assert (m.x, m.y) == (300, 200)
    assert m.center == (320, 215)


def test_limiar_de_similaridade():
    scr = FakeScreen()
    tile = pattern()
    noisy = np.clip(tile.astype(int) + np.random.default_rng(3).integers(-60, 60, tile.shape), 0, 255).astype(np.uint8)
    scr.paste(noisy, 100, 100)
    m = matcher.find(scr.img, tile)
    assert 0.5 < m.score < 0.98
    v = scr.vision({"t": matcher.encode_png(tile)})
    assert v.find_image("t", {"threshold": 50}).found
    assert not v.find_image("t", {"threshold": 99}).found


def test_multiplas_escalas_dpi_125():
    scr = FakeScreen()
    tile = pattern(48, 36)
    big = cv2.resize(tile, (60, 45), interpolation=cv2.INTER_LINEAR)  # 125%
    scr.paste(big, 500, 300)
    single = matcher.find(scr.img, tile, scales=[1.0])
    multi = matcher.find(scr.img, tile, scales=matcher.scales_for(True))
    assert multi.score > single.score
    assert multi.score > 0.85
    assert abs(multi.scale - 1.25) < 0.07
    assert abs(multi.center[0] - 530) <= 3 and abs(multi.center[1] - 322) <= 3


def test_escolhe_maior_confianca():
    scr = FakeScreen()
    tile = pattern()
    worse = tile.copy()
    worse[10:20, 10:30] = 128
    scr.paste(worse, 50, 50)
    scr.paste(tile, 600, 400)
    m = matcher.find(scr.img, tile)
    assert (m.x, m.y) == (600, 400)


def test_regioes_monitor_area_e_janela():
    scr = FakeScreen()
    tile = pattern()
    scr.paste(tile, 900, 100)  # monitor 2 (começa em x=800)
    v = scr.vision({"t": matcher.encode_png(tile)}, windows={"Bloco de Notas": Rect(850, 50, 300, 200)})
    assert v.find_image("t", {"region_mode": "monitor", "monitor": 2}).found
    assert not v.find_image("t", {"region_mode": "monitor", "monitor": 1}).found
    f = v.find_image("t", {"region_mode": "region", "region": [880, 90, 100, 60]})
    assert f.found and (f.x, f.y) == (920, 115)  # coordenadas absolutas
    assert v.find_image("t", {"region_mode": "window", "window": "notas"}).found
    with pytest.raises(VisionError):
        v.find_image("t", {"region_mode": "window", "window": "inexistente"})
    with pytest.raises(VisionError):
        v.find_image("t", {"region_mode": "monitor", "monitor": 5})


def test_cor_e_pixel():
    scr = FakeScreen()
    scr.img[120, 450] = (0, 0, 250)  # BGR: vermelho
    v = scr.vision({})
    assert v.pixel(450, 120) == (250, 0, 0)
    f = v.find_color((255, 0, 0), 10, {})
    assert f.found and (f.x, f.y) == (450, 120)
    assert not v.find_color((255, 0, 0), 2, {}).found
    assert matcher.parse_color("#FF8000") == (255, 128, 0)
    assert matcher.parse_color("10, 20, 30") == (10, 20, 30)


def _engine(scr, cmds, images):
    inp = FakeInputs()
    eng = Engine(Macro(commands=cmds, images=images), inp, scr.vision(images))
    return eng, inp


def test_smart_click_clica_com_deslocamento():
    scr = FakeScreen()
    tile = pattern()
    scr.paste(tile, 300, 200)
    imgs = {"b": matcher.encode_png(tile)}
    eng, inp = _engine(scr, [make("smart_click", image="b", on_found="offset", offset_x=5, offset_y=-3, button="right")], imgs)
    res = eng.run()
    assert res.completed, res.error
    assert inp.of("click") == [("click", "right", 1, 325, 212)]


def test_smart_click_nao_encontrada_acoes():
    scr = FakeScreen()
    imgs = {"b": matcher.encode_png(pattern())}
    # parar
    eng, inp = _engine(scr, [make("smart_click", image="b", timeout_ms=50, on_not_found="stop"), make("type_text", text="x")], imgs)
    res = eng.run()
    assert res.completed and inp.typed() == ""
    # ir para etapa
    cmds = [make("smart_click", image="b", timeout_ms=30, on_not_found="goto", goto_not_found="fim"),
            make("type_text", text="nao"), make("label", label="fim"), make("type_text", text="sim")]
    eng, inp = _engine(scr, cmds, imgs)
    eng.run()
    assert inp.typed() == "sim"


def test_smart_click_bloco_e_else():
    def prog():
        return [
            make("smart_click", image="b", timeout_ms=30, on_found="block", on_not_found="else"),
            make("type_text", text="achou"),
            make("else"),
            make("type_text", text="nao achou"),
            make("end_if"),
        ]

    tile = pattern()
    imgs = {"b": matcher.encode_png(tile)}
    scr = FakeScreen()
    eng, inp = _engine(scr, prog(), imgs)
    eng.run()
    assert inp.typed() == "nao achou"
    scr.paste(tile, 10, 10)
    eng, inp = _engine(scr, prog(), imgs)
    eng.run()
    assert inp.typed() == "achou"


def test_guardar_coordenadas_em_variavel_e_usar():
    scr = FakeScreen()
    tile = pattern()
    scr.paste(tile, 100, 50)
    imgs = {"b": matcher.encode_png(tile)}
    cmds = [make("find_image", image="b", on_found="store", var="alvo"),
            make("left_click", x="alvo_x + 100", y="alvo_y")]
    eng, inp = _engine(scr, cmds, imgs)
    res = eng.run()
    assert res.completed, res.error
    assert inp.of("click") == [("click", "left", 1, 220, 65)]


def test_tentar_novamente_encontra_quando_aparece():
    import threading

    scr = FakeScreen()
    tile = pattern()
    imgs = {"b": matcher.encode_png(tile)}
    threading.Timer(0.25, lambda: scr.paste(tile, 200, 200)).start()
    eng, inp = _engine(scr, [make("click_image", image="b", timeout_ms=100, interval_ms=20, on_not_found="retry", retries=5)], imgs)
    res = eng.run()
    assert res.completed, res.error
    assert inp.of("click")[0][3:] == (220, 215)


def test_aguardar_imagem_desaparecer():
    import threading

    scr = FakeScreen()
    tile = pattern()
    scr.paste(tile, 200, 200)
    imgs = {"b": matcher.encode_png(tile)}
    threading.Timer(0.2, lambda: scr.clear(200, 200, 40, 30)).start()
    eng, inp = _engine(scr, [make("wait_image_vanish", image="b", timeout_ms=3000, interval_ms=20), make("type_text", text="ok")], imgs)
    res = eng.run()
    assert res.completed and inp.typed() == "ok"


def test_if_imagem_e_pixel():
    scr = FakeScreen()
    tile = pattern()
    scr.paste(tile, 30, 30)
    scr.img[5, 5] = (255, 255, 255)
    imgs = {"b": matcher.encode_png(tile)}
    cmds = [
        make("if", cond="image_found", image="b"), make("type_text", text="I"), make("end_if"),
        make("if", cond="pixel", x=5, y=5, color="#FAFAFA", tolerance=10), make("type_text", text="P"), make("end_if"),
        make("if", cond="image_not_found", image="b"), make("type_text", text="X"), make("end_if"),
    ]
    eng, inp = _engine(scr, cmds, imgs)
    res = eng.run()
    assert res.completed, res.error
    assert inp.typed() == "IP"


def test_imagem_inexistente_e_erro_claro():
    scr = FakeScreen()
    eng, inp = _engine(scr, [make("smart_click", image="sumiu")], {})
    res = eng.run()
    assert not res.completed and "não está na macro" in res.error
