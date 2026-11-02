"""苏州市本科高校周边生活服务 POI 抓取、投影与空间分析脚本。

整体流程：
1. 从工作区根目录的 .env 读取高德地图 API 密钥；
2. 查询校区位置、周边 1 km 内的 POI，以及苏州市区县边界；
3. 将高德 GCJ-02 坐标近似转换到 WGS84，再投影到 Albers 等积圆锥坐标系；
4. 保存表格、矢量数据、区县底图和静默生成的地图/统计图。

应使用项目指定的 Anaconda 环境 mytorch_3_10 运行：
    python myfirsthomework/第二版/scripts/suzhou_campus_poi.py

也可以加 --reuse-data 跳过 POI 和边界下载，使用本版 data 目录已有数据重新生成分析结果。
API 密钥只从 .env 读取，不写在脚本或输出文件中。
"""

from __future__ import annotations

import math
import os
import tempfile
import time
import argparse
from pathlib import Path

# 先定位第二版输出目录，并把临时文件目录设在工作区内。contextily 下载瓦片时
# 会用 tempfile；提前设置可避免 Windows 默认临时目录权限/路径问题。
OUT = Path(__file__).resolve().parents[1]
EARLY_CACHE_DIR = OUT / "data" / "tile_cache"
EARLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(EARLY_CACHE_DIR)

import geopandas as gpd
import matplotlib
import contextily as ctx

# Agg 是无界面绘图后端，所有图片只写入文件，不会弹出 GUI 窗口。
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon, MultiPolygon


# 脚本在 myfirsthomework/第二版/scripts/ 下：parents[3] 是工作区根目录。
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
DATA_DIR = OUT / "data"
CHART_DIR = OUT / "charts"
MAP_DIR = OUT / "maps"
BOUNDARY_DIR = DATA_DIR / "boundaries"
ENV_FILE = ROOT / ".env"
API_URL = "https://restapi.amap.com/v5/place/around"
TEXT_API_URL = "https://restapi.amap.com/v5/place/text"
DISTRICT_API_URL = "https://restapi.amap.com/v3/config/district"
RADIUS_M = 1000
PAGE_SIZE = 25
MAX_PAGES = 8  # Amap Place Search 2.0 caps a query at 200 results.
PAUSE_SECONDS = 0.25
MIN_API_INTERVAL_SECONDS = 0.45
LAST_API_CALL_AT = 0.0

# 校区名称会在运行时通过高德文本搜索解析为坐标，因此不必在脚本中手工维护坐标。
# 南京大学苏州校区和中国人民大学苏州校区也包含在列表中。
CAMPUSES = [
    "苏州大学天赐庄校区",
    "苏州大学独墅湖校区",
    "苏州大学阳澄湖校区",
    "苏州科技大学石湖校区",
    "苏州科技大学天平校区",
    "西交利物浦大学",
    "苏州城市学院",
    "苏州工学院东湖校区",
    "苏州工学院东南校区",
    "苏州职业技术大学石湖校区",
    "苏州职业技术大学干将路校区",
    "昆山杜克大学",
    "苏州大学应用技术学院",
    "江苏科技大学苏州理工学院",
    "南京大学苏州校区",
    "中国人民大学苏州校区",
]
CAMPUS_ALIASES = {
    # 部分校区在高德数据中仍使用旧名；主名称搜不到时依次尝试别名。
    "苏州工学院东湖校区": ["常熟理工学院东湖校区"],
    "苏州工学院东南校区": ["常熟理工学院东南校区"],
    "苏州职业技术大学石湖校区": ["苏州市职业大学石湖校区", "苏州职业大学石湖校区", "苏州市职业大学"],
    "苏州职业技术大学干将路校区": ["苏州市职业大学干将路校区", "苏州职业大学干将路校区"],
}

# 高德 POI 类型编码。关键词用于补充类型编码，适应不同商户记录的分类差异。
# 每个类别分别按校区发起周边搜索，最终再按校区距离去重归属。
CATEGORIES = {
    "餐厅": {"types": "050000", "keywords": ""},
    "咖啡厅": {"types": "050500", "keywords": "咖啡"},
    "超市/便利店": {"types": "060200|060400", "keywords": "超市|便利店"},
    "书店": {"types": "061205", "keywords": "书店"},
}
CATEGORY_COLORS = {
    "餐厅": "#E76F51",
    "咖啡厅": "#8D6E63",
    "超市/便利店": "#2A9D8F",
    "书店": "#457B9D",
}

# 中国区域常用 Albers 等积圆锥投影参数；坐标单位为米，后续距离/缓冲计算均在此坐标系下进行。
ALBERS = CRS.from_proj4(
    "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 "
    "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)


def configure_chinese_font() -> None:
    """设置中文字体候选、负号显示方式及整套图表的基础配色。"""
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.facecolor": "#FAFAF7",
        "axes.facecolor": "#FAFAF7",
        "axes.edgecolor": "#D7D9D5",
        "axes.labelcolor": "#334155",
        "text.color": "#243447",
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "savefig.facecolor": "#FAFAF7",
    })


def api_get(session: requests.Session, key: str, params: dict, url: str = API_URL) -> dict:
    """统一发送高德 API 请求，并处理节流、超时错误和高德限流重试。

    session 复用 HTTP 连接；key 从 .env 读取；params 是接口查询参数；url 可切换
    周边搜索、文本搜索或行政区查询接口。返回解析后的 JSON 字典；异常不带出 URL，避免泄密。
    """
    global LAST_API_CALL_AT
    request_params = {**params, "key": key, "output": "json"}
    for attempt in range(4):
        gap = MIN_API_INTERVAL_SECONDS - (time.monotonic() - LAST_API_CALL_AT)
        if gap > 0:
            time.sleep(gap)
        try:
            response = session.get(url, params=request_params, timeout=(10, 30))
            LAST_API_CALL_AT = time.monotonic()
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            # requests exceptions can include the full request URL (and API key).
            raise RuntimeError(f"高德 API 网络请求失败（{type(exc).__name__}）；请检查网络连接。") from None
        if result.get("status") == "1":
            return result
        if result.get("infocode") in {"10021", "10022"} and attempt < 3:
            time.sleep(1.5 * (attempt + 1))
            continue
        raise RuntimeError(
            f"Amap API error {result.get('infocode')}: {result.get('info')}"
        )
    raise RuntimeError("高德 API 请求超过限速重试次数。")


def locate_campus(session: requests.Session, key: str, query: str) -> dict | None:
    """用高德文本搜索定位校区，返回校区名称、匹配名称和 GCJ-02 坐标。

    若主名称没有结果，会继续尝试 CAMPUS_ALIASES 中配置的旧称/别称；
    找不到可用坐标时返回 None，由主流程记录并跳过该校区。
    """
    pois = []
    selected_query = query
    for candidate in [query, *CAMPUS_ALIASES.get(query, [])]:
        data = api_get(session, key, {
            "keywords": candidate,
            "city": "苏州",
            "city_limit": "true",
            "page_size": 10,
            "page_num": 1,
            "show_fields": "business",
        }, url=TEXT_API_URL)
        pois = data.get("pois", [])
        if pois:
            selected_query = candidate
            break
    if not pois:
        print(f"  未匹配到校区，跳过：{query}")
        return None
    # Prefer the closest name match, rather than a similarly named campus.
    poi = next((p for p in pois if p.get("name", "") == selected_query), pois[0])
    try:
        lon, lat = map(float, poi["location"].split(","))
    except (KeyError, ValueError):
        print(f"  校区坐标缺失，跳过：{query}")
        return None
    return {"campus": query, "matched_name": poi.get("name", ""), "campus_id": poi.get("id", ""), "lon": lon,
            "lat": lat, "address": poi.get("address", "")}


def fetch_suzhou_boundaries(session: requests.Session, key: str) -> gpd.GeoDataFrame:
    """下载苏州市下辖区县边界并保存 GeoJSON、GeoPackage 两种格式。

    高德区划接口返回的边界折线为 GCJ-02；这里逐点近似转成 WGS84，
    以便后续统一投影到 Albers 并叠加到道路底图上。
    """
    time.sleep(2.0)
    root = api_get(session, key, {
        "keywords": "苏州市", "subdistrict": 1, "extensions": "base",
        "page": 1, "offset": 20,
    }, url=DISTRICT_API_URL)
    districts = (root.get("districts") or [{}])[0].get("districts", [])
    records = []
    for item in districts:
        # 先取得区县 adcode，再用 adcode 请求该区县的完整边界折线。
        adcode = item.get("adcode", "")
        detail = api_get(session, key, {
            "keywords": adcode, "subdistrict": 0, "extensions": "all",
            "page": 1, "offset": 1,
        }, url=DISTRICT_API_URL)
        feature = (detail.get("districts") or [{}])[0]
        rings = []
        # polyline 中可能包含多个由 | 分隔的面部件，每一段再按 ; 分割坐标点。
        for part in (feature.get("polyline") or "").split("|"):
            coords = []
            for pair in part.split(";"):
                try:
                    lon, lat = map(float, pair.split(","))
                    coords.append(gcj02_to_wgs84(lon, lat))
                except (ValueError, TypeError):
                    continue
            if len(coords) >= 3:
                polygon = Polygon(coords)
                if not polygon.is_empty:
                    rings.append(polygon)
        if rings:
            # 修复少量无效面，避免写入矢量文件或重投影时发生拓扑错误。
            geom = rings[0] if len(rings) == 1 else MultiPolygon(rings)
            if not geom.is_valid:
                geom = geom.buffer(0)
            records.append({"name": feature.get("name", item.get("name", "")),
                            "adcode": adcode, "level": feature.get("level", "district"),
                            "geometry": geom})
        time.sleep(MIN_API_INTERVAL_SECONDS)
    if not records:
        raise RuntimeError("未能从高德行政区接口获取苏州市区县边界。")
    boundaries = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    boundaries.to_file(BOUNDARY_DIR / "苏州市区县行政边界.geojson", driver="GeoJSON")
    boundaries.to_file(BOUNDARY_DIR / "苏州市区县行政边界.gpkg", layer="districts", driver="GPKG")
    return boundaries


def fetch_category(session: requests.Session, key: str, campus: dict,
                   category: str, config: dict) -> list[dict]:
    """抓取某校区周边某一类别的 POI，返回可直接组成表格的记录列表。

    分页结果在当前类别/校区查询内按 POI ID 去重；没有 ID 时用名称和位置组合兜底。
    这里保留高德原始 GCJ-02 坐标，之后统一做坐标转换和跨校区距离归属。
    """
    all_pois: list[dict] = []
    seen: set[str] = set()
    for page_num in range(1, MAX_PAGES + 1):
        # around 接口的 location 是校区中心点；radius 的单位是米。
        params = {
            "location": f"{campus['lon']},{campus['lat']}",
            "radius": RADIUS_M,
            "types": config["types"],
            "page_size": PAGE_SIZE,
            "page_num": page_num,
            "show_fields": "business,indoor",
        }
        if config["keywords"]:
            params["keywords"] = config["keywords"]
        data = api_get(session, key, params)
        pois = data.get("pois", [])
        for poi in pois:
            pid = poi.get("id") or f"{poi.get('name')}|{poi.get('location')}"
            if pid in seen:
                continue
            seen.add(pid)
            try:
                lon, lat = map(float, poi["location"].split(","))
            except (KeyError, ValueError):
                continue
            all_pois.append({
                # 保存分类、地址、电话、行政区和原始坐标，便于复查及后续复用。
                "poi_id": poi.get("id", ""),
                "name": poi.get("name", ""),
                "category": category,
                "amap_type": poi.get("type", ""),
                "typecode": poi.get("typecode", ""),
                "address": poi.get("address", ""),
                "district": poi.get("adname", ""),
                "township": poi.get("township", ""),
                "telephone": poi.get("tel", ""),
                "longitude_gcj02": lon,
                "latitude_gcj02": lat,
                "campus": campus["campus"],
                "campus_lon_gcj02": campus["lon"],
                "campus_lat_gcj02": campus["lat"],
            })
        if len(pois) < PAGE_SIZE:
            break
        time.sleep(PAUSE_SECONDS)
    return all_pois


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    """将中国大陆范围内的 GCJ-02 坐标近似转换为 WGS84 经纬度。

    高德地图返回 GCJ-02；Albers 投影以 WGS84 为基准。此处采用常见反算近似，
    仅适用于中国大陆区域。超出中国范围时原样返回坐标。
    """
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lon, lat
    a, ee = 6378245.0, 0.00669342162296594323

    # 两个内部函数分别计算 GCJ 偏移量在纬度和经度方向上的分量。
    def transform_lat(x: float, y: float) -> float:
        value = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
        value += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
        value += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi))*2/3
        value += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30))*2/3
        return value

    def transform_lon(x: float, y: float) -> float:
        value = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
        value += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
        value += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi))*2/3
        value += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi))*2/3
        return value

    dlat, dlon = transform_lat(lon - 105, lat - 35), transform_lon(lon - 105, lat - 35)
    radlat = lat / 180 * math.pi
    magic = 1 - ee * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = dlat * 180 / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = dlon * 180 / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon - dlon, lat - dlat


def transform_points(rows: pd.DataFrame) -> gpd.GeoDataFrame:
    """增加 WGS84 经纬度、Albers 米制坐标和点几何，返回 GeoDataFrame。

    输入表需包含 longitude_gcj02、latitude_gcj02 两列；输出活动几何列和
    坐标参考系均为 ALBERS，可直接用于地图、空间统计和距离计算。
    """
    wgs = rows.apply(lambda r: gcj02_to_wgs84(r.longitude_gcj02, r.latitude_gcj02), axis=1)
    rows = rows.copy()
    rows["longitude_wgs84"] = [p[0] for p in wgs]
    rows["latitude_wgs84"] = [p[1] for p in wgs]
    transformer = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    rows["x_albers_m"], rows["y_albers_m"] = transformer.transform(
        rows["longitude_wgs84"].to_numpy(), rows["latitude_wgs84"].to_numpy()
    )
    rows["geometry"] = [Point(x, y) for x, y in zip(rows.x_albers_m, rows.y_albers_m)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=ALBERS)


def assign_nearest_campus(rows: pd.DataFrame, campuses: list[dict]) -> pd.DataFrame:
    """将重叠搜索范围内的 POI 归给最近的校区中心，并计算距离（米）。

    同一商户可能落入多个校区 1 km 搜索圆。先统一转换并投影到米制坐标，
    再按欧氏距离选最近校区，避免一个 POI 被多个校区重复统计。
    """
    transformer = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    centers = []
    for campus in campuses:
        lon, lat = gcj02_to_wgs84(campus["lon"], campus["lat"])
        x, y = transformer.transform(lon, lat)
        centers.append((campus, x, y))
    assigned = []
    distances = []
    for row in rows.itertuples(index=False):
        lon, lat = gcj02_to_wgs84(row.longitude_gcj02, row.latitude_gcj02)
        x, y = transformer.transform(lon, lat)
        campus, cx, cy = min(centers, key=lambda item: (x - item[1])**2 + (y - item[2])**2)
        assigned.append((campus["campus"], campus["lon"], campus["lat"]))
        distances.append(math.hypot(x - cx, y - cy))
    result = rows.copy()
    result[["campus", "campus_lon_gcj02", "campus_lat_gcj02"]] = assigned
    result["distance_to_campus_m"] = distances
    return result


def add_basemap_style(ax) -> None:
    """为空间密度图设置浅色背景、网格和等比例坐标轴。"""
    ax.set_facecolor("#F0F3F1")
    ax.grid(color="white", linewidth=1.0, alpha=0.9)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_aspect("equal", adjustable="datalim")


def save_map(gdf: gpd.GeoDataFrame, campuses: list[dict], boundaries: gpd.GeoDataFrame) -> None:
    """绘制并保存区县边界、街道底图、校区中心和 POI 分布图。

    区县边界和点位统一使用 Albers 米制投影；contextily 叠加 Esri 街道瓦片。
    虚线圆表示各校区 1 km 搜索范围，星号表示校区中心。
    """
    fig, ax = plt.subplots(figsize=(14, 11), constrained_layout=True)
    boundaries_albers = boundaries.to_crs(ALBERS)
    boundaries_albers.plot(ax=ax, facecolor="#F7F4EB", edgecolor="none", alpha=0.8, zorder=0)
    # Esri 街道瓦片提供道路和地名；高德区划面提供区县边界及边界标签。
    ctx.add_basemap(
        ax, source=ctx.providers.Esri.WorldStreetMap, crs=ALBERS,
        zoom="auto", reset_extent=False, attribution_size=7, zorder=1,
    )
    boundaries_albers.boundary.plot(ax=ax, color="#536B84", linewidth=1.15,
                                    alpha=0.88, zorder=2)
    for row in boundaries_albers.itertuples(index=False):
        label_pt = row.geometry.representative_point()
        ax.annotate(row.name, (label_pt.x, label_pt.y), ha="center", va="center",
                    fontsize=8, color="#475569", zorder=2,
                    bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.68))
    palette = CATEGORY_COLORS
    for category, subset in gdf.groupby("category", sort=False):
        subset.plot(ax=ax, color=palette[category], markersize=34, alpha=0.92,
                    edgecolor="white", linewidth=0.4, label=category, zorder=4)
    transformer = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    for campus in campuses:
        lon, lat = gcj02_to_wgs84(campus["lon"], campus["lat"])
        x, y = transformer.transform(lon, lat)
        ax.scatter([x], [y], marker="*", s=145, color="#172554", edgecolor="white",
                   linewidth=0.9, zorder=6)
        circle = plt.Circle((x, y), RADIUS_M, fill=False, color="#172554",
                            linestyle=(0, (3, 3)), linewidth=1.35, alpha=0.72, zorder=5)
        ax.add_patch(circle)
    minx, miny, maxx, maxy = boundaries_albers.total_bounds
    pad_x, pad_y = (maxx - minx) * 0.025, (maxy - miny) * 0.025
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.annotate("N", xy=(0.97, 0.92), xytext=(0.97, 0.85), xycoords="axes fraction",
                textcoords="axes fraction", ha="center", va="center", fontsize=11,
                fontweight="bold", color="#243447",
                arrowprops=dict(arrowstyle="-|>", color="#243447", lw=1.5), zorder=9)
    bar_len = 20000
    bx = minx + (maxx - minx) * 0.055
    by = miny + (maxy - miny) * 0.055
    ax.plot([bx, bx + bar_len], [by, by], color="#1F2937", lw=3,
            solid_capstyle="butt", zorder=8)
    ax.text(bx + bar_len / 2, by + (maxy - miny) * 0.012, "20 km", ha="center",
            va="bottom", fontsize=8, color="#1F2937", zorder=8,
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    legend = ax.legend(title="POI 类型", frameon=True, facecolor="white", edgecolor="#E2E8F0",
                       loc="upper left", fontsize=9)
    legend.set_zorder(8)
    ax.set_xlabel("Albers X (m)")
    ax.set_ylabel("Albers Y (m)")
    ax.set_title("苏州市本科高校周边生活服务 POI 分布", fontsize=17, fontweight="bold", pad=14)
    fig.text(0.99, 0.005, "★ 高校校区    虚线圆：1 km 搜索半径    底图：Esri World Street Map",
             ha="right", fontsize=9, color="#64748B")
    fig.savefig(MAP_DIR / "苏州高校周边POI_Albers.png", dpi=260, bbox_inches="tight")
    plt.close(fig)


def save_charts(gdf: gpd.GeoDataFrame) -> None:
    """生成四类常用统计图，逐张保存后关闭画布以控制内存占用。

    图表包括类别总量、校区类别交叉对比、Albers 六边形密度、距校区距离分布。
    所有图片静默保存到 CHART_DIR，不调用 plt.show()。
    """
    # 图 1：各类别 POI 总数，类别顺序固定，便于不同版本横向比较。
    totals = gdf.category.value_counts().reindex(CATEGORIES.keys(), fill_value=0)
    fig, ax = plt.subplots(figsize=(9.5, 5.5), constrained_layout=True)
    bars = ax.bar(totals.index, totals.values,
                  color=[CATEGORY_COLORS[x] for x in totals.index], width=0.65)
    ax.bar_label(bars, padding=4, fontsize=11, fontweight="bold")
    ax.set_ylabel("POI 数量（个）")
    ax.set_title("四类生活服务 POI 数量", fontsize=15, fontweight="bold")
    ax.grid(axis="y", alpha=0.22)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(CHART_DIR / "01_类别数量.png", dpi=240, bbox_inches="tight")
    plt.close(fig)

    # 图 2：按校区分组的横向条形图，用于比较各校区四类设施的数量构成。
    cross = pd.crosstab(gdf.campus, gdf.category).reindex(columns=CATEGORIES.keys(), fill_value=0)
    order = cross.sum(axis=1).sort_values().index
    cross = cross.loc[order]
    fig, ax = plt.subplots(figsize=(12, max(5.5, len(cross) * 0.48)), constrained_layout=True)
    y = np.arange(len(cross))
    h = 0.19
    for i, category in enumerate(CATEGORIES):
        vals = cross[category].to_numpy()
        ax.barh(y + (i - 1.5) * h, vals, height=h, color=CATEGORY_COLORS[category], label=category)
    ax.set_yticks(y, [x.replace("校区", "") for x in cross.index])
    ax.set_xlabel("POI 数量（个）")
    ax.set_title("各高校校区周边 POI 类别构成", fontsize=15, fontweight="bold")
    ax.grid(axis="x", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncols=4, loc="lower right", frameon=False)
    fig.savefig(CHART_DIR / "02_校区类别对比.png", dpi=240, bbox_inches="tight")
    plt.close(fig)

    # 图 3：统计六边形网格内的 POI 数量，并用对数颜色刻度显示空间集聚。
    fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
    hb = ax.hexbin(gdf.x_albers_m, gdf.y_albers_m, gridsize=40, mincnt=1,
                   cmap="magma", linewidths=0.0, bins="log")
    fig.colorbar(hb, ax=ax, shrink=0.78, label="POI 数量（对数刻度）")
    add_basemap_style(ax)
    ax.set_xlabel("Albers X (m)")
    ax.set_ylabel("Albers Y (m)")
    ax.set_title("苏州高校周边 POI 空间密度（六边形网格）", fontsize=15, fontweight="bold")
    fig.savefig(CHART_DIR / "03_空间密度六边形.png", dpi=240, bbox_inches="tight")
    plt.close(fig)

    # 图 4：按 250 米分箱统计 POI 到最近校区中心的距离，并标出中位数。
    campuses_xy = {}
    projector = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    campus_rows = gdf[["campus", "campus_lon_gcj02", "campus_lat_gcj02"]].drop_duplicates()
    for row in campus_rows.itertuples(index=False):
        lon, lat = gcj02_to_wgs84(row.campus_lon_gcj02, row.campus_lat_gcj02)
        campuses_xy[row.campus] = projector.transform(lon, lat)
    dists = []
    for row in gdf.itertuples(index=False):
        cx, cy = campuses_xy[row.campus]
        dists.append(math.hypot(row.x_albers_m - cx, row.y_albers_m - cy))
    fig, ax = plt.subplots(figsize=(9.5, 5.5), constrained_layout=True)
    bins = np.arange(0, RADIUS_M + 250, 250)
    ax.hist(dists, bins=bins, color="#4C78A8", edgecolor="white", alpha=0.9)
    ax.axvline(np.median(dists), color="#E45756", linestyle="--", linewidth=2,
               label=f"中位数 {np.median(dists):.0f} m")
    ax.set_xlabel("距所搜校区中心距离（m）")
    ax.set_ylabel("POI 数量（个）")
    ax.set_title("高校周边 POI 距离分布", fontsize=15, fontweight="bold")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(CHART_DIR / "04_距校区距离分布.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """程序入口：读取配置/数据，执行 1 km 筛选，保存数据、地图和统计图。"""
    parser = argparse.ArgumentParser(description="下载苏州高校周边 POI 并生成空间分析图。")
    parser.add_argument("--reuse-data", action="store_true",
                        help="复用第二版已有 POI 和区县数据，仅重新转换和制图。")
    args = parser.parse_args()
    # 建立分门别类的输出目录，并将底图瓦片缓存到第二版 data 目录。
    for folder in (DATA_DIR, CHART_DIR, MAP_DIR, BOUNDARY_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    ctx.set_cache_dir(str(DATA_DIR / "tile_cache"))
    configure_chinese_font()
    load_dotenv(ENV_FILE)
    key = os.getenv("AMAP_API_KEY", "").strip()
    if not key:
        raise RuntimeError(f"未在 {ENV_FILE} 中找到 AMAP_API_KEY")

    if args.reuse_data:
        # 复用模式适合网络/API 不可用时重新投影或重画图；对应数据文件需已存在。
        raw = pd.read_csv(DATA_DIR / "苏州高校周边POI_GCJ02.csv")
        campuses = pd.read_csv(DATA_DIR / "校区中心点_GCJ02.csv").to_dict("records")
        boundaries = gpd.read_file(BOUNDARY_DIR / "苏州市区县行政边界.gpkg")
        print(f"复用 {len(raw)} 条已下载 POI 和 {len(campuses)} 个校区点。")
    else:
        # 首次运行：解析校区位置，逐校区/逐类别下载 POI，最后获取区县边界。
        all_rows: list[dict] = []
        campuses: list[dict] = []
        with requests.Session() as session:
            session.headers.update({"User-Agent": "SuzhouCampusPOI/2.0"})
            print(f"读取到 API 密钥（仅确认存在；不会显示或写入输出）。开始解析 {len(CAMPUSES)} 个校区……")
            for query in CAMPUSES:
                campus = locate_campus(session, key, query)
                if campus is None:
                    continue
                campuses.append(campus)
                print(f"校区：{query}")
                for category, config in CATEGORIES.items():
                    rows = fetch_category(session, key, campus, category, config)
                    all_rows.extend(rows)
                    print(f"  {category}: {len(rows)} 条")
                    time.sleep(PAUSE_SECONDS)
            boundaries = fetch_suzhou_boundaries(session, key)

        if not all_rows:
            raise RuntimeError("未获取到 POI；请检查网络、Key 权限和高德 API 返回信息。")

        # 汇总抓取结果并去重；部分咖啡 POI 会被 API 编入餐饮类别，随后按
        # 类型编码或名称将其改归“咖啡厅”。
        raw = pd.DataFrame(all_rows)
        raw = raw.drop_duplicates(subset="poi_id", keep="first")
        cafe_mask = raw["typecode"].astype(str).str.contains(r"(?:^|\|)0505", regex=True) | raw["name"].astype(str).str.contains("咖啡", na=False)
        raw.loc[cafe_mask, "category"] = "咖啡厅"
    # 搜索圆重叠时只保留最近校区归属，并严格筛选距离 <= 1000 m 的 POI。
    raw = assign_nearest_campus(raw, campuses)
    raw = raw[raw["distance_to_campus_m"] <= RADIUS_M].copy()
    # 输出 GCJ-02 原始表、Albers 投影表/GeoPackage、WGS84 GeoJSON，便于表格和 GIS 软件使用。
    raw.to_csv(DATA_DIR / "苏州高校周边POI_GCJ02.csv", index=False, encoding="utf-8-sig")
    gdf = transform_points(raw)
    gdf.to_csv(DATA_DIR / "苏州高校周边POI_Albers.csv", index=False, encoding="utf-8-sig")
    gdf.to_file(DATA_DIR / "苏州高校周边POI_Albers.gpkg", layer="poi", driver="GPKG")
    gdf.to_crs("EPSG:4326").to_file(
        DATA_DIR / "苏州高校周边POI_WGS84.geojson", driver="GeoJSON"
    )
    # 另存校区中心和校区-类别统计明细，方便复核、复用或自行制图。
    campus_df = pd.DataFrame(campuses)
    campus_df.to_csv(DATA_DIR / "校区中心点_GCJ02.csv", index=False, encoding="utf-8-sig")
    gdf.groupby(["campus", "category"]).size().rename("poi_count").reset_index().to_csv(
        DATA_DIR / "校区类别统计.csv", index=False, encoding="utf-8-sig"
    )
    save_map(gdf, campuses, boundaries)
    save_charts(gdf)
    print(f"\n完成：{len(gdf)} 个去重 POI，{len(campuses)} 个校区。")
    print(f"地图：{MAP_DIR / '苏州高校周边POI_Albers.png'}")
    print(f"统计图：{CHART_DIR}")


if __name__ == "__main__":
    main()
