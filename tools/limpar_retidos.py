"""
Apaga do broker as mensagens retidas (status e conexao) de uma ou mais estações.
No MQTT, publicar um payload vazio com retain=True remove a mensagem retida;
o dashboard entende isso e tira a estação da tela.

    python -m tools.limpar_retidos sim-01 sim-02 sim-03
"""

import sys
import threading

from shared import topicos
from shared.mqtt_cliente import conectar, criar_cliente, descricao_broker


def main(estacoes) -> int:
    if not estacoes:
        print(__doc__)
        return 1

    conectado = threading.Event()
    cliente = criar_cliente("smartgym-limpeza")
    cliente.on_connect = lambda c, u, f, rc, p: conectado.set() if not rc.is_failure else None
    conectar(cliente)
    if not conectado.wait(15):
        print(f"Não foi possível conectar em {descricao_broker()}")
        cliente.loop_stop()
        return 1

    envios = [
        cliente.publish(topicos.topico(estacao_id, tipo), b"", qos=topicos.QOS, retain=True)
        for estacao_id in estacoes
        for tipo in (topicos.STATUS, topicos.CONEXAO)
    ]
    for envio in envios:
        envio.wait_for_publish(timeout=10)
    cliente.disconnect()
    cliente.loop_stop()
    print(f"Mensagens retidas removidas em {descricao_broker()}: {', '.join(estacoes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
