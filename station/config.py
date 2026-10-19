"""Parâmetros da estação de treino (publisher). Sobrescreva pelo .env."""

import os
from pathlib import Path

import shared.config  # noqa: F401  (garante que o .env foi carregado)

PASTA_ESTACAO = Path(__file__).resolve().parent

# ─── Identificação da estação ────────────────────────────────────
ESTACAO_ID = os.getenv("ESTACAO_ID", "estacao-01")
ESTACAO_NOME = os.getenv("ESTACAO_NOME", "Estação 01")
EXERCICIO = os.getenv("EXERCICIO", "Rosca direta")

# ─── Hardware ────────────────────────────────────────────────────
SERIAL_PORTA = os.getenv("SERIAL_PORTA") or None   # None = detecção automática
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
CAMERA_INDICE = int(os.getenv("CAMERA_INDICE", "0"))
ARQUIVO_ALUNOS = Path(os.getenv("ARQUIVO_ALUNOS", PASTA_ESTACAO / "alunos.json"))

# ─── Contagem de repetições (ângulo do cotovelo, em graus) ───────
ANGULO_EXTENSAO = float(os.getenv("ANGULO_EXTENSAO", "150"))     # braço estendido
ANGULO_INICIO_MOV = float(os.getenv("ANGULO_INICIO_MOV", "130"))  # começou a flexionar
ANGULO_FLEXAO = float(os.getenv("ANGULO_FLEXAO", "55"))           # flexão completa

# ─── Regras da sessão ────────────────────────────────────────────
# Sem nova repetição por esse tempo, a série é considerada concluída.
TEMPO_FIM_SERIE_S = float(os.getenv("TEMPO_FIM_SERIE_S", "6"))
# Sem atividade (nem repetição) por esse tempo, a estação faz logout sozinha.
TEMPO_INATIVIDADE_S = float(os.getenv("TEMPO_INATIVIDADE_S", "180"))
# Leituras repetidas do mesmo cartão dentro dessa janela são ignoradas.
JANELA_DEBOUNCE_RFID_S = float(os.getenv("JANELA_DEBOUNCE_RFID_S", "2.5"))
# Descanso sugerido entre séries (enunciado: 60 s a 90 s).
DESCANSO_MIN_S = int(os.getenv("DESCANSO_MIN_S", "60"))
DESCANSO_MAX_S = int(os.getenv("DESCANSO_MAX_S", "90"))
