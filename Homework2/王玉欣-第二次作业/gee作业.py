#%%
import ee
import geemap
ee.Authenticate() # 进行 Google Earth Engine 的账号授权验证
#%%
ee.Initialize(project='spatial-framing-513414-i7')
# 使用真实的 Google Cloud 项目 ID 连接到 GEE 服务器
roi = ee.Geometry.Rectangle([118.3, 31.1, 119.2, 32.6])
# 定义一个矩形范围，大致为南京市及其周边区域
s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')  # 调用Sentinel-2 地表反射率数据集
      .filterBounds(roi)  # 限制在南京市周边区域
      .filterDate('2024-01-01', '2024-12-31') # 筛选出 2024 年全年的影像
      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))) # 过滤掉云量大于 20% 的影像，保证数据质量

def mask_clouds(image):     # 剔除云的影响
    qa = image.select('QA60')
    mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    return image.updateMask(mask).divide(10000)

composite = s2.map(mask_clouds).median().clip(roi)
'''
对筛选出的多景影像应用去云函数，然后取中位数（median）进行合成。
   这能有效填补残余的云层空洞，生成一张干净、无云的年度合成影像，
   并裁剪到研究区范围内
'''
ndvi = composite.normalizedDifference(['B8', 'B4']).rename('NDVI')
'''
利用 Sentinel-2 的 B8（近红外波段）和 B4（红光波段） 
    计算归一化植被指数（NDVI）
'''
#%%
m = geemap.Map() # 调用 geemap 库创建一个交互式地图
m.centerObject(roi, 10) # 将地图视角居中到研究区，缩放级别为 10
m.addLayer(ndvi, {'min': -0.2, 'max': 0.8,
                   'palette': ['blue', 'white', 'yellow', 'lightgreen', 'darkgreen']},
           'NDVI')
'''蓝色为水体或极低值，白色为城市建筑裸土等，浅绿色到深绿色，颜色越深表示绿色植被覆盖越好
'''
#%%
m
#%%
m.to_html(filename=r"C:\Users\王玉欣\Desktop\nanjing_ndvi_map.html")

