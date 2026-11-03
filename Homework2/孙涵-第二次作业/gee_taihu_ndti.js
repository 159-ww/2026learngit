// 太湖北部梅梁湾 NDTI。粘贴到 https://code.earthengine.google.com/ 后运行。
// 研究区和时间可在这里修改；本作业固定为 2025 年 10 月合成影像。
var roi = ee.Geometry.Rectangle([120.02, 31.31, 120.27, 31.55], 'EPSG:4326', false);
var start = '2025-10-01';
var end = '2025-11-01'; // GEE 的 filterDate 结束日期不包含当天。
var folder = 'Taihu_NDTI_2025_10';

// Sentinel-2 L2A 地表反射率。去除云、云影、薄云、雪等无效像元。
var sr = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi)
  .filterDate(start, end)
  .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', 80));

function maskClouds(image) {
  var scl = image.select('SCL');
  var clear = scl.eq(4).or(scl.eq(5)).or(scl.eq(6)).or(scl.eq(7));
  return image.select(['B2', 'B3', 'B4'])
    .updateMask(clear)
    .copyProperties(image, ['system:time_start', 'system:index']);
}

print('参与合成的 Sentinel-2 景数', sr.size());
print('参与合成的影像 ID', sr.aggregate_array('system:index'));

var clearScenes = sr.map(maskClouds);
// 逐波段中位数合成，避免将某一景的云洞当作湖水差异。
var compositeDN = clearScenes.median().clip(roi);
var observationCount = clearScenes.select('B3').count().rename('clear_count').clip(roi);

// JRC 历史水面出现频率仅用于固定湖内范围；去掉近岸混合像元。
// 它统计的是 1984–2021 年，不是本次影像的水质观测。
var historicalWater = ee.Image('JRC/GSW1_4/GlobalSurfaceWater')
  .select('occurrence').gte(80).unmask(0)
  .focal_min({radius: 30, units: 'meters'});
var lakeMask = historicalWater.and(observationCount.gte(2));

// SR 波段储存为 DN，比例因子 0.0001。NDTI 的同一比例因子会抵消。
// NDTI = (红光 B4 - 绿光 B3) / (红光 B4 + 绿光 B3)。
var red = compositeDN.select('B4');
var green = compositeDN.select('B3');
var valid = lakeMask.and(red.add(green).gt(0));
var ndti = red.subtract(green).divide(red.add(green))
  .rename('NDTI').updateMask(valid).clip(roi);

Map.centerObject(roi, 11);
Map.addLayer(compositeDN, {
  bands: ['B4', 'B3', 'B2'], min: 100, max: 2500, gamma: 1.3
}, 'Sentinel-2 真彩色：2025 年 10 月');
var ndtiVis = {
  min: -0.30, max: -0.05,
  palette: ['164b91', '4fa9c6', 'd8e7dc', 'f2c879', 'c75b3a']
};
Map.addLayer(ndti, ndtiVis, '太湖梅梁湾 NDTI');
Map.addLayer(ee.Image(0).paint(roi, 1, 2).selfMask(),
  {palette: ['ffea00']}, '研究区边界');

var stats = ndti.reduceRegion({
  reducer: ee.Reducer.mean().combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true})
    .combine({reducer2: ee.Reducer.minMax(), sharedInputs: true}),
  geometry: roi, scale: 10, maxPixels: 1e8, tileScale: 4
});
print('湖内 NDTI 统计（相对值，并非 NTU）', stats);
print('有效观测次数范围', observationCount.reduceRegion({
  reducer: ee.Reducer.minMax(), geometry: roi, scale: 30, maxPixels: 1e7
}));
print(ui.Chart.image.histogram({
  image: ndti, region: roi, scale: 30, maxBuckets: 40
}).setOptions({
  title: '梅梁湾湖内 NDTI 分布',
  hAxis: {title: 'NDTI（无量纲）'}, vAxis: {title: '像元数'},
  legend: {position: 'none'}, colors: ['c75b3a']
}));

// 地图色标，供 GEE 交互查看。
var legend = ui.Panel({style: {position: 'bottom-left', padding: '8px'}});
legend.add(ui.Label('NDTI：蓝色较低，橙红色较高'));
legend.add(ui.Thumbnail({
  image: ee.Image.pixelLonLat().select('longitude'),
  params: {bbox: [-0.30, 0, -0.05, 0.1], dimensions: '240x16',
    min: -0.30, max: -0.05, palette: ndtiVis.palette},
  style: {stretch: 'horizontal', margin: '0px'}
}));
legend.add(ui.Label('−0.30              −0.175              −0.05'));
Map.add(legend);

// Run 只生成导出任务，还需在 Tasks 中启动任务。
// 原始波段：B2/B3/B4 的原始 DN；另附 clear_count，供质量检查。
Export.image.toDrive({
  image: compositeDN.select(['B2', 'B3', 'B4']).addBands(observationCount)
    .toInt16().unmask(-9999, false),
  description: 'Taihu_2025_10_S2_source', fileNamePrefix: 'taihu_2025_10_s2_source',
  folder: folder, region: roi, scale: 10, crs: 'EPSG:32651', maxPixels: 1e8,
  fileFormat: 'GeoTIFF', formatOptions: {noData: -9999, cloudOptimized: true}
});

var sceneTable = ee.FeatureCollection(sr.toList(sr.size()).map(function(item) {
  var image = ee.Image(item);
  return ee.Feature(null, {
    asset_id: ee.String('COPERNICUS/S2_SR_HARMONIZED/')
      .cat(ee.String(image.get('system:index'))),
    date: image.date().format('YYYY-MM-dd'),
    tile_cloud_percent: image.get('CLOUDY_PIXEL_PERCENTAGE')
  });
}));
Export.table.toDrive({
  collection: sceneTable, description: 'Taihu_2025_10_scene_manifest',
  fileNamePrefix: 'taihu_2025_10_scene_manifest', folder: folder,
  fileFormat: 'CSV', selectors: ['asset_id', 'date', 'tile_cloud_percent']
});
Export.image.toDrive({
  image: ndti.toFloat().unmask(-9999, false),
  description: 'Taihu_2025_10_NDTI', fileNamePrefix: 'taihu_2025_10_ndti',
  folder: folder, region: roi, scale: 10, crs: 'EPSG:32651', maxPixels: 1e8,
  fileFormat: 'GeoTIFF', formatOptions: {noData: -9999, cloudOptimized: true}
});
