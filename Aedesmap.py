# Aedesmap_V20.py
# ----------------------------------------------------------------
# Versão V20: a tabela que aparecia como “Ocorrências por Bairro”
# agora passa a ser “Ocorrências por Distrito”, incluindo apenas
# os distritos realmente presentes no shapefile (removemos “Aclimação”).
# ----------------------------------------------------------------

import argparse
import pandas as pd
import geopandas as gpd
import folium
from folium.plugins import HeatMap
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import unicodedata
import time
import os
import git

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
min_opacity  = 0.1   # conforme V17

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

#
# Função auxiliar para normalizar texto (remover acentos, converter para caixa alta)
#
def normalize_str(s):
    return (
        unicodedata.normalize("NFKD", str(s))
        .encode("ASCII", "ignore")
        .decode("ASCII", "ignore")
        .upper()
    )

# 1️⃣ LEITURA DOS DADOS DE OCORRÊNCIA
df = pd.read_json(OCORRE_JSON)

# ——————————————————————————————————————————
# 1a️⃣ Geocodificação de registros sem Latitude/Longitude
# ----------------------------------------------------------------
if "Endereco" not in df.columns:
    raise ValueError("Coluna 'Endereco' não encontrada no JSON de ocorrências.")

geolocator = Nominatim(user_agent="aedesmap_geocoder")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

if "Latitude" not in df.columns:
    df["Latitude"] = pd.NA
if "Longitude" not in df.columns:
    df["Longitude"] = pd.NA

# Itera apenas sobre linhas sem coordenadas
for idx, row in df[df["Latitude"].isna() | df["Longitude"].isna()].iterrows():
    endereco = row["Endereco"]
    if pd.isna(endereco) or endereco.strip() == "":
        continue
    try:
        loc = geocode(endereco)
    except Exception:
        loc = None
    if loc:
        df.at[idx, "Latitude"] = loc.latitude
        df.at[idx, "Longitude"] = loc.longitude
    time.sleep(0.2)

# 1b️⃣ Garantir Data_interacao como datetime
if "Data_interacao" not in df.columns:
    raise ValueError("Não encontrei a coluna 'Data_interacao' no JSON de ocorrências.")
df["Data_interacao"] = pd.to_datetime(df["Data_interacao"])

# 2️⃣ APLICAR FILTRO POR PERÍODO
if args.ultimos_dias is not None:
    hoje = datetime.today().date()
    inicio_data = hoje - timedelta(days=args.ultimos_dias - 1)
    df = df[df["Data_interacao"].dt.date >= inicio_data]
else:
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

# 3️⃣ LEITURA DAS UBS GEOJSON
gdfU = gpd.read_file(UBS_GEOJSON)

# 4️⃣ PREPARAÇÃO DO SHAPEFILE DE DISTRITOS (BAIRROS)
gdf_dst_full = gpd.read_file(DST_SHP).set_crs(31983).to_crs(4326)

# Normaliza o nome do distrito para remover acento
gdf_dst_full["ds_nome_norm"] = gdf_dst_full["ds_nome"].apply(normalize_str)

# Definir quais distritos queremos (removemos “ACLIMACAO” porque não existe como distrito)
TARGETS = ["CAMBUCI", "LIBERDADE", "IPIRANGA"]

# Filtrar apenas esses três (já normalizados)
gdf_bairros = (
    gdf_dst_full[gdf_dst_full["ds_nome_norm"].isin(TARGETS)]
    .rename(columns={"ds_nome_norm": "bairro"})
    .loc[:, ["bairro", "geometry"]]
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
for doenca, sub in df.groupby("Doenca_suspeita"):
    pts = sub[["Latitude", "Longitude"]].values.tolist()
    pts = [p + [1] for p in pts]
    HeatMap(
        pts,
        name=f"{doenca} ({len(pts)})",
        gradient=gradient,
        radius=radius,
        blur=blur,
        min_opacity=0.1,
    ).add_to(m)

# 7️⃣ MARCADORES DE UBS PRÓXIMAS
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
    gdfU_vis = gpd.GeoDataFrame(columns=gdfU.columns)

# ----------------------------------------------------------------
# 8️⃣ CONTAGEM “OCORRÊNCIAS POR DISTRITO” VIA SPATIAL JOIN
# ----------------------------------------------------------------
tabela_contagens = {}
if not df.empty:
    # Primeiro, criamos GeoDataFrame com buffer minúsculo para minimizar erros de borda
    gdf_occ = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.Longitude, df.Latitude),
        crs="EPSG:4326"
    )
    # Aplica um buffer de 0.0001° (~11m) para capturar pontos colados na borda
    gdf_occ["geometry_buffered"] = gdf_occ.geometry.buffer(0.0001)

    joined = gpd.sjoin(
        gdf_occ.set_geometry("geometry_buffered"),
        gdf_bairros,
        how="left",
        predicate="intersects",
    )
    contagem_bairros = joined["bairro"].value_counts(dropna=False).to_dict()
else:
    contagem_bairros = {}

# Garantir que aparece cada distrito, mesmo que zero
for b in TARGETS:
    tabela_contagens[b] = int(contagem_bairros.get(b, 0))

# 9️⃣ CRIA O SNIPPET (HTML) FIXO COM A TABELA + LINHA TOTAL
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
  <b>Ocorrências por Distrito</b>
  <table style="border-collapse: collapse; margin-top: 4px;">
    <tr>
      <th style="padding: 2px 6px; border-bottom: 1px solid #666;">Distrito</th>
      <th style="padding: 2px 6px; border-bottom: 1px solid #666;">Qtd.</th>
    </tr>
"""
for b in TARGETS:
    qtd = tabela_contagens[b]
    html_table += f"""
    <tr>
      <td style="padding: 2px 6px; border-bottom: 1px solid #ddd;">{b}</td>
      <td style="padding: 2px 6px; border-bottom: 1px solid #ddd; text-align: right;">{qtd}</td>
    </tr>
    """

# Linha “Total” no final
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
m.save("index.html")
print("✔  index.html pronto — abra no navegador.")

# ------------------------------------------------
# 11 - COMMIT AUTOMÁTICO NO GIT PARA VERCEL
# ------------------------------------------------
repo_path = "D:/DOCUMENTOS/GITHUB/AEDESMAP"
html_file = "index.html"

repo = git.Repo(repo_path)
repo.index.add([html_file])
repo.index.commit("Atualizando mapa de calor")
origin = repo.remote(name="origin")
origin.push()
print("HTML atualizado no GitHub!")
