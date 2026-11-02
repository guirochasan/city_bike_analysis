import pandas as pd
import os

# ── 1. Caminhos dos CSVs de entrada ──────────────────────────────────
CSVs_jan = [
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202401-citibike-tripdata_1.csv',
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202401-citibike-tripdata_2.csv'
]

CSVs_set = [
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202409-citibike-tripdata/202409-citibike-tripdata_1.csv',
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202409-citibike-tripdata/202409-citibike-tripdata_2.csv',
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202409-citibike-tripdata/202409-citibike-tripdata_3.csv',
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202409-citibike-tripdata/202409-citibike-tripdata_4.csv',
    '/home/guirocha/city_bike_analysis/ecvd_citibike/202409-citibike-tripdata/202409-citibike-tripdata_5.csv'
]

# ── 2. Diretórios de saída ───────────────────────────────────────────
out_jan = '/home/guirocha/city_bike_analysis/ecvd_citibike/ordenado_jan2024'
out_set = '/home/guirocha/city_bike_analysis/ecvd_citibike/ordenado_set2024'

os.makedirs(out_jan, exist_ok=True)
os.makedirs(out_set, exist_ok=True)

# ── 3. Função: processa cada arquivo individualmente ─────────────────
def processar_mes_separado(lista_csvs, dir_saida):
    for f in lista_csvs:
        df = pd.read_csv(f, low_memory=False)

        df['started_at'] = pd.to_datetime(df['started_at'])
        df['ended_at']   = pd.to_datetime(df['ended_at'])

        df = df.dropna(subset=['start_lat', 'start_lng', 'end_lat', 'end_lng'])

        df = df.sort_values('started_at').reset_index(drop=True)

        destino = os.path.join(dir_saida, os.path.basename(f))
        df.to_csv(destino, index=False)
        print(f"[{len(df)} linhas] {destino}")

# ── 4. Executa ───────────────────────────────────────────────────────
processar_mes_separado(CSVs_jan, out_jan)
processar_mes_separado(CSVs_set, out_set)   