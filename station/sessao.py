"""
Máquina de estados da estação de treino e regras de publicação MQTT.

    LIVRE    --cartão cadastrado-->               PRONTO    (publica "Ocupada")
    PRONTO   --1ª repetição-->                    EM_SERIE
    EM_SERIE --TEMPO_FIM_SERIE_S sem repetição--> DESCANSO  (publica performance)
    DESCANSO --nova repetição-->                  EM_SERIE  (série seguinte)
    qualquer --mesmo cartão / inatividade-->      LIVRE     (publica "Livre")
    qualquer --outro cartão-->                    (mantém)  (publica acesso NEGADO)

Eventos publicados (MQTT é orientado a eventos, então nada é enviado em loop):
  * login/logout      -> `status` ("Ocupada"/"Livre", retained) + `acesso`
  * cartão recusado   -> `acesso` (NEGADO)
  * fim de cada série -> `performance` (aluno, repetições, cadência, fadiga, descanso)

A classe não conhece MQTT, câmera nem serial: recebe uma função `publicar` e
uma função `notificar` (sinais para o hardware). Isso deixa a lógica testável
e reaproveitada pelo simulador.
"""

import statistics
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

from shared import topicos
from station import config
from station.contador import Repeticao


class Estado(str, Enum):
    LIVRE = "LIVRE"
    PRONTO = "PRONTO"        # aluno identificado, ainda não iniciou a série
    EM_SERIE = "EM_SERIE"    # contando repetições
    DESCANSO = "DESCANSO"    # série publicada, aguardando a próxima


class ResultadoCartao(str, Enum):
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    NEGADO = "NEGADO"
    IGNORADO = "IGNORADO"    # leitura repetida do mesmo cartão (debounce)


def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class SessaoEstacao:
    def __init__(
        self,
        estacao_id: str,
        estacao_nome: str,
        exercicio: str,
        alunos: Dict[str, dict],
        publicar: Callable[..., None],
        notificar: Optional[Callable[[str], None]] = None,
        relogio: Callable[[], float] = time.monotonic,
        *,
        tempo_fim_serie_s: float = config.TEMPO_FIM_SERIE_S,
        tempo_inatividade_s: float = config.TEMPO_INATIVIDADE_S,
        janela_debounce_s: float = config.JANELA_DEBOUNCE_RFID_S,
        descanso_min_s: int = config.DESCANSO_MIN_S,
        descanso_max_s: int = config.DESCANSO_MAX_S,
        log: Callable[[str], None] = print,
    ):
        self.estacao_id = estacao_id
        self.estacao_nome = estacao_nome
        self.exercicio = exercicio
        self.alunos = alunos
        self._publicar = publicar
        self._notificar = notificar or (lambda evento: None)
        self._relogio = relogio
        self.tempo_fim_serie_s = tempo_fim_serie_s
        self.tempo_inatividade_s = tempo_inatividade_s
        self.janela_debounce_s = janela_debounce_s
        self.descanso_min_s = descanso_min_s
        self.descanso_max_s = descanso_max_s
        self._log = log

        self._ultimo_cartao = (None, float("-inf"))
        self._limpar_sessao()

    # ─── Estado consultável (usado pelo HUD) ─────────────────────
    @property
    def ocupada(self) -> bool:
        return self.estado != Estado.LIVRE

    @property
    def repeticoes_serie(self) -> int:
        return sum(1 for r in self._reps if r.completa)

    @property
    def incompletas_serie(self) -> int:
        return sum(1 for r in self._reps if not r.completa)

    def descanso_restante_s(self) -> Optional[float]:
        if self.estado != Estado.DESCANSO or self.descanso_sugerido_s is None:
            return None
        return max(0.0, self.descanso_sugerido_s - (self._relogio() - self._inicio_descanso))

    # ─── Entradas ────────────────────────────────────────────────
    def anunciar(self) -> None:
        """Publica o status atual (chamado na inicialização da estação)."""
        self._publicar_status()

    def cartao_lido(self, uid: str) -> ResultadoCartao:
        agora = self._relogio()
        uid_anterior, instante_anterior = self._ultimo_cartao
        if uid == uid_anterior and agora - instante_anterior < self.janela_debounce_s:
            return ResultadoCartao.IGNORADO
        self._ultimo_cartao = (uid, agora)

        perfil = self.alunos.get(uid)

        if not self.ocupada:
            if perfil is None:
                self._negar(uid, None, "Cartão não cadastrado")
                return ResultadoCartao.NEGADO
            self._login(uid, perfil)
            return ResultadoCartao.LOGIN

        if uid == self.uid:
            self.logout("Logout pelo cartão")
            return ResultadoCartao.LOGOUT

        self._negar(uid, perfil["nome"] if perfil else None, f"Estação ocupada por {self.aluno['nome']}")
        return ResultadoCartao.NEGADO

    def registrar_repeticao(self, repeticao: Repeticao) -> None:
        if not self.ocupada:
            return
        agora = self._relogio()
        if self.estado in (Estado.PRONTO, Estado.DESCANSO):
            self.serie_atual += 1
            self._reps = []
            self._inicio_serie = agora - repeticao.duracao_s
            self.estado = Estado.EM_SERIE
            self.descanso_sugerido_s = None
            self._log(f"[Sessão] Série {self.serie_atual} iniciada")
        self._reps.append(repeticao)
        self._fim_serie = agora
        self._ultima_atividade = agora

    def tick(self) -> None:
        """Chamado a cada iteração do loop: fecha séries e aplica timeout de inatividade."""
        if not self.ocupada:
            return
        ocioso = self._relogio() - self._ultima_atividade
        if self.estado == Estado.EM_SERIE and ocioso >= self.tempo_fim_serie_s:
            self.finalizar_serie("pausa")
        elif self.estado in (Estado.PRONTO, Estado.DESCANSO) and ocioso >= self.tempo_inatividade_s:
            self.logout("Logout automático por inatividade")

    def finalizar_serie(self, motivo: str = "manual") -> Optional[dict]:
        """Fecha a série atual e publica a performance. Retorna o payload enviado."""
        if self.estado != Estado.EM_SERIE or not self._reps:
            return None

        payload = self._montar_performance(motivo)
        self._publicar(topicos.PERFORMANCE, payload)
        self._log(
            f"[MQTT] Performance: {payload['aluno']} | série {payload['serie']} | "
            f"{payload['repeticoes']} reps (+{payload['repeticoes_incompletas']} incompletas) | "
            f"descanso {payload['descanso_sugerido_s']}s"
        )

        agora = self._relogio()
        self.estado = Estado.DESCANSO
        self.descanso_sugerido_s = payload["descanso_sugerido_s"]
        self._inicio_descanso = agora
        self._ultima_atividade = agora
        self.ultima_performance = payload
        self._reps = []
        self._notificar("SERIE")
        return payload

    def logout(self, motivo: str) -> None:
        if not self.ocupada:
            return
        if self.estado == Estado.EM_SERIE:
            self.finalizar_serie("logout")

        self._publicar(topicos.ACESSO, self._evento_acesso("SAIDA", self.uid, self.aluno["nome"], motivo))
        self._log(f"[Sessão] {self.aluno['nome']} saiu ({motivo})")
        self._limpar_sessao()
        self._publicar_status()
        self._notificar("LIVRE")

    def encerrar(self) -> None:
        """Desligamento da estação: libera a máquina antes de sair."""
        self.logout("Estação desligada")

    # ─── Internos ────────────────────────────────────────────────
    def _limpar_sessao(self) -> None:
        self.estado = Estado.LIVRE
        self.uid: Optional[str] = None
        self.aluno: Optional[dict] = None
        self.desde = agora_iso()
        self.serie_atual = 0
        self._reps: List[Repeticao] = []
        self._inicio_serie = 0.0
        self._fim_serie = 0.0
        self._ultima_atividade = self._relogio()
        self._inicio_descanso = 0.0
        self.descanso_sugerido_s: Optional[int] = None
        self.ultima_performance: Optional[dict] = None

    def _login(self, uid: str, perfil: dict) -> None:
        self.estado = Estado.PRONTO
        self.uid = uid
        self.aluno = perfil
        self.desde = agora_iso()
        self._ultima_atividade = self._relogio()
        # Ordem importa: "Ocupada" sai logo após o bipe do RFID.
        self._publicar_status()
        self._publicar(topicos.ACESSO, self._evento_acesso("LIBERADO", uid, perfil["nome"], "Login"))
        self._notificar("OCUPADA")
        self._log(f"[Sessão] Acesso liberado: {perfil['nome']} ({uid})")

    def _negar(self, uid: str, nome: Optional[str], motivo: str) -> None:
        self._publicar(topicos.ACESSO, self._evento_acesso("NEGADO", uid, nome, motivo))
        self._notificar("NEGADO")
        self._log(f"[Sessão] Acesso negado ({uid}): {motivo}")

    def _publicar_status(self) -> None:
        status = topicos.OCUPADA if self.ocupada else topicos.LIVRE
        payload = {
            "estacao_id": self.estacao_id,
            "estacao_nome": self.estacao_nome,
            "exercicio": self.exercicio,
            "status": status,
            "aluno": self.aluno["nome"] if self.aluno else None,
            "plano": self.aluno.get("plano") if self.aluno else None,
            "desde": self.desde,
            "ts": agora_iso(),
        }
        # retain=True: quem abrir o dashboard depois recebe o status atual na hora.
        self._publicar(topicos.STATUS, payload, retain=True)
        self._log(f"[MQTT] Status: {status}" + (f" ({payload['aluno']})" if payload["aluno"] else ""))

    def _evento_acesso(self, resultado: str, uid: str, nome: Optional[str], motivo: str) -> dict:
        return {
            "estacao_id": self.estacao_id,
            "estacao_nome": self.estacao_nome,
            "resultado": resultado,
            "uid": uid,
            "aluno": nome,
            "motivo": motivo,
            "ts": agora_iso(),
        }

    def _montar_performance(self, motivo: str) -> dict:
        duracoes = [r.duracao_s for r in self._reps]
        completas = sum(1 for r in self._reps if r.completa)
        incompletas = len(self._reps) - completas
        cadencia = statistics.mean(duracoes)

        # Fadiga: as últimas repetições ficaram >= 30% mais lentas que as primeiras.
        fadiga, queda_pct = False, 0.0
        if len(duracoes) >= 4:
            k = max(2, len(duracoes) // 3)
            inicio, fim = statistics.mean(duracoes[:k]), statistics.mean(duracoes[-k:])
            queda_pct = (fim / inicio - 1) * 100 if inicio > 0 else 0.0
            fadiga = queda_pct >= 30

        ritmo_rapido = cadencia < 1.0
        amplitude_ruim = incompletas / len(self._reps) >= 0.3

        alertas = []
        if fadiga:
            alertas.append(f"Perda de ritmo: últimas repetições {queda_pct:.0f}% mais lentas (fadiga)")
        if ritmo_rapido:
            alertas.append("Execução rápida demais (< 1 s por repetição)")
        if incompletas:
            alertas.append(f"Amplitude incompleta em {incompletas} repetição(ões)")

        # Descanso sugerido entre 60 s e 90 s conforme os sinais de fadiga/técnica.
        penalidade = (0.5 if fadiga else 0) + (0.5 if (amplitude_ruim or ritmo_rapido) else 0)
        descanso = round(self.descanso_min_s + (self.descanso_max_s - self.descanso_min_s) * penalidade)

        return {
            "id": uuid.uuid4().hex,
            "estacao_id": self.estacao_id,
            "estacao_nome": self.estacao_nome,
            "exercicio": self.exercicio,
            "aluno": self.aluno["nome"],
            "plano": self.aluno.get("plano"),
            "serie": self.serie_atual,
            "repeticoes": completas,
            "repeticoes_incompletas": incompletas,
            "duracao_s": round(self._fim_serie - self._inicio_serie, 1),
            "cadencia_media_s": round(cadencia, 2),
            "fadiga": fadiga,
            "alertas": alertas,
            "descanso_sugerido_s": descanso,
            "motivo_fim": motivo,
            "ts": agora_iso(),
        }
