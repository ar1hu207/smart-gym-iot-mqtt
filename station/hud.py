"""HUD da estação desenhado com OpenCV (as fontes Hershey só aceitam ASCII)."""

import unicodedata
from typing import Optional

import cv2

from station.sessao import Estado, SessaoEstacao

# Cores em BGR
VERDE = (90, 200, 70)
VERMELHO = (60, 60, 230)
AMARELO = (0, 200, 255)
ROSA = (91, 20, 237)
BRANCO = (240, 240, 240)
CINZA = (160, 160, 160)
PRETO = (0, 0, 0)

FONTE = cv2.FONT_HERSHEY_SIMPLEX
NOMES_ESTADO = {
    Estado.PRONTO: "PRONTO - inicie a serie",
    Estado.EM_SERIE: "EM SERIE",
    Estado.DESCANSO: "DESCANSO",
}


def ascii_(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()


def escrever(frame, texto, pos, escala=0.6, cor=BRANCO, espessura=1):
    texto = ascii_(texto)
    cv2.putText(frame, texto, pos, FONTE, escala, PRETO, espessura + 3, cv2.LINE_AA)
    cv2.putText(frame, texto, pos, FONTE, escala, cor, espessura, cv2.LINE_AA)


def escurecer(frame, x0, y0, x1, y1, opacidade=0.6):
    trecho = frame[y0:y1, x0:x1]
    frame[y0:y1, x0:x1] = cv2.addWeighted(trecho, 1 - opacidade, trecho * 0, opacidade, 0)


def desenhar(
    frame,
    sessao: SessaoEstacao,
    *,
    mqtt_ok: bool,
    rfid_ok: bool,
    angulo: Optional[float],
    aviso: str = "",
    cor_aviso=BRANCO,
):
    altura, largura = frame.shape[:2]

    # ── Barra superior: estação + indicador Livre/Ocupada + conexões ──
    escurecer(frame, 0, 0, largura, 64, 0.7)
    cor_status = VERMELHO if sessao.ocupada else VERDE
    cv2.circle(frame, (32, 32), 16, cor_status, -1, cv2.LINE_AA)
    escrever(frame, "OCUPADA" if sessao.ocupada else "LIVRE", (58, 42), 0.9, cor_status, 2)
    escrever(frame, f"{sessao.estacao_nome} | {sessao.exercicio}", (230, 40), 0.65, BRANCO, 1)
    escrever(frame, f"MQTT {'ON' if mqtt_ok else 'OFF'}", (largura - 270, 40), 0.6, VERDE if mqtt_ok else VERMELHO, 2)
    escrever(frame, f"RFID {'ON' if rfid_ok else 'TECLADO'}", (largura - 140, 40), 0.6, VERDE if rfid_ok else AMARELO, 2)

    if not sessao.ocupada:
        escurecer(frame, 0, 64, largura, altura, 0.55)
        escrever(frame, "SMART GYM", (largura // 2 - 170, altura // 2 - 40), 2.0, ROSA, 4)
        escrever(frame, "Aproxime o cartao RFID para iniciar o treino",
                 (largura // 2 - 330, altura // 2 + 30), 0.8, BRANCO, 2)
    else:
        # ── Painel do aluno ──
        escurecer(frame, 0, 64, 430, 300, 0.55)
        escrever(frame, sessao.aluno["nome"], (20, 105), 0.9, ROSA, 2)
        escrever(frame, f"Plano: {sessao.aluno.get('plano', '-')}", (20, 138), 0.55, CINZA)
        escrever(frame, f"Estado: {NOMES_ESTADO[sessao.estado]}", (20, 175), 0.6, BRANCO, 1)
        if sessao.estado == Estado.EM_SERIE:
            escrever(frame, f"Serie atual: {sessao.serie_atual}", (20, 205), 0.6, BRANCO)
        else:
            escrever(frame, f"Series concluidas: {sessao.serie_atual}", (20, 205), 0.6, BRANCO)
        if angulo is not None:
            escrever(frame, f"Cotovelo: {angulo:.0f} graus", (20, 235), 0.6, AMARELO)

        restante = sessao.descanso_restante_s()
        if restante is not None:
            if restante > 0:
                escrever(frame, f"Descanso: {restante:.0f}s (sugerido {sessao.descanso_sugerido_s}s)", (20, 270), 0.6, AMARELO, 2)
            else:
                escrever(frame, "Descanso concluido - pode iniciar", (20, 270), 0.6, VERDE, 2)

        # ── Contador grande de repetições ──
        escurecer(frame, largura - 260, 64, largura, 260, 0.55)
        escrever(frame, "REPS", (largura - 230, 105), 0.8, CINZA, 2)
        escrever(frame, str(sessao.repeticoes_serie), (largura - 230, 205), 3.2, BRANCO, 6)
        if sessao.incompletas_serie:
            escrever(frame, f"+{sessao.incompletas_serie} incompletas", (largura - 230, 245), 0.55, AMARELO)

        # ── Resumo da última série publicada ──
        perf = sessao.ultima_performance
        if perf:
            escurecer(frame, 0, altura - 120, largura, altura - 40, 0.55)
            escrever(frame, f"Ultima serie ({perf['serie']}): {perf['repeticoes']} reps | "
                            f"cadencia {perf['cadencia_media_s']}s | fadiga: {'sim' if perf['fadiga'] else 'nao'}",
                     (20, altura - 88), 0.6, BRANCO)
            if perf["alertas"]:
                escrever(frame, perf["alertas"][0], (20, altura - 58), 0.55, AMARELO)

    if aviso:
        largura_txt = cv2.getTextSize(ascii_(aviso), FONTE, 0.8, 2)[0][0]
        x = max(10, (largura - largura_txt) // 2)
        escurecer(frame, x - 20, altura // 2 + 70, x + largura_txt + 20, altura // 2 + 120, 0.75)
        escrever(frame, aviso, (x, altura // 2 + 105), 0.8, cor_aviso, 2)

    escurecer(frame, 0, altura - 32, largura, altura, 0.7)
    escrever(frame, "[1-3] cartao simulado  [0] cartao desconhecido  [ESPACO] rep  [I] rep incompleta  "
                    "[F] fim da serie  [L] logout  [Q] sair", (12, altura - 11), 0.45, CINZA)
