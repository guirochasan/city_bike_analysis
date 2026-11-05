import subprocess
import os
import glob

# 1. Diretórios de entrada
DIRS_FRAMES = {
    'jan2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/frames_jan2024',
    'set2024': '/home/guirocha/city_bike_analysis/ecvd_citibike/frames_set2024',
}

FPS = 60

for mes, diretorio in DIRS_FRAMES.items():
    video_saida = f"/home/guirocha/city_bike_analysis/ecvd_citibike/animacao_{mes}.mp4"
    
    if not os.path.exists(diretorio):
        continue
        
    print(f"[{mes}] Ordenando quadros matematicamente...")
    arquivos = glob.glob(os.path.join(diretorio, '*.png'))
    if not arquivos:
        continue
        
    # Ordenação rigorosa pelo número do frame
    arquivos.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0]))
    
    print(f"[{mes}] Injetando quadros contínuos no FFmpeg a {FPS} FPS...")
    
    # 2. Comando usando 'image2pipe'
    comando = [
        'ffmpeg',
        '-y',
        '-f', 'image2pipe',       
        '-vcodec', 'png',         
        '-framerate', str(FPS),   
        '-i', '-',                
        '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', # FILTRO: Força dimensões pares
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-preset', 'fast',
        video_saida
    ]
    
    try:
        # Abre o subprocesso mantendo o "tubo" de comunicação aberto
        processo = subprocess.Popen(comando, stdin=subprocess.PIPE)
        
        # O Python envia as imagens uma a uma, na ordem exata, direto para a memória do FFmpeg
        for arq in arquivos:
            with open(arq, 'rb') as f:
                processo.stdin.write(f.read())
                
        # Fecha o tubo (avisa ao FFmpeg que acabou) e espera o vídeo ser finalizado
        processo.stdin.close()
        processo.wait()
        
        print(f"[{mes}] Sucesso! Vídeo compilado em: {video_saida}\n")
        
    except Exception as e:
        print(f"[{mes}] Erro ao renderizar o vídeo: {e}\n")