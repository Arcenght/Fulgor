"""API do calendário de hábitos. Rodar: uvicorn app.main:app --reload --env-file .env"""
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
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


def escrita(cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
            x_dispositivo: Optional[int] = Header(default=None), conn=Depends(get_conn)) -> str:
    """Identifica quem escreve; devolve o nome do dispositivo (gravado como 'origem' e no histórico).

    Aceita (1) token Bearer (ESP32, scripts) ou (2) o id do dispositivo escolhido na página
    (cabeçalho X-Dispositivo), se HABITOS_ESCRITA_PAGINA não for 0. A leitura é sempre aberta.
    """
    if cred:
        nome = tokens.validar(conn, cred.credentials)
    elif x_dispositivo is not None and config.ESCRITA_PELA_PAGINA:
        nome = tokens.nome_ativo(conn, x_dispositivo)
    else:
        nome = None
    if nome is None:
        raise HTTPException(401, "Dispositivo não selecionado ou token inválido", headers={"WWW-Authenticate": "Bearer"})
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

def _area(conn, area_id):
    return conn.execute("SELECT * FROM area WHERE id = ?", (area_id,)).fetchone()


def _valores(a):
    return (a.nome, a.tipo, a.unidade or None, json.dumps(a.limites) if a.limites else None, a.cor)


@api.post("/areas", status_code=201)
def criar_area(a: AreaIn, origem: str = Depends(escrita), conn=Depends(get_conn)):
    try:
        cur = conn.execute("INSERT INTO area (nome, tipo, unidade, limites, cor) VALUES (?,?,?,?,?)", _valores(a))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Já existe uma área com esse nome")
    nova = db.area_para_dict(_area(conn, cur.lastrowid))
    db.log(conn, "area", cur.lastrowid, "criar", None, nova, origem)
    conn.commit()
    return nova


@api.put("/areas/{area_id}")
def editar_area(area_id: int, a: AreaIn, origem: str = Depends(escrita), conn=Depends(get_conn)):
    antes = _area(conn, area_id)
    if antes is None:
        raise HTTPException(404, "Área não encontrada")
    try:
        conn.execute("UPDATE area SET nome=?, tipo=?, unidade=?, limites=?, cor=? WHERE id=?", (*_valores(a), area_id))
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(409, "Já existe uma área com esse nome")
    depois = db.area_para_dict(_area(conn, area_id))
    db.log(conn, "area", area_id, "editar", db.area_para_dict(antes), depois, origem)
    conn.commit()
    return depois


@api.delete("/areas/{area_id}", status_code=204)
def remover_area(area_id: int, origem: str = Depends(escrita), conn=Depends(get_conn)):
    antes = _area(conn, area_id)
    if antes is None:
        raise HTTPException(404, "Área não encontrada")
    eventos = [dict(r) for r in conn.execute("SELECT * FROM evento WHERE area_id = ?", (area_id,))]
    db.log(conn, "area", area_id, "remover", {"area": db.area_para_dict(antes), "eventos": eventos}, None, origem)
    conn.execute("DELETE FROM area WHERE id = ?", (area_id,))
    conn.commit()


class DispositivoIn(BaseModel):
    nome: str = Field(min_length=1, max_length=40)


@api.get("/dispositivos")
def listar_dispositivos(conn=Depends(get_conn)):
    return tokens.listar_ativos(conn)


@api.post("/dispositivos", status_code=201)
def criar_dispositivo(d: DispositivoIn, origem: str = Depends(escrita), conn=Depends(get_conn)):
    try:
        did, token = tokens.criar_com_id(conn, d.nome, origem)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Já existe um dispositivo com esse nome")
    return {"id": did, "nome": d.nome, "token": token}  # o token só aparece agora (uso em API/ESP32)


@api.put("/dispositivos/{did}")
def renomear_dispositivo(did: int, d: DispositivoIn, origem: str = Depends(escrita), conn=Depends(get_conn)):
    try:
        ok = tokens.renomear(conn, did, d.nome, origem)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Já existe um dispositivo com esse nome")
    if not ok:
        raise HTTPException(404, "Dispositivo não encontrado")
    return {"id": did, "nome": d.nome}


@api.delete("/dispositivos/{did}", status_code=204)
def remover_dispositivo(did: int, origem: str = Depends(escrita), conn=Depends(get_conn)):
    if len(tokens.listar_ativos(conn)) <= 1:
        raise HTTPException(409, "Mantenha pelo menos um dispositivo ativo.")
    if not tokens.revogar_id(conn, did, origem):
        raise HTTPException(404, "Dispositivo não encontrado")


@api.get("/historico")
def listar_historico(entidade: Optional[Literal["area", "dispositivo"]] = None, entidade_id: Optional[int] = None,
                     limite: int = Query(50, ge=1, le=500), conn=Depends(get_conn)):
    sql, args = "SELECT * FROM historico WHERE 1=1", []
    if entidade:
        sql += " AND entidade = ?"; args.append(entidade)
    if entidade_id is not None:
        sql += " AND entidade_id = ?"; args.append(entidade_id)
    out = []
    for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limite)):
        d = dict(r)
        for k in ("antes", "depois"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    return out


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