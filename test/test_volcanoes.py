from pyrocko.dataset.volcanoes import Volcanoes


def test_volcanoes():
    volcanoes = Volcanoes()
    assert volcanoes.nvolcanoes != 0
    assert volcanoes.nvolcanoes_pleistocene != 0
    assert volcanoes.nvolcanoes_holocene != 0
    print(volcanoes.volcanoes[0])
