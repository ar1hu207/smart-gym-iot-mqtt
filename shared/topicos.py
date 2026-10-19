"""
Contrato de tópicos MQTT da Smart Gym.

Hierarquia:  <TOPICO_RAIZ>/<estacao_id>/<tipo>

| tipo          | quem publica | QoS | retain | quando                                   |
|---------------|--------------|-----|--------|------------------------------------------|
| status        | estação      | 1   | sim    | login/logout via RFID ("Livre"/"Ocupada") |
| performance   | estação      | 1   | não    | ao final de cada série concluída          |
| acesso        | estação      | 1   | não    | toda leitura de cartão (liberado/negado)  |
| conexao       | estação/LWT  | 1   | sim    | ao conectar (online) e na queda (LWT)     |

O dashboard assina `<TOPICO_RAIZ>/+/<tipo>` para cada tipo, ou seja,
monitora qualquer quantidade de estações sem configuração extra.
"""

from typing import Optional, Tuple

from shared.config import TOPICO_RAIZ

STATUS = "status"
PERFORMANCE = "performance"
ACESSO = "acesso"
CONEXAO = "conexao"

TIPOS = (STATUS, PERFORMANCE, ACESSO, CONEXAO)

# Valores de status exigidos pelo enunciado
LIVRE = "Livre"
OCUPADA = "Ocupada"

QOS = 1


def topico(estacao_id: str, tipo: str, raiz: str = TOPICO_RAIZ) -> str:
    """Monta o tópico de uma estação. Ex.: fiap/3espz/smartgym/estacao-01/status"""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de tópico desconhecido: {tipo}")
    return f"{raiz}/{estacao_id}/{tipo}"


def assinaturas(raiz: str = TOPICO_RAIZ) -> list:
    """Lista (tópico, qos) que o dashboard assina, com curinga '+' por estação."""
    return [(f"{raiz}/+/{tipo}", QOS) for tipo in TIPOS]


def interpretar_topico(topico_recebido: str, raiz: str = TOPICO_RAIZ) -> Optional[Tuple[str, str]]:
    """Extrai (estacao_id, tipo) de um tópico recebido. Retorna None se não pertencer ao contrato."""
    prefixo = raiz + "/"
    if not topico_recebido.startswith(prefixo):
        return None
    partes = topico_recebido[len(prefixo):].split("/")
    if len(partes) != 2 or partes[1] not in TIPOS or not partes[0]:
        return None
    return partes[0], partes[1]
