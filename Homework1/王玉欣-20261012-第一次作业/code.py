# %%
# 作业1：南京市鼓楼区小学POI提取和绘制学区划分图和相关统计图

import os
import time
import requests
import pandas as pd
import geopandas as gpd
import folium
import matplotlib.pyplot as plt
from shapely.geometry import Point
from shapely.ops import unary_union, voronoi_diagram

plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

os.makedirs('output', exist_ok=True)

print("=" * 60)
print("南京市鼓楼区小学POI提取和绘制学区划分图和相关统计图")
print("=" * 60)

# %%
# 1. 高德API配置
# ==============

API_KEY = 'aab8325409a5cc551cb4dcca3468641'
BASE_URL = 'https://restapi.amap.com/v5/place/text'

# %%
# 2. 搜索POI
# ==========

def search_poi(keywords='小学', api_key=API_KEY, page_size=25, max_page=5):
    """用多边形搜索接口，限定鼓楼区范围"""
    url = 'https://restapi.amap.com/v3/place/polygon'
    
    # 鼓楼区大致范围（左下角|右上角）
    polygon = '118.73,32.03|118.80,32.10'
    
    all_pois, page = [], 1
    while page <= max_page:
        params = {
            'key': api_key,
            'keywords': keywords,
            'polygon': polygon,
            'coordinate': 'wgs84',
            'output': 'json',
            'offset': page_size,   # 注意：polygon接口用 offset 而不是 page_size
            'page': page,
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get('status') != '1':
            print(f"API错误: {data.get('info')}")
            break
        pois = data.get('pois', [])
        if not pois:
            break
        all_pois.extend(pois)
        print(f"第{page}页: {len(pois)} 条 (累计 {len(all_pois)})")
        if len(pois) < page_size:
            break
        page += 1
        time.sleep(0.3)
    
    # 只保留鼓楼区的记录
    rows = []
    for p in all_pois:
        if p.get('adname') != '鼓楼区':
            continue
        loc = p.get('location', '')
        if not loc or ',' not in loc:
            continue
        lon, lat = map(float, loc.split(','))
        rows.append({
            '名称': p.get('name'),
            '地址': p.get('address'),
            '经度': lon,
            '纬度': lat,
            '行政区划': p.get('adname'),
        })
    return pd.DataFrame(rows)


print("\n【下载鼓楼区小学POI】")
schools = search_poi()
print(f"✓ 共获取 {len(schools)} 所小学")
print(schools[['名称', '地址', '行政区划']].head(100))
schools.to_csv('output/schools_full.csv', index=False, encoding='utf-8-sig')
print("已保存: output/schools_full.csv")

# %%
# 3. 交互式地图：小学POI（OSM底图）
# ===================================

center_lat = schools['纬度'].mean()
center_lon = schools['经度'].mean()

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=13,
    tiles='OpenStreetMap'
)

for idx, row in schools.iterrows():
    folium.CircleMarker(
        location=[row['纬度'], row['经度']],
        radius=4,
        color='black',
        fillColor='black',
        fillOpacity=1,
        popup=f"{row['名称']}<br>{row['地址']}",
        tooltip=row['名称']
    ).add_to(m)

print(f"✓ 交互式地图已生成，包含 {len(schools)} 所小学")
m
# %%
# 4. 构建GeoDataFrame —— WGS84 (EPSG:4326)
# ========================================

gdf = gpd.GeoDataFrame(
    schools,
    geometry=[Point(xy) for xy in zip(schools['经度'], schools['纬度'])],
    crs='EPSG:4326'
)


# %%
# 5. 投影到 UTM 50N (EPSG:32650)
# ==============================

gdf_proj = gdf.to_crs(epsg=32650)
print(f"\n✓ 已投影到 EPSG:32650 (UTM 50N)，单位: 米")

# %%
# 6. 生成泰森多边形
# =================

hull = unary_union(gdf_proj.geometry).convex_hull.buffer(500)

vor = voronoi_diagram(unary_union(gdf_proj.geometry), envelope=hull)
vor_gdf = gpd.GeoDataFrame(geometry=list(vor.geoms), crs='EPSG:32650')
vor_clip = gpd.clip(vor_gdf, hull)

joined = gpd.sjoin(vor_clip, gdf_proj, how='left', predicate='contains')
joined = joined.drop_duplicates(subset='geometry', keep='first')
joined = joined.dropna(subset=['名称'])

print(f"✓ 生成 {len(joined)} 个泰森多边形（学区）")



# %%
# 7. 交互式地图：泰森多边形学区（带底图）
# =======================================

m2 = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=13,
    tiles='OpenStreetMap'
)

# 泰森多边形：转回 WGS84，只描边不填充
joined_wgs = joined.to_crs(epsg=4326)

folium.GeoJson(
    joined_wgs,
    style_function=lambda x: {
        'fillOpacity': 0,
        'color': 'red',
        'weight': 2,
    },
    tooltip=folium.GeoJsonTooltip(fields=['名称'], aliases=['学区:'])
).add_to(m2)

# 小学点
for idx, row in schools.iterrows():
    folium.CircleMarker(
        location=[row['纬度'], row['经度']],
        radius=4,
        color='black',
        fillColor='black',
        fillOpacity=1,
        popup=f"{row['名称']}<br>{row['地址']}",
        tooltip=row['名称']
    ).add_to(m2)

print(f"✓ 学区交互地图已生成，包含 {len(joined)} 个学区")
m2

# %%
# 8. 投影坐标系下的学区多边形图
# =================================

fig, ax = plt.subplots(figsize=(10, 10))
joined.boundary.plot(ax=ax, color='red', linewidth=1.2)
gdf_proj.plot(ax=ax, color='black', markersize=15)
ax.set_title('南京市鼓楼区小学学区划分（泰森多边形法）')
ax.set_xlabel('Easting (m)')
ax.set_ylabel('Northing (m)')
ax.grid(True, alpha=0.3)   
plt.tight_layout()
plt.savefig('output/school_districts_map.png', dpi=300)
plt.show()

# %%
# 9. 学区面积统计
# ===============

joined['学区面积'] = joined.geometry.area / 1e6

# 给重名的学校加 _1 _2 后缀
counts = joined.groupby('名称')['名称'].transform('count')
joined['唯一名'] = joined['名称'].where(
    counts == 1,
    joined['名称'] + '_' + (joined.groupby('名称').cumcount() + 1).astype(str)
)

# 按面积排序
joined_sorted = joined.sort_values('学区面积')

fig, ax = plt.subplots(figsize=(12, 16))
ax.barh(joined_sorted['唯一名'], joined_sorted['学区面积'],
        color='steelblue', edgecolor='black')

# 每根柱子右边标数值
for i, v in enumerate(joined_sorted['学区面积']):
    ax.text(v, i, f' {v:.2f}', va='center', fontsize=8)

ax.set_xlabel('学区面积 (km²)')
ax.set_title('鼓楼区各小学学区面积统计')
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
plt.savefig('output/district_area_chart.png', dpi=300)
plt.show()


# %%
# 10. 学校密度热力图
# ===============
fig, ax = plt.subplots(figsize=(10, 8))
ax.hist2d(gdf_proj.geometry.x, gdf_proj.geometry.y, bins=10, cmap='YlOrRd')
ax.set_title('鼓楼区小学空间分布热力图')
ax.set_xlabel('Easting (m)')
ax.set_ylabel('Northing (m)')
plt.colorbar(ax.collections[0], ax=ax, label='学校数')
plt.tight_layout()
plt.savefig('output/school_heatmap.png', dpi=300)
plt.show()