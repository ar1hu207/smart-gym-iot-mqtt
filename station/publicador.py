"""
Publisher MQTT da estação.

* QoS 1 em tudo: a mensagem chega ao broker pelo menos uma vez, mesmo com
  oscilação de Wi-Fi (o paho guarda a fila e reenvia ao reconectar).
* `status` e `conexao` são retained: o broker guarda a última mensagem e a
  entrega imediatamente a qualquer dashboard que se conecte depois.
* Last Will (LWT): se a estação cair sem se despedir, o próprio broker publica
  `conexao = offline` e o dashboard mostra a estação como offline.
"""

import json
import threading
from typing import Callable, Dict

import paho.mqtt.client as mqtt

from shared import topicos
from shared.mqtt_cliente import conectar, criar_cliente, descricao_broker
from station.sessao import agora_iso


class PublicadorMQTT:
    def __init__(self, estacao_id: str, estacao_nome: str, log: Callable[[str], None] = print):
        self.estacao_id = estacao_id
        self.estacao_nome = estacao_nome
        self._log = log
        self._conectado = threading.Event()
        self._retidos: Dict[str, dict] = {}   # último payload retained por tipo
        self._lock = threading.Lock()

        self.cliente = criar_cliente(f"smartgym-{estacao_id}")
        self.cliente.will_set(
            topicos.topico(estacao_id, topicos.CONEXAO),
            json.dumps(self._payload_conexao(False, "queda inesperada (LWT)"), ensure_ascii=False),
            qos=topicos.QOS,
            retain=True,
        )
        self.cliente.on_connect = self._ao_conectar
        self.cliente.on_disconnect = self._ao_desconectar

    @property
    def conectado(self) -> bool:
        return self._conectado.is_set()

    def iniciar(self, timeout_s: float = 8.0) -> bool:
        self._log(f"[MQTT] Conectando em {descricao_broker()} ...")
        conectar(self.cliente)
        ok = self._conectado.wait(timeout_s)
        if not ok:
            self._log("[MQTT] Broker ainda não respondeu; mensagens ficam na fila até conectar.")
        return ok

    def publicar(self, tipo: str, payload: dict, retain: bool = False) -> None:
        if retain:
            with self._lock:
                self._retidos[tipo] = payload
        self.cliente.publish(
            topicos.topico(self.estacao_id, tipo),
            json.dumps(payload, ensure_ascii=False),
            qos=topicos.QOS,
            retain=retain,
        )

    def encerrar(self) -> None:
        """Despedida limpa: marca a estação como offline (sem acionar o LWT)."""
        info = self.cliente.publish(
            topicos.topico(self.estacao_id, topicos.CONEXAO),
            json.dumps(self._payload_conexao(False, "desligada"), ensure_ascii=False),
            qos=topicos.QOS,
            retain=True,
        )
        try:
            info.wait_for_publish(timeout=3)
        except (RuntimeError, ValueError):
            pass
        self.cliente.disconnect()
        self.cliente.loop_stop()

    # ─── Callbacks do paho (rodam na thread de rede) ─────────────
    def _ao_conectar(self, cliente, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self._log(f"[MQTT] Conexão recusada: {reason_code}")
            return
        self._log(f"[MQTT] Conectado ao broker {descricao_broker()}")
        cliente.publish(
            topicos.topico(self.estacao_id, topicos.CONEXAO),
            json.dumps(self._payload_conexao(True, "conectada"), ensure_ascii=False),
            qos=topicos.QOS,
            retain=True,
        )
        # Após uma reconexão, reafirma o último status (caso o broker tenha reiniciado).
        with self._lock:
            retidos = dict(self._retidos)
        for tipo, payload in retidos.items():
            cliente.publish(topicos.topico(self.estacao_id, tipo), json.dumps(payload, ensure_ascii=False),
                            qos=topicos.QOS, retain=True)
        self._conectado.set()

    def _ao_desconectar(self, cliente, userdata, flags, reason_code, properties):
        self._conectado.clear()
        if reason_code != 0:
            self._log(f"[MQTT] Desconectado ({reason_code}); tentando reconectar...")

    def _payload_conexao(self, online: bool, motivo: str) -> dict:
        return {
            "estacao_id": self.estacao_id,
            "estacao_nome": self.estacao_nome,
            "online": online,
            "motivo": motivo,
            "ts": agora_iso(),
        }
