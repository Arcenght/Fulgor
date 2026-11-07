"""Testes da lógica (sem FastAPI): python -m tests.test_db"""
import os
import sqlite3
import tempfile
from datetime import date

from app import db, tokens


def novo(nome="t.db"):
    c = db.conectar(os.path.join(tempfile.mkdtemp(), nome))
    db.iniciar(c)
    return c


conn = novo()
db.iniciar(conn)  # idempotente: não duplica as áreas iniciais
areas = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM area ORDER BY id")}
assert list(areas) == ["Projeto", "Páginas lidas", "Exercício"], areas


def add(nome, data, valor=1):
    conn.execute("INSERT INTO evento (area_id, data, valor) VALUES (?,?,?)", (areas[nome], data, valor))
    conn.commit()


def dia(nome, data):
    ano = int(data[:4])
    cal = db.calendario(conn, areas[nome], date(ano, 1, 1), date(ano, 12, 31))
    return next(d for d in cal["dias"] if d["data"] == data)


# Páginas: faixas 1-24 / 25-49 / 50-74 / 75+
for data, paginas, esperado in [
    ("2026-03-01", 10, 1), ("2026-03-02", 24, 1), ("2026-03-03", 25, 2),
    ("2026-03-04", 49, 2), ("2026-03-05", 50, 3), ("2026-03-06", 74, 3),
    ("2026-03-07", 75, 4), ("2026-03-08", 300, 4),
]:
    add("Páginas lidas", data, paginas)
    assert dia("Páginas lidas", data)["nivel"] == esperado, (data, paginas)

add("Páginas lidas", "2026-03-10", 20); add("Páginas lidas", "2026-03-10", 10)
d = dia("Páginas lidas", "2026-03-10")
assert (d["contagem"], d["total"], d["nivel"]) == (2, 30, 2), d

add("Projeto", "2026-03-01", 1.5); add("Projeto", "2026-03-01", 2)
d = dia("Projeto", "2026-03-01")
assert (d["contagem"], d["total"], d["nivel"]) == (2, 3.5, 4), d

add("Exercício", "2026-03-01")
assert dia("Exercício", "2026-03-01")["nivel"] == 4
assert dia("Exercício", "2026-03-02")["nivel"] == 0

# Intervalos
assert len(db.calendario(conn, areas["Projeto"], date(2026, 1, 1), date(2026, 12, 31))["dias"]) == 365
assert len(db.calendario(conn, areas["Projeto"], date(2028, 1, 1), date(2028, 12, 31))["dias"]) == 366
assert db.calendario(conn, 999, date(2026, 1, 1), date(2026, 1, 2)) is None

# Janela rolante: começa num domingo, 53 colunas, termina em "hoje"
hoje = date(2026, 11, 7)  # sábado
ini, fim = db.janela_rolante(hoje)
assert (ini, fim) == (date(2025, 11, 2), hoje) and ini.weekday() == 6
dias = db.calendario(conn, areas["Projeto"], ini, fim)["dias"]
assert len(dias) == 371 and dias[0]["data"] == "2025-11-02" and dias[-1]["data"] == "2026-11-07"
dom = date(2026, 11, 8)  # domingo: última coluna tem 1 dia
ini, fim = db.janela_rolante(dom)
assert ini == date(2025, 11, 9) and ini.weekday() == 6 and (fim - ini).days + 1 == 365

# Valor inválido e remoção em cascata
try:
    conn.execute("INSERT INTO evento (area_id, data, valor) VALUES (?,?,?)", (areas["Projeto"], "2026-04-01", 0))
    raise SystemExit("deveria rejeitar valor 0")
except sqlite3.IntegrityError:
    pass
conn.execute("DELETE FROM area WHERE id = ?", (areas["Projeto"],)); conn.commit()
assert conn.execute("SELECT COUNT(*) FROM evento WHERE area_id = ?", (areas["Projeto"],)).fetchone()[0] == 0

# Tokens por dispositivo
t = tokens.criar(conn, "celular")
assert tokens.validar(conn, t) == "celular"
assert tokens.validar(conn, "errado") is None
assert t not in str([tuple(r) for r in conn.execute("SELECT * FROM dispositivo")])  # só o hash é guardado
t2 = tokens.criar(conn, "esp32-bancada")
assert tokens.validar(conn, t2) == "esp32-bancada" and tokens.validar(conn, t) == "celular"
try:
    tokens.criar(conn, "celular")
    raise SystemExit("deveria rejeitar nome ativo repetido")
except sqlite3.IntegrityError:
    pass
assert tokens.revogar(conn, "celular") is True
assert tokens.validar(conn, t) is None and tokens.validar(conn, t2) == "esp32-bancada"
assert tokens.revogar(conn, "celular") is False
t3 = tokens.criar(conn, "celular")  # nome liberado após revogar
assert tokens.validar(conn, t3) == "celular" and tokens.validar(conn, t) is None

# Migração de banco antigo (sem origem/criado_em) preserva os dados
p = os.path.join(tempfile.mkdtemp(), "old.db")
old = sqlite3.connect(p)
old.executescript("""
CREATE TABLE area (id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, tipo TEXT NOT NULL, unidade TEXT, limites TEXT, cor TEXT NOT NULL DEFAULT '#216e39');
CREATE TABLE evento (id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, data TEXT NOT NULL, valor REAL NOT NULL DEFAULT 1, nota TEXT);
INSERT INTO area (nome, tipo) VALUES ('X', 'booleano');
INSERT INTO evento (area_id, data) VALUES (1, '2026-01-01');
""")
old.commit(); old.close()
c2 = db.conectar(p); db.iniciar(c2)
assert {"origem", "criado_em"} <= {r["name"] for r in c2.execute("PRAGMA table_info(evento)")}
assert c2.execute("SELECT COUNT(*) FROM evento").fetchone()[0] == 1

print("todos os testes passaram")