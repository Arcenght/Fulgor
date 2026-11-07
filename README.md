# Calendário de hábitos

Calendário estilo GitHub para hábitos pessoais. FastAPI + SQLite, com a página em `static/index.html`.

## Rodar

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload

Abra http://127.0.0.1:8000 (página) ou http://127.0.0.1:8000/docs (API).
O banco é criado em `data/habitos.db` (ou no caminho de `HABITOS_DB`), com as áreas Projeto, Páginas lidas e Exercício.

## Níveis de cor (0 a 4)

- `booleano`: nível 4 se houver registro no dia (em "Projeto" as horas ficam em `valor`).
- `quantidade`: soma do dia comparada com `limites` (Páginas lidas: 1-24, 25-49, 50-74, 75+).

## Testes

    python -m tests.test_db
