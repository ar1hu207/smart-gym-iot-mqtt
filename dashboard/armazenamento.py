"""
Histórico de séries em SQLite (biblioteca padrão), para o log sobreviver a um
reinício do dashboard. O `id` gerado pela estação evita duplicatas quando o
QoS 1 entrega a mesma mensagem mais de uma vez.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List

ESQUEMA = """
CREATE TABLE IF NOT EXISTS series (
    id                      TEXT PRIMARY KEY,
    recebido_em             TEXT NOT NULL,
    ts                      TEXT NOT NULL,
    estacao_id              TEXT NOT NULL,
    estacao_nome            TEXT,
    exercicio               TEXT,
    aluno                   TEXT NOT NULL,
    serie                   INTEGER,
    repeticoes              INTEGER NOT NULL,
    repeticoes_incompletas  INTEGER DEFAULT 0,
    duracao_s               REAL,
    cadencia_media_s        REAL,
    fadiga                  INTEGER DEFAULT 0,
    descanso_sugerido_s     INTEGER,
    alertas                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_series_ts ON series (ts);
"""

COLUNAS = (
    "id", "recebido_em", "ts", "estacao_id", "estacao_nome", "exercicio", "aluno", "serie", "repeticoes",
    "repeticoes_incompletas", "duracao_s", "cadencia_media_s", "fadiga", "descanso_sugerido_s", "alertas",
)


class Armazenamento:
    def __init__(self, caminho: Path):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._con.executescript(ESQUEMA)

    def salvar_serie(self, p: dict) -> bool:
        """Insere a série. Retorna False se o id já existia (mensagem duplicada)."""
        linha = {
            **{coluna: p.get(coluna) for coluna in COLUNAS},
            "id": p.get("id") or f"{p.get('estacao_id')}-{p.get('ts')}-{p.get('serie')}",
            "recebido_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ts": p.get("ts") or datetime.now().astimezone().isoformat(timespec="seconds"),
            "fadiga": int(bool(p.get("fadiga"))),
            "alertas": " | ".join(p.get("alertas") or []),
        }
        with self._lock:
            cursor = self._con.execute(
                f"INSERT OR IGNORE INTO series ({', '.join(COLUNAS)}) VALUES ({', '.join('?' * len(COLUNAS))})",
                [linha[c] for c in COLUNAS],
            )
            self._con.commit()
            return cursor.rowcount == 1

    def recentes(self, limite: int = 50) -> List[dict]:
        with self._lock:
            linhas = self._con.execute("SELECT * FROM series ORDER BY ts DESC, recebido_em DESC LIMIT ?", (limite,)).fetchall()
        return [self._para_dict(l) for l in linhas]

    def resumo_do_dia(self) -> dict:
        hoje = datetime.now().astimezone().date().isoformat()
        with self._lock:
            l = self._con.execute(
                "SELECT COUNT(*) AS series, COALESCE(SUM(repeticoes), 0) AS repeticoes, "
                "COUNT(DISTINCT aluno) AS alunos FROM series WHERE substr(ts, 1, 10) = ?",
                (hoje,),
            ).fetchone()
        return {"series": l["series"], "repeticoes": l["repeticoes"], "alunos": l["alunos"]}

    @staticmethod
    def _para_dict(linha: sqlite3.Row) -> dict:
        d = dict(linha)
        d["fadiga"] = bool(d["fadiga"])
        d["alertas"] = [a for a in (d["alertas"] or "").split(" | ") if a]
        return d
