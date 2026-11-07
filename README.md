# Calendário de hábitos

Calendário estilo GitHub para hábitos pessoais. FastAPI + SQLite, com a página em `static/index.html`.

## Rodar

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m app.tokens criar web          # imprime o token UMA vez; cole-o na página
    uvicorn app.main:app --reload --env-file .env

Abra http://127.0.0.1:8000 (página) ou http://127.0.0.1:8000/docs (API; botão "Authorize" para usar o token).
Copie `.env.example` para `.env` para ajustar a configuração.

## Dispositivos e tokens

Cada dispositivo tem o seu token (a página, o celular, cada ESP32...). Só o hash fica no banco.

    python -m app.tokens criar celular
    python -m app.tokens listar
    python -m app.tokens revogar celular

Chamadas à API levam `Authorization: Bearer <token>`. O nome do dispositivo é gravado em `evento.origem`.
Escrita sempre exige token; a leitura também, a menos que `HABITOS_LEITURA_PUBLICA=1`.

## Regras

- Só eventos são guardados; contagem e nível (0 a 4) são calculados na leitura.
- O "dia" é o da data enviada (texto `YYYY-MM-DD`) e o "hoje" do servidor segue `HABITOS_TZ` (padrão America/Sao_Paulo).
- Não é possível registrar em data futura. Datas passadas são livres; `HABITOS_JANELA_DIAS=N` limita a edição aos últimos N dias.
- O calendário mostra os últimos 12 meses terminando hoje (ou um ano específico, até hoje).
- `booleano`: nível 4 se houver registro (em "Projeto" as horas ficam em `valor`). `quantidade`: soma do dia contra `limites` (Páginas lidas: 1-24, 25-49, 50-74, 75+).

## Endpoints principais

`GET /api/calendarios?ano=` · `POST /api/eventos` · `DELETE /api/eventos/{id}` · `GET /api/eventos?area_id&de&ate` · `GET|POST|DELETE /api/areas` · `GET /api/hoje`

## Testes

    python -m tests.test_db