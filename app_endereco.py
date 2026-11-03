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

# Situação cadastral agrupada por rótulo, para o filtro (vários códigos têm o mesmo significado)
SITUACAO_CODIGOS_POR_LABEL = {}
for _codigo, _label in SITUACAO_MAP.items():
    SITUACAO_CODIGOS_POR_LABEL.setdefault(_label, []).append(_codigo)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARQUET_PATTERN = os.path.join(BASE_DIR, 'estabelecimentos_mg_part*.parquet')
CNAES_PATH = os.path.join(BASE_DIR, 'cnaes.csv')


@st.cache_data
def load_cnaes():
    """Carrega a tabela de CNAEs (código -> descrição) para a busca por atividade."""
    try:
        df_cnae = pd.read_csv(CNAES_PATH, sep=';', dtype={'codigo': str}, encoding='utf-8')
    except Exception:
        return {}, []

    cod_para_desc = dict(zip(df_cnae['codigo'], df_cnae['descricao']))
    opcoes = sorted(
        (f"{desc} ({cod})" for cod, desc in cod_para_desc.items()),
        key=str.lower,
    )
    return cod_para_desc, opcoes


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
def buscar_cnpjs(cod_municipio, texto_rua, numero=None, bairro=None, cnae=None, situacao_codigos=None, razao_social=None):
    """List all CNPJs on streets matching the text, optionally filtered by
    number, bairro, CNAE (principal ou secundário), situação cadastral na Receita e razão social."""
    conditions = ["municipio = ?", "logradouro ILIKE ?"]
    params = [cod_municipio, f'%{texto_rua}%']

    if numero:
        conditions.append("CAST(numero AS VARCHAR) = ?")
        params.append(str(numero))

    if razao_social:
        conditions.append("razao_social ILIKE ?")
        params.append(f'%{razao_social}%')

    if bairro:
        conditions.append("bairro ILIKE ?")
        params.append(f'%{bairro}%')

    if cnae:
        conditions.append(
            "(cnae_fiscal_principal = ? OR ',' || cnae_fiscal_secundaria || ',' ILIKE ?)"
        )
        params.append(cnae)
        params.append(f'%,{cnae},%')

    if situacao_codigos:
        placeholders = ', '.join('?' for _ in situacao_codigos)
        conditions.append(f"situacao_cadastral IN ({placeholders})")
        params.extend(situacao_codigos)

    sql = f"""
        SELECT CNPJ, razao_social, tipo_de_logradouro, logradouro, numero, bairro,
               situacao_cadastral, data_situacao_cadastral,
               cnae_fiscal_principal, cnae_fiscal_secundaria
        FROM '{PARQUET_PATTERN}'
        WHERE {' AND '.join(conditions)}
        ORDER BY data_situacao_cadastral DESC, logradouro, numero, CNPJ
    """
    return query_duckdb(sql, params)


# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Busca por Endereço - MG", layout="wide")
st.title("🔍 Busca de CNPJs por Endereço")
st.markdown("Encontre todos os estabelecimentos em uma rua de Minas Gerais.")

with st.expander("ℹ️ Como filtrar"):
    st.markdown(
        """
        **Para a busca começar**, selecione o **Município** e preencha pelo menos um destes campos
        (mínimo 3 caracteres): **Logradouro**, **Razão Social** ou **Bairro**.

        Depois de começar a busca, use os demais campos para refinar o resultado:
        - **Número**: filtra pelo número do endereço.
        - **CNAE**: filtra pela atividade do estabelecimento (principal ou secundária) — digite o nome
          da atividade (ex: "restaurante") ou o código.
        - **Situação Receita**: filtra pela situação cadastral na Receita Federal (Ativa, Baixada, etc).

        Na tabela de resultados, a coluna **Código Cliente** mostra se o CNPJ já tem cadastro na
        Biz Distribuidora: um código indica que o cliente já está cadastrado, e "Não cadastrado"
        indica que ainda não existe cadastro para esse CNPJ.
        """
    )

# ── Load municipalities and CNAEs ──────────────────────────────────────────────
mun_nome_para_cod = load_municipios()
cnae_cod_para_desc, cnae_opcoes = load_cnaes()

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

col_razao, col_bairro = st.columns(2)

with col_razao:
    razao_social_input = st.text_input("Razão Social (opcional)", placeholder="Ex: PADARIA")

with col_bairro:
    bairro_input = st.text_input("Bairro (opcional)", placeholder="Ex: CENTRO")

col_cnae, col_situacao = st.columns(2)

with col_cnae:
    cnae_opcao = st.selectbox(
        "CNAE - principal ou secundário (opcional)",
        options=cnae_opcoes,
        index=None,
        placeholder="Buscar por atividade ou código...",
    )

with col_situacao:
    situacao_opcao = st.selectbox(
        "Situação Receita (opcional)",
        options=sorted(SITUACAO_CODIGOS_POR_LABEL.keys()),
        index=None,
        placeholder="Todas",
        help="Situação cadastral do CNPJ na Receita Federal — não reflete o cadastro na Biz Distribuidora.",
    )
    st.caption("ℹ️ Situação cadastral na Receita Federal. Não é a situação do cadastro na Biz.")

# ── Results ──────────────────────────────────────────────────────────────────
rua_valida = bool(texto_rua) and len(texto_rua) >= 3
razao_social_strip = razao_social_input.strip() if razao_social_input else ''
razao_valida = len(razao_social_strip) >= 3
bairro_strip = bairro_input.strip() if bairro_input else ''
bairro_valida = len(bairro_strip) >= 3

if municipio_nome and (rua_valida or razao_valida or bairro_valida):
    cod_municipio = mun_nome_para_cod[municipio_nome]
    rua_filtro = texto_rua if rua_valida else ''
    num_filtro = numero_input.strip() if numero_input else None
    bairro_filtro = bairro_strip if bairro_valida else None
    cnae_filtro = cnae_opcao.rsplit('(', 1)[-1].rstrip(')') if cnae_opcao else None
    situacao_filtro = tuple(SITUACAO_CODIGOS_POR_LABEL[situacao_opcao]) if situacao_opcao else None
    razao_social_filtro = razao_social_strip if razao_valida else None

    with st.spinner("Buscando estabelecimentos..."):
        df_result = buscar_cnpjs(
            cod_municipio, rua_filtro, num_filtro, bairro_filtro, cnae_filtro, situacao_filtro,
            razao_social_filtro,
        )

    if df_result.empty:
        st.warning("Nenhum estabelecimento encontrado com esses filtros.")
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

        # Show CNAE description instead of just the raw code
        df_display['cnae_fiscal_principal'] = df_display['cnae_fiscal_principal'].map(
            lambda cod: f"{cnae_cod_para_desc.get(str(cod), 'Desconhecido')} ({cod})"
        )

        df_display = df_display[['CNPJ', 'Código Cliente', 'razao_social', 'Logradouro', 'numero', 'bairro',
                                  'situacao_cadastral', 'data_situacao_cadastral',
                                  'cnae_fiscal_principal']]
        df_display.columns = ['CNPJ', 'Código Cliente', 'Razão Social', 'Logradouro', 'Número', 'Bairro',
                              'Situação Receita', 'Data Situação', 'CNAE Principal']

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "CNPJ": st.column_config.TextColumn("CNPJ", width="medium"),
                "Situação Receita": st.column_config.TextColumn("Situação Receita", help="Situação cadastral na Receita Federal, não reflete o cadastro na Biz Distribuidora"),
                "Data Situação": st.column_config.DateColumn("Data Situação", format="DD/MM/YYYY"),
                "Código Cliente": st.column_config.TextColumn("Código Cliente", help="Código na base da Biz Distribuidora, se o CNPJ tiver cadastro"),
            }
        )

elif municipio_nome and (texto_rua or razao_social_input or bairro_input) and not (rua_valida or razao_valida or bairro_valida):
    st.info("Digite pelo menos 3 caracteres no logradouro, na razão social ou no bairro para buscar.")
