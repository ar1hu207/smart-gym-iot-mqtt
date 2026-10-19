"""
Estado do dashboard em memória + difusão para os navegadores conectados.

O assinante MQTT chama `aplicar()` a cada mensagem; o Painel atualiza o
estado, grava a série no SQLite e empurra um snapshot para cada navegador
inscrito no stream SSE (Server-Sent Events). Assim a página atualiza sozinha,
sem refresh manual.
"""

import queue
import threading
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

from shared import topicos
from dashboard.armazenamento import Armazenamento


def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Painel:
    def __init__(self, armazenamento: Armazenamento, broker: str, topico_raiz: str, log=print):
        self._armazenamento = armazenamento
        self._log = log
        self._lock = threading.RLock()
        self._estacoes: Dict[str, dict] = {}
        self._acessos: deque = deque(maxlen=15)
        self._broker = {"conectado": False, "endereco": broker, "topico_raiz": topico_raiz}
        self._inscritos: List[queue.Queue] = []

    # ─── Entrada (thread do MQTT) ────────────────────────────────
    def definir_broker(self, conectado: bool) -> None:
        with self._lock:
            self._broker["conectado"] = conectado
        self._difundir("broker")

    def aplicar(self, estacao_id: str, tipo: str, payload: dict) -> None:
        destaque: Optional[dict] = None
        with self._lock:
            estacao = self._estacao(estacao_id, payload)

            if tipo == topicos.STATUS:
                estacao.update(
                    status=payload.get("status"),
                    exercicio=payload.get("exercicio") or estacao["exercicio"],
                    aluno=payload.get("aluno"),
                    plano=payload.get("plano"),
                    desde=payload.get("desde"),
                )
                if payload.get("status") == topicos.LIVRE:
                    estacao["ultima_serie"] = None
                destaque = {"estacao": estacao["nome"], "status": payload.get("status"), "aluno": payload.get("aluno")}

            elif tipo == topicos.PERFORMANCE:
                if not self._armazenamento.salvar_serie(payload):
                    return  # duplicata entregue pelo QoS 1
                estacao["ultima_serie"] = {**payload, "recebido_em": agora_iso()}
                destaque = payload

            elif tipo == topicos.ACESSO:
                self._acessos.appendleft({**payload, "recebido_em": agora_iso()})
                destaque = payload

            elif tipo == topicos.CONEXAO:
                estacao["online"] = bool(payload.get("online"))
                destaque = {"estacao": estacao["nome"], "online": estacao["online"]}

            estacao["atualizado_em"] = agora_iso()

        self._difundir(tipo, destaque)

    def remover(self, estacao_id: str) -> None:
        with self._lock:
            if self._estacoes.pop(estacao_id, None) is None:
                return
        self._difundir("remocao", {"estacao_id": estacao_id})

    # ─── Saída (rotas Flask) ─────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            estacoes = sorted((dict(e) for e in self._estacoes.values()), key=lambda e: e["id"])
            acessos = list(self._acessos)
            broker = dict(self._broker)
        online = [e for e in estacoes if e["online"] is not False]
        return {
            "estacoes": estacoes,
            "acessos": acessos,
            "historico": self._armazenamento.recentes(50),
            "resumo": {
                **self._armazenamento.resumo_do_dia(),
                "livres": sum(1 for e in online if e["status"] == topicos.LIVRE),
                "ocupadas": sum(1 for e in online if e["status"] == topicos.OCUPADA),
                "offline": len(estacoes) - len(online),
            },
            "broker": broker,
            "gerado_em": agora_iso(),
        }

    def inscrever(self) -> queue.Queue:
        fila: queue.Queue = queue.Queue(maxsize=50)
        with self._lock:
            self._inscritos.append(fila)
        return fila

    def desinscrever(self, fila: queue.Queue) -> None:
        with self._lock:
            if fila in self._inscritos:
                self._inscritos.remove(fila)

    # ─── Internos ────────────────────────────────────────────────
    def _estacao(self, estacao_id: str, payload: dict) -> dict:
        estacao = self._estacoes.setdefault(estacao_id, {
            "id": estacao_id, "nome": estacao_id, "exercicio": None, "status": None, "online": None,
            "aluno": None, "plano": None, "desde": None, "ultima_serie": None, "atualizado_em": None,
        })
        if payload.get("estacao_nome"):
            estacao["nome"] = payload["estacao_nome"]
        return estacao

    def _difundir(self, tipo: str, destaque: Optional[dict] = None) -> None:
        mensagem = {"tipo": tipo, "destaque": destaque, "estado": self.snapshot()}
        with self._lock:
            inscritos = list(self._inscritos)
        for fila in inscritos:
            try:
                fila.put_nowait(mensagem)
            except queue.Full:
                self.desinscrever(fila)  # navegador travado: descarta, ele reconecta sozinho
