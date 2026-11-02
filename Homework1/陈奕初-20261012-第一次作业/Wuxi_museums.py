# %%
# 无锡市博物馆 POI 分析
# 高德 API 下载 POI → GCJ02 转 WGS84 (EPSG:4326) → 地图 + 统计图

import math
import time

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import requests
from shapely.geometry import Point

# %% 1. 配置
API_KEY = 'xxxxxxxx'
BASE_URL = 'https://restapi.amap.com/v5/place/text'

CITY_NAME = '无锡'
KEYWORDS = '博物馆'
MAX_PER_DISTRICT = 20
PAGE_SIZE = 20
REQUEST_INTERVAL = 0.3

DISTRICTS = {
    '梁溪区': '320213', '锡山区': '320205', '惠山区': '320206',
    '滨湖区': '320211', '新吴区': '320214', '江阴市': '320281',
    '宜兴市': '320282',
}

DISTRICT_COLORS = {
    '梁溪区': '#e41a1c', '锡山区': '#377eb8', '惠山区': '#4daf4a',
    '滨湖区': '#984ea3', '新吴区': '#ff7f00', '江阴市': '#a65628',
    '宜兴市': '#f781bf',
}

# %% 2. GCJ02 → WGS84 坐标转换
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lon, lat):
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(lon, lat):
    ret = (-100.0 + 2.0 * lon + 3.0 * lat + 0.2 * lat * lat
           + 0.1 * lon * lat + 0.2 * math.sqrt(abs(lon)))
    ret += (20.0 * math.sin(6.0 * lon * math.pi)
            + 20.0 * math.sin(2.0 * lon * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi)
            + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi)
            + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(lon, lat):
    ret = (300.0 + lon + 2.0 * lat + 0.1 * lon * lon
           + 0.1 * lon * lat + 0.1 * math.sqrt(abs(lon)))
    ret += (20.0 * math.sin(6.0 * lon * math.pi)
            + 20.0 * math.sin(2.0 * lon * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lon * math.pi)
            + 40.0 * math.sin(lon / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lon / 12.0 * math.pi)
            + 300.0 * math.sin(lon / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lon, lat):
    """单点 GCJ02 → WGS84，反算偏移量"""
    if _out_of_china(lon, lat):
        return lon, lat

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)

    radlat = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)

    return lon * 2 - (lon + dlon), lat * 2 - (lat + dlat)


def convert_to_wgs84(df, lon_col='经度_gcj02', lat_col='纬度_gcj02'):
    """批量转换 DataFrame 中的 GCJ02 坐标为 WGS84，新增 '经度'/'纬度' 两列"""
    coords = [
        gcj02_to_wgs84(float(lon), float(lat))
        if pd.notna(lon) and pd.notna(lat) else (None, None)
        for lon, lat in zip(df[lon_col], df[lat_col])
    ]
    df['经度'], df['纬度'] = zip(*coords)
    return df


# %% 3. 抓取 POI
def _parse_pois(pois):
    rows = []
    for poi in pois:
        loc = poi.get('location') or ''
        lon, lat = loc.split(',')[:2] if ',' in loc else (None, None)
        biz = poi.get('business') or {}
        rows.append({
            '名称': poi.get('name'),
            '地址': poi.get('address'),
            '经度_gcj02': lon,
            '纬度_gcj02': lat,
            '类型': poi.get('type'),
            '行政区划': poi.get('adname'),
            '电话': poi.get('tel') or biz.get('tel'),
            '开放时间': biz.get('opentime_today') or biz.get('opentime_week'),
        })

    df = pd.DataFrame(rows)
    df['经度_gcj02'] = pd.to_numeric(df['经度_gcj02'], errors='coerce')
    df['纬度_gcj02'] = pd.to_numeric(df['纬度_gcj02'], errors='coerce')
    return df


def search_poi(keywords, region, max_count=MAX_PER_DISTRICT):
    """按 adcode 分页搜索 POI"""
    all_pois, page = [], 1
    while len(all_pois) < max_count:
        params = {
            'key': API_KEY, 'keywords': keywords, 'region': region,
            'city_limit': 'true', 'output': 'json',
            'page_size': PAGE_SIZE, 'page': page, 'show_fields': 'business',
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=10)
        except requests.exceptions.RequestException as exc:
            print(f'请求异常: {exc}')
            break

        if resp.status_code != 200:
            print(f'HTTP 错误: {resp.status_code}')
            break

        data = resp.json()
        if data.get('status') != '1':
            print(f"API 错误: {data.get('info')}")
            break

        pois = data.get('pois') or []
        if not pois:
            break

        all_pois.extend(pois)
        if len(pois) < PAGE_SIZE:
            break

        page += 1
        time.sleep(REQUEST_INTERVAL)

    return _parse_pois(all_pois[:max_count])


print(f'抓取 {CITY_NAME} {KEYWORDS} ...')
frames = []
for district, adcode in DISTRICTS.items():
    df_d = search_poi(KEYWORDS, adcode)
    print(f'  {district}: {len(df_d)} 条')
    if not df_d.empty:
        df_d['搜索行政区'] = district
        frames.append(df_d)
    time.sleep(REQUEST_INTERVAL)

museums_gcj = pd.concat(frames, ignore_index=True)
museums_gcj = (museums_gcj
               .dropna(subset=['经度_gcj02', '纬度_gcj02'])
               .drop_duplicates(subset=['名称', '地址'])
               .reset_index(drop=True))
print(f'共 {len(museums_gcj)} 条（已去重）')

# %% 4. 坐标转换 + 构建 GeoDataFrame
museums_df = convert_to_wgs84(museums_gcj)

# 简单验证：计算偏移量（米）
dlon = (museums_df['经度'] - museums_df['经度_gcj02']) * 111000 * \
       museums_df['纬度_gcj02'].apply(lambda y: math.cos(math.radians(y)))
dlat = (museums_df['纬度'] - museums_df['纬度_gcj02']) * 111000
offset = (dlon ** 2 + dlat ** 2) ** 0.5
print(f'GCJ02→WGS84 偏移: {offset.min():.0f} ~ {offset.max():.0f} m '
      f'(均值 {offset.mean():.0f} m)')

geometry = [Point(xy) for xy in zip(museums_df['经度'], museums_df['纬度'])]
museums_gdf = gpd.GeoDataFrame(museums_df, geometry=geometry, crs='EPSG:4326')
museums_gdf_utm = museums_gdf.to_crs('EPSG:32651')   # UTM 51N，用于精确量算
print(f'GeoDataFrame: {len(museums_gdf)} 条，CRS={museums_gdf.crs}')

# %% 5. 保存数据
museums_df.to_csv('data/wuxi_museums_wgs84.csv', index=False, encoding='utf-8-sig')
museums_gdf.to_file('data/wuxi_museums_wgs84.geojson', driver='GeoJSON', encoding='utf-8')
print('✓ CSV / GeoJSON 已保存到 data/')

# %% 6. 交互式地图（OpenStreetMap 免费底图）
center = [museums_df['纬度'].mean(), museums_df['经度'].mean()]
base_map = folium.Map(location=center, zoom_start=11,
                      tiles='OpenStreetMap', control_scale=True)

for _, row in museums_df.iterrows():
    if pd.isna(row['经度']):
        continue
    color = DISTRICT_COLORS.get(row['行政区划'], 'gray')
    popup = (
        f"<b>{row['名称']}</b><br>"
        f"地址：{row['地址'] or '—'}<br>"
        f"行政区：{row['行政区划'] or '—'}<br>"
        f"电话：{row['电话'] or '—'}<br>"
        f"开放时间：{row['开放时间'] or '—'}<br>"
        f"<span style='color:#888'>WGS84: {row['经度']:.6f}, {row['纬度']:.6f}</span>"
    )
    folium.CircleMarker(
        location=[row['纬度'], row['经度']],
        radius=6, color=color, fill=True, fillColor=color,
        fillOpacity=0.75, weight=1,
        popup=folium.Popup(popup, max_width=340),
        tooltip=row['名称'],
    ).add_to(base_map)

# 图例
legend_items = ''.join(
    f'<div><span style="display:inline-block;width:12px;height:12px;'
    f'background:{c};border-radius:50%;margin-right:6px"></span>{d}</div>'
    for d, c in DISTRICT_COLORS.items()
)
base_map.get_root().html.add_child(folium.Element(f'''
<div style="position:fixed;top:12px;right:12px;width:130px;background:#fff;
            border:1px solid #999;border-radius:4px;z-index:9999;
            font-size:13px;padding:8px 10px;box-shadow:2px 2px 6px rgba(0,0,0,.15)">
  <div style="font-weight:bold;margin-bottom:4px">行政区</div>
  {legend_items}
</div>
'''))

base_map.save('data/wuxi_museums.html')
print('✓ 交互式地图已保存: data/wuxi_museums.html')
base_map

# %% 7. 统计图：各行政区数量
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

district_counts = (museums_df['行政区划'].value_counts()
                   .reindex(list(DISTRICTS)).fillna(0).astype(int))

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.bar(district_counts.index, district_counts.values,
              color=[DISTRICT_COLORS[k] for k in district_counts.index],
              edgecolor='black', alpha=0.85)
for b in bars:
    ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f'{int(b.get_height())}',
            ha='center', va='bottom', fontsize=11)
ax.set_xlabel('行政区划'); ax.set_ylabel('博物馆数量')
ax.set_title('无锡市各行政区博物馆数量分布', fontsize=14, fontweight='bold')
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.savefig('data/wuxi_museums_by_district.png', dpi=300, bbox_inches='tight')
plt.show()

# %% 8. 统计图：类型 TOP 10
def _mid_type(t):
    if not t or pd.isna(t):
        return '其他'
    parts = str(t).split(';')
    return parts[1] if len(parts) >= 2 else parts[0]


type_counts = museums_df['类型'].apply(_mid_type).value_counts().head(10)

fig, ax = plt.subplots(figsize=(10, 7))
bars = ax.barh(type_counts.index[::-1], type_counts.values[::-1],
               color='#4C72B0', edgecolor='black', alpha=0.85)
for b in bars:
    ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f'{int(b.get_width())}',
            ha='left', va='center', fontsize=11)
ax.set_xlabel('数量'); ax.set_ylabel('博物馆中类')
ax.set_title('无锡市博物馆类型分布（TOP 10）', fontsize=14, fontweight='bold')
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
plt.savefig('data/wuxi_museums_by_type.png', dpi=300, bbox_inches='tight')
plt.show()

# %% 9. 密度热力图
fig, ax = plt.subplots(figsize=(11, 8))
h = ax.hist2d(museums_df['经度'], museums_df['纬度'],
              bins=25, cmap='YlOrRd', cmin=1)
plt.colorbar(h[3], ax=ax, label='博物馆数量')
ax.set_xlabel('经度 (WGS84)'); ax.set_ylabel('纬度 (WGS84)')
ax.set_title('无锡市博物馆密度热力图', fontsize=14, fontweight='bold')
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig('data/wuxi_museums_density.png', dpi=300, bbox_inches='tight')
plt.show()

# %% 10. 空间统计（投影坐标系，单位：米）
spatial_stats = []
for district in DISTRICTS:
    sub = museums_gdf_utm[museums_gdf_utm['行政区划'] == district]
    if sub.empty:
        continue
    xs, ys = sub.geometry.x, sub.geometry.y
    spatial_stats.append({
        '行政区划': district, '数量': len(sub),
        '中心X(m)': xs.mean(), '中心Y(m)': ys.mean(),
        'X离散度(m)': xs.std(), 'Y离散度(m)': ys.std(),
        '东西跨度(m)': xs.max() - xs.min(),
        '南北跨度(m)': ys.max() - ys.min(),
    })

stats_df = pd.DataFrame(spatial_stats)
print('\n空间统计（EPSG:32651）：')
print(stats_df.round(1).to_string(index=False))
stats_df.to_csv('data/wuxi_museums_spatial_stats.csv', index=False, encoding='utf-8-sig')
print('\n全部完成，结果在 data/ 目录')
