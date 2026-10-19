"""
Visão computacional: MediaPipe Pose -> ângulo do cotovelo.

Usa o braço mais visível para a câmera (a imagem é espelhada, então "direito"
e "esquerdo" não importam para a contagem).
"""

from dataclasses import dataclass
from typing import Any, Optional, Tuple

import cv2
import numpy as np

VISIBILIDADE_MINIMA = 0.5


def calcular_angulo(a, b, c) -> float:
    """Ângulo em graus no vértice `b` formado pelos pontos a-b-c."""
    a, b, c = np.array(a, dtype=float), np.array(b, dtype=float), np.array(c, dtype=float)
    ba, bc = a - b, c - b
    cosseno = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    return float(np.degrees(np.arccos(np.clip(cosseno, -1.0, 1.0))))


@dataclass
class LeituraPose:
    angulo: Optional[float]                 # None se o braço não estiver visível
    cotovelo_px: Optional[Tuple[int, int]]
    resultado: Any                          # resultado bruto do MediaPipe (para desenhar)


class DetectorPose:
    def __init__(self, complexidade: int = 1):
        import mediapipe as mp  # importado aqui para o modo --sem-camera não exigir MediaPipe

        self._mp_pose = mp.solutions.pose
        self._desenho = mp.solutions.drawing_utils
        self._estilos = mp.solutions.drawing_styles
        self._pose = self._mp_pose.Pose(
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6,
            model_complexity=complexidade,
        )
        marco = self._mp_pose.PoseLandmark
        self._bracos = (
            (marco.RIGHT_SHOULDER, marco.RIGHT_ELBOW, marco.RIGHT_WRIST),
            (marco.LEFT_SHOULDER, marco.LEFT_ELBOW, marco.LEFT_WRIST),
        )

    def processar(self, frame_bgr) -> Optional[LeituraPose]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        resultado = self._pose.process(rgb)
        if not resultado.pose_landmarks:
            return None

        marcos = resultado.pose_landmarks.landmark
        altura, largura = frame_bgr.shape[:2]
        braco = max(self._bracos, key=lambda ids: min(marcos[i].visibility for i in ids))
        if min(marcos[i].visibility for i in braco) < VISIBILIDADE_MINIMA:
            return LeituraPose(None, None, resultado)

        ombro, cotovelo, pulso = ((marcos[i].x * largura, marcos[i].y * altura) for i in braco)
        return LeituraPose(
            angulo=calcular_angulo(ombro, cotovelo, pulso),
            cotovelo_px=(int(cotovelo[0]), int(cotovelo[1])),
            resultado=resultado,
        )

    def desenhar(self, frame_bgr, leitura: LeituraPose) -> None:
        self._desenho.draw_landmarks(
            frame_bgr,
            leitura.resultado.pose_landmarks,
            self._mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=self._estilos.get_default_pose_landmarks_style(),
        )

    def fechar(self) -> None:
        self._pose.close()
