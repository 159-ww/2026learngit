// GEE Code Editor 版：南京市 NDBI 建筑指数提取与可视化（Landsat 9）

// NDBI = (SWIR - NIR) / (SWIR + NIR) = (SR_B6 - SR_B5) / (SR_B6 + SR_B5)
//   NDBI > 0  建成区（建筑物、裸地）   <- 正值，图中红色
//   NDBI ≈ 0  过渡带                   <- 灰色中点
//   NDBI < 0  植被、水体               <- 负值，图中蓝色

// ==================== 1. 参数配置 ====================
var CENTER = [118.779, 32.042];   // 南京市中心（新街口）[经度, 纬度]
var BUFFER_M = 15000;             // 研究区半径 15 km（30 km × 30 km 方框）
var START_DATE = '2025-04-01';    // 影像起始日期（春-秋，避开冬季）
var END_DATE = '2025-10-31';      // 影像截止日期
var MAX_CLOUD = 30;               // 单景云量阈值 %（南京夏季多云，收紧到 30）
var SCALE = 30;                   // 输出分辨率 30 m（Landsat 原生分辨率）

// NDBI 显示范围：夏季常有霾，NDBI 动态范围会被压缩，
// 用 ±0.2 拉开色差；0 仍然正好对应灰色中点。
// 如果重跑后图整体偏灰，可继续调到 ±0.15；偏饱和则调回 ±0.3。
var VMIN = -0.2, VMAX = 0.2;

// 发散型色带：蓝（负值：水体/植被）-> 灰（0）-> 红（正值：建成区）
var PALETTE = ['#0d366b', '#2a78d6', '#cde2fb', '#f0efec',
               '#f2b6b2', '#e34948', '#882c2b'];

// ==================== 2. 研究区 ====================
var roi = ee.Geometry.Point(CENTER).buffer(BUFFER_M).bounds();
Map.setCenter(CENTER[0], CENTER[1], 11);  // (经度, 纬度, 缩放级别)

// ==================== 3. 影像筛选、缩放与去云 ====================
// 地表反射率缩放系数（Landsat Collection 2 Level 2 官方公式）
function applyScaleFactors(image) {
  var optical = image.select('SR_B.').multiply(0.0000275).add(-0.2);
  var thermal = image.select('ST_B.*').multiply(0.00341802).add(149.0);
  return image.addBands(optical, null, true).addBands(thermal, null, true);
}

function maskClouds(image) {
  // QA_PIXEL 位掩膜：bit1 膨胀云 / bit2 卷云 / bit3 云 / bit4 云影
  var qa = image.select('QA_PIXEL');
  var bad = qa.bitwiseAnd((1 << 1) | (1 << 2) | (1 << 3) | (1 << 4));
  return image.updateMask(bad.eq(0));
}

var collection = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')  // Landsat 9 L2 地表反射率
  .filterBounds(roi)
  .filterDate(START_DATE, END_DATE)
  .filter(ee.Filter.lt('CLOUD_COVER', MAX_CLOUD))
  .map(applyScaleFactors)
  .map(maskClouds);

print('筛选出的影像景数：', collection.size());

// 中值合成：每个像元取所有影像的中值，天然抑制残余云影
var composite = collection.median().clip(roi);

// ==================== 4. 计算 NDBI 与区域统计 ====================
// SR_B6 = 短波红外 SWIR，SR_B5 = 近红外 NIR（已缩放为地表反射率）
var ndbi = composite.normalizedDifference(['SR_B6', 'SR_B5']).rename('NDBI');

var stats = ndbi.reduceRegion({
  reducer: ee.Reducer.min()
    .combine(ee.Reducer.max(), null, true)
    .combine(ee.Reducer.mean(), null, true)
    .combine(ee.Reducer.stdDev(), null, true),
  geometry: roi,
  scale: SCALE,
  maxPixels: 1e9
});
print('NDBI 统计（最小值/最大值/均值/标准差）：', stats);

// ==================== 5. 可视化 ====================
Map.centerObject(roi, 11);
// 显示无需转投影：Code Editor 地图自动转换为 Web Mercator（EPSG:3857）
// 注意：Google 底图在中国大陆是 GCJ-02 加密坐标，与 WGS84 影像有几百米偏移，
//       对齐关系以影像本身（和 GAUL 边界）为准，不要以底图判读地物。
Map.addLayer(
  ndbi,
  {min: VMIN, max: VMAX, palette: PALETTE},
  'NDBI 建筑指数', true, 0.85
);
Map.addLayer(
  ee.FeatureCollection('FAO/GAUL/2015/level2').filterBounds(roi),
  {color: '00FF00'}, 'GAUL边界(WGS84)'
);

// 验证点：直接读已知坐标的像元值（不经过底图，不受 GCJ-02 偏移影响）
var river_point = ee.Geometry.Point([118.740, 32.098]);   // 长江江面
var city_point  = ee.Geometry.Point([118.779, 32.042]);   // 新街口（闹市区）
var hill_point  = ee.Geometry.Point([118.845, 32.063]);   // 紫金山（植被）
print('长江江面 NDBI =', ndbi.reduceRegion(ee.Reducer.first(), river_point, SCALE).get('NDBI'));
print('新街口 NDBI   =', ndbi.reduceRegion(ee.Reducer.first(), city_point, SCALE).get('NDBI'));
print('紫金山 NDBI   =', ndbi.reduceRegion(ee.Reducer.first(), hill_point, SCALE).get('NDBI'));

// ==================== 6. 导出到 Google Drive ====================
// Run 之后去右侧 Tasks 面板点击 Run 才会真正执行导出
Export.image.toDrive({
  image: ndbi,
  description: 'ndbi_nanjing_2025',   // 任务名（Tasks 面板里显示的名字）
  folder: 'GEE_NDBI_南京',            // Drive 里的目标文件夹（自动创建）
  fileNamePrefix: 'ndbi_nanjing_2025',
  scale: SCALE,
  region: roi,
  crs: 'EPSG:32650',                  // 导出坐标系：WGS 84 / UTM 50N（南京在 50 带，
                                       // 单位米，面积/长度计算不失真，方便与本地 GIS 数据叠加）
  maxPixels: 1e13
});
