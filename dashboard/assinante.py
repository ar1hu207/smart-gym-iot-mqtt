"""
Subscriber MQTT do dashboard.

Assina `<TOPICO_RAIZ>/+/status|performance|acesso|conexao` (o curinga `+`
captura qualquer estação) e repassa cada mensagem válida para o Painel.
"""

import json

from shared import topicos
from shared.mqtt_cliente import conectar, criar_cliente, descricao_broker
from dashboard.painel import Painel

CAMPOS_OBRIGATORIOS = {
    topicos.STATUS: ("status",),
    topicos.PERFORMANCE: ("aluno", "repeticoes"),
    topicos.ACESSO: ("resultado",),
    topicos.CONEXAO: ("online",),
}


class AssinanteMQTT:
    def __init__(self, painel: Painel, log=print):
        self._painel = painel
        self._log = log
        self.cliente = criar_cliente("smartgym-dashboard")
        self.cliente.on_connect = self._ao_conectar
        self.cliente.on_disconnect = self._ao_desconectar
        self.cliente.on_message = self._ao_receber

    def iniciar(self) -> None:
        self._log(f"[MQTT] Dashboard conectando em {descricao_broker()} ...")
        conectar(self.cliente)

    def parar(self) -> None:
        self.cliente.disconnect()
        self.cliente.loop_stop()

    def _ao_conectar(self, cliente, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self._log(f"[MQTT] Conexão recusada: {reason_code}")
            return
        # Assinar dentro do on_connect garante nova assinatura após cada reconexão.
        cliente.subscribe(topicos.assinaturas())
        self._log(f"[MQTT] Conectado. Assinando {topicos.TOPICO_RAIZ}/+/{{{','.join(topicos.TIPOS)}}}")
        self._painel.definir_broker(True)

    def _ao_desconectar(self, cliente, userdata, flags, reason_code, properties):
        self._log(f"[MQTT] Desconectado do broker ({reason_code})")
        self._painel.definir_broker(False)

    def _ao_receber(self, cliente, userdata, mensagem):
        destino = topicos.interpretar_topico(mensagem.topic)
        if not destino:
            return
        estacao_id, tipo = destino
        if not mensagem.payload:
            # Payload vazio = mensagem retida apagada do broker (tools/limpar_retidos.py).
            if tipo in (topicos.STATUS, topicos.CONEXAO):
                self._painel.remover(estacao_id)
            return
        try:
            payload = json.loads(mensagem.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._log(f"[MQTT] Payload inválido em {mensagem.topic}")
            return
        if not isinstance(payload, dict) or any(c not in payload for c in CAMPOS_OBRIGATORIOS[tipo]):
            self._log(f"[MQTT] Mensagem fora do contrato em {mensagem.topic}")
            return
        retido = " (retained)" if mensagem.retain else ""
        self._log(f"[MQTT] <- {tipo}{retido} de {estacao_id}")
        self._painel.aplicar(estacao_id, tipo, payload)
