"""
Compilador de Vídeo H.264 via FFmpeg — Citi Bike NYC (2024)
Disciplina: Exploração e Visualização de Dados (ECVD — UFPB)

Compila diretórios de quadros PNG (`frames_jan2024`, `frames_set2024`) em vídeos MP4 a 60 FPS
utilizando `image2pipe`, ou aciona automaticamente a renderização direta em memória (`cria_frames.py`)
caso os diretórios intermediários de PNGs não estejam presentes em disco.
Compatível com Windows, Linux e macOS (detecta `ffmpeg` nativo ou `imageio-ffmpeg` do `.venv`).
"""

from pathlib import Path
import shutil
import subprocess

from cria_frames import BASE_DIR, FPS_PADRAO, obter_executavel_ffmpeg, renderizar_mes

DIRS_FRAMES = {
    "jan2024": BASE_DIR / "frames_jan2024",
    "set2024": BASE_DIR / "frames_set2024",
}


def compilar_de_pngs(chave_mes: str, diretorio: Path, fps: int = FPS_PADRAO) -> Path:
    """Injeta arquivos PNG ordenados continuamente via `image2pipe` no FFmpeg."""
    arquivos = sorted(
        diretorio.glob("frame_*.png"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not arquivos:
        raise FileNotFoundError(f"Nenhum quadro PNG encontrado em {diretorio}")

    ffmpeg_bin = obter_executavel_ffmpeg()
    video_saida = BASE_DIR / f"animacao_{chave_mes}.mp4"

    print(f"[{chave_mes}] Compilando {len(arquivos)} quadros PNG a {fps} FPS -> {video_saida.name}...")
    comando = [
        ffmpeg_bin,
        "-y",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
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

    processo = subprocess.Popen(comando, stdin=subprocess.PIPE)
    assert processo.stdin is not None
    for arq in arquivos:
        processo.stdin.write(arq.read_bytes())
    processo.stdin.close()
    codigo = processo.wait()
    if codigo != 0:
        raise RuntimeError(f"Erro ao compilar vídeo {chave_mes} (código {codigo}).")

    print(f"[{chave_mes}] Vídeo salvo com sucesso em: {video_saida}")
    return video_saida


def main() -> None:
    for mes, pasta_frames in DIRS_FRAMES.items():
        if pasta_frames.exists() and any(pasta_frames.glob("frame_*.png")):
            compilar_de_pngs(mes, pasta_frames)
        else:
            print(f"[{mes}] Pasta '{pasta_frames.name}' ausente; acionando renderização direta via Blitting...")
            renderizar_mes(mes, salvar_pngs=False, compilar_mp4=True)


if __name__ == "__main__":
    main()
