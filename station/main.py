"""
Estação de treino inteligente — Publisher MQTT.

Fluxo: RFID (serial) -> login -> MediaPipe conta repetições -> fim da série
-> publica performance -> mesmo cartão -> logout. O status "Ocupada"/"Livre"
é publicado no instante do bipe do cartão.

Uso (a partir da raiz do repositório):
    python -m station.main                 # câmera + RFID (porta detectada automaticamente)
    python -m station.main --porta COM5    # porta serial explícita
    python -m station.main --sem-serial    # sem placa: cartões pelas teclas 1-3 (0 = desconhecido)
    python -m station.main --sem-camera    # sem webcam: repetições pela tecla ESPAÇO
"""

import argparse
import json
import queue
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from shared import topicos
from station import config, hud
from station.contador import ContadorRepeticoes, Repeticao
from station.publicador import PublicadorMQTT
from station.rfid import LeitorRFID, detectar_porta
from station.sessao import ResultadoCartao, SessaoEstacao

JANELA = "Smart Gym - Estacao"
UID_DESCONHECIDO = "99:88:77:66"


def carregar_alunos(caminho: Path) -> dict:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return {uid.upper(): perfil for uid, perfil in dados.items() if not uid.startswith("_")}


def argumentos():
    parser = argparse.ArgumentParser(description="Estação Smart Gym (publisher MQTT)")
    parser.add_argument("--porta", help="porta serial da placa RFID (ex.: COM5, /dev/ttyUSB0)")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDICE, help="índice da webcam")
    parser.add_argument("--sem-camera", action="store_true", help="não abre a webcam (reps pela tecla ESPAÇO)")
    parser.add_argument("--sem-serial", action="store_true", help="não procura a placa RFID (cartões pelo teclado)")
    parser.add_argument("--estacao-id", default=config.ESTACAO_ID)
    parser.add_argument("--estacao-nome", default=config.ESTACAO_NOME)
    return parser.parse_args()


def main() -> int:
    args = argumentos()
    alunos = carregar_alunos(config.ARQUIVO_ALUNOS)
    uids_teclado = list(alunos)[:9]

    print("=" * 60)
    print(f" Smart Gym | {args.estacao_nome} ({args.estacao_id}) | CP05 - IoT/MQTT")
    print(f" Tópicos: {topicos.topico(args.estacao_id, topicos.STATUS).rsplit('/', 1)[0]}/<tipo>")
    print("=" * 60)

    publicador = PublicadorMQTT(args.estacao_id, args.estacao_nome)
    publicador.iniciar()

    # ── RFID: a thread serial só enfileira UIDs; a sessão roda no loop principal ──
    fila_cartoes: "queue.Queue[str]" = queue.Queue()
    leitor = None
    if not args.sem_serial:
        porta = args.porta or config.SERIAL_PORTA or detectar_porta()
        if porta:
            leitor = LeitorRFID(porta, config.SERIAL_BAUD, fila_cartoes.put)
            if not leitor.iniciar():
                leitor = None
        else:
            print("[RFID] Nenhuma placa encontrada. Simule cartões pelas teclas 1-3 (0 = desconhecido).")

    aviso = {"texto": "", "cor": hud.BRANCO, "ate": 0.0}

    def mostrar(texto: str, cor, segundos: float = 3.5) -> None:
        aviso.update(texto=texto, cor=cor, ate=time.monotonic() + segundos)

    def publicar(tipo: str, payload: dict, retain: bool = False) -> None:
        publicador.publicar(tipo, payload, retain)
        if tipo == topicos.PERFORMANCE:
            mostrar(f"Serie {payload['serie']} enviada via MQTT: {payload['repeticoes']} reps", hud.ROSA, 4)

    def notificar(evento: str) -> None:
        if leitor:
            leitor.enviar(evento)

    sessao = SessaoEstacao(args.estacao_id, args.estacao_nome, config.EXERCICIO, alunos, publicar, notificar)
    sessao.anunciar()
    notificar("LIVRE")

    # ── Câmera + MediaPipe ──
    camera = detector = None
    if not args.sem_camera:
        camera = cv2.VideoCapture(args.camera)
        if camera.isOpened():
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            from station.visao import DetectorPose
            detector = DetectorPose()
        else:
            print("[Câmera] Webcam indisponível; use ESPAÇO para simular repetições.")
            camera = None

    contador = ContadorRepeticoes()
    ultima_rep_teclado = None

    def tratar_cartao(uid: str) -> None:
        resultado = sessao.cartao_lido(uid)
        if resultado == ResultadoCartao.LOGIN:
            contador.reiniciar()
            mostrar(f"Bem-vindo, {sessao.aluno['nome']}! Maquina OCUPADA", hud.VERDE)
        elif resultado == ResultadoCartao.LOGOUT:
            mostrar("Sessao encerrada. Maquina LIVRE", hud.AMARELO)
        elif resultado == ResultadoCartao.NEGADO:
            mostrar(f"Acesso negado - cartao {uid}", hud.VERMELHO)

    def repeticao_teclado(completa: bool) -> None:
        nonlocal ultima_rep_teclado
        if not sessao.ocupada:
            return
        agora = time.monotonic()
        duracao = agora - ultima_rep_teclado if ultima_rep_teclado and agora - ultima_rep_teclado < 6 else 2.0
        ultima_rep_teclado = agora
        sessao.registrar_repeticao(Repeticao(completa=completa, duracao_s=round(duracao, 2),
                                             menor_angulo=40.0 if completa else 90.0))

    cv2.namedWindow(JANELA, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(JANELA, 1280, 720)

    try:
        while True:
            # 1) Cartões lidos pela thread serial
            while True:
                try:
                    tratar_cartao(fila_cartoes.get_nowait())
                except queue.Empty:
                    break

            # 2) Frame da câmera (ou fundo neutro no modo sem câmera)
            if camera:
                ok, frame = camera.read()
                if not ok:
                    continue
                frame = cv2.flip(frame, 1)
            else:
                frame = np.full((720, 1280, 3), 30, dtype=np.uint8)

            # 3) Contagem de repetições só com aluno logado
            angulo = None
            if detector and sessao.ocupada:
                leitura = detector.processar(frame)
                if leitura:
                    detector.desenhar(frame, leitura)
                    angulo = leitura.angulo
                    if angulo is not None:
                        repeticao = contador.atualizar(angulo, time.monotonic())
                        if repeticao:
                            sessao.registrar_repeticao(repeticao)

            # 4) Regras de tempo: fim de série e logout por inatividade
            sessao.tick()

            # 5) HUD
            texto_aviso = aviso["texto"] if time.monotonic() < aviso["ate"] else ""
            hud.desenhar(frame, sessao, mqtt_ok=publicador.conectado, rfid_ok=bool(leitor and leitor.ativo),
                         angulo=angulo, aviso=texto_aviso, cor_aviso=aviso["cor"])
            cv2.imshow(JANELA, frame)

            # 6) Teclado (simulação e controles)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), 27) or cv2.getWindowProperty(JANELA, cv2.WND_PROP_VISIBLE) < 1:
                break
            if ord("1") <= tecla <= ord("9") and tecla - ord("1") < len(uids_teclado):
                fila_cartoes.put(uids_teclado[tecla - ord("1")])
            elif tecla == ord("0"):
                fila_cartoes.put(UID_DESCONHECIDO)
            elif tecla == ord(" "):
                repeticao_teclado(completa=True)
            elif tecla == ord("i"):
                repeticao_teclado(completa=False)
            elif tecla == ord("f"):
                sessao.finalizar_serie("manual")
            elif tecla == ord("l") and sessao.ocupada:
                sessao.logout("Logout pelo teclado")
                mostrar("Sessao encerrada. Maquina LIVRE", hud.AMARELO)
    except KeyboardInterrupt:
        pass
    finally:
        sessao.encerrar()
        publicador.encerrar()
        if leitor:
            leitor.parar()
        if camera:
            camera.release()
        if detector:
            detector.fechar()
        cv2.destroyAllWindows()
        print("[Sistema] Estação encerrada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
