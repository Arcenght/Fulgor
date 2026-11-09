"""API do calendário de hábitos. Rodar: uvicorn app.main:app --reload --env-file .env"""
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import config, db, tokens


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.conectar()
    db.iniciar(conn)
    conn.close()
    yield


app = FastAPI(title="Calendário de hábitos", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def get_conn():
    conn = db.conectar()
    try:
        yield conn
    finally:
        conn.close()


def escrita(cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer), conn=Depends(get_conn)) -> str:
    """Exige token válido; devolve o nome do dispositivo (gravado como 'origem' do evento).

    O token serve apenas para escrever e identificar quem registrou.
    A leitura é sempre aberta: todos os dispositivos veem as mesmas áreas e o mesmo calendário.
    """
    nome = tokens.validar(conn, cred.credentials) if cred else None
    if nome is None:
        raise HTTPException(401, "Token ausente ou inválido", headers={"WWW-Authenticate": "Bearer"})
    return nome


def checar_janela(d: date):
    if config.JANELA_DIAS is not None and d < config.hoje() - timedelta(days=config.JANELA_DIAS):
        raise HTTPException(422, f"Só é possível alterar os últimos {config.JANELA_DIAS} dias.")


def intervalo(ano: Optional[int]):
    """Sem ano: janela rolante de 53 semanas até hoje. Com ano: 1º de janeiro até hoje (ou 31/12)."""
    h = config.hoje()
    if ano is None:
        return db.janela_rolante(h)
    if ano > h.year or ano < 1970:
        raise HTTPException(422, "Ano inválido")
    return date(ano, 1, 1), min(date(ano, 12, 31), h)


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


api = APIRouter(prefix="/api")


# ---------- Leitura (aberta, sem token) ----------

@api.get("/hoje")
def obter_hoje():
    return {"hoje": config.hoje().isoformat(), "fuso": str(config.TZ)}


@api.get("/areas")
def listar_areas(conn=Depends(get_conn)):
    return [db.area_para_dict(r) for r in conn.execute("SELECT * FROM area ORDER BY id")]


@api.get("/eventos")
def listar_eventos(area_id: int, de: date, ate: date, conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM evento WHERE area_id = ? AND data BETWEEN ? AND ? ORDER BY data, id",
        (area_id, de.isoformat(), ate.isoformat()),
    ).fetchall()
    return [dict(r) for r in rows]


def _cabecalho(ini, fim):
    return {"hoje": config.hoje().isoformat(), "inicio": ini.isoformat(), "fim": fim.isoformat()}


@api.get("/calendario")
def obter_calendario(area_id: int, ano: Optional[int] = None, conn=Depends(get_conn)):
    ini, fim = intervalo(ano)
    r = db.calendario(conn, area_id, ini, fim)
    if r is None:
        raise HTTPException(404, "Área não encontrada")
    return {**_cabecalho(ini, fim), **r}


@api.get("/calendarios")
def obter_todos(ano: Optional[int] = None, conn=Depends(get_conn)):
    ini, fim = intervalo(ano)
    ids = [r["id"] for r in conn.execute("SELECT id FROM area ORDER BY id")]
    return {**_cabecalho(ini, fim), "areas": [db.calendario(conn, i, ini, fim) for i in ids]}


# ---------- Escrita (exige token; o token só identifica o dispositivo) ----------

@api.post("/areas", status_code=201, dependencies=[Depends(escrita)])
def criar_area(a: AreaIn, conn=Depends(get_conn)):
    try:
        cur = conn.execute(
            "INSERT INTO area (nome, tipo, unidade, limites, cor) VALUES (?,?,?,?,?)",
            (a.nome, a.tipo, a.unidade, json.dumps(a.limites) if a.limites else None, a.cor),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Já existe uma área com esse nome")
    return db.area_para_dict(conn.execute("SELECT * FROM area WHERE id=?", (cur.lastrowid,)).fetchone())


@api.delete("/areas/{area_id}", status_code=204, dependencies=[Depends(escrita)])
def remover_area(area_id: int, conn=Depends(get_conn)):
    cur = conn.execute("DELETE FROM area WHERE id = ?", (area_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "Área não encontrada")


@api.post("/eventos", status_code=201)
def criar_evento(e: EventoIn, origem: str = Depends(escrita), conn=Depends(get_conn)):
    if e.data > config.hoje():
        raise HTTPException(422, "Não é possível registrar em data futura.")
    checar_janela(e.data)
    if conn.execute("SELECT 1 FROM area WHERE id = ?", (e.area_id,)).fetchone() is None:
        raise HTTPException(404, "Área não encontrada")
    cur = conn.execute(
        "INSERT INTO evento (area_id, data, valor, nota, origem, criado_em) VALUES (?,?,?,?,?,?)",
        (e.area_id, e.data.isoformat(), e.valor, e.nota, origem,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM evento WHERE id=?", (cur.lastrowid,)).fetchone())


@api.delete("/eventos/{evento_id}", status_code=204, dependencies=[Depends(escrita)])
def remover_evento(evento_id: int, conn=Depends(get_conn)):
    row = conn.execute("SELECT data FROM evento WHERE id = ?", (evento_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Evento não encontrado")
    checar_janela(date.fromisoformat(row["data"]))
    conn.execute("DELETE FROM evento WHERE id = ?", (evento_id,))
    conn.commit()


app.include_router(api)

# Serve a página em "/". Fica por último para não encobrir as rotas da API.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="static")