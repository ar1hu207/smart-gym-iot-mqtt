"""Testes do estado do dashboard (sem broker e sem navegador)."""

import pytest

from dashboard.armazenamento import Armazenamento
from dashboard.painel import Painel


@pytest.fixture
def painel(tmp_path):
    return Painel(Armazenamento(tmp_path / "teste.db"), broker="localhost:1883", topico_raiz="t", log=lambda *_: None)


def performance(id_="p1", reps=12, ts="2026-10-19T20:00:00-03:00"):
    return {"id": id_, "estacao_id": "e1", "estacao_nome": "Estação 01", "aluno": "Ana", "serie": 1,
            "repeticoes": reps, "repeticoes_incompletas": 0, "cadencia_media_s": 2.1, "fadiga": False,
            "alertas": [], "descanso_sugerido_s": 60, "ts": ts}


def test_status_ocupada_e_livre(painel):
    painel.aplicar("e1", "status", {"estacao_nome": "Estação 01", "status": "Ocupada", "aluno": "Ana"})
    snap = painel.snapshot()
    assert snap["estacoes"][0]["status"] == "Ocupada"
    assert snap["resumo"]["ocupadas"] == 1

    painel.aplicar("e1", "status", {"status": "Livre", "aluno": None})
    snap = painel.snapshot()
    assert snap["resumo"]["livres"] == 1
    assert snap["estacoes"][0]["aluno"] is None


def test_performance_vai_para_o_historico_sem_duplicar(painel):
    painel.aplicar("e1", "performance", performance())
    painel.aplicar("e1", "performance", performance())  # reentrega do QoS 1
    painel.aplicar("e1", "performance", performance("p2", 10, ts="2026-10-19T20:02:00-03:00"))
    historico = painel.snapshot()["historico"]
    assert [h["repeticoes"] for h in historico] == [10, 12]  # mais recente primeiro


def test_estacao_offline_pelo_last_will(painel):
    painel.aplicar("e1", "status", {"status": "Ocupada"})
    painel.aplicar("e1", "conexao", {"online": False})
    resumo = painel.snapshot()["resumo"]
    assert (resumo["offline"], resumo["ocupadas"]) == (1, 0)


def test_inscritos_recebem_cada_atualizacao(painel):
    fila = painel.inscrever()
    painel.aplicar("e1", "acesso", {"resultado": "NEGADO", "uid": "99:88:77:66", "motivo": "Cartão não cadastrado"})
    mensagem = fila.get_nowait()
    assert mensagem["tipo"] == "acesso"
    assert mensagem["estado"]["acessos"][0]["resultado"] == "NEGADO"


def test_remover_estacao(painel):
    painel.aplicar("e1", "status", {"status": "Livre"})
    painel.remover("e1")
    assert painel.snapshot()["estacoes"] == []
