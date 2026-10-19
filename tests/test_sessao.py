"""Testes da máquina de estados da estação (sem MQTT, câmera ou serial)."""

import pytest

from shared import topicos
from station.contador import Repeticao
from station.sessao import Estado, ResultadoCartao, SessaoEstacao

ANA = "AA:BB:CC:DD"
BETO = "11:22:33:44"
ALUNOS = {ANA: {"nome": "Ana", "plano": "Hipertrofia"}, BETO: {"nome": "Beto", "plano": "Força"}}


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def avancar(self, segundos):
        self.t += segundos


class Publicador:
    def __init__(self):
        self.mensagens = []

    def __call__(self, tipo, payload, retain=False):
        self.mensagens.append((tipo, payload, retain))

    def do_tipo(self, tipo):
        return [p for t, p, _ in self.mensagens if t == tipo]

    def tipos(self):
        return [t for t, _, _ in self.mensagens]


@pytest.fixture
def cenario():
    relogio, publicador, sinais = Relogio(), Publicador(), []
    sessao = SessaoEstacao(
        "estacao-01", "Estação 01", "Rosca direta", ALUNOS, publicador, sinais.append, relogio,
        tempo_fim_serie_s=5, tempo_inatividade_s=60, janela_debounce_s=2,
        descanso_min_s=60, descanso_max_s=90, log=lambda *_: None,
    )
    return sessao, publicador, relogio, sinais


def fazer_reps(sessao, relogio, duracoes, completa=True):
    for d in duracoes:
        relogio.avancar(d)
        sessao.registrar_repeticao(Repeticao(completa, d, 40.0 if completa else 95.0))
        sessao.tick()


def test_login_publica_ocupada_retida_logo_apos_o_bipe(cenario):
    sessao, pub, _, sinais = cenario
    assert sessao.cartao_lido(ANA) == ResultadoCartao.LOGIN
    tipo, payload, retain = pub.mensagens[0]
    assert (tipo, payload["status"], payload["aluno"], retain) == (topicos.STATUS, "Ocupada", "Ana", True)
    assert pub.do_tipo(topicos.ACESSO)[0]["resultado"] == "LIBERADO"
    assert sessao.estado == Estado.PRONTO
    assert sinais == ["OCUPADA"]


def test_cartao_nao_cadastrado_e_negado_sem_mudar_status(cenario):
    sessao, pub, _, sinais = cenario
    assert sessao.cartao_lido("00:00:00:01") == ResultadoCartao.NEGADO
    assert pub.do_tipo(topicos.STATUS) == []
    assert pub.do_tipo(topicos.ACESSO)[0]["motivo"] == "Cartão não cadastrado"
    assert sessao.estado == Estado.LIVRE
    assert sinais == ["NEGADO"]


def test_outro_aluno_nao_entra_com_maquina_ocupada(cenario):
    sessao, pub, _, _ = cenario
    sessao.cartao_lido(ANA)
    assert sessao.cartao_lido(BETO) == ResultadoCartao.NEGADO
    assert sessao.aluno["nome"] == "Ana"
    assert "ocupada por Ana" in pub.do_tipo(topicos.ACESSO)[-1]["motivo"]


def test_leitura_repetida_do_mesmo_cartao_e_ignorada(cenario):
    sessao, _, relogio, _ = cenario
    sessao.cartao_lido(ANA)
    relogio.avancar(1)
    assert sessao.cartao_lido(ANA) == ResultadoCartao.IGNORADO
    assert sessao.ocupada


def test_mesmo_cartao_faz_logout_e_publica_livre(cenario):
    sessao, pub, relogio, sinais = cenario
    sessao.cartao_lido(ANA)
    relogio.avancar(3)
    assert sessao.cartao_lido(ANA) == ResultadoCartao.LOGOUT
    tipo, payload, retain = pub.mensagens[-1]
    assert (tipo, payload["status"], payload["aluno"], retain) == (topicos.STATUS, "Livre", None, True)
    assert sinais[-1] == "LIVRE"
    assert sessao.estado == Estado.LIVRE


def test_performance_so_e_publicada_ao_fim_da_serie(cenario):
    sessao, pub, relogio, sinais = cenario
    sessao.cartao_lido(ANA)
    fazer_reps(sessao, relogio, [2.0] * 10)
    assert pub.do_tipo(topicos.PERFORMANCE) == []
    assert sessao.estado == Estado.EM_SERIE

    relogio.avancar(5)
    sessao.tick()
    [perf] = pub.do_tipo(topicos.PERFORMANCE)
    assert perf["aluno"] == "Ana"
    assert perf["repeticoes"] == 10
    assert perf["serie"] == 1
    assert perf["fadiga"] is False
    assert perf["descanso_sugerido_s"] == 60
    assert sessao.estado == Estado.DESCANSO
    assert sinais[-1] == "SERIE"


def test_fadiga_aumenta_descanso_sugerido(cenario):
    sessao, pub, relogio, _ = cenario
    sessao.cartao_lido(ANA)
    fazer_reps(sessao, relogio, [2.0, 2.0, 2.1, 2.4, 2.8, 3.2, 3.5, 3.8, 4.0])
    sessao.finalizar_serie()
    [perf] = pub.do_tipo(topicos.PERFORMANCE)
    assert perf["fadiga"] is True
    assert perf["descanso_sugerido_s"] == 75
    assert any("fadiga" in a for a in perf["alertas"])


def test_repeticoes_incompletas_sao_contadas_a_parte(cenario):
    sessao, pub, relogio, _ = cenario
    sessao.cartao_lido(ANA)
    fazer_reps(sessao, relogio, [2.0] * 6)
    fazer_reps(sessao, relogio, [2.0] * 3, completa=False)
    sessao.finalizar_serie()
    [perf] = pub.do_tipo(topicos.PERFORMANCE)
    assert (perf["repeticoes"], perf["repeticoes_incompletas"]) == (6, 3)
    assert perf["descanso_sugerido_s"] == 75  # 33% de amplitude parcial


def test_series_seguintes_incrementam_o_numero(cenario):
    sessao, pub, relogio, _ = cenario
    sessao.cartao_lido(ANA)
    for _ in range(3):
        fazer_reps(sessao, relogio, [2.0] * 8)
        relogio.avancar(6)
        sessao.tick()
        relogio.avancar(30)
    assert [p["serie"] for p in pub.do_tipo(topicos.PERFORMANCE)] == [1, 2, 3]


def test_logout_no_meio_da_serie_publica_performance_antes_do_livre(cenario):
    sessao, pub, relogio, _ = cenario
    sessao.cartao_lido(ANA)
    fazer_reps(sessao, relogio, [2.0] * 5)
    relogio.avancar(1)
    sessao.cartao_lido(ANA)
    assert pub.tipos()[-3:] == [topicos.PERFORMANCE, topicos.ACESSO, topicos.STATUS]
    assert pub.do_tipo(topicos.PERFORMANCE)[0]["motivo_fim"] == "logout"
    assert pub.mensagens[-1][1]["status"] == "Livre"


def test_inatividade_libera_a_maquina(cenario):
    sessao, pub, relogio, _ = cenario
    sessao.cartao_lido(ANA)
    relogio.avancar(61)
    sessao.tick()
    assert sessao.estado == Estado.LIVRE
    assert pub.do_tipo(topicos.STATUS)[-1]["status"] == "Livre"
    assert "inatividade" in pub.do_tipo(topicos.ACESSO)[-1]["motivo"]


def test_repeticao_sem_aluno_logado_e_ignorada(cenario):
    sessao, pub, relogio, _ = cenario
    fazer_reps(sessao, relogio, [2.0] * 3)
    relogio.avancar(10)
    sessao.tick()
    assert pub.mensagens == []
