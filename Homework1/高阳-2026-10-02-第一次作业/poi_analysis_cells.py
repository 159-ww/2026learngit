# %% 1. 导入库和配置路径
import time

import os
from pathlib import Path

import requests
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt

API_KEY = "请输入你的API"


# 本次作业的研究对象
CITY = "上海"
KEYWORDS = "地铁站"
API_URL = "https://restapi.amap.com/v5/place/text"

# 将数据和图表保存到本代码文件所在的作业文件夹
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
FIGURE_DIR = PROJECT_DIR / "figures"

DATA_DIR.mkdir(exist_ok=True)
FIGURE_DIR.mkdir(exist_ok=True)

# %% 2. 定义请求函数
def fetch_poi_page(page):
    params = {
        "key": API_KEY,
        "keywords": KEYWORDS,
        "region": CITY,
        "city_limit": "true",
        "page_size": 25,
        "page_num": page,
        "output": "json",
    }

    response = requests.get(API_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "1":
        raise RuntimeError(
            f"高德请求失败：{data.get('info')}，"
            f"错误码：{data.get('infocode')}"
        )

    return data.get("pois", [])


# %% 3. 分页下载
# 分页获取数据，最多请求 20 页
all_pois = []
seen_ids = set()

for page in range(1, 21):
    pois = fetch_poi_page(page)
    if not pois:
        break

    new_pois = []
    for poi in pois:
        poi_id = poi.get("id")
        if poi_id and poi_id not in seen_ids:
            seen_ids.add(poi_id)
            new_pois.append(poi)

    all_pois.extend(new_pois)
    print(
        f"第 {page} 页：返回 {len(pois)} 条，"
        f"新增 {len(new_pois)} 条，累计 {len(all_pois)} 条"
    )

    if len(pois) < 25 or not new_pois:
        break

    time.sleep(0.5)

print(f"下载完成，共获取 {len(all_pois)} 条不重复的 POI")

# %% 4. 整理并保存数据
# 提取 POI 的主要信息，整理为表格
records = []

for poi in all_pois:
    location = poi.get("location", "")
    if not location or "," not in location:
        continue

    try:
        longitude, latitude = map(float, location.split(","))
    except ValueError:
        continue

    records.append({
        "POI_ID": poi.get("id"),
        "名称": poi.get("name"),
        "类型": poi.get("type"),
        "类型编码": poi.get("typecode"),
        "地址": poi.get("address"),
        "行政区": poi.get("adname"),
        "经度_GCJ02": longitude,
        "纬度_GCJ02": latitude,
    })

df = pd.DataFrame(records)

output_path = DATA_DIR / "shanghai_subway_pois_gcj02.csv"
df.to_csv(output_path, index=False, encoding="utf-8-sig")

print(f"已保存 {len(df)} 条有效 POI：{output_path}")
print(df.head())
# %% 5. 读取已保存的数据
df = pd.read_csv(
    DATA_DIR / "shanghai_subway_pois_gcj02.csv",
    encoding="utf-8-sig",
    dtype={"POI_ID": str, "类型编码": str},
)
print(f"从本地 CSV 读取 {len(df)} 条 POI，无需请求高德 API")
print(df.head())
# %% 6. 整理地铁站数据
stations = df.loc[
    df["类型编码"].astype(str).eq("150500")
].copy()

stations["站名"] = (
    stations["名称"]
    .str.replace(r"[（(]地铁站[）)]$", "", regex=True)
    .str.strip()
)

print(f"整理完成，共 {len(stations)} 条地铁站 POI 样本")

# %% 7. 定义坐标转换函数
from math import sin, cos, sqrt, pi


def coordinate_offset(lon, lat):
    """计算 WGS84 到 GCJ-02 的经纬度偏移。"""
    x, y = lon - 105.0, lat - 35.0
    a = 6378245.0
    f = 1 / 298.3
    ee = 1 - (1 - f) ** 2

    dlat = (
        -100 + 2 * x + 3 * y + 0.2 * y * y
        + 0.1 * x * y + 0.2 * sqrt(abs(x))
    )
    dlat += (
        20 * sin(6 * x * pi) + 20 * sin(2 * x * pi)
    ) * 2 / 3
    dlat += (
        20 * sin(y * pi) + 40 * sin(y / 3 * pi)
    ) * 2 / 3
    dlat += (
        160 * sin(y / 12 * pi) + 320 * sin(y * pi / 30)
    ) * 2 / 3

    dlon = (
        300 + x + 2 * y + 0.1 * x * x
        + 0.1 * x * y + 0.1 * sqrt(abs(x))
    )
    dlon += (
        20 * sin(6 * x * pi) + 20 * sin(2 * x * pi)
    ) * 2 / 3
    dlon += (
        20 * sin(x * pi) + 40 * sin(x / 3 * pi)
    ) * 2 / 3
    dlon += (
        150 * sin(x / 12 * pi) + 300 * sin(x / 30 * pi)
    ) * 2 / 3

    rad = lat * pi / 180
    magic = 1 - ee * sin(rad) ** 2
    root = sqrt(magic)

    dlat = dlat * 180 / (
        a * (1 - ee) / (magic * root) * pi
    )
    dlon = dlon * 180 / (
        a / root * cos(rad) * pi
    )
    return dlon, dlat


def gcj_to_wgs(lon_gcj, lat_gcj):
    """迭代反算 WGS84，结果顺序为经度、纬度。"""
    if not (72.004 <= lon_gcj <= 137.8347
            and 0.8293 <= lat_gcj <= 55.8271):
        return lon_gcj, lat_gcj

    lon_wgs, lat_wgs = lon_gcj, lat_gcj

    for _ in range(30):
        dlon, dlat = coordinate_offset(lon_wgs, lat_wgs)
        error_lon = lon_wgs + dlon - lon_gcj
        error_lat = lat_wgs + dlat - lat_gcj

        lon_wgs -= error_lon
        lat_wgs -= error_lat

        if max(abs(error_lon), abs(error_lat)) < 1e-6:
            return lon_wgs, lat_wgs

    raise RuntimeError("坐标转换未收敛，请检查输入坐标")


print("坐标转换函数已定义")

# %% 8. 将地铁站坐标从 GCJ-02 转为 WGS84
wgs_coordinates = [
    gcj_to_wgs(lon, lat)
    for lon, lat in zip(
        stations["经度_GCJ02"],
        stations["纬度_GCJ02"],
    )
]

stations[["经度_WGS84", "纬度_WGS84"]] = pd.DataFrame(
    wgs_coordinates,
    index=stations.index,
)

print(f"已转换 {len(stations)} 条站点坐标")
print(
    stations[
        ["站名", "经度_GCJ02", "纬度_GCJ02",
         "经度_WGS84", "纬度_WGS84"]
    ].head().to_string(index=False)
)

# %% 9. 创建地理数据并转换为适合研究区域的 UTM 投影
stations_wgs84 = gpd.GeoDataFrame(
    stations.copy(),
    geometry=gpd.points_from_xy(
        stations["经度_WGS84"],
        stations["纬度_WGS84"],
    ),
    crs="EPSG:4326",
)

# 根据站点分布位置自动选择合适的 UTM 分区
utm_crs = stations_wgs84.estimate_utm_crs()
stations_projected = stations_wgs84.to_crs(utm_crs)

stations_projected["X_米"] = stations_projected.geometry.x
stations_projected["Y_米"] = stations_projected.geometry.y

print("使用的投影坐标系：", utm_crs)
print(
    stations_projected[
        ["站名", "X_米", "Y_米"]
    ].head().to_string(index=False)
)
# %% 10. 保存投影坐标和空间数据

# CSV 保存属性、经纬度和以米为单位的投影坐标
coordinate_path = DATA_DIR / "shanghai_subway_stations_coordinates.csv"

stations_projected.drop(columns="geometry").to_csv(
    coordinate_path,
    index=False,
    encoding="utf-8-sig",
)

# GeoPackage 同时保存站点位置、属性和投影坐标系
spatial_path = DATA_DIR / "shanghai_subway_stations.gpkg"

stations_projected.to_file(
    spatial_path,
    layer="subway_stations",
    driver="GPKG",
    index=False,
)

print("投影坐标系：", stations_projected.crs)
print("坐标表已保存：", coordinate_path)
print("空间数据已保存：", spatial_path)
# %% 11. 绘制上海地铁站 POI 样本分布地图

# 设置中文字体
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(10, 9))

stations_projected.plot(
    ax=ax,
    color="#1768AC",
    markersize=18,
    alpha=0.75,
    edgecolor="white",
    linewidth=0.3,
)

ax.set_title(
    f"上海市地铁站 POI 样本分布（{len(stations_projected)} 条）",
    fontsize=16,
    pad=15,
)
ax.set_xlabel("东向坐标（米）")
ax.set_ylabel("北向坐标（米）")
ax.set_aspect("equal")
ax.ticklabel_format(style="plain", axis="both", useOffset=False)
ax.grid(alpha=0.25)
ax.set_axisbelow(True)

fig.text(
    0.5, 0.02,
    f"数据来源：高德 POI 搜索｜投影：{stations_projected.crs}"
    "\n展示搜索获取的站点样本，不代表上海全部地铁站；未绘制线路。",
    ha="center",
    fontsize=9,
)

fig.tight_layout(rect=[0, 0.07, 1, 1])

map_path = FIGURE_DIR / "shanghai_subway_station_map.png"
fig.savefig(map_path, dpi=300, bbox_inches="tight")
plt.show()

print("地图已保存：", map_path)

# %% 12. 统计各行政区的地铁站 POI 样本数量

district_counts = (
    stations_projected["行政区"]
    .fillna("行政区未知")
    .value_counts()
    .sort_values()
)

fig, ax = plt.subplots(figsize=(10, 7))

bars = ax.barh(
    district_counts.index,
    district_counts.values,
    color="#1768AC",
)

ax.bar_label(bars, padding=4)
ax.set_xlim(0, district_counts.max() * 1.15)
ax.set_xlabel("地铁站 POI 样本数量（条）")
ax.set_ylabel("行政区")
ax.set_title("上海市各行政区地铁站 POI 样本数量", fontsize=15)
ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
ax.grid(axis="x", alpha=0.25)
ax.set_axisbelow(True)

fig.text(
    0.5, 0.02,
    "数据来源：高德 POI 搜索；统计仅针对本次获取的样本。",
    ha="center",
    fontsize=9,
)

fig.tight_layout(rect=[0, 0.05, 1, 1])

chart_path = FIGURE_DIR / "shanghai_subway_district_counts.png"
fig.savefig(chart_path, dpi=300, bbox_inches="tight")
plt.show()

district_counts.rename("样本数量").rename_axis("行政区").to_csv(
    DATA_DIR / "shanghai_subway_district_counts.csv",
    encoding="utf-8-sig",
)

print(f"统计总数：{district_counts.sum()} 条")
print("统计图已保存：", chart_path)
# %%
