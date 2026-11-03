# -*- coding: utf-8 -*-
"""
GEE 作业：南京市 NDBI 建筑指数提取与可视化
============================================
流程：登录 GEE → 筛选 Landsat 9 影像 → QA_PIXEL 去云 → 中值合成
      → 计算 NDBI → 统计 → 下载 GeoTIFF → 静态图 + 交互地图

NDBI = (SWIR - NIR) / (SWIR + NIR) = (SR_B6 - SR_B5) / (SR_B6 + SR_B5)
  NDBI > 0  建成区（建筑物、裸地）   <- 正值，图中红色
  NDBI ≈ 0  过渡带                   <- 灰色中点
  NDBI < 0  植被、水体               <- 负值，图中蓝色

运行前需要：
  1. pip install earthengine-api rasterio folium pandas
  2. earthengine authenticate   # 浏览器登录 Google 账号（国内需挂 VPN）
"""

import os

import ee
import folium
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform
import requests
from matplotlib.colors import LinearSegmentedColormap

# ==================== 1. 参数配置 ====================
CENTER = [118.779, 32.042]   # 南京市中心 [经度, 纬度]
BUFFER_M = 15000               # 研究区半径 15 km（30 km × 30 km 方框）
START_DATE = '2025-04-01'      # 影像起始日期（春-秋，避开冬季）
END_DATE = '2025-10-31'        # 影像截止日期
MAX_CLOUD = 30                 # 单景云量阈值 %（南京夏季多云，收紧到 30）
SCALE = 30                     # 输出分辨率 30 m（Landsat 原生分辨率）

VMIN, VMAX = -0.2, 0.2         # NDBI 显示范围（南京夏季有霾，动态范围被压缩；0 仍对应灰色中点）

# 发散型色带：蓝（负值：水体/植被）-> 灰（0）-> 红（正值：建成区）
PALETTE = ['#0d366b', '#2a78d6', '#cde2fb', '#f0efec',
           '#f2b6b2', '#e34948', '#882c2b']

# 地物标注 [经度, 纬度, 名称]
LANDMARKS = [
    (118.740, 32.098, '长江'),
    (118.796, 32.070, '玄武湖'),
    (118.845, 32.063, '紫金山'),
]

# 输出路径（相对本脚本所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULT_DIR = os.path.join(BASE_DIR, 'results')
TIF_PATH = os.path.join(DATA_DIR, 'ndbi_nanjing_2025.tif')
PNG_PATH = os.path.join(RESULT_DIR, 'ndbi_nanjing_2025.png')
HTML_PATH = os.path.join(RESULT_DIR, 'ndbi_nanjing_map.html')
CSV_PATH = os.path.join(RESULT_DIR, 'ndbi_nanjing_stats.csv')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

# ==================== 2. 初始化 GEE ====================
try:
    ee.Initialize()
    print('[1/6] GEE 初始化成功')
except Exception as e:
    raise SystemExit(
        'GEE 初始化失败，请先运行 earthengine authenticate 登录（国内需挂 VPN）。'
        f'\n原始错误：{e}'
    )

# ==================== 3. 构建研究区 ====================
roi = ee.Geometry.Point(CENTER).buffer(BUFFER_M).bounds()
print(f'[2/6] 研究区：以 ({CENTER[0]}, {CENTER[1]}) 为中心的 '
      f'{BUFFER_M * 2 / 1000:.0f} km × {BUFFER_M * 2 / 1000:.0f} km 范围')


# ==================== 4. 影像筛选、缩放与去云 ====================
def apply_scale_factors(image):
    """地表反射率缩放系数（Landsat Collection 2 Level 2 官方公式）"""
    optical = image.select('SR_B.').multiply(0.0000275).add(-0.2)
    thermal = image.select('ST_B.*').multiply(0.00341802).add(149.0)
    return image.addBands(optical, None, True).addBands(thermal, None, True)


def mask_clouds(image):
    """QA_PIXEL 位掩膜：bit1 膨胀云 / bit2 卷云 / bit3 云 / bit4 云影"""
    qa = image.select('QA_PIXEL')
    bad = qa.bitwiseAnd((1 << 1) | (1 << 2) | (1 << 3) | (1 << 4))
    return image.updateMask(bad.eq(0))


collection = (
    ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')  # Landsat 9 L2 地表反射率
    .filterBounds(roi)
    .filterDate(START_DATE, END_DATE)
    .filter(ee.Filter.lt('CLOUD_COVER', MAX_CLOUD))
    .map(apply_scale_factors)
    .map(mask_clouds)
)
n_scenes = collection.size().getInfo()
print(f'[3/6] 筛选出 {n_scenes} 景 Landsat 9 影像（云量 < {MAX_CLOUD}%），'
      f'时间 {START_DATE} ~ {END_DATE}')

# 中值合成：对每个像元取所有影像的中值，天然抑制残余云影
composite = collection.median().clip(roi)

# ==================== 5. 计算 NDBI ====================
# SR_B6 = 短波红外 SWIR，SR_B5 = 近红外 NIR（已缩放为地表反射率）
ndbi = composite.normalizedDifference(['SR_B6', 'SR_B5']).rename('NDBI')

# 区域统计（逐像元计算后取区域均值/最值/标准差）
print('[4/6] 计算 NDBI 并统计区域指标...')


def reduce(red):
    return (ndbi.reduceRegion(reducer=red, geometry=roi,
                              scale=SCALE, maxPixels=1e9)
            .get('NDBI').getInfo())


stats = {
    '最小值': reduce(ee.Reducer.min()),
    '最大值': reduce(ee.Reducer.max()),
    '均值': reduce(ee.Reducer.mean()),
    '标准差': reduce(ee.Reducer.stdDev()),
}
print(f"     NDBI 均值 = {stats['均值']:.4f}，"
      f"范围 = [{stats['最小值']:.3f}, {stats['最大值']:.3f}]")

# ==================== 6. 下载 GeoTIFF ====================
print('[5/6] 下载 NDBI GeoTIFF（约 100 万像素，请稍候）...')
url = ndbi.getDownloadURL({
    'scale': SCALE,
    'region': roi,
    'format': 'GEO_TIFF',
    'crs': 'EPSG:32650',         # WGS 84 / UTM 50N：南京所在投影带，单位米
})
resp = requests.get(url, timeout=600)
if resp.status_code != 200 or resp.content[:4] != b'II*\x00':
    raise SystemExit(f'下载失败：HTTP {resp.status_code}\n{resp.text[:500]}')
with open(TIF_PATH, 'wb') as f:
    f.write(resp.content)
print(f'     已保存：{TIF_PATH}')

# ==================== 7. 可视化 ====================
# 7.1 静态图（matplotlib，读取 GeoTIFF 绘制）
print('[6/6] 生成静态图与交互地图...')
with rasterio.open(TIF_PATH) as src:
    arr = src.read(1).astype(np.float32)
    west, south, east, north = src.bounds
    tif_crs = src.crs

# 标注点坐标：从经纬度转换到 GeoTIFF 的坐标系（4326 时不变，UTM 时转为米）
if tif_crs.is_geographic:
    points = [(lon, lat) for lon, lat, _ in LANDMARKS]
    xlabel, ylabel = '经度 (°E)', '纬度 (°N)'
else:
    points = []
    for lon, lat, _ in LANDMARKS:
        x, y = warp_transform(CRS.from_epsg(4326), tif_crs, [lon], [lat])
        points.append((x[0], y[0]))
    xlabel, ylabel = '东向 X (m)', '北向 Y (m)'

cmap = LinearSegmentedColormap.from_list(  # pyright: ignore[reportArgumentType] 字符串色板运行时正常
    'ndbi', PALETTE, N=256)
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']  # 中文字体
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(9, 9), dpi=200)
im = ax.imshow(arr, cmap=cmap, vmin=VMIN, vmax=VMAX,
               extent=[west, east, south, north])

ax.set_title('南京市 NDBI 建筑指数\n'
             'Landsat 9 中值合成 · 2025-04 ~ 2025-10 · 30 m',
             fontsize=13, color='#0b0b0b', pad=12)

# 地物标注（黑字 + 白色描边，任何底色上都可读）
for (x, y), (_, _, name) in zip(points, LANDMARKS):
    ax.text(x, y, name, fontsize=9, color='#0b0b0b', ha='center',
            path_effects=[pe.withStroke(linewidth=3, foreground='white')])

# 图面元素：弱化网格线，刻度用浅灰
ax.grid(True, color='#e1e0d9', linewidth=0.5)
ax.tick_params(colors='#898781', labelsize=8)
ax.set_xlabel(xlabel, fontsize=9, color='#52514e')
ax.set_ylabel(ylabel, fontsize=9, color='#52514e')

cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
cbar.set_label('NDBI', fontsize=10, color='#52514e')
cbar.ax.tick_params(colors='#898781', labelsize=8)

fig.savefig(PNG_PATH, bbox_inches='tight', facecolor='white')
plt.close(fig)
print(f'     已保存：{PNG_PATH}')

# 7.2 交互地图（folium：OSM 底图 + GEE 瓦片图层，同一套色带）
map_id = ndbi.getMapId({'min': VMIN, 'max': VMAX, 'palette': PALETTE})
tiles = map_id['tile_fetcher'].url_format

m = folium.Map(location=CENTER[::-1], zoom_start=12, tiles='OpenStreetMap')
folium.TileLayer(tiles=tiles, name='NDBI 建筑指数',
                 attr='Landsat 9 NDBI · Google Earth Engine',
                 overlay=True, opacity=0.85).add_to(m)
m.fit_bounds([[south, west], [north, east]])
folium.LayerControl().add_to(m)

# 图例：与主图相同的色带渐变条
stops = [f'{c} {i / (len(PALETTE) - 1) * 100:.0f}%'
         for i, c in enumerate(PALETTE)]
legend = f"""
<div style="position:fixed; bottom:24px; left:12px; z-index:9999;
            background:#fcfcfb; padding:8px 12px; border-radius:6px;
            font:12px/1.6 system-ui,'Segoe UI',sans-serif;
            box-shadow:0 1px 4px rgba(11,11,11,.15)">
  <div style="font-weight:600; color:#0b0b0b">NDBI 建筑指数</div>
  <div style="height:10px; width:190px; border-radius:2px;
              background:linear-gradient(to right, {','.join(stops)})"></div>
  <div style="display:flex; justify-content:space-between; color:#52514e">
    <span>{VMIN}</span><span>0</span><span>{VMAX}</span>
  </div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend))  # pyright: ignore[reportAttributeAccessIssue] folium 类型存根不完整
m.save(HTML_PATH)
print(f'     已保存：{HTML_PATH}')

# 7.3 统计结果 CSV
df = pd.DataFrame({'指标': list(stats.keys()),
                   'NDBI': [round(v, 4) for v in stats.values()]})
df.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
print(f'     已保存：{CSV_PATH}')

print('\n完成！结果说明：NDBI > 0（红色）为建成区，'
      'NDBI < 0（蓝色）为水体和植被。')
