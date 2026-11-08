"""
Pré-processamento e Ordenação Cronológica dos Dados Brutos — Citi Bike NYC (2024)
Disciplina: Exploração e Visualização de Dados (ECVD — UFPB)

Este script localiza automaticamente os arquivos CSV brutos de Janeiro e Setembro de 2024
(usando caminhos relativos portáveis entre Windows, Linux e macOS), remove registros com
coordenadas ausentes/corrompidas ("Null Island") ou durações fisicamente inválidas
(< 1 min ou > 24h) e exporta arquivos cronologicamente ordenados por `started_at`.
"""

from pathlib import Path
import glob
import pandas as pd

# ── 1. Resolução Portável de Diretórios ───────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
WORKSPACE_ROOT = REPO_ROOT.parent


def localizar_csvs_mes(codigo_mes: str) -> list[Path]:
    """Busca os CSVs brutos do mês (ex.: '202401' ou '202409') em locais candidatos."""
    pasta_nome = f"{codigo_mes}-citibike-tripdata"
    candidatos = [
        WORKSPACE_ROOT / pasta_nome,
        REPO_ROOT / pasta_nome,
        BASE_DIR / pasta_nome,
        BASE_DIR,
    ]
    for pasta in candidatos:
        if pasta.exists():
            arquivos = sorted(pasta.glob(f"{codigo_mes}-citibike-tripdata*.csv"))
            if arquivos:
                return arquivos
    return []


# Limites geográficos estritos da Região Metropolitana de NYC (elimina erros de GPS)
LAT_MIN, LAT_MAX = 40.4, 41.0
LNG_MIN, LNG_MAX = -74.3, -73.7


# ── 2. Pipeline de Limpeza e Ordenação ────────────────────────────────────────
def processar_mes_separado(arquivos_csv: list[Path], dir_saida: Path, nome_mes: str) -> None:
    """Limpa ruídos espaciais/temporais e salva cada partição ordenada por `started_at`."""
    if not arquivos_csv:
        print(f"[AVISO] Nenhum CSV bruto encontrado para {nome_mes}.")
        return

    dir_saida.mkdir(parents=True, exist_ok=True)
    print(f"=== Pré-processando {nome_mes} ({len(arquivos_csv)} arquivo(s)) ===")

    for caminho_csv in arquivos_csv:
        df = pd.read_csv(caminho_csv, low_memory=False)
        total_bruto = len(df)

        # Conversão temporal e cálculo de duração em minutos
        df["started_at"] = pd.to_datetime(df["started_at"])
        df["ended_at"] = pd.to_datetime(df["ended_at"])
        duracao_min = (df["ended_at"] - df["started_at"]).dt.total_seconds() / 60.0

        # Remoção de valores ausentes, durações inválidas (< 1 min ou > 24h) e coordenadas fora de NYC
        df = df.dropna(subset=["start_lat", "start_lng", "end_lat", "end_lng"])
        mascara_valida = (
            (duracao_min >= 1.0)
            & (duracao_min <= 1440.0)
            & df["start_lat"].between(LAT_MIN, LAT_MAX)
            & df["start_lng"].between(LNG_MIN, LNG_MAX)
            & df["end_lat"].between(LAT_MIN, LAT_MAX)
            & df["end_lng"].between(LNG_MIN, LNG_MAX)
        )
        df = df.loc[mascara_valida].sort_values("started_at").reset_index(drop=True)

        destino = dir_saida / caminho_csv.name
        df.to_csv(destino, index=False)
        retencao = (len(df) / total_bruto * 100) if total_bruto else 0.0
        print(f"  -> {caminho_csv.name}: {len(df):,} viagens válidas ({retencao:.2f}%) salvas em {destino.name}")


if __name__ == "__main__":
    processar_mes_separado(
        localizar_csvs_mes("202401"),
        BASE_DIR / "ordenado_jan2024",
        "Janeiro/2024",
    )
    processar_mes_separado(
        localizar_csvs_mes("202409"),
        BASE_DIR / "ordenado_set2024",
        "Setembro/2024",
    )
