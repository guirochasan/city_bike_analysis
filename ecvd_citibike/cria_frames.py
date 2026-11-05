import pandas as pd
import geopandas as gpd
import contextily as cx
import matplotlib.pyplot as plt
import os
import glob
import shutil

# ── 1. Diretórios de entrada (CSVs já ordenados) ─────────────────────
DIRS_ENTRADA = {
    'jan2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/ordenado_jan2024',
    'set2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/ordenado_set2024',
}

# Diretórios de saída dos frames
DIRS_SAIDA = {
    'jan2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/frames_jan2024',
    'set2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/frames_set2024',
}

for d in DIRS_SAIDA.values():
    if os.path.exists(d):
        shutil.rmtree(d) # apaga pasta velha
    os.makedirs(d, exist_ok=True) # cria pasta nova

# ── 2. Função principal ───────────────────────────────────────────────
def gerar_animacao(dir_entrada, dir_saida, nome_mes):
    # Lê todos os CSVs do diretório e junta em um único DataFrame
    arquivos = sorted(glob.glob(os.path.join(dir_entrada, '*.csv')))
    df = pd.concat(
        [pd.read_csv(f, parse_dates=['started_at', 'ended_at'], low_memory=False) for f in arquivos],
        ignore_index=True
    )
    
    # ── FILTRO ESPACIAL (Foco em Nova York, previne o mapa no Oceano Atlântico) ──
    df = df[
        (df['start_lat'] >= 40.4) & (df['start_lat'] <= 41.0) &
        (df['start_lng'] >= -74.3) & (df['start_lng'] <= -73.7) &
        (df['end_lat'] >= 40.4) & (df['end_lat'] <= 41.0) &
        (df['end_lng'] >= -74.3) & (df['end_lng'] <= -73.7)
    ]
    
    # ── FILTRO TEMPORAL (Apenas a 1ª semana do mês) ──
    data_inicial = df['started_at'].min()
    data_final = data_inicial + pd.Timedelta(days=7)
    df = df[(df['started_at'] >= data_inicial) & (df['started_at'] <= data_final)]
    
    print(f"[{nome_mes}] Filtros aplicados! {len(df)} viagens válidas entre {data_inicial.date()} e {data_final.date()}.")

    # Extrai o catálogo único de coordenadas
    coords_partidas = df[['start_station_name', 'start_lat', 'start_lng']].rename(columns={'start_station_name':'estacao', 'start_lat':'lat', 'start_lng':'lng'})
    coords_chegadas = df[['end_station_name', 'end_lat', 'end_lng']].rename(columns={'end_station_name':'estacao', 'end_lat':'lat', 'end_lng':'lng'})
    
    coords = pd.concat([coords_partidas, coords_chegadas]).drop_duplicates(subset=['estacao']).set_index('estacao')
    coords['lat'] = pd.to_numeric(coords['lat'], errors='coerce')
    coords['lng'] = pd.to_numeric(coords['lng'], errors='coerce')
    coords = coords.dropna()

    # Enquadramento fixo da câmera (imune a erros de GPS)
    gdf_limites = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            [coords['lng'].min(), coords['lng'].max()],
            [coords['lat'].min(), coords['lat'].max()]
        ), crs="EPSG:4326"
    ).to_crs(epsg=3857)

    xmin, xmax = gdf_limites.geometry.x.min(), gdf_limites.geometry.x.max()
    ymin, ymax = gdf_limites.geometry.y.min(), gdf_limites.geometry.y.max()

    # ── Agregação Base (O Relógio da Realidade cravado em 1 hora) ──
    df_saidas = df.rename(columns={'start_station_name': 'estacao'})
    saidas = df_saidas.groupby([pd.Grouper(key='started_at', freq='2h'), 'estacao']).size().rename('saidas')
    saidas.index.names = ['tempo', 'estacao']

    df_entradas = df.rename(columns={'end_station_name': 'estacao'})
    entradas = df_entradas.groupby([pd.Grouper(key='ended_at', freq='2h'), 'estacao']).size().rename('entradas')
    entradas.index.names = ['tempo', 'estacao']

    movimento = pd.concat([saidas, entradas], axis=1).fillna(0)
    movimento['trafego'] = movimento['saidas'] + movimento['entradas']
    movimento['saldo'] = movimento['entradas'] - movimento['saidas']

    # ── Pivoteamento e Interpolação Não-Linear (O Relógio da Animação a cada 10 min) ──
    trafego_pivot = movimento['trafego'].unstack(level='estacao').fillna(0)
    saldo_pivot = movimento['saldo'].unstack(level='estacao').fillna(0)

    # O método 'pchip' garante que o crescimento da bolha acelere e desacelere suavemente 
    trafego_interp = trafego_pivot.resample('3min').interpolate(method='pchip').fillna(0)
    saldo_interp = saldo_pivot.resample('3min').interpolate(method='pchip').fillna(0)

    # ── Motor de Renderização ──
    frame_idx = 0
    for timestamp in trafego_interp.index:
        frame_data = pd.DataFrame({
            'trafego': trafego_interp.loc[timestamp],
            'saldo': saldo_interp.loc[timestamp]
        }).join(coords, how='inner')

        frame_data = frame_data[frame_data['trafego'] > 0.2].reset_index()

        fig, ax = plt.subplots(figsize=(10, 10))
        ax.set_axis_off()

        if not frame_data.empty:
            gdf_frame = gpd.GeoDataFrame(
                frame_data,
                geometry=gpd.points_from_xy(frame_data.lng, frame_data.lat),
                crs="EPSG:4326"
            ).to_crs(epsg=3857)

            gdf_frame.plot(
                ax=ax,
                markersize=gdf_frame['trafego'] * 2,
                column='saldo',
                cmap='RdBu',
                vmin=-20,
                vmax=20,
                alpha=0.8,
                edgecolor='white',
                linewidth=0.3
            )

        # ── CADEADO DA CÂMERA (A CORREÇÃO ESTÁ AQUI) ──
        # Forçar os limites AQUI anula o auto-zoom do GeoPandas nas madrugadas
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)

        cx.add_basemap(ax, source=cx.providers.Esri.WorldGrayCanvas)

        texto_data = timestamp.strftime('%Y-%m-%d %H:%M')
        ax.text(0.05, 0.95, texto_data, transform=ax.transAxes, fontsize=16,
                fontweight='bold', bbox=dict(facecolor='white', alpha=0.9, edgecolor='none', pad=5))

        nome_arquivo = os.path.join(dir_saida, f"frame_{frame_idx:04d}.png")
        plt.savefig(nome_arquivo, dpi=120, bbox_inches='tight', pad_inches=0)
        plt.close(fig)

        frame_idx += 1
        if frame_idx % 50 == 0:
            print(f"  [{nome_mes}] {frame_idx} quadros interpolados e gerados...")

    print(f"[{nome_mes}] Concluído! {frame_idx} quadros → '{dir_saida}'")

# ── 3. Executa para cada mês ──────────────────────────────────────────
for mes, dir_ent in DIRS_ENTRADA.items():
    gerar_animacao(dir_ent, DIRS_SAIDA[mes], mes)