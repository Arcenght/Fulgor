"""Acesso ao SQLite e regras de cálculo do calendário (só biblioteca padrão)."""
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("HABITOS_DB", "data/habitos.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS area (
  id      INTEGER PRIMARY KEY,
  nome    TEXT NOT NULL UNIQUE,
  tipo    TEXT NOT NULL CHECK (tipo IN ('booleano', 'quantidade')),
  unidade TEXT,   -- 'h', 'páginas'... (opcional)
  limites TEXT,   -- JSON: 4 valores mínimos dos níveis 1..4 (só para 'quantidade')
  cor     TEXT NOT NULL DEFAULT '#216e39'
);

-- Só eventos são guardados; contagem e nível são calculados na leitura.
CREATE TABLE IF NOT EXISTS evento (
  id        INTEGER PRIMARY KEY,
  area_id   INTEGER NOT NULL REFERENCES area(id) ON DELETE CASCADE,
  data      TEXT NOT NULL,                 -- dia local, 'YYYY-MM-DD'
  valor     REAL NOT NULL DEFAULT 1 CHECK (valor > 0),
  nota      TEXT,
  origem    TEXT,                          -- nome do dispositivo que registrou
  criado_em TEXT                           -- UTC, ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_evento_area_data ON evento(area_id, data);

CREATE TABLE IF NOT EXISTS dispositivo (
  id          INTEGER PRIMARY KEY,
  nome        TEXT NOT NULL,
  token_hash  TEXT NOT NULL UNIQUE,        -- SHA-256 do token; o token em si não é guardado
  criado_em   TEXT NOT NULL,
  revogado_em TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dispositivo_ativo ON dispositivo(nome) WHERE revogado_em IS NULL;

-- Histórico de criação/edição/remoção de áreas e dispositivos (antes/depois em JSON).
-- Ao remover uma área, 'antes' guarda também todos os eventos dela.
CREATE TABLE IF NOT EXISTS historico (
  id          INTEGER PRIMARY KEY,
  entidade    TEXT NOT NULL CHECK (entidade IN ('area', 'dispositivo')),
  entidade_id INTEGER NOT NULL,
  acao        TEXT NOT NULL CHECK (acao IN ('criar', 'editar', 'remover')),
  antes       TEXT,
  depois      TEXT,
  origem      TEXT,
  em          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_historico_entidade ON historico(entidade, entidade_id);
"""

# Para 'quantidade', limites = mínimo de cada nível 1..4:
# 1-24 -> nível 1, 25-49 -> 2, 50-74 -> 3, 75+ -> 4.
AREAS_INICIAIS = [
    ("Projeto", "booleano", "h", None, "#2f81f7"),
    ("Páginas lidas", "quantidade", "páginas", [1, 25, 50, 75], "#a371f7"),
    ("Exercício", "booleano", None, None, "#216e39"),
]

DISPOSITIVOS_INICIAIS = ["pc1", "pc2", "celular"]


def conectar(path=None):
    destino = Path(path or DB_PATH)
    destino.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(destino), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def iniciar(conn):
    conn.executescript(SCHEMA)
    # Migração de bancos criados antes dessas colunas existirem.
    colunas = {r["name"] for r in conn.execute("PRAGMA table_info(evento)")}
    for col in ("origem", "criado_em"):
        if col not in colunas:
            conn.execute(f"ALTER TABLE evento ADD COLUMN {col} TEXT")
    if conn.execute("SELECT COUNT(*) FROM area").fetchone()[0] == 0:
        for nome, tipo, unidade, limites, cor in AREAS_INICIAIS:
            conn.execute(
                "INSERT INTO area (nome, tipo, unidade, limites, cor) VALUES (?,?,?,?,?)",
                (nome, tipo, unidade, json.dumps(limites) if limites else None, cor),
            )
    if conn.execute("SELECT COUNT(*) FROM dispositivo").fetchone()[0] == 0:
        for nome in DISPOSITIVOS_INICIAIS:  # a página não precisa do token; para API/ESP32 crie um dispositivo em "Gerenciar"
            conn.execute("INSERT INTO dispositivo (nome, token_hash, criado_em) VALUES (?,?,?)",
                         (nome, hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(),
                          datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()


def log(conn, entidade, entidade_id, acao, antes, depois, origem):
    """Registra uma alteração no histórico (o commit fica por conta de quem chama)."""
    conn.execute(
        "INSERT INTO historico (entidade, entidade_id, acao, antes, depois, origem, em) VALUES (?,?,?,?,?,?,?)",
        (entidade, entidade_id, acao,
         None if antes is None else json.dumps(antes, ensure_ascii=False),
         None if depois is None else json.dumps(depois, ensure_ascii=False),
         origem, datetime.now(timezone.utc).isoformat(timespec="seconds")))


def area_para_dict(row):
    d = dict(row)
    d["limites"] = json.loads(d["limites"]) if d["limites"] else None
    return d


def calcular_nivel(area, contagem, total):
    """Nível 0..4 de um dia. `contagem` = nº de registros, `total` = soma dos valores."""
    if contagem == 0:
        return 0
    if area["tipo"] == "booleano":
        return 4
    atingidos = sum(1 for minimo in (area["limites"] or []) if total >= minimo)
    return max(1, atingidos)  # qualquer registro aparece pelo menos como nível 1


def janela_rolante(hoje):
    """Como no GitHub: 53 colunas de semana (domingo a sábado) terminando em `hoje`."""
    domingo = hoje - timedelta(days=(hoje.weekday() + 1) % 7)
    return domingo - timedelta(weeks=52), hoje


def calendario(conn, area_id, inicio, fim):
    """Dias de `inicio` a `fim` (inclusive, objetos date) com contagem, total e nível."""
    row = conn.execute("SELECT * FROM area WHERE id = ?", (area_id,)).fetchone()
    if row is None:
        return None
    area = area_para_dict(row)
    rows = conn.execute(
        "SELECT data, COUNT(*) AS c, SUM(valor) AS t FROM evento "
        "WHERE area_id = ? AND data BETWEEN ? AND ? GROUP BY data",
        (area_id, inicio.isoformat(), fim.isoformat()),
    ).fetchall()
    por_dia = {r["data"]: (r["c"], r["t"]) for r in rows}

    dias, d = [], inicio
    while d <= fim:
        iso = d.isoformat()
        contagem, total = por_dia.get(iso, (0, 0))
        dias.append({"data": iso, "contagem": contagem, "total": total,
                     "nivel": calcular_nivel(area, contagem, total)})
        d += timedelta(days=1)
    return {"area": area, "dias": dias}