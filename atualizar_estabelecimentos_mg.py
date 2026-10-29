# -*- coding: utf-8 -*-
"""
Regera os arquivos estabelecimentos_mg_part*.parquet a partir de
estabelecimentos.parquet (atualizado mensalmente pela Receita).

Uso:
    python atualizar_estabelecimentos_mg.py
"""

import duckdb
import glob
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ESTABELECIMENTOS_PATH = os.path.join(BASE_DIR, 'estabelecimentos.parquet')
EMPRESAS_PATH = os.path.join(BASE_DIR, 'empresas.parquet')

NUM_PARTS = 3          # GitHub free tier rejeita arquivos acima de 100MB
COMPRESSION_LEVEL = 19  # ZSTD: acima disso o ganho de tamanho é marginal
MAX_SIZE_MB = 95        # margem de segurança abaixo do limite de 100MB do GitHub


def gerar_estabelecimentos_mg(
    estab_path=ESTABELECIMENTOS_PATH,
    empresas_path=EMPRESAS_PATH,
    output_dir=BASE_DIR,
    num_parts=NUM_PARTS,
):
    """Filtra os estabelecimentos de MG, monta o CNPJ (14 dígitos), junta a
    razão social de empresas.parquet e divide o resultado em `num_parts`
    arquivos estabelecimentos_mg_part{N}.parquet."""

    if not os.path.exists(estab_path):
        raise FileNotFoundError(f"Arquivo fonte não encontrado: {estab_path}")
    if not os.path.exists(empresas_path):
        raise FileNotFoundError(f"Arquivo fonte não encontrado: {empresas_path}")

    # Remove partes antigas (inclusive de execuções com um num_parts diferente)
    # para nunca deixar um arquivo obsoleto que o glob 'part*.parquet' dos apps
    # capturaria junto com os novos.
    padrao_antigo = os.path.join(output_dir, 'estabelecimentos_mg_part*.parquet')
    for f in glob.glob(padrao_antigo):
        os.remove(f)

    print("Regerando arquivos de estabelecimentos de MG...")
    start = time.time()

    con = duckdb.connect(database=':memory:')
    try:
        con.execute(f"""
            CREATE TEMP TABLE mg_base AS
            SELECT
                CAST(e.cnpj_basico AS BIGINT) * 1000000
                  + CAST(e.cnpj_ordem AS BIGINT) * 100
                  + CAST(e.cnpj_dv    AS BIGINT)          AS CNPJ,
                e.municipio,
                e.tipo_de_logradouro,
                e.logradouro,
                e.bairro,
                e.numero,
                e.situacao_cadastral,
                e.data_situacao_cadastral,
                e.cnae_fiscal_principal,
                e.cnae_fiscal_secundaria,
                emp.razao_social
            FROM '{estab_path}' e
            LEFT JOIN '{empresas_path}' emp
              ON CAST(e.cnpj_basico AS BIGINT) = TRY_CAST(emp.cnpj_basico AS BIGINT)
            WHERE e.uf = 'MG'
            ORDER BY CNPJ
        """)

        total = con.execute("SELECT COUNT(*) FROM mg_base").fetchone()[0]
        if total == 0:
            raise RuntimeError("Nenhum estabelecimento de MG encontrado em estabelecimentos.parquet")

        tamanho_parte = -(-total // num_parts)  # ceil division

        output_paths = []
        row_counts = []
        for i in range(num_parts):
            output_path = os.path.join(output_dir, f'estabelecimentos_mg_part{i + 1}.parquet')
            offset = i * tamanho_parte
            con.execute(f"""
                COPY (SELECT * FROM mg_base OFFSET {offset} LIMIT {tamanho_parte})
                TO '{output_path}' (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL {COMPRESSION_LEVEL})
            """)
            output_paths.append(output_path)
            row_counts.append(con.execute(f"SELECT COUNT(*) FROM '{output_path}'").fetchone()[0])
    finally:
        con.close()

    elapsed = time.time() - start
    sizes_mb = [os.path.getsize(p) / (1024 * 1024) for p in output_paths]

    print(f"Concluído em {elapsed / 60:.1f} min")
    print(f"  Total : {total:,} linhas em {num_parts} partes")
    for i, (rows, size_mb) in enumerate(zip(row_counts, sizes_mb), start=1):
        print(f"  Part{i} : {rows:,} linhas ({size_mb:.1f} MB)")

    grandes = [p for p, s in zip(output_paths, sizes_mb) if s > MAX_SIZE_MB]
    if grandes:
        print(f"\nAviso: {len(grandes)} parte(s) acima de {MAX_SIZE_MB}MB. "
              f"Aumente num_parts na próxima execução.")

    return {
        'total': total,
        'num_parts': num_parts,
        'row_counts': row_counts,
        'sizes_mb': sizes_mb,
        'elapsed_s': elapsed,
    }


if __name__ == '__main__':
    gerar_estabelecimentos_mg()
