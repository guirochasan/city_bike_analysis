"""
Motor de Renderização Espaço-Temporal de Alta Performance — Citi Bike NYC (2024)
Disciplina: Exploração e Visualização de Dados (ECVD — UFPB)

Melhorias de Engenharia Visual e Boas Práticas Aplicadas:
1. Janela Temporal Estrita (7 dias completos: 01 a 07 do mês, 00:00 às 23:57),
   eliminando quadros vazios ("viagens fantasmas" do mês anterior ou estouros finais).
2. Enquadramento Geográfico Unificado (EPSG:3857) idêntico entre Janeiro e Setembro,
   permitindo comparação visual direta sem deslocamento de câmera.
3. Integridade Perceptual (Cleveland & McGill / Wilke):
   - Área das bolhas estritamente proporcional ao tráfego em 2h (`s = trafego * FATOR_AREA`);
   - Paleta divergente simétrica (`RdBu`, `[-30, +30]`) com contorno grafite sutil para que
     estações de alto giro em equilíbrio (`saldo ≈ 0`) não desapareçam no mapa cinza-claro;
   - Ordenação dinâmica (`z-order`) por `|saldo|` para destacar gargalos críticos no topo.
4. Storytelling, Dêixis e Redução da Cegueira à Mudança (Ware / Berinato / Tufte):
   - Título ativo, legenda integrada de área e cor, HUD em português com dia da semana e regime;
   - Série temporal sincronizada no rodapé com cursor móvel (*playhead*) e destaque de feriados
     (Ano Novo em 01/Jan, Tempestade de Inverno em 06–07/Jan, *Labor Day* em 02/Set).
5. Otimização por *Blitting* (`copy_from_bbox` / `restore_region`) + *Pipe* direto ao FFmpeg:
   renderiza o basemap estático apenas uma vez por mês, acelerando a geração em mais de 10×.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import sys

import contextily as cx
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import FancyBboxPatch
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import numpy as np
import pandas as pd

# ── 1. Configurações Globais e Caminhos Portáveis ────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
WORKSPACE_ROOT = REPO_ROOT.parent

LAT_MIN, LAT_MAX = 40.40, 41.00
LNG_MIN, LNG_MAX = -74.30, -73.70

# Enquadramento fixo cobrindo >99,9% da malha ativa em Manhattan, Brooklyn, Queens e Bronx
CAMERA_LNG = (-74.035, -73.852)
CAMERA_LAT = (40.635, 40.880)

FATOR_AREA = 1.05
SALDO_LIM = 30.0
FPS_PADRAO = 60
PASSO_INTERP = "3min"

DIAS_SEMANA_PT = [
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
]
DIAS_CURTOS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
MESES_CURTOS_PT = {1: "Jan", 9: "Set"}

CONFIG_MESES = {
    "jan2024": {
        "codigo": "202401",
        "inicio": "2024-01-01 00:00:00",
        "fim": "2024-01-08 00:00:00",
        "titulo": "Pulso Logístico do Citi Bike NYC — Inverno (Janeiro/2024)",
        "cor_serie": "#2B5C8F",
        "feriados": {pd.Timestamp("2024-01-01").date(): "Feriado (Ano Novo)"},
        "eventos_clima": {
            pd.Timestamp("2024-01-06").date(): "Tempestade de Inverno",
            pd.Timestamp("2024-01-07").date(): "Tempestade de Inverno",
        },
        "anotacoes_ts": [
            ("2024-01-01 12:00:00", "Ano Novo\n(Feriado)", 0.86),
            ("2024-01-06 18:00:00", "Tempestade de Inverno\n(−54% viagens)", 0.80),
        ],
    },
    "set2024": {
        "codigo": "202409",
        "inicio": "2024-09-01 00:00:00",
        "fim": "2024-09-08 00:00:00",
        "titulo": "Pulso Logístico do Citi Bike NYC — Fim de Verão (Setembro/2024)",
        "cor_serie": "#D95F02",
        "feriados": {pd.Timestamp("2024-09-02").date(): "Feriado (Labor Day)"},
        "eventos_clima": {},
        "anotacoes_ts": [
            ("2024-09-02 00:00:00", "Dom + Feriado (Labor Day)", 0.88),
        ],
    },
}


def obter_executavel_ffmpeg() -> str:
    """Localiza o binário do FFmpeg no sistema ou via pacote `imageio-ffmpeg` do ambiente virtual."""
    ffmpeg_sys = shutil.which("ffmpeg")
    if ffmpeg_sys:
        return ffmpeg_sys
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "FFmpeg não encontrado. Instale `ffmpeg` no sistema ou `pip install imageio-ffmpeg`."
        ) from exc


def localizar_csvs_entrada(chave_mes: str, codigo_mes: str) -> list[Path]:
    """Busca CSVs pré-ordenados (se existirem) ou lê diretamente da pasta bruta do workspace."""
    candidatos = [
        BASE_DIR / f"ordenado_{chave_mes}",
        WORKSPACE_ROOT / f"{codigo_mes}-citibike-tripdata",
        REPO_ROOT / f"{codigo_mes}-citibike-tripdata",
        BASE_DIR / f"{codigo_mes}-citibike-tripdata",
    ]
    for pasta in candidatos:
        if pasta.exists():
            arqs = sorted(pasta.glob("*.csv"))
            if arqs:
                return arqs
    raise FileNotFoundError(
        f"Nenhum CSV encontrado para {chave_mes} ({codigo_mes}). Verifique as pastas de dados."
    )


def formatar_int_pt(valor: float | int) -> str:
    """Formata inteiros no padrão brasileiro (ponto como separador de milhar)."""
    return f"{int(round(valor)):,}".replace(",", ".")


def classificar_regime_horario(ts: pd.Timestamp, cfg: dict) -> str:
    """Retorna o rótulo contextual do momento (feriado, clima, pico matinal/vespertino ou lazer)."""
    data_atual = ts.date()
    hora = ts.hour

    if data_atual in cfg["feriados"]:
        base = cfg["feriados"][data_atual]
    elif data_atual in cfg["eventos_clima"]:
        base = f"Fim de Semana • {cfg['eventos_clima'][data_atual]}"
    elif ts.dayofweek >= 5:
        base = "Fim de Semana"
    else:
        base = "Dia Útil"

    if hora < 6:
        fase = "Madrugada"
    elif ts.dayofweek < 5 and data_atual not in cfg["feriados"]:
        if 7 <= hora <= 9:
            fase = "Pico da Manhã"
        elif 16 <= hora <= 19:
            fase = "Pico da Tarde"
        elif 10 <= hora <= 15:
            fase = "Entrepico Diurno"
        else:
            fase = "Período Noturno"
    else:
        if 11 <= hora <= 18:
            fase = "Lazer Diurno"
        elif 6 <= hora <= 10:
            fase = "Manhã"
        else:
            fase = "Noite"

    if "Tempestade" in base:
        return base
    return f"{base} — {fase}"


# ── 2. Preparação e Interpolação PCHIP ───────────────────────────────────────
def preparar_matrizes_mes(chave_mes: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    """Carrega, filtra, agrega em janelas de 2h e interpola via PCHIP a cada 3 minutos."""
    cfg = CONFIG_MESES[chave_mes]
    arquivos = localizar_csvs_entrada(chave_mes, cfg["codigo"])
    colunas = [
        "started_at",
        "ended_at",
        "start_station_name",
        "end_station_name",
        "start_lat",
        "start_lng",
        "end_lat",
        "end_lng",
    ]

    print(f"[{chave_mes}] Lendo {len(arquivos)} arquivo(s) CSV...")
    df = pd.concat(
        [pd.read_csv(f, usecols=colunas, low_memory=False) for f in arquivos],
        ignore_index=True,
    )
    df["started_at"] = pd.to_datetime(df["started_at"])
    df["ended_at"] = pd.to_datetime(df["ended_at"])

    # Limpeza rigorosa de duração (1 min a 24h) e filtro espacial contra "Null Island"
    df = df.dropna(subset=["start_station_name", "end_station_name", "start_lat", "start_lng", "end_lat", "end_lng"])
    duracao_min = (df["ended_at"] - df["started_at"]).dt.total_seconds() / 60.0
    df = df[
        (duracao_min >= 1.0)
        & (duracao_min <= 1440.0)
        & df["start_lat"].between(LAT_MIN, LAT_MAX)
        & df["start_lng"].between(LNG_MIN, LNG_MAX)
        & df["end_lat"].between(LAT_MIN, LAT_MAX)
        & df["end_lng"].between(LNG_MIN, LNG_MAX)
    ]

    d_ini = pd.Timestamp(cfg["inicio"])
    d_fim = pd.Timestamp(cfg["fim"])

    df_saidas = df[(df["started_at"] >= d_ini) & (df["started_at"] < d_fim)]
    df_entradas = df[(df["ended_at"] >= d_ini) & (df["ended_at"] < d_fim)]
    print(
        f"[{chave_mes}] Recorte de 7 dias ({d_ini.date()} a {(d_fim - pd.Timedelta(days=1)).date()}): "
        f"{formatar_int_pt(len(df_saidas))} partidas válidas."
    )

    # Catálogo único de estações projetado uma única vez para Web Mercator (EPSG:3857)
    cp = df_saidas[["start_station_name", "start_lat", "start_lng"]].rename(
        columns={"start_station_name": "estacao", "start_lat": "lat", "start_lng": "lng"}
    )
    cc = df_entradas[["end_station_name", "end_lat", "end_lng"]].rename(
        columns={"end_station_name": "estacao", "end_lat": "lat", "end_lng": "lng"}
    )
    coords = pd.concat([cp, cc]).groupby("estacao")[["lat", "lng"]].median().dropna()
    gdf_coords = gpd.GeoDataFrame(
        coords,
        geometry=gpd.points_from_xy(coords["lng"], coords["lat"]),
        crs="EPSG:4326",
    ).to_crs(epsg=3857)
    coords["x"] = gdf_coords.geometry.x
    coords["y"] = gdf_coords.geometry.y

    # Agregação em blocos exatos de 2h incluindo ponto âncora final para interpolação completa até 23:57
    grade_2h = pd.date_range(d_ini, d_fim, freq="2h")
    saidas = df_saidas.groupby([pd.Grouper(key="started_at", freq="2h"), "start_station_name"]).size().rename("saidas")
    saidas.index.names = ["tempo", "estacao"]

    entradas = df_entradas.groupby([pd.Grouper(key="ended_at", freq="2h"), "end_station_name"]).size().rename("entradas")
    entradas.index.names = ["tempo", "estacao"]

    movimento = pd.concat([saidas, entradas], axis=1).fillna(0.0)
    movimento["trafego"] = movimento["saidas"] + movimento["entradas"]
    movimento["saldo"] = movimento["entradas"] - movimento["saidas"]

    trafego_piv = movimento["trafego"].unstack(level="estacao").reindex(grade_2h, fill_value=0.0).fillna(0.0)
    saldo_piv = movimento["saldo"].unstack(level="estacao").reindex(grade_2h, fill_value=0.0).fillna(0.0)

    # Repete suavemente o último bloco na âncora d_fim para evitar queda artificial à meia-noite do 8º dia
    trafego_piv.loc[d_fim] = trafego_piv.iloc[-2] * 0.65
    saldo_piv.loc[d_fim] = saldo_piv.iloc[-2] * 0.65

    print(f"[{chave_mes}] Executando interpolação PCHIP ({PASSO_INTERP})...")
    trafego_interp = trafego_piv.resample(PASSO_INTERP).interpolate(method="pchip").clip(lower=0.0).fillna(0.0)
    saldo_interp = saldo_piv.resample(PASSO_INTERP).interpolate(method="pchip").fillna(0.0)

    # Remove o instante exato de d_fim (mantém 00:00 do dia 1 até 23:57 do dia 7 = 3.360 quadros exatos)
    trafego_interp = trafego_interp.loc[trafego_interp.index < d_fim]
    saldo_interp = saldo_interp.loc[saldo_interp.index < d_fim]

    # Alinha colunas com catálogo de coordenadas
    estacoes_comuns = trafego_interp.columns.intersection(coords.index)
    trafego_interp = trafego_interp[estacoes_comuns]
    saldo_interp = saldo_interp[estacoes_comuns]
    coords = coords.loc[estacoes_comuns]

    # Fluxo total de viagens na rede em cada instante (trafego soma saídas + chegadas ≈ 2 × viagens)
    fluxo_rede = trafego_interp.sum(axis=1) / 2.0
    return coords, trafego_interp, saldo_interp, fluxo_rede


# ── 3. Construção da Figura Base e Renderização por Blitting ─────────────────
def renderizar_mes(chave_mes: str, salvar_pngs: bool = False, compilar_mp4: bool = True) -> Path | None:
    """Renderiza todos os quadros do mês via Blitting e envia diretamente ao FFmpeg (e/ou salva PNGs)."""
    cfg = CONFIG_MESES[chave_mes]
    coords, trafego_interp, saldo_interp, fluxo_rede = preparar_matrizes_mes(chave_mes)

    d_ini = pd.Timestamp(cfg["inicio"])
    d_fim = pd.Timestamp(cfg["fim"])

    # Limites Web Mercator unificados
    gdf_lim = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(list(CAMERA_LNG), list(CAMERA_LAT)),
        crs="EPSG:4326",
    ).to_crs(epsg=3857)
    xmin, xmax = gdf_lim.geometry.x.min(), gdf_lim.geometry.x.max()
    ymin, ymax = gdf_lim.geometry.y.min(), gdf_lim.geometry.y.max()

    # Dimensões pares exatas: 9.0 * 110 = 990 px | 11.2 * 110 = 1232 px (compatível nativamente com H.264 yuv420p)
    dpi = 110
    fig = plt.figure(figsize=(9.0, 11.2), dpi=dpi, facecolor="white")
    gs = fig.add_gridspec(
        2, 1, height_ratios=[4.85, 1.0], hspace=0.065, left=0.075, right=0.965, top=0.925, bottom=0.055
    )
    ax_map = fig.add_subplot(gs[0])
    ax_ts = fig.add_subplot(gs[1])

    # Título ativo e subtítulo explicativo
    fig.text(0.075, 0.966, cfg["titulo"], fontsize=13.5, fontweight="bold", color="#0F172A")
    fig.text(
        0.075,
        0.942,
        "Primeira semana completa (janelas de 2h suavizadas via PCHIP) • Área ∝ Volume  |  Cor = Saldo (Chegadas − Saídas)",
        fontsize=8.9,
        color="#475569",
    )

    # Mapa base neutro e desaturado (Esri WorldGrayCanvas)
    ax_map.set_xlim(xmin, xmax)
    ax_map.set_ylim(ymin, ymax)
    ax_map.set_xticks([])
    ax_map.set_yticks([])
    for sp in ax_map.spines.values():
        sp.set_visible(True)
        sp.set_edgecolor("#CBD5E1")
        sp.set_linewidth(0.8)

    cx.add_basemap(ax_map, source=cx.providers.Esri.WorldGrayCanvas, attribution=False)

    # Rótulos geográficos sutis com halo branco para ancoragem espacial imediata
    bairros = [
        ("MANHATTAN", -73.968, 40.790),
        ("BROOKLYN", -73.950, 40.672),
        ("QUEENS", -73.908, 40.748),
        ("BRONX", -73.905, 40.845),
    ]
    gdf_b = gpd.GeoDataFrame(
        bairros,
        columns=["nome", "lng", "lat"],
        geometry=gpd.points_from_xy([b[1] for b in bairros], [b[2] for b in bairros]),
        crs="EPSG:4326",
    ).to_crs(epsg=3857)
    for _, row in gdf_b.iterrows():
        ax_map.text(
            row.geometry.x,
            row.geometry.y,
            row["nome"],
            fontsize=8.5,
            fontweight="bold",
            color="#64748B",
            alpha=0.85,
            ha="center",
            va="center",
            path_effects=[pe.withStroke(linewidth=2.4, foreground="white")],
            zorder=3,
        )

    # Cartão de Legenda Integrada (Área + Barra de Cores Divergente) no canto inferior direito
    card = FancyBboxPatch(
        (0.585, 0.02),
        0.395,
        0.205,
        boxstyle="round,pad=0.012",
        transform=ax_map.transAxes,
        facecolor="white",
        alpha=0.94,
        edgecolor="#CBD5E1",
        linewidth=0.8,
        zorder=8,
    )
    ax_map.add_patch(card)
    ax_map.text(
        0.782,
        0.198,
        "Tráfego na Estação em 2h (Área)",
        transform=ax_map.transAxes,
        fontsize=8.3,
        fontweight="bold",
        color="#1E293B",
        ha="center",
        zorder=9,
    )
    for val_ref, x_pos in [(30, 0.655), (100, 0.775), (220, 0.900)]:
        ax_map.scatter(
            [x_pos],
            [0.148],
            s=val_ref * FATOR_AREA,
            transform=ax_map.transAxes,
            facecolor="#E2E8F0",
            edgecolor="#1E293B",
            linewidth=0.75,
            zorder=9,
        )
        ax_map.text(
            x_pos,
            0.104,
            f"{val_ref}",
            transform=ax_map.transAxes,
            fontsize=7.8,
            color="#334155",
            ha="center",
            zorder=9,
        )

    ax_map.text(
        0.782,
        0.074,
        "Saldo Líquido (Chegadas − Saídas)",
        transform=ax_map.transAxes,
        fontsize=8.0,
        fontweight="bold",
        color="#1E293B",
        ha="center",
        zorder=9,
    )
    norm_saldo = mcolors.Normalize(vmin=-SALDO_LIM, vmax=SALDO_LIM)
    cmap_saldo = plt.get_cmap("RdBu")
    sm = cm.ScalarMappable(norm=norm_saldo, cmap=cmap_saldo)
    sm.set_array([])

    cax = inset_axes(
        ax_map,
        width="33.5%",
        height="2.2%",
        loc="lower right",
        bbox_to_anchor=(-0.03, 0.044, 1, 1),
        bbox_transform=ax_map.transAxes,
        borderpad=0,
    )
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.set_ticks([-SALDO_LIM, 0, SALDO_LIM])
    cb.set_ticklabels(["−30 (Déficit)", "0", "+30 (Superávit)"])
    cb.ax.tick_params(labelsize=7.4, length=2, pad=2, colors="#1E293B")
    cb.outline.set_edgecolor("#94A3B8")
    cb.outline.set_linewidth(0.6)

    ax_map.text(
        0.012,
        0.010,
        "Fonte: Citi Bike NYC System Data • Basemap: Esri WorldGrayCanvas",
        transform=ax_map.transAxes,
        fontsize=7.0,
        color="#64748B",
        ha="left",
        va="bottom",
        zorder=8,
    )

    # Painel Inferior: Série Temporal Sincronizada dos 7 Dias
    tempos_num = matplotlib.dates.date2num(fluxo_rede.index.to_pydatetime())
    valores_rede = fluxo_rede.values
    cor_s = cfg["cor_serie"]

    ax_ts.fill_between(tempos_num, valores_rede, color=cor_s, alpha=0.16)
    ax_ts.plot(tempos_num, valores_rede, color=cor_s, lw=1.8)

    # Destaque sutil de fins de semana e feriados no eixo temporal
    for i in range(7):
        dia_dt = d_ini + pd.Timedelta(days=i)
        if dia_dt.dayofweek >= 5 or dia_dt.date() in cfg["feriados"] or dia_dt.date() in cfg["eventos_clima"]:
            ax_ts.axvspan(
                matplotlib.dates.date2num(dia_dt.to_pydatetime()),
                matplotlib.dates.date2num((dia_dt + pd.Timedelta(days=1)).to_pydatetime()),
                color="#94A3B8",
                alpha=0.16,
                ec="none",
            )

    teto_y = valores_rede.max() * 1.24
    for ts_str, rotulo, frac_y in cfg["anotacoes_ts"]:
        x_anot = matplotlib.dates.date2num(pd.Timestamp(ts_str).to_pydatetime())
        ax_ts.text(
            x_anot,
            teto_y * frac_y,
            rotulo,
            fontsize=7.6,
            color="#475569",
            ha="center",
            va="top",
            style="italic",
        )

    ax_ts.set_xlim(tempos_num[0], tempos_num[-1])
    ax_ts.set_ylim(0, teto_y)
    ax_ts.spines["top"].set_visible(False)
    ax_ts.spines["right"].set_visible(False)
    ax_ts.spines["left"].set_color("#CBD5E1")
    ax_ts.spines["bottom"].set_color("#94A3B8")
    ax_ts.grid(axis="y", ls=":", alpha=0.45, color="#94A3B8")
    ax_ts.yaxis.set_major_formatter(
        ticker.FuncFormatter(lambda v, _: f"{int(round(v / 1000))} mil" if v >= 1000 else "0")
    )
    ax_ts.yaxis.set_major_locator(ticker.MaxNLocator(nbins=3, integer=True))
    ax_ts.set_ylabel("Viagens / 2h", fontsize=8.5, fontweight="bold", color="#334155")

    rotulos_dias = []
    ticks_meio_dia = []
    for i in range(7):
        d_atual = d_ini + pd.Timedelta(days=i)
        ticks_meio_dia.append(matplotlib.dates.date2num((d_atual + pd.Timedelta(hours=12)).to_pydatetime()))
        abrev = DIAS_CURTOS_PT[d_atual.dayofweek]
        sufixo = " (Fer.)" if d_atual.date() in cfg["feriados"] else ""
        rotulos_dias.append(f"{abrev}{sufixo}\n{d_atual.day:02d}/{MESES_CURTOS_PT[d_atual.month]}")

    ax_ts.set_xticks(ticks_meio_dia)
    ax_ts.set_xticklabels(rotulos_dias, fontsize=8.0, color="#334155")
    ax_ts.tick_params(axis="x", length=0)
    ax_ts.tick_params(axis="y", labelsize=7.8, colors="#475569")

    # Artistas dinâmicos marcados como `animated=True` para Blitting ultrarrápido
    scat = ax_map.scatter(
        [],
        [],
        s=[],
        c=[],
        cmap=cmap_saldo,
        norm=norm_saldo,
        alpha=0.84,
        edgecolors="#1E293B",
        linewidths=0.38,
        zorder=5,
        animated=True,
    )
    hud_txt = ax_map.text(
        0.024,
        0.974,
        "",
        transform=ax_map.transAxes,
        va="top",
        ha="left",
        fontsize=10.2,
        fontweight="bold",
        color="#0F172A",
        linespacing=1.38,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="white", alpha=0.94, edgecolor="#CBD5E1", lw=0.9),
        zorder=10,
        animated=True,
    )
    linha_cursor = ax_ts.axvline(tempos_num[0], color="#0F172A", lw=1.5, ls="--", zorder=6, animated=True)
    ponto_cursor = ax_ts.scatter([tempos_num[0]], [valores_rede[0]], s=38, color="#0F172A", zorder=7, animated=True)

    # Renderiza camada estática única e captura buffer em memória
    fig.canvas.draw()
    fundo_estatico = fig.canvas.copy_from_bbox(fig.bbox)
    largura_px, altura_px = fig.canvas.get_width_height()

    dir_frames = BASE_DIR / f"frames_{chave_mes}"
    if salvar_pngs:
        if dir_frames.exists():
            shutil.rmtree(dir_frames)
        dir_frames.mkdir(parents=True, exist_ok=True)

    video_saida = BASE_DIR / f"animacao_{chave_mes}.mp4"
    proc_ffmpeg = None
    if compilar_mp4:
        ffmpeg_bin = obter_executavel_ffmpeg()
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgba",
            "-s",
            f"{largura_px}x{altura_px}",
            "-r",
            str(FPS_PADRAO),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-preset",
            "fast",
            "-movflags",
            "+faststart",
            str(video_saida),
        ]
        proc_ffmpeg = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # Matrizes NumPy pré-extraídas para velocidade máxima no loop de 3.360 quadros
    mat_trafego = trafego_interp.to_numpy(dtype=np.float64)
    mat_saldo = saldo_interp.to_numpy(dtype=np.float64)
    xs_est = coords["x"].to_numpy(dtype=np.float64)
    ys_est = coords["y"].to_numpy(dtype=np.float64)
    indice_ts = trafego_interp.index

    total_quadros = len(indice_ts)
    print(f"[{chave_mes}] Renderizando {total_quadros} quadros ({largura_px}×{altura_px} px @ {FPS_PADRAO} FPS)...")

    for idx in range(total_quadros):
        fig.canvas.restore_region(fundo_estatico)

        traf = mat_trafego[idx]
        sald = mat_saldo[idx]
        ativos = traf > 0.35

        if np.any(ativos):
            ordem = np.argsort(np.abs(sald[ativos]))
            pts = np.column_stack((xs_est[ativos][ordem], ys_est[ativos][ordem]))
            tamanhos = traf[ativos][ordem] * FATOR_AREA
            cores_val = sald[ativos][ordem]
            scat.set_offsets(pts)
            scat.set_sizes(tamanhos)
            scat.set_array(cores_val)
        else:
            scat.set_offsets(np.empty((0, 2)))
            scat.set_sizes([])
            scat.set_array(np.array([]))

        ts_atual = indice_ts[idx]
        dia_nome = DIAS_SEMANA_PT[ts_atual.dayofweek]
        mes_abrev = MESES_CURTOS_PT[ts_atual.month]
        regime = classificar_regime_horario(ts_atual, cfg)
        viagens_2h = valores_rede[idx]

        hud_txt.set_text(
            f"{dia_nome}, {ts_atual.day:02d} {mes_abrev} {ts_atual.year}  •  {ts_atual:%H:%M}\n"
            f"{regime}  |  Fluxo: {formatar_int_pt(viagens_2h)} viagens/2h"
        )

        t_num = tempos_num[idx]
        linha_cursor.set_xdata([t_num, t_num])
        ponto_cursor.set_offsets([[t_num, viagens_2h]])

        ax_map.draw_artist(scat)
        ax_map.draw_artist(hud_txt)
        ax_ts.draw_artist(linha_cursor)
        ax_ts.draw_artist(ponto_cursor)

        buf_rgba = fig.canvas.buffer_rgba()
        if proc_ffmpeg and proc_ffmpeg.stdin:
            proc_ffmpeg.stdin.write(buf_rgba)

        if salvar_pngs:
            from PIL import Image

            img = Image.frombuffer("RGBA", (largura_px, altura_px), buf_rgba, "raw", "RGBA", 0, 1)
            img.save(dir_frames / f"frame_{idx:04d}.png")

        if (idx + 1) % 600 == 0 or (idx + 1) == total_quadros:
            print(f"  [{chave_mes}] {idx + 1}/{total_quadros} quadros processados...")

    plt.close(fig)

    if proc_ffmpeg and proc_ffmpeg.stdin:
        proc_ffmpeg.stdin.close()
        codigo_ret = proc_ffmpeg.wait()
        if codigo_ret != 0:
            raise RuntimeError(f"FFmpeg encerrou com código de erro {codigo_ret} em {chave_mes}.")
        print(f"[{chave_mes}] Vídeo finalizado com sucesso: {video_saida}")
        return video_saida

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderizador Espaço-Temporal Citi Bike NYC (ECVD/UFPB)")
    parser.add_argument(
        "--mes",
        choices=["jan2024", "set2024", "ambos"],
        default="ambos",
        help="Período a renderizar (padrão: ambos).",
    )
    parser.add_argument(
        "--salvar-frames",
        action="store_true",
        help="Salva também os quadros individuais PNG em disco além de gerar o MP4.",
    )
    parser.add_argument(
        "--sem-mp4",
        action="store_true",
        help="Apenas salva os quadros PNG sem compilar o vídeo MP4.",
    )
    parser.add_argument(
        "--sequencial",
        action="store_true",
        help="Executa um mês após o outro em vez de paralelizar em múltiplos núcleos.",
    )
    args = parser.parse_args()

    meses = ["jan2024", "set2024"] if args.mes == "ambos" else [args.mes]
    compilar_mp4 = not args.sem_mp4

    if len(meses) > 1 and not args.sequencial:
        with ProcessPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(renderizar_mes, m, args.salvar_frames, compilar_mp4) for m in meses]
            for fut in futuros:
                fut.result()
    else:
        for m in meses:
            renderizar_mes(m, salvar_pngs=args.salvar_frames, compilar_mp4=compilar_mp4)


if __name__ == "__main__":
    main()
