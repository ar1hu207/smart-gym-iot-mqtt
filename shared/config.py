"""
Configuração compartilhada entre a estação (publisher), o dashboard (subscriber)
e as ferramentas de apoio.

Todos os valores podem ser sobrescritos por variáveis de ambiente ou por um
arquivo `.env` na raiz do repositório (veja `.env.example`).
"""

import os
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


def _carregar_env(caminho: Path = RAIZ_PROJETO / ".env") -> None:
    """Carrega um .env simples (CHAVE=valor) sem depender de bibliotecas externas.

    Variáveis já definidas no ambiente têm prioridade sobre o arquivo.
    """
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_env()

# ─── Broker MQTT ─────────────────────────────────────────────────
# Padrão: broker público da HiveMQ. Para usar o broker da aula ou um
# Mosquitto local, basta trocar MQTT_HOST/MQTT_PORT no .env.
MQTT_HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USUARIO = os.getenv("MQTT_USUARIO") or None
MQTT_SENHA = os.getenv("MQTT_SENHA") or None
MQTT_TLS = os.getenv("MQTT_TLS", "0") == "1"
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "30"))

# Prefixo de todos os tópicos. Em broker público, cada grupo deve usar um
# prefixo próprio para não receber mensagens de outras equipes.
TOPICO_RAIZ = os.getenv("TOPICO_RAIZ", "fiap/3espz/smartgym").strip().rstrip("/")
