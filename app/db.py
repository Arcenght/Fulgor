"""Acesso ao SQLite e regras de cálculo do calendário (só biblioteca padrão)."""
import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get("HABITOS_DB", "habitos.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS area (
  id      INTEGER PRIMARY KEY,
  nome    TEXT NOT NULL UNIQUE,
  tipo    TEXT NOT NULL CHECK (tipo IN ('booleano', 'quantidade')),
  unidade TEXT,   -- 'h', 'páginas'... (opcional)
  limites TEXT,   -- JSON: 4 valores mínimos dos níveis 1..4 (só para 'quantidade')
  cor     TEXT NOT NULL DEFAULT '#216e39'
);

CREATE TABLE IF NOT EXISTS evento (
  id      INTEGER PRIMARY KEY,
  area_id INTEGER NOT NULL REFERENCES area(id) ON DELETE CASCADE,
  data    TEXT NOT NULL,                 -- 'YYYY-MM-DD'
  valor   REAL NOT NULL DEFAULT 1 CHECK (valor > 0),
  nota    TEXT
);

CREATE INDEX IF NOT EXISTS idx_evento_area_data ON evento(area_id, data);
"""

# Áreas iniciais. Para 'quantidade', limites = mínimo de cada nível 1..4:
# 1-24 -> nível 1, 25-49 -> 2, 50-74 -> 3, 75+ -> 4.
AREAS_INICIAIS = [
    ("Projeto", "booleano", "h", None, "#2f81f7"),
    ("Páginas lidas", "quantidade", "páginas", [1, 25, 50, 75], "#a371f7"),
    ("Exercício", "booleano", None, None, "#216e39"),
]


def conectar(path=None):
    conn = sqlite3.connect(str(path or DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def iniciar(conn):
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM area").fetchone()[0] == 0:
        for nome, tipo, unidade, limites, cor in AREAS_INICIAIS:
            conn.execute(
                "INSERT INTO area (nome, tipo, unidade, limites, cor) VALUES (?,?,?,?,?)",
                (nome, tipo, unidade, json.dumps(limites) if limites else None, cor),
            )
    conn.commit()


def area_para_dict(row):
    d = dict(row)
    d["limites"] = json.loads(d["limites"]) if d["limites"] else None
    return d


def calcular_nivel(area, contagem, total):
    """Nível 0..4 de um dia. `area` é o dict de área, `contagem` = nº de registros, `total` = soma dos valores."""
    if contagem == 0:
        return 0
    if area["tipo"] == "booleano":
        return 4
    atingidos = sum(1 for minimo in (area["limites"] or []) if total >= minimo)
    return max(1, atingidos)  # qualquer registro aparece pelo menos como nível 1


def calendario(conn, area_id, ano):
    """Todos os dias do ano com contagem, total e nível. None se a área não existe."""
    row = conn.execute("SELECT * FROM area WHERE id = ?", (area_id,)).fetchone()
    if row is None:
        return None
    area = area_para_dict(row)
    rows = conn.execute(
        "SELECT data, COUNT(*) AS c, SUM(valor) AS t FROM evento "
        "WHERE area_id = ? AND data BETWEEN ? AND ? GROUP BY data",
        (area_id, f"{ano}-01-01", f"{ano}-12-31"),
    ).fetchall()
    por_dia = {r["data"]: (r["c"], r["t"]) for r in rows}

    dias, d = [], date(ano, 1, 1)
    while d.year == ano:
        iso = d.isoformat()
        contagem, total = por_dia.get(iso, (0, 0))
        dias.append({"data": iso, "contagem": contagem, "total": total,
                     "nivel": calcular_nivel(area, contagem, total)})
        d += timedelta(days=1)
    return {"area": area, "ano": ano, "dias": dias}
