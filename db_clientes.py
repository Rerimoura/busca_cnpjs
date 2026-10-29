"""Consulta de cadastro de clientes da Biz Distribuidora (banco Postgres/Neon)."""
import os

import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _get_connection():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        port=os.environ.get('DB_PORT', '5432'),
        sslmode='require',
    )


@st.cache_data(ttl=300)
def buscar_codigo_cliente(cnpj: int):
    """Retorna (codigo_cliente, erro). codigo_cliente é None se o CNPJ não tem cadastro."""
    try:
        conn = _get_connection()
    except Exception as e:
        return None, f"Não foi possível conectar à base de clientes: {e}"

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT cliente FROM clientes WHERE cnpj = %s LIMIT 1", (cnpj,))
            row = cur.fetchone()
            return (int(row[0]), None) if row else (None, None)
    except Exception as e:
        return None, f"Erro ao consultar base de clientes: {e}"
    finally:
        conn.close()


@st.cache_data(ttl=300)
def buscar_codigos_clientes(cnpjs: tuple):
    """Retorna um dict {cnpj: codigo_cliente} para os CNPJs cadastrados dentre os informados."""
    if not cnpjs:
        return {}

    try:
        conn = _get_connection()
    except Exception:
        return {}

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cnpj, cliente FROM clientes WHERE cnpj = ANY(%s)",
                (list(cnpjs),),
            )
            return {int(cnpj): int(cliente) for cnpj, cliente in cur.fetchall()}
    except Exception:
        return {}
    finally:
        conn.close()
