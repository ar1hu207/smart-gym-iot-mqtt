/*
 * Smart Gym - Estação de Treino | Leitor RFID (Checkpoint 05)
 * FIAP - Physical Computing (IoT & IoB)
 *
 * Função da placa: ler o cartão MIFARE com o MFRC522, enviar o UID para o
 * script Python (que valida o aluno e publica no MQTT) e sinalizar o estado
 * da máquina com LEDs e buzzer.
 *
 * Protocolo serial (115200 baud, uma mensagem por linha):
 *   Placa  -> Python : "UID:A1:B2:C3:D4"
 *   Python -> Placa  : "LIVRE"   -> LED verde aceso
 *                      "OCUPADA" -> LED vermelho aceso
 *                      "NEGADO"  -> pisca vermelho + 2 bipes curtos
 *                      "SERIE"   -> bipe longo (série concluída e publicada)
 *
 * Funciona em Arduino Uno/Nano e em ESP32 (os pinos mudam pelo #if abaixo).
 * Biblioteca necessária: MFRC522 (miguelbalboa) - Arduino IDE > Gerenciar Bibliotecas.
 */

#include <SPI.h>
#include <MFRC522.h>

#if defined(ESP32)
// ESP32 DevKit: SPI padrão SCK=18, MISO=19, MOSI=23
const uint8_t PINO_SS = 5;
const uint8_t PINO_RST = 22;
const uint8_t PINO_LED_VERDE = 25;
const uint8_t PINO_LED_VERMELHO = 26;
const uint8_t PINO_BUZZER = 27;
#else
// Arduino Uno/Nano: SPI padrão SCK=13, MISO=12, MOSI=11
const uint8_t PINO_SS = 10;
const uint8_t PINO_RST = 9;
const uint8_t PINO_LED_VERDE = 6;
const uint8_t PINO_LED_VERMELHO = 7;
const uint8_t PINO_BUZZER = 8;
#endif

const unsigned long BAUD = 115200;
const unsigned long JANELA_REPETICAO_MS = 2000;  // ignora o mesmo cartão parado no leitor

MFRC522 rfid(PINO_SS, PINO_RST);

String ultimoUid = "";
unsigned long instanteUltimoUid = 0;
bool ocupada = false;
String bufferSerial = "";

// ─── Sinalização ───────────────────────────────────────────────
void bip(unsigned int duracaoMs) {
  digitalWrite(PINO_BUZZER, HIGH);
  delay(duracaoMs);
  digitalWrite(PINO_BUZZER, LOW);
}

void mostrarEstado() {
  digitalWrite(PINO_LED_VERDE, ocupada ? LOW : HIGH);
  digitalWrite(PINO_LED_VERMELHO, ocupada ? HIGH : LOW);
}

void sinalizarNegado() {
  digitalWrite(PINO_LED_VERDE, LOW);
  for (int i = 0; i < 3; i++) {
    digitalWrite(PINO_LED_VERMELHO, HIGH);
    if (i < 2) bip(70); else delay(70);
    delay(90);
    digitalWrite(PINO_LED_VERMELHO, LOW);
    delay(90);
  }
  mostrarEstado();
}

// ─── Comandos vindos do Python ─────────────────────────────────
void processarComando(String comando) {
  comando.trim();
  comando.toUpperCase();
  if (comando == "LIVRE") {
    ocupada = false;
    mostrarEstado();
  } else if (comando == "OCUPADA") {
    ocupada = true;
    mostrarEstado();
  } else if (comando == "NEGADO") {
    sinalizarNegado();
  } else if (comando == "SERIE") {
    bip(350);
  }
}

void lerComandos() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      processarComando(bufferSerial);
      bufferSerial = "";
    } else if (c != '\r' && bufferSerial.length() < 32) {
      bufferSerial += c;
    }
  }
}

// ─── Leitura do cartão ─────────────────────────────────────────
String uidParaTexto(const MFRC522::Uid &uid) {
  String texto = "";
  for (byte i = 0; i < uid.size; i++) {
    if (i > 0) texto += ":";
    if (uid.uidByte[i] < 0x10) texto += "0";
    texto += String(uid.uidByte[i], HEX);
  }
  texto.toUpperCase();
  return texto;
}

void lerCartao() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

  String uid = uidParaTexto(rfid.uid);
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  unsigned long agora = millis();
  if (uid == ultimoUid && agora - instanteUltimoUid < JANELA_REPETICAO_MS) return;
  ultimoUid = uid;
  instanteUltimoUid = agora;

  bip(80);                    // bipe de leitura; o Python decide se libera ou nega
  Serial.print("UID:");
  Serial.println(uid);
}

void setup() {
  Serial.begin(BAUD);
  SPI.begin();
  rfid.PCD_Init();

  pinMode(PINO_LED_VERDE, OUTPUT);
  pinMode(PINO_LED_VERMELHO, OUTPUT);
  pinMode(PINO_BUZZER, OUTPUT);
  mostrarEstado();

  Serial.println("SMARTGYM_RFID_PRONTO");
}

void loop() {
  lerComandos();
  lerCartao();
}
