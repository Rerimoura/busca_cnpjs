import streamlit as st
import pandas as pd
import duckdb
import os

from db_clientes import buscar_codigos_clientes

# Status mapping
SITUACAO_MAP = {
    '01': 'Nula', '1': 'Nula',
    '02': 'Ativa', '2': 'Ativa',
    '03': 'Suspensa', '3': 'Suspensa',
    '04': 'Inapta', '4': 'Inapta',
    '08': 'Baixada', '8': 'Baixada'
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARQUET_PATTERN = os.path.join(BASE_DIR, 'estabelecimentos_mg_part*.parquet')


@st.cache_data
def load_municipios():
    file_path = os.path.join(BASE_DIR, 'municipios.xlsx')
    fallback_path = os.path.join(BASE_DIR, 'municipios_fallback.xlsx')

    try:
        df_mun = pd.read_excel(file_path, usecols=['MUNICIPIO', 'NOME_MUNICIPIO'])
    except PermissionError:
        if os.path.exists(fallback_path):
            df_mun = pd.read_excel(fallback_path, usecols=['MUNICIPIO', 'NOME_MUNICIPIO'])
        else:
            return {}
    except Exception:
        return {}

    df_mun['MUNICIPIO'] = df_mun['MUNICIPIO'].astype(str)
    return dict(zip(df_mun['NOME_MUNICIPIO'], df_mun['MUNICIPIO']))


def query_duckdb(sql, params=None):
    """Execute a DuckDB query and return a DataFrame."""
    con = duckdb.connect(database=':memory:')
    try:
        if params:
            result = con.execute(sql, params).df()
        else:
            result = con.execute(sql).df()
        return result
    finally:
        con.close()


@st.cache_data(ttl=300)
def buscar_cnpjs(cod_municipio, texto_rua, numero=None):
    """List all CNPJs on streets matching the text, optionally filtered by number."""
    if numero:
        sql = f"""
            SELECT CNPJ, razao_social, tipo_de_logradouro, logradouro, numero, bairro,
                   situacao_cadastral, data_situacao_cadastral
            FROM '{PARQUET_PATTERN}'
            WHERE municipio = ?
              AND logradouro ILIKE ?
              AND CAST(numero AS VARCHAR) = ?
            ORDER BY data_situacao_cadastral DESC, logradouro, numero, CNPJ
        """
        return query_duckdb(sql, [cod_municipio, f'%{texto_rua}%', str(numero)])
    else:
        sql = f"""
            SELECT CNPJ, razao_social, tipo_de_logradouro, logradouro, numero, bairro,
                   situacao_cadastral, data_situacao_cadastral
            FROM '{PARQUET_PATTERN}'
            WHERE municipio = ?
              AND logradouro ILIKE ?
            ORDER BY data_situacao_cadastral DESC, logradouro, numero, CNPJ
        """
        return query_duckdb(sql, [cod_municipio, f'%{texto_rua}%'])


# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Busca por Endereço - MG", layout="wide")
st.title("🔍 Busca de CNPJs por Endereço")
st.markdown("Encontre todos os estabelecimentos em uma rua de Minas Gerais.")

# ── Load municipalities ──────────────────────────────────────────────────────
mun_nome_para_cod = load_municipios()

if not mun_nome_para_cod:
    st.error("Erro ao carregar a lista de municípios.")
    st.stop()

# ── Filters ──────────────────────────────────────────────────────────────────
col_mun, col_rua, col_num = st.columns([2, 3, 1])

with col_mun:
    municipio_nome = st.selectbox(
        "Município",
        options=sorted(mun_nome_para_cod.keys()),
        index=None,
        placeholder="Selecione o município..."
    )

with col_rua:
    texto_rua = st.text_input("Buscar logradouro (parte do nome)", placeholder="Ex: AMAZONAS")

with col_num:
    numero_input = st.text_input("Número (opcional)", placeholder="Ex: 123")

# ── Results ──────────────────────────────────────────────────────────────────
if municipio_nome and texto_rua and len(texto_rua) >= 3:
    cod_municipio = mun_nome_para_cod[municipio_nome]
    num_filtro = numero_input.strip() if numero_input else None

    with st.spinner("Buscando estabelecimentos..."):
        df_result = buscar_cnpjs(cod_municipio, texto_rua, num_filtro)

    if df_result.empty:
        st.warning("Nenhum estabelecimento encontrado com esse endereço.")
    else:
        # ── Metrics ──────────────────────────────────────────────────────
        st.markdown("---")
        total = len(df_result)
        ativos = len(df_result[
            df_result['situacao_cadastral'].astype(str).isin(['02', '2'])
        ])

        m1, m2 = st.columns(2)
        m1.metric("📊 Total de Estabelecimentos", total)
        m2.metric("✅ Ativos", ativos)

        # ── Format table ─────────────────────────────────────────────────
        df_display = df_result.copy()

        # Lookup customer registration code in Biz Distribuidora's database
        codigos_clientes = buscar_codigos_clientes(tuple(df_display['CNPJ'].astype(int)))
        df_display['Código Cliente'] = df_display['CNPJ'].astype(int).map(codigos_clientes).apply(
            lambda x: str(int(x)) if pd.notna(x) else 'Não cadastrado'
        )

        # Combine tipo + logradouro into one column
        df_display['Logradouro'] = (
            df_display['tipo_de_logradouro'].fillna('') + ' ' +
            df_display['logradouro'].fillna('')
        ).str.strip()

        df_display['situacao_cadastral'] = (
            df_display['situacao_cadastral']
            .astype(str)
            .map(SITUACAO_MAP)
            .fillna('Desconhecido')
        )

        # Convert date to datetime object so Streamlit sorts it correctly
        df_display['data_situacao_cadastral'] = pd.to_datetime(
            df_display['data_situacao_cadastral'].astype(str), format='%Y%m%d', errors='coerce'
        )

        df_display = df_display[['CNPJ', 'razao_social', 'Logradouro', 'numero', 'bairro',
                                  'situacao_cadastral', 'data_situacao_cadastral', 'Código Cliente']]
        df_display.columns = ['CNPJ', 'Razão Social', 'Logradouro', 'Número', 'Bairro',
                              'Situação', 'Data Situação', 'Código Cliente']

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "CNPJ": st.column_config.TextColumn("CNPJ", width="medium"),
                "Data Situação": st.column_config.DateColumn("Data Situação", format="DD/MM/YYYY"),
                "Código Cliente": st.column_config.TextColumn("Código Cliente", help="Código na base da Biz Distribuidora, se o CNPJ tiver cadastro"),
            }
        )

elif municipio_nome and texto_rua and len(texto_rua) < 3:
    st.info("Digite pelo menos 3 caracteres para buscar o logradouro.")
