"""
Simulador de estações (sem câmera e sem Arduino).

Usa a MESMA SessaoEstacao e o MESMO PublicadorMQTT da estação real; só troca
a origem dos eventos (cartões e repetições sintéticos). Serve para testar o
dashboard, mostrar várias máquinas ao mesmo tempo e como plano B na
apresentação.

    python -m tools.simulador                      # 3 estações, ritmo acelerado (4x)
    python -m tools.simulador --estacoes 1 --fator 1
    python -m tools.simulador --duracao 120        # encerra sozinho após 2 min

Ao terminar, cada estação simulada faz logout e publica "offline". Para
apagar as mensagens retidas delas do broker: python -m tools.limpar_retidos sim-01 sim-02 sim-03
"""

import argparse
import random
import threading
import time

from station.contador import Repeticao
from station.publicador import PublicadorMQTT
from station.sessao import Estado, SessaoEstacao

ESTACOES = [
    ("sim-01", "Estação 01", "Rosca direta"),
    ("sim-02", "Estação 02", "Rosca martelo"),
    ("sim-03", "Estação 03", "Tríceps na polia"),
    ("sim-04", "Estação 04", "Desenvolvimento"),
    ("sim-05", "Estação 05", "Remada baixa"),
    ("sim-06", "Estação 06", "Leg press"),
]

ALUNOS = {
    "5A:10:00:01": {"nome": "Ana Beatriz", "plano": "Hipertrofia"},
    "5A:10:00:02": {"nome": "Bruno Costa", "plano": "Força"},
    "5A:10:00:03": {"nome": "Fernanda Alves", "plano": "Resistência"},
    "5A:10:00:04": {"nome": "Lucas Pereira", "plano": "Iniciante"},
    "5A:10:00:05": {"nome": "Rafael Gomes", "plano": "Hipertrofia"},
    "5A:10:00:06": {"nome": "Juliana Rocha", "plano": "Funcional"},
    "5A:10:00:07": {"nome": "Pedro Martins", "plano": "Força"},
    "5A:10:00:08": {"nome": "Camila Duarte", "plano": "Resistência"},
}
UID_DESCONHECIDO = "99:88:77:66"


class Encerrar(Exception):
    pass


class Relogio:
    """Relógio acelerado: com fator 4, 1 s real equivale a 4 s de treino."""

    def __init__(self, fator: float, parar: threading.Event):
        self.fator = fator
        self.parar = parar
        self.t0 = time.monotonic()

    def __call__(self) -> float:
        return self.t0 + (time.monotonic() - self.t0) * self.fator

    def dormir(self, segundos_simulados: float) -> None:
        if self.parar.wait(segundos_simulados / self.fator):
            raise Encerrar


class Recepcao:
    """Garante que o mesmo aluno não treine em duas máquinas ao mesmo tempo."""

    def __init__(self, alunos: dict):
        self._livres = set(alunos)
        self._lock = threading.Lock()

    def pegar(self, rnd: random.Random):
        with self._lock:
            if not self._livres:
                return None
            uid = rnd.choice(sorted(self._livres))
            self._livres.remove(uid)
            return uid

    def devolver(self, uid: str) -> None:
        with self._lock:
            self._livres.add(uid)


def treinar(sessao: SessaoEstacao, relogio: Relogio, rnd: random.Random) -> None:
    """Simula de 2 a 4 séries; algumas com fadiga (repetições cada vez mais lentas)."""
    relogio.dormir(rnd.uniform(3, 8))
    for _ in range(rnd.randint(2, 4)):
        total = rnd.randint(8, 14)
        cadencia = rnd.uniform(1.8, 2.8)
        com_fadiga = rnd.random() < 0.4
        for i in range(total):
            fator = 1 + (0.7 * i / total if com_fadiga else rnd.uniform(-0.08, 0.08))
            duracao = cadencia * fator
            relogio.dormir(duracao)
            completa = rnd.random() > 0.06
            sessao.registrar_repeticao(Repeticao(completa, round(duracao, 2), 40.0 if completa else 95.0))
        # Para de se mexer: a sessão fecha a série sozinha após TEMPO_FIM_SERIE_S.
        while sessao.estado == Estado.EM_SERIE:
            relogio.dormir(0.5)
            sessao.tick()
        relogio.dormir(rnd.uniform(25, 45))


def rodar_estacao(estacao, recepcao: Recepcao, relogio: Relogio, semente: int) -> None:
    estacao_id, nome, exercicio = estacao
    rnd = random.Random(semente)

    def log(texto: str) -> None:
        print(f"[{estacao_id}] {texto}")

    publicador = PublicadorMQTT(estacao_id, nome, log=log)
    publicador.iniciar()
    sessao = SessaoEstacao(estacao_id, nome, exercicio, ALUNOS, publicador.publicar, relogio=relogio,
                           tempo_fim_serie_s=4, log=log)
    sessao.anunciar()
    try:
        while True:
            relogio.dormir(rnd.uniform(8, 25))            # máquina livre por um tempo
            if rnd.random() < 0.25:
                sessao.cartao_lido(UID_DESCONHECIDO)       # cartão não cadastrado -> NEGADO
                relogio.dormir(3)
            uid = recepcao.pegar(rnd)
            if uid is None:
                continue
            try:
                sessao.cartao_lido(uid)                    # login -> "Ocupada"
                treinar(sessao, relogio, rnd)
                sessao.cartao_lido(uid)                    # mesmo cartão -> logout -> "Livre"
            finally:
                recepcao.devolver(uid)
    except Encerrar:
        pass
    finally:
        sessao.encerrar()
        publicador.encerrar()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador de estações Smart Gym")
    parser.add_argument("--estacoes", type=int, default=3, choices=range(1, len(ESTACOES) + 1))
    parser.add_argument("--fator", type=float, default=4.0, help="aceleração do tempo (1 = tempo real)")
    parser.add_argument("--duracao", type=float, default=0, help="segundos reais até encerrar (0 = até Ctrl+C)")
    parser.add_argument("--semente", type=int, default=None, help="semente aleatória (reprodutível)")
    args = parser.parse_args()

    parar = threading.Event()
    relogio = Relogio(args.fator, parar)
    recepcao = Recepcao(ALUNOS)
    base = args.semente if args.semente is not None else random.randrange(1_000_000)

    threads = [
        threading.Thread(target=rodar_estacao, args=(e, recepcao, relogio, base + i), name=e[0], daemon=True)
        for i, e in enumerate(ESTACOES[: args.estacoes])
    ]
    for t in threads:
        t.start()
    print(f"Simulando {args.estacoes} estação(ões) a {args.fator}x. Ctrl+C para encerrar.")
    try:
        inicio = time.monotonic()
        while any(t.is_alive() for t in threads):
            if args.duracao and time.monotonic() - inicio >= args.duracao:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    parar.set()
    for t in threads:
        t.join(timeout=10)
    print("Simulador encerrado.")


if __name__ == "__main__":
    main()
