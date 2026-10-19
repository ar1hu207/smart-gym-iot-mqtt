"""
Leitura do RFID (Arduino/ESP32 + MFRC522) pela porta serial.

Protocolo (115200 baud, uma mensagem por linha):
    placa  -> Python : "UID:A1:B2:C3:D4"
    Python -> placa  : "LIVRE" | "OCUPADA" | "NEGADO" | "SERIE"   (LEDs e buzzer)

Também aceita o formato do Checkpoint 01 ("ACESSO_LIBERADO:<uid>"), para
reaproveitar o firmware antigo.
"""

import re
import threading
import time
from typing import Callable, Optional

import serial
import serial.tools.list_ports

PREFIXOS = ("UID:", "RFID:", "ACESSO_LIBERADO:", "ACESSO_NEGADO:")
PALAVRAS_PLACA = ("arduino", "ch340", "ch910", "cp210", "silicon labs", "wch", "usb serial", "usb-serial", "ftdi")


def normalizar_uid(texto: str) -> Optional[str]:
    """'a1 b2 c3 d4' / 'A1B2C3D4' / 'A1:B2:C3:D4' -> 'A1:B2:C3:D4'."""
    hexa = re.sub(r"[^0-9A-Fa-f]", "", texto).upper()
    if len(hexa) < 8 or len(hexa) % 2:
        return None
    return ":".join(hexa[i:i + 2] for i in range(0, len(hexa), 2))


def interpretar_linha(linha: str) -> Optional[str]:
    """Extrai o UID de uma linha recebida da placa. Linhas de log retornam None."""
    linha = linha.strip()
    for prefixo in PREFIXOS:
        if linha.upper().startswith(prefixo):
            return normalizar_uid(linha[len(prefixo):])
    return None


def detectar_porta() -> Optional[str]:
    """Procura uma porta com cara de Arduino/ESP32 (CH340, CP210x, FTDI...)."""
    for porta in serial.tools.list_ports.comports():
        descricao = f"{porta.description} {porta.manufacturer or ''}".lower()
        if any(palavra in descricao for palavra in PALAVRAS_PLACA):
            return porta.device
    return None


class LeitorRFID:
    def __init__(self, porta: str, baud: int, ao_ler: Callable[[str], None], log: Callable[[str], None] = print):
        self.porta = porta
        self.baud = baud
        self._ao_ler = ao_ler
        self._log = log
        self._serial: Optional[serial.Serial] = None
        self._lock_escrita = threading.Lock()
        self._ativo = False
        self._thread: Optional[threading.Thread] = None

    @property
    def ativo(self) -> bool:
        return self._ativo

    def iniciar(self) -> bool:
        try:
            self._serial = serial.Serial(self.porta, self.baud, timeout=0.2)
        except serial.SerialException as erro:
            self._log(f"[RFID] Não foi possível abrir {self.porta}: {erro}")
            return False
        time.sleep(2)  # o Arduino Uno reinicia ao abrir a serial
        self._serial.reset_input_buffer()
        self._ativo = True
        self._thread = threading.Thread(target=self._loop, name="leitor-rfid", daemon=True)
        self._thread.start()
        self._log(f"[RFID] Leitor conectado em {self.porta} ({self.baud} baud)")
        return True

    def enviar(self, comando: str) -> None:
        """Envia um comando de sinalização para a placa (LEDs/buzzer)."""
        if not self._ativo:
            return
        try:
            with self._lock_escrita:
                self._serial.write((comando + "\n").encode("ascii"))
        except serial.SerialException as erro:
            self._log(f"[RFID] Falha ao enviar '{comando}': {erro}")

    def parar(self) -> None:
        self._ativo = False
        if self._serial:
            self._serial.close()

    def _loop(self) -> None:
        while self._ativo:
            try:
                bruto = self._serial.readline()
            except (serial.SerialException, OSError) as erro:
                self._log(f"[RFID] Conexão serial perdida: {erro}")
                self._ativo = False
                break
            if not bruto:
                continue
            linha = bruto.decode("utf-8", errors="ignore").strip()
            uid = interpretar_linha(linha)
            if uid:
                self._log(f"[RFID] Cartão lido: {uid}")
                self._ao_ler(uid)
            elif linha:
                self._log(f"[Placa] {linha}")
