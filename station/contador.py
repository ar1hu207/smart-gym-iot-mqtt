"""
Contador de repetições baseado no ângulo do cotovelo (ombro-cotovelo-pulso).

É uma máquina de estados pequena e independente do MediaPipe, para poder ser
testada com sequências de ângulos sintéticas:

    AGUARDANDO_EXTENSAO --(ângulo > EXTENSAO)--> ESTENDIDO
    ESTENDIDO           --(ângulo < INICIO_MOV)--> EM_MOVIMENTO
    EM_MOVIMENTO        --(ângulo > EXTENSAO)--> ESTENDIDO  => conta 1 repetição

Ao fechar o ciclo, a repetição é "completa" se o menor ângulo atingido chegou
à flexão total (<= FLEXAO). Caso contrário é "incompleta" (amplitude parcial,
um dos fatores de qualidade do treino descritos no enunciado).
"""

from dataclasses import dataclass
from typing import Optional

from station import config

AGUARDANDO_EXTENSAO = "AGUARDANDO_EXTENSAO"
ESTENDIDO = "ESTENDIDO"
EM_MOVIMENTO = "EM_MOVIMENTO"


@dataclass
class Repeticao:
    completa: bool
    duracao_s: float
    menor_angulo: float


class ContadorRepeticoes:
    def __init__(
        self,
        angulo_extensao: float = config.ANGULO_EXTENSAO,
        angulo_inicio_mov: float = config.ANGULO_INICIO_MOV,
        angulo_flexao: float = config.ANGULO_FLEXAO,
    ):
        if not angulo_flexao < angulo_inicio_mov < angulo_extensao:
            raise ValueError("Esperado: flexao < inicio_mov < extensao")
        self.angulo_extensao = angulo_extensao
        self.angulo_inicio_mov = angulo_inicio_mov
        self.angulo_flexao = angulo_flexao
        self.reiniciar()

    def reiniciar(self) -> None:
        self.fase = AGUARDANDO_EXTENSAO
        self._inicio_mov: Optional[float] = None
        self._menor_angulo = 180.0

    def atualizar(self, angulo: float, instante: float) -> Optional[Repeticao]:
        """Recebe o ângulo atual do cotovelo. Retorna uma Repeticao quando um ciclo fecha."""
        if self.fase == AGUARDANDO_EXTENSAO:
            if angulo > self.angulo_extensao:
                self.fase = ESTENDIDO

        elif self.fase == ESTENDIDO:
            if angulo < self.angulo_inicio_mov:
                self.fase = EM_MOVIMENTO
                self._inicio_mov = instante
                self._menor_angulo = angulo

        elif self.fase == EM_MOVIMENTO:
            self._menor_angulo = min(self._menor_angulo, angulo)
            if angulo > self.angulo_extensao:
                self.fase = ESTENDIDO
                return Repeticao(
                    completa=self._menor_angulo <= self.angulo_flexao,
                    duracao_s=round(instante - self._inicio_mov, 2),
                    menor_angulo=round(self._menor_angulo, 1),
                )
        return None
