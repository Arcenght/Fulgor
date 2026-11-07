"""Configuração por variáveis de ambiente."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

# Fuso que define o "dia" de cada registro e o fim do calendário.
TZ = ZoneInfo(os.environ.get("HABITOS_TZ", "America/Sao_Paulo"))

# Quantos dias para trás ainda se pode registrar/remover. Vazio = sem limite (modo de testes).
# Para endurecer depois, basta definir HABITOS_JANELA_DIAS=7, por exemplo.
JANELA_DIAS = int(os.environ["HABITOS_JANELA_DIAS"]) if os.environ.get("HABITOS_JANELA_DIAS") else None

# 1 = leitura sem token (a escrita sempre exige token).
LEITURA_PUBLICA = os.environ.get("HABITOS_LEITURA_PUBLICA") == "1"


def hoje() -> date:
    return datetime.now(TZ).date()