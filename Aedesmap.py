# Aedesmap.py
# ----------------------------------------------------------------
# Versão V18: mesmo que V17, mas agora inclui de volta a parte de
# filtragem por período (--inicio / --fim / --ultimos_dias).
# Nenhum outro trecho do V17 foi alterado; apenas adicionamos o parsing
# e o filtro de datas antes de gerar o mapa.
# ----------------------------------------------------------------

import argparse
import pandas as pd
import geopandas as gpd
import folium
from folium.plugins import HeatMap
from datetime import datetime, timedelta

OCORRE_JSON = "ocorrencias_SP_chatbot_REAL_v5.json"
UBS_GEOJSON = "ubs_SP_oficiais.geojson"
DST_SHP      = "SIRGAS_SHP_distrito.shp"  # shapefile contendo todos os distritos de SP

# ————— Parâmetros do HeatMap —————
gradient     = {
    0.2: "#3a7ee7",
    0.5: "#6ed8e7",
    0.8: "#ffff66",
    1.0: "#ff0000",
}
radius       = 35
blur         = 18
min_opacity  = 0.1   # variável continua definida, mas no HeatMap usaremos 0.1 conforme V17

#
# ➤ 0️⃣: PARSE DOS ARGUMENTOS DE PERÍODO
#
parser = argparse.ArgumentParser(
    description="Gera mapa de calor com filtro opcional de período (--inicio, --fim ou --ultimos_dias)."
)
parser.add_argument(
    "--inicio",
    help="Data de início do período (formato YYYY-MM-DD).",
    required=False,
    type=str,
)
parser.add_argument(
    "--fim",
    help="Data de término do período (formato YYYY-MM-DD).",
    required=False,
    type=str,
)
parser.add_argument(
    "--ultimos_dias",
    help="Últimos N dias (inteiro). Se informado, ignora --inicio/--fim.",
    required=False,
    type=int,
)
args = parser.parse_args()

# 1️⃣ LEITURA DOS DADOS DE OCORRÊNCIA
df = pd.read_json(OCORRE_JSON)

# Garantir que a coluna Data_interacao seja datetime
if "Data_interacao" not in df.columns:
    raise ValueError("Não encontrei a coluna 'Data_interacao' no JSON de ocorrências.")
df["Data_interacao"] = pd.to_datetime(df["Data_interacao"])

# 2️⃣ APLICAR FILTRO POR PERÍODO
# Se passaram --ultimos_dias, usamos esse filtro e ignoramos inicio/fim
if args.ultimos_dias is not None:
    hoje = datetime.today().date()
    inicio_data = hoje - timedelta(days=args.ultimos_dias - 1)
    df = df[df["Data_interacao"].dt.date >= inicio_data]
else:
    # Se não, podemos ter tanto --inicio quanto --fim — ambos opcionais
    if args.inicio:
        try:
            dt_inicio = pd.to_datetime(args.inicio).normalize()
        except:
            raise ValueError("Parâmetro --inicio deve estar no formato YYYY-MM-DD.")
        df = df[df["Data_interacao"] >= dt_inicio]
    if args.fim:
        try:
            dt_fim = pd.to_datetime(args.fim).normalize() + timedelta(days=1)
        except:
            raise ValueError("Parâmetro --fim deve estar no formato YYYY-MM-DD.")
        df = df[df["Data_interacao"] < dt_fim]

# Após filtrar, podemos continuar normalmente (se df ficar vazio, o mapa ficará vazio mas sem erro).

# 3️⃣ LEITURA DAS UBS GEOJSON
gdfU = gpd.read_file(UBS_GEOJSON)

# 4️⃣ PREPARAÇÃO DO SHAPEFILE DE DISTRITOS (BAIRROS)
gdf_dst_full = gpd.read_file(DST_SHP).set_crs(31983).to_crs(4326)

# Nome da coluna que identifica o distrito no shapefile (pode variar)
district_name_column = "ds_nome"

TARGETS = ["CAMBUCI", "ACLIMAÇÃO", "LIBERDADE", "IPIRANGA"]

# Filtrar apenas esses quatro bairros
gdf_bairros = (
    gdf_dst_full[
        gdf_dst_full[district_name_column]
        .str.upper()
        .isin([t.upper() for t in TARGETS])
    ][[district_name_column, "geometry"]]
    .copy()
)

# 5️⃣ CRIA MAPA BASE
map_center = [df["Latitude"].mean(), df["Longitude"].mean()] if not df.empty else [-23.572, -46.630]
m = folium.Map(
    location=map_center,
    zoom_start=13,
    tiles="OpenStreetMap"
)

# 6️⃣ HEATMAP POR DOENÇA
#    - Se df estiver vazio, o for simplesmente não adicionará camadas.
for doenca, sub in df.groupby("Doenca_suspeita"):
    pts = sub[["Latitude", "Longitude"]].values.tolist()
    pts = [p + [1] for p in pts]  # cada ponto vem com peso 1
    HeatMap(
        pts,
        name=f"{doenca} ({len(pts)})",
        gradient=gradient,
        radius=radius,
        blur=blur,
        min_opacity=0.1,   # exato como estava no V17 (não alteramos para min_opacity=min_opacity)
    ).add_to(m)

# 7️⃣ MARCADORES DE UBS PRÓXIMAS
#    - transforma df em GeoSeries apenas para criar o buffer (~2km ≈ 0.02°)
if not df.empty:
    occ_pts = gpd.GeoSeries(
        gpd.points_from_xy(df.Longitude, df.Latitude),
        crs="EPSG:4326"
    )
    buffer_area = occ_pts.unary_union.buffer(0.02)
    gdfU_vis = gdfU[gdfU.within(buffer_area)]
    for _, r in gdfU_vis.iterrows():
        folium.Marker(
            [r.lat, r.lon],
            tooltip=r.nome,
            icon=folium.Icon(color="green", icon="plus-sign")
        ).add_to(m)
else:
    # Se não há ocorrências no período, não colocamos marcadores (mantemos a variável, mas vazia)
    gdfU_vis = gpd.GeoDataFrame(columns=gdfU.columns)

# ----------------------------------------------------------------
# 8️⃣ CONTAGEM “OCORRÊNCIAS POR BAIRRO” VIA SPATIAL JOIN
# ----------------------------------------------------------------
if not df.empty:
    gdf_occ = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.Longitude, df.Latitude),
        crs="EPSG:4326"
    )
    joined = gpd.sjoin(
        gdf_occ,
        gdf_bairros.rename(columns={district_name_column: "bairro"}),
        how="left",
        predicate="within",
    )
    contagem_bairros = joined["bairro"].value_counts(dropna=False).to_dict()
else:
    contagem_bairros = {}

# Montar dicionário garantindo todos os quatro bairros
tabela_contagens = {}
for b in TARGETS:
    tabela_contagens[b] = int(contagem_bairros.get(b, 0))

# ----------------------------------------------------------------
# 9️⃣ CRIA O SNIPPET (HTML) FIXO COM A TABELA + LINHA TOTAL
# ----------------------------------------------------------------
html_table = """
<div style="
    position: fixed;
    bottom: 10px;
    left: 10px;
    z-index: 9999;
    background-color: rgba(255, 255, 255, 0.8);
    padding: 8px;
    border: 1px solid #444;
    font-size: 12px;
">
  <b>Ocorrências por Bairro</b>
  <table style="border-collapse: collapse; margin-top: 4px;">
    <tr>
      <th style="padding: 2px 6px; border-bottom: 1px solid #666;">Bairro</th>
      <th style="padding: 2px 6px; border-bottom: 1px solid #666;">Qtd.</th>
    </tr>
"""
# Linhas individuais para cada bairro
for b in TARGETS:
    qtd = tabela_contagens[b]
    html_table += f"""
    <tr>
      <td style="padding: 2px 6px; border-bottom: 1px solid #ddd;">{b}</td>
      <td style="padding: 2px 6px; border-bottom: 1px solid #ddd; text-align: right;">{qtd}</td>
    </tr>
    """

# Linha “Total” ao final da tabela
total_geral = sum(tabela_contagens.values())
html_table += f"""
    <tr>
      <td style="padding: 2px 6px; border-top: 2px solid #666;"><b>Total</b></td>
      <td style="padding: 2px 6px; border-top: 2px solid #666; text-align: right;"><b>{total_geral}</b></td>
    </tr>
"""
html_table += """
  </table>
</div>
"""

from folium import Element
m.get_root().html.add_child(Element(html_table))

# 🔟 LayerControl e salvamento
folium.LayerControl().add_to(m)
# Note que alteramos o nome do arquivo de saída apenas para distinguir a versão de período:
m.save("mapa_calor_ubs.html")
print("✔  mapa_calor_ubs.html pronto — abra no navegador.")

# ------------------------------------------------------------------------------------------
# 11 - COMMITA AUTOMATICAMENTE NO GIT PARA CAPTURA PELO VERCEL
# ------------------------------------------------------------------------------------------

import os
import git

repo_path = "D:/DOCUMENTOS/GITHUB/AEDESMAP"
html_file = "mapa_calor_ubs.html"

# Inicializa o repositório Git local
repo = git.Repo(repo_path)

# Adiciona o arquivo ao commit
repo.index.add([html_file])
repo.index.commit("Atualizando mapa de calor")

# Faz o push para o repositório remoto
origin = repo.remote(name="origin")
origin.push()

print("HTML atualizado no GitHub!")
