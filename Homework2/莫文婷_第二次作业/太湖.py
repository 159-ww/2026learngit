import os
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'

import ee
import geemap

# 1. 初始化
ee.Initialize(project='earth-engine-512908')

# 2. 定义区域：改为 30 公里缓冲区，并稍微往苏州陆地偏移一点
# 原先 [120.25, 31.25] 偏湖面，稍微偏东南一点到苏州吴中区附近
taihu_point = ee.Geometry.Point([120.35, 31.20]) 
taihu_buffer = taihu_point.buffer(30000)  # 30000米 = 30公里

# 3. 加载数据计算 NDVI
s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
collection = (s2.filterDate('2024-06-01', '2024-08-31')
              .filterBounds(taihu_buffer)
              .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)))
image = collection.sort('CLOUDY_PIXEL_PERCENTAGE').first()
ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI').clip(taihu_buffer)

# 4. 创建地图
m = geemap.Map(center=[31.20, 120.35], zoom=10) # 放大级别调小一点(10)以适应更大范围
m.add_basemap('SATELLITE') # Google 卫星底图，避免403

# 添加图层
m.addLayer(image, {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 3000}, 'Sentinel-2 原图')
m.addLayer(ndvi, {'min': -0.2, 'max': 0.8, 'palette': ['white', 'lightgreen', 'green', 'darkgreen']}, 'NDVI 指标')

# 5. 导出为 HTML 网页
out_html = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
m.to_html(out_html)
print(f"新版网页已生成：{out_html}！双击打开看看 30 公里的效果。")