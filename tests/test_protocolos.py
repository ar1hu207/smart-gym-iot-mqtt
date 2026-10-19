"""Testes do contrato de tópicos MQTT e do protocolo serial do RFID."""

from shared import topicos
from station.rfid import interpretar_linha, normalizar_uid


def test_topico_segue_a_hierarquia():
    assert topicos.topico("estacao-01", "status", raiz="fiap/smartgym") == "fiap/smartgym/estacao-01/status"


def test_interpretar_topico():
    raiz = "fiap/smartgym"
    assert topicos.interpretar_topico("fiap/smartgym/estacao-01/performance", raiz) == ("estacao-01", "performance")
    assert topicos.interpretar_topico("fiap/smartgym/estacao-01/outro", raiz) is None
    assert topicos.interpretar_topico("outra/raiz/estacao-01/status", raiz) is None
    assert topicos.interpretar_topico("fiap/smartgym/a/b/status", raiz) is None


def test_assinaturas_usam_curinga_por_estacao():
    assert ("fiap/smartgym/+/status", 1) in topicos.assinaturas("fiap/smartgym")
    assert len(topicos.assinaturas("fiap/smartgym")) == len(topicos.TIPOS)


def test_normalizar_uid_aceita_varios_formatos():
    for entrada in ("a1:b2:c3:d4", "A1 B2 C3 D4", "A1B2C3D4", " a1-b2-c3-d4 "):
        assert normalizar_uid(entrada) == "A1:B2:C3:D4"
    assert normalizar_uid("04:A2:2B:1A:5C:80:00") == "04:A2:2B:1A:5C:80:00"  # UID de 7 bytes
    assert normalizar_uid("A1:B2") is None


def test_interpretar_linha_serial():
    assert interpretar_linha("UID:a1:b2:c3:d4\r\n") == "A1:B2:C3:D4"
    assert interpretar_linha("ACESSO_LIBERADO: A1 B2 C3 D4") == "A1:B2:C3:D4"  # firmware do CP01
    assert interpretar_linha("SMARTGYM_RFID_PRONTO") is None
    assert interpretar_linha("") is None
