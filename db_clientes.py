"""Consulta de cadastro de clientes da Biz Distribuidora (banco Postgres/Neon)."""
import os

import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _get_setting(key, default=None):
    """Busca a configuração em variáveis de ambiente (.env local) ou em st.secrets (Streamlit Cloud)."""
    if key in os.environ:
        return os.environ[key]
    try:
        return st.secrets[key]
    except Exception:
        return default


def _get_connection():
    return psycopg2.connect(
        host=_get_setting('DB_HOST'),
        dbname=_get_setting('DB_NAME'),
        user=_get_setting('DB_USER'),
        password=_get_setting('DB_PASSWORD'),
        port=_get_setting('DB_PORT', '5432'),
        sslmode='require',
    )


# Regra de situação de crédito na Biz:
#   situacao = 'A' e limite_aberto > 0  -> Liberado no prazo
#   situacao = 'A' e antecipado = 'A28' -> Liberado no antecipado
#   demais casos                        -> Suspenso
# "limite_aberto::text <> 'NaN'" descarta valores NaN: no tipo NUMERIC do Postgres,
# ao contrário do IEEE754, NaN é tratado como igual a si mesmo e maior que qualquer
# outro número, então nem "limite_aberto > 0" nem "limite_aberto = limite_aberto"
# sozinhos excluem NaN.
_SITUACAO_CREDITO_SQL = """
    CASE
        WHEN situacao = 'A' AND limite_aberto > 0 AND limite_aberto::text <> 'NaN' AND antecipado <> 'A28'
            THEN 'Liberado no prazo'
        WHEN situacao = 'A' AND antecipado = 'A28'
            THEN 'Liberado no antecipado'
        ELSE 'Suspenso'
    END
"""


@st.cache_data(ttl=300)
def buscar_codigo_cliente(cnpj: int):
    """Retorna (codigo_cliente, situacao_credito, erro).
    codigo_cliente e situacao_credito são None se o CNPJ não tem cadastro."""
    try:
        conn = _get_connection()
    except Exception as e:
        return None, None, f"Não foi possível conectar à base de clientes: {e}"

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT cliente, {_SITUACAO_CREDITO_SQL} FROM clientes WHERE cnpj = %s LIMIT 1",
                (cnpj,),
            )
            row = cur.fetchone()
            return (int(row[0]), row[1], None) if row else (None, None, None)
    except Exception as e:
        return None, None, f"Erro ao consultar base de clientes: {e}"
    finally:
        conn.close()


@st.cache_data(ttl=300)
def buscar_codigos_clientes(cnpjs: tuple):
    """Retorna um dict {cnpj: (codigo_cliente, situacao_credito)} para os CNPJs
    cadastrados dentre os informados."""
    if not cnpjs:
        return {}

    try:
        conn = _get_connection()
    except Exception:
        return {}

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT cnpj, cliente, {_SITUACAO_CREDITO_SQL} FROM clientes WHERE cnpj = ANY(%s)",
                (list(cnpjs),),
            )
            return {
                int(cnpj): (int(cliente), situacao_credito)
                for cnpj, cliente, situacao_credito in cur.fetchall()
            }
    except Exception:
        return {}
    finally:
        conn.close()
