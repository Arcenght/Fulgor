"""Tokens por dispositivo. Uso (a partir da raiz do projeto):

    python -m app.tokens criar celular     # mostra o token UMA vez
    python -m app.tokens listar
    python -m app.tokens revogar celular
"""
import hashlib
import secrets
import sqlite3
import sys
from datetime import datetime, timezone

from . import db


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def criar(conn, nome):
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO dispositivo (nome, token_hash, criado_em) VALUES (?,?,?)",
                 (nome, _hash(token), agora()))
    conn.commit()
    return token


def validar(conn, token):
    """Nome do dispositivo dono do token, ou None se inexistente/revogado."""
    row = conn.execute("SELECT nome FROM dispositivo WHERE token_hash = ? AND revogado_em IS NULL",
                       (_hash(token),)).fetchone()
    return row["nome"] if row else None


def revogar(conn, nome):
    cur = conn.execute("UPDATE dispositivo SET revogado_em = ? WHERE nome = ? AND revogado_em IS NULL",
                       (agora(), nome))
    conn.commit()
    return cur.rowcount > 0


def listar(conn):
    return [dict(r) for r in conn.execute(
        "SELECT nome, criado_em, revogado_em FROM dispositivo ORDER BY id")]


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    conn = db.conectar()
    db.iniciar(conn)
    if a[:1] == ["criar"] and len(a) == 2:
        try:
            print(f"Token de '{a[1]}' (guarde agora, ele não será mostrado de novo):\n{criar(conn, a[1])}")
        except sqlite3.IntegrityError:
            sys.exit(f"Já existe um dispositivo ativo chamado '{a[1]}'. Revogue-o antes ou use outro nome.")
    elif a[:1] == ["revogar"] and len(a) == 2:
        print("Revogado." if revogar(conn, a[1]) else f"Nenhum dispositivo ativo chamado '{a[1]}'.")
    elif a[:1] == ["listar"]:
        for d in listar(conn):
            print(f"{d['nome']:<20} criado {d['criado_em']}" + (f"  REVOGADO {d['revogado_em']}" if d["revogado_em"] else ""))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()