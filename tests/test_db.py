"""Testes da lógica (sem FastAPI): python test_db.py"""
import tempfile, os
import db

path = os.path.join(tempfile.mkdtemp(), "t.db")
conn = db.conectar(path)
db.iniciar(conn)
db.iniciar(conn)  # idempotente: não duplica as áreas iniciais

areas = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM area ORDER BY id")}
assert list(areas) == ["Projeto", "Páginas lidas", "Exercício"], areas

def add(nome, data, valor=1):
    conn.execute("INSERT INTO evento (area_id, data, valor) VALUES (?,?,?)", (areas[nome], data, valor))
    conn.commit()

def dia(nome, data, ano=2026):
    cal = db.calendario(conn, areas[nome], ano)
    return next(d for d in cal["dias"] if d["data"] == data)

# Páginas: faixas 1-24 / 25-49 / 50-74 / 75+
for data, paginas, esperado in [
    ("2026-03-01", 10, 1), ("2026-03-02", 24, 1), ("2026-03-03", 25, 2),
    ("2026-03-04", 49, 2), ("2026-03-05", 50, 3), ("2026-03-06", 74, 3),
    ("2026-03-07", 75, 4), ("2026-03-08", 300, 4),
]:
    add("Páginas lidas", data, paginas)
    assert dia("Páginas lidas", data)["nivel"] == esperado, (data, paginas)

# Vários registros no mesmo dia somam: 20 + 10 = 30 -> nível 2
add("Páginas lidas", "2026-03-10", 20); add("Páginas lidas", "2026-03-10", 10)
d = dia("Páginas lidas", "2026-03-10")
assert (d["contagem"], d["total"], d["nivel"]) == (2, 30, 2), d

# Projeto: booleano, horas ficam em 'total', nível sempre 4 quando há registro
add("Projeto", "2026-03-01", 1.5); add("Projeto", "2026-03-01", 2)
d = dia("Projeto", "2026-03-01")
assert (d["contagem"], d["total"], d["nivel"]) == (2, 3.5, 4), d

# Exercício
add("Exercício", "2026-03-01")
assert dia("Exercício", "2026-03-01")["nivel"] == 4
assert dia("Exercício", "2026-03-02")["nivel"] == 0

# Estrutura do ano
assert len(db.calendario(conn, areas["Projeto"], 2026)["dias"]) == 365
assert len(db.calendario(conn, areas["Projeto"], 2028)["dias"]) == 366
assert db.calendario(conn, 999, 2026) is None

# Valor inválido e remoção em cascata
try:
    conn.execute("INSERT INTO evento (area_id, data, valor) VALUES (?,?,?)", (areas["Projeto"], "2026-04-01", 0))
    raise SystemExit("deveria rejeitar valor 0")
except Exception as e:
    assert "CHECK" in str(e) or "constraint" in str(e).lower()
conn.execute("DELETE FROM area WHERE id = ?", (areas["Projeto"],)); conn.commit()
assert conn.execute("SELECT COUNT(*) FROM evento WHERE area_id = ?", (areas["Projeto"],)).fetchone()[0] == 0

print("todos os testes passaram")
