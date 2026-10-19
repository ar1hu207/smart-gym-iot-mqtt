"""
Monitor de linha de comando: assina `<TOPICO_RAIZ>/#` e imprime cada mensagem.
Útil para mostrar o tráfego MQTT "cru" durante a apresentação.

    python -m tools.monitor_mqtt
"""

import json
from datetime import datetime

from shared import config
from shared.mqtt_cliente import criar_cliente, descricao_broker

CORES = {"status": "\033[96m", "performance": "\033[95m", "acesso": "\033[93m", "conexao": "\033[90m"}
RESET = "\033[0m"


def ao_conectar(cliente, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"Conexão recusada: {reason_code}")
        return
    cliente.subscribe(f"{config.TOPICO_RAIZ}/#", qos=1)
    print(f"Conectado a {descricao_broker()} | assinando {config.TOPICO_RAIZ}/#\n")


def ao_receber(cliente, userdata, mensagem):
    tipo = mensagem.topic.rsplit("/", 1)[-1]
    cor = CORES.get(tipo, "")
    try:
        corpo = json.dumps(json.loads(mensagem.payload), ensure_ascii=False)
    except (ValueError, UnicodeDecodeError):
        corpo = repr(mensagem.payload)
    retido = " [retained]" if mensagem.retain else ""
    print(f"{datetime.now():%H:%M:%S} {cor}{mensagem.topic}{retido}{RESET}\n    {corpo}")


def main() -> None:
    cliente = criar_cliente("smartgym-monitor")
    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber
    cliente.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=config.MQTT_KEEPALIVE)
    try:
        cliente.loop_forever()
    except KeyboardInterrupt:
        cliente.disconnect()


if __name__ == "__main__":
    main()
