"""API do calendário de hábitos. Rodar: uvicorn main:app --reload"""
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.conectar()
    db.iniciar(conn)
    conn.close()
    yield


app = FastAPI(title="Calendário de hábitos", lifespan=lifespan)


def get_conn():
    conn = db.conectar()
    try:
        yield conn
    finally:
        conn.close()


class AreaIn(BaseModel):
    nome: str = Field(min_length=1)
    tipo: Literal["booleano", "quantidade"]
    unidade: Optional[str] = None
    limites: Optional[list[float]] = None
    cor: str = Field(default="#216e39", pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def checar_limites(self):
        if self.tipo == "quantidade":
            l = self.limites
            if not l or len(l) != 4 or l != sorted(l) or l[0] <= 0:
                raise ValueError("'quantidade' exige 'limites': 4 valores positivos em ordem crescente")
        else:
            self.limites = None
        return self


class EventoIn(BaseModel):
    area_id: int
    data: date
    valor: float = Field(default=1, gt=0)
    nota: Optional[str] = None


@app.get("/areas")
def listar_areas(conn=Depends(get_conn)):
    rows = conn.execute("SELECT * FROM area ORDER BY id").fetchall()
    return [db.area_para_dict(r) for r in rows]


@app.post("/areas", status_code=201)
def criar_area(a: AreaIn, conn=Depends(get_conn)):
    import json
    try:
        cur = conn.execute(
            "INSERT INTO area (nome, tipo, unidade, limites, cor) VALUES (?,?,?,?,?)",
            (a.nome, a.tipo, a.unidade, json.dumps(a.limites) if a.limites else None, a.cor),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Já existe uma área com esse nome")
    return db.area_para_dict(conn.execute("SELECT * FROM area WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/areas/{area_id}", status_code=204)
def remover_area(area_id: int, conn=Depends(get_conn)):
    cur = conn.execute("DELETE FROM area WHERE id = ?", (area_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Área não encontrada")


@app.get("/eventos")
def listar_eventos(area_id: int, ano: int = Query(default_factory=lambda: date.today().year),
                   conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM evento WHERE area_id = ? AND data BETWEEN ? AND ? ORDER BY data, id",
        (area_id, f"{ano}-01-01", f"{ano}-12-31"),
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/eventos", status_code=201)
def criar_evento(e: EventoIn, conn=Depends(get_conn)):
    if conn.execute("SELECT 1 FROM area WHERE id = ?", (e.area_id,)).fetchone() is None:
        raise HTTPException(404, "Área não encontrada")
    cur = conn.execute(
        "INSERT INTO evento (area_id, data, valor, nota) VALUES (?,?,?,?)",
        (e.area_id, e.data.isoformat(), e.valor, e.nota),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM evento WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/eventos/{evento_id}", status_code=204)
def remover_evento(evento_id: int, conn=Depends(get_conn)):
    cur = conn.execute("DELETE FROM evento WHERE id = ?", (evento_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Evento não encontrado")


@app.get("/calendario")
def obter_calendario(area_id: int, ano: int = Query(default_factory=lambda: date.today().year),
                     conn=Depends(get_conn)):
    r = db.calendario(conn, area_id, ano)
    if r is None:
        raise HTTPException(404, "Área não encontrada")
    return r


@app.get("/calendarios")
def obter_todos(ano: int = Query(default_factory=lambda: date.today().year), conn=Depends(get_conn)):
    ids = [r["id"] for r in conn.execute("SELECT id FROM area ORDER BY id")]
    return [db.calendario(conn, i, ano) for i in ids]


# Serve a página em "/". Fica por último para não encobrir as rotas da API.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="static")
