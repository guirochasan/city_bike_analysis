import pandas as pd
import geopandas as gpd
import contextily as cx
import matplotlib.pyplot as plt
import os
import glob

# ── 1. Diretórios de entrada (CSVs já ordenados) ─────────────────────
DIRS_ENTRADA = {
    'jan2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/ordenado_jan2024',
    'set2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/ordenado_set2024',
}

# Diretórios de saída dos frames (serão criados)
DIRS_SAIDA = {
    'jan2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/frames_jan2024',
    'set2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/frames_set2024',
}

for d in DIRS_SAIDA.values():
    os.makedirs(d, exist_ok=True)

# ── 2. Função principal ───────────────────────────────────────────────
def gerar_animacao(dir_entrada, dir_saida, nome_mes):
    # Lê todos os CSVs do diretório e junta em um único DataFrame
    arquivos = sorted(glob.glob(os.path.join(dir_entrada, '*.csv')))
    df = pd.concat(
        [pd.read_csv(f, parse_dates=['started_at', 'ended_at'], low_memory=False) for f in arquivos],
        ignore_index=True
    )
    print(f"[{nome_mes}] {len(df)} linhas carregadas de {len(arquivos)} arquivo(s).")

    # Enquadramento fixo
    gdf_limites = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(
            [df['start_lng'].min(), df['start_lng'].max()],
            [df['start_lat'].min(), df['start_lat'].max()]
        ), crs="EPSG:4326"
    ).to_crs(epsg=3857)

    xmin, xmax = gdf_limites.geometry.x.min(), gdf_limites.geometry.x.max()
    ymin, ymax = gdf_limites.geometry.y.min(), gdf_limites.geometry.y.max()

    # Agrupamento por fatias de 6h
    fatias_tempo = df.groupby(pd.Grouper(key='started_at', freq='6h'))
    frame_idx = 0

    for periodo, dados in fatias_tempo:
        if dados.empty:
            continue

        partidas = dados.groupby(['start_station_name', 'start_lat', 'start_lng']).size().reset_index(name='saidas')
        chegadas = dados.groupby(['end_station_name', 'end_lat', 'end_lng']).size().reset_index(name='entradas')

        partidas.columns = ['estacao', 'lat', 'lng', 'saidas']
        chegadas.columns = ['estacao', 'lat', 'lng', 'entradas']

        estacoes = pd.merge(partidas, chegadas, on=['estacao', 'lat', 'lng'], how='outer').fillna(0)
        estacoes['trafego_total'] = estacoes['saidas'] + estacoes['entradas']
        estacoes['saldo_logistico'] = estacoes['entradas'] - estacoes['saidas']

        gdf_frame = gpd.GeoDataFrame(
            estacoes,
            geometry=gpd.points_from_xy(estacoes.lng, estacoes.lat),
            crs="EPSG:4326"
        ).to_crs(epsg=3857)

        fig, ax = plt.subplots(figsize=(10, 10))
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_axis_off()

        if not gdf_frame.empty:
            gdf_frame.plot(
                ax=ax,
                markersize=gdf_frame['trafego_total'] * 2,
                column='saldo_logistico',
                cmap='RdBu',
                vmin=-30,
                vmax=30,
                alpha=0.8,
                edgecolor='white',
                linewidth=0.3
            )

        # URL direta do CartoDB (estilo Positron sem rótulos) com injeção da chave API
        chave_api = "cb1_4zy1_1_005da78b8530b5f92fb82d18"
        url_carto = f"https://a.basemaps.cartocdn.com/light_nolabels/{{z}}/{{x}}/{{y}}.png?api_key={chave_api}"

        # Adiciona o mapa base usando a URL autenticada
        cx.add_basemap(ax, source=url_carto, reset_cache=True)

        texto_data = periodo.strftime('%Y-%m-%d %H:%M')
        ax.text(0.05, 0.95, texto_data, transform=ax.transAxes, fontsize=16,
                fontweight='bold', bbox=dict(facecolor='white', alpha=0.9, edgecolor='none', pad=5))

        nome_arquivo = os.path.join(dir_saida, f"frame_{frame_idx:04d}.png")
        plt.savefig(nome_arquivo, dpi=120, bbox_inches='tight', pad_inches=0)
        plt.close(fig)

        frame_idx += 1
        if frame_idx % 20 == 0:
            print(f"  [{nome_mes}] {frame_idx} quadros processados...")

    print(f"[{nome_mes}] Finalizado! {frame_idx} quadros → '{dir_saida}'")

# ── 3. Executa para cada mês ──────────────────────────────────────────
for mes, dir_ent in DIRS_ENTRADA.items():
    gerar_animacao(dir_ent, DIRS_SAIDA[mes], mes)   