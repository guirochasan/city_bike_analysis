# Análise de Mobilidade e Fluxo Espaço-Temporal: Citi Bike NYC

## 1. Visão Geral do Projeto
Este projeto tem como objetivo criar visualizações de alta qualidade e animações cronológicas baseadas em dados do sistema de compartilhamento de bicicletas Citi Bike em Nova York. O foco recai sobre a análise comparativa entre dois períodos distintos (Janeiro e Setembro de 2024), evidenciando o fluxo logístico de bicicletas, o status das estações (déficit vs. superávit) e as tendências temporais de mobilidade urbana.

## 2. Estrutura Tecnológica e Metodologia

Para garantir uma renderização fluida e rigor matemático, o pipeline de dados foi construído com as seguintes tecnologias e lógicas:

### 2.1. Ferramentas Utilizadas
* **Pandas:** Manipulação, agregação e pivoteamento de grandes volumes de dados temporais.
* **GeoPandas:** Conversão de coordenadas e posicionamento geográfico.
* **Matplotlib & Contextily:** Motor de renderização estática utilizando o basemap *Esri WorldGrayCanvas* para evitar conflitos de API Keys e garantir um fundo neutro.
* **FFmpeg:** Compilação das imagens estáticas em vídeo via injeção contínua (demuxer `image2pipe`), contornando limitações do codec H.264 (ajuste de proporções ímpares).

### 2.2. Lógica Espacial e Limpeza
* **Projeção:** Os dados brutos foram convertidos do sistema EPSG:4326 (Lat/Long padrão) para o EPSG:3857 (Web Mercator), essencial para o plot preciso sobre mapas projetados.
* **Filtro de "Null Island":** Implementação de barreiras geográficas estritas (Latitude 40.4 a 41.0 e Longitude -74.3 a -73.7) para descartar dados corrompidos de GPS que forçavam o enquadramento da câmera para o Oceano Atlântico.
* **Cadeado de Câmera:** Travamento dos limites dos eixos (`xlim`, `ylim`) independentemente do volume de tráfego, impedindo o auto-zoom do GeoPandas durante as madrugadas de baixa atividade.

### 2.3. Lógica Temporal e Interpolação Orgânica
* **O Relógio da Realidade:** Agrupamento dos dados extraídos em janelas exatas de **1 hora** para capturar com precisão os picos de trânsito reais, sem diluir informações importantes.
* **O Relógio da Animação:** Para evitar uma animação com saltos abruptos ("robótica"), aplicou-se a interpolação **PCHIP** (Piecewise Cubic Hermite Interpolating Polynomial) com *resample* de 10 minutos. Isso gera 6 quadros por hora, onde o crescimento e retração das bolhas acelera e desacelera de forma não-linear, mimetizando perfeitamente o comportamento orgânico da cidade.
* **Recorte Analítico:** Processamento otimizado focado nos 7 primeiros dias de cada mês, gerando aproximadamente 1.008 frames que resultam em animações concisas de ~33 segundos (a 30 FPS).

---

## 3. Modelos de Demonstração

Abaixo estão os resultados renderizados. Os vídeos ilustram o comportamento da rede e o "respirar" da cidade.

* **Animação - Inverno (Janeiro de 2024):** 
  * [ INSIRA AQUI O LINK / CAMINHO DO VÍDEO animacao_jan2024.mp4 ]
  * **Observações do período:** [ Descreva aqui como o frio afetou a velocidade das bolhas ou o volume geral do mapa. ]

* **Animação - Fim de Verão (Setembro de 2024):** 
  * [ INSIRA AQUI O LINK / CAMINHO DO VÍDEO animacao_set2024.mp4 ]
  * **Observações do período:** [ Descreva as diferenças visíveis de volume e comportamento em relação a janeiro. ]

---

## 4. Critérios de Avaliação

O projeto foi submetido aos seguintes critérios técnicos e visuais:

### 4.1. Visualização de Fluxo e Status das Estações (Surplus/Déficit)
A paleta divergente (`RdBu`) mapeia perfeitamente a logística do sistema:
* **Bolhas Azuis (Superávit):** Estações recebendo mais bicicletas do que despachando (ex: áreas comerciais de manhã).
* **Bolhas Vermelhas (Déficit):** Estações esvaziando rapidamente.
* O tamanho dinâmico da bolha (`trafego_total`) ilustra a intensidade bruta do ponto geométrico, enquanto a cor conta a história do saldo logístico.
* **Avaliação:** [ Insira se o contraste visual cumpriu o objetivo e se o crescimento não-linear (pchip) ficou natural. ]

### 4.2. Legibilidade de Tendências Temporais
* O letreiro com o *timestamp* posicionado no canto superior acompanha o avanço temporal, permitindo ao observador cruzar instantaneamente o inchaço visual do mapa com os horários de pico reais (08:00 AM e 05:00 PM).
* **Avaliação:** [ Insira se a janela de 7 dias foi suficiente para provar o ritmo cíclico pendular entre dias úteis e finais de semana. ]

### 4.3. Eficiência de Engenharia e Processamento
* A transição de Folium dinâmico para imagens estáticas com GeoPandas eliminou problemas de restrição em notebooks.
* A automação do pipeline (limpeza prévia da pasta com `shutil` e uso da biblioteca SciPy para calcular pontos cegos dos dados) transformou horas de processamento em uma renderização otimizada.
* **Avaliação:** [ Descreva sua experiência final com o tempo de renderização do código em Python vs FFmpeg. ]

---

## 5. Conclusões Finais

[ Escreva suas conclusões analíticas sobre o experimento espacial, os padrões de mobilidade da cidade de Nova York descobertos no mapa e próximos passos/melhorias para o futuro. ]