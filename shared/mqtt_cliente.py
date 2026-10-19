"""
Fábrica do cliente MQTT (paho-mqtt 2.x) usada pela estação, pelo dashboard e
pelas ferramentas. Centraliza credenciais, TLS e reconexão automática.
"""

import uuid
from typing import Optional

import paho.mqtt.client as mqtt

from shared import config


def criar_cliente(prefixo_id: str) -> mqtt.Client:
    """Cria um cliente MQTT com id único, credenciais/TLS do .env e backoff de reconexão."""
    cliente = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{prefixo_id}-{uuid.uuid4().hex[:8]}",
        clean_session=True,
    )
    if config.MQTT_USUARIO:
        cliente.username_pw_set(config.MQTT_USUARIO, config.MQTT_SENHA)
    if config.MQTT_TLS:
        cliente.tls_set()
    # Se a rede cair, o loop do paho tenta reconectar com espera de 1s até 30s.
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)
    return cliente


def conectar(cliente: mqtt.Client, host: Optional[str] = None, porta: Optional[int] = None) -> None:
    """Conecta de forma assíncrona e inicia a thread de rede do paho."""
    cliente.connect_async(host or config.MQTT_HOST, porta or config.MQTT_PORT, keepalive=config.MQTT_KEEPALIVE)
    cliente.loop_start()


def descricao_broker() -> str:
    return f"{config.MQTT_HOST}:{config.MQTT_PORT}{' (TLS)' if config.MQTT_TLS else ''}"
