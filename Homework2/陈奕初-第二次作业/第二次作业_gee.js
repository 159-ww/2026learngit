
// ============================================================
// 大阳山翡翠湖矿坑 NDVI 年际变化分析（2001—2025）
// 研究范围: 中心点周围500m的1km*1km区域
// ============================================================

// ---------- 1. 定义分析范围 ----------
var center = ee.Geometry.Point([120.456080, 31.350040]);

// 使用UTM 51N投影，单位为米
var utm = ee.Projection('EPSG:32651');

// 将研究中心转换为UTM平面坐标
var centerUTM = center.transform(utm, 1);
var coords = ee.List(centerUTM.coordinates());
var x = ee.Number(coords.get(0));
var y = ee.Number(coords.get(1));

// 直接构建1000m × 1000m正方形
var roi = ee.Geometry.Rectangle(
  [
    x.subtract(500),
    y.subtract(500),
    x.add(500),
    y.add(500)
  ],
  utm,
  false
);

Map.centerObject(roi, 15);
Map.addLayer(roi, {color: 'red'}, '1000m×1000m研究区');
Map.addLayer(center, {color: 'blue'}, '研究中心');

// ---------- 2. 时间节点 ----------
var PERIOD_A_START = '2005-01-01';
var PERIOD_A_END = '2011-01-01';
var PERIOD_B_START = '2020-01-01';
var PERIOD_B_END = '2026-01-01';

// ---------- 3. 云掩膜及反射率校正 ----------
function prepareLandsat(image, blueBand, greenBand, redBand, nirBand) {
  var qa = image.select('QA_PIXEL');
  var qaMask = qa.bitwiseAnd(63).eq(0);
  var saturationMask = image.select('QA_RADSAT').eq(0);

  var optical = image.select(
    [blueBand, greenBand, redBand, nirBand],
    ['Blue', 'Green', 'Red', 'NIR']
  ).multiply(0.0000275).add(-0.2);

  return optical
    .updateMask(qaMask)
    .updateMask(saturationMask)
    .copyProperties(image, ['system:time_start']);
}

// ---------- 4. 分传感器处理 ----------
var sr5 = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
  .filterBounds(roi)
  .filterDate('2001-01-01', '2012-01-01')
  .filter(ee.Filter.lt('CLOUD_COVER', 30))
  .map(function(image) {
    return prepareLandsat(image, 'SR_B1', 'SR_B2', 'SR_B3', 'SR_B4');
  });

var sr7 = ee.ImageCollection('LANDSAT/LE07/C02/T1_L2')
  .filterBounds(roi)
  .filterDate('2001-01-01', '2024-01-01')
  .filter(ee.Filter.lt('CLOUD_COVER', 30))
  .map(function(image) {
    return prepareLandsat(image, 'SR_B1', 'SR_B2', 'SR_B3', 'SR_B4');
  });

var sr8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
  .filterBounds(roi)
  .filterDate('2013-01-01', '2026-01-01')
  .filter(ee.Filter.lt('CLOUD_COVER', 30))
  .map(function(image) {
    return prepareLandsat(image, 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5');
  });

var sr9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
  .filterBounds(roi)
  .filterDate('2022-01-01', '2026-01-01')
  .filter(ee.Filter.lt('CLOUD_COVER', 30))
  .map(function(image) {
    return prepareLandsat(image, 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5');
  });

var srAll = sr5.merge(sr7).merge(sr8).merge(sr9);

// 计算NDVI
function calculateNDVI(collection) {
  return collection.map(function(image) {
    var nir = image.select('NIR');
    var red = image.select('Red');
    var denominator = nir.add(red);

    var ndvi = image.expression(
      '(NIR - RED) / (NIR + RED)', {
        'NIR': nir,
        'RED': red
      }
    ).rename('NDVI')
     .updateMask(denominator.abs().gt(0.001));

    return ndvi.copyProperties(image, ['system:time_start']);
  });
}

var ndviAll = calculateNDVI(srAll);

// ---------- 5. 2001—2025年逐年NDVI趋势图 ----------

// 每年使用当年全部有效影像进行中位数合成
var years = ee.List.sequence(2001, 2025);

var annualNDVI = ee.ImageCollection.fromImages(
  years.map(function(year) {
    year = ee.Number(year);
    var start = ee.Date.fromYMD(year, 1, 1);
    var end = start.advance(1, 'year');

    var annual = ndviAll
      .filterDate(start, end)
      .median()
      .set('year', year)
      .set('system:time_start', start.millis());

    return annual;
  })
);

// 计算每年研究区NDVI空间中位数
var annualStats = ee.FeatureCollection(
  annualNDVI.map(function(image) {
    var stat = image.reduceRegion({
      reducer: ee.Reducer.median(),
      geometry: roi,
      scale: 30,
      maxPixels: 1e8,
      tileScale: 2
    });

    return ee.Feature(null, {
      'year': image.get('year'),
      'NDVI': stat.get('NDVI')
    });
  })
).sort('year');

// 绘制年度趋势图
var chart = ui.Chart.feature.byFeature(
  annualStats,
  'year',
  ['NDVI']
).setChartType('LineChart')
.setOptions({
  title: '大阳山翡翠湖矿坑周边植被年际变化（2001—2025）',
  titleTextStyle: {
    fontSize: 16,
    bold: true
  },
  hAxis: {
    title: '年份',
    format: '####',
    slantedText: false,
    textStyle: {fontSize: 10},
    titleTextStyle: {fontSize: 13}
  },
  vAxis: {
    title: 'NDVI 中位数',
    viewWindowMode: 'pretty',
    gridlines: {
      count: 6,
      color: '#e5e5e5'
    },
    minorGridlines: {
      count: 1,
      color: '#f2f2f2'
    },
    titleTextStyle: {fontSize: 13}
  },
  colors: ['#2e7d32'],
  lineWidth: 2,
  pointSize: 4,
  legend: {position: 'none'},
  chartArea: {
    width: '85%',
    height: '72%'
  },
  backgroundColor: 'white'
});

print('2001—2025年逐年NDVI趋势图', chart);
print('逐年NDVI统计数据', annualStats);

// ---------- 6. 前后期NDVI合成与变化 ----------
var periodA = ndviAll
  .filterDate(PERIOD_A_START, PERIOD_A_END)
  .median()
  .clip(roi);

var periodB = ndviAll
  .filterDate(PERIOD_B_START, PERIOD_B_END)
  .median()
  .clip(roi);

var visNDVI = {
  min: -0.2,
  max: 0.8,
  palette: ['8c510a', 'dfc27d', 'f6e8c3', 'a6dba0', '1b7837']
};

Map.addLayer(periodA, visNDVI, 'NDVI前期 (2005–2010)', false);
Map.addLayer(periodB, visNDVI, 'NDVI后期 (2020–2025)', true);

var change = periodB.subtract(periodA)
  .rename('NDVI_change')
  .clip(roi);

Map.addLayer(change, {
  min: -0.3,
  max: 0.3,
  palette: ['d73027', 'f7f7f7', '1a9850']
}, 'NDVI变化 (后期-前期)', false);

// ---------- 7. 前后期真实彩色遥感影像 ----------
var rgbA = srAll
  .filterDate(PERIOD_A_START, PERIOD_A_END)
  .median()
  .select(['Red', 'Green', 'Blue'])
  .clip(roi);

var rgbB = srAll
  .filterDate(PERIOD_B_START, PERIOD_B_END)
  .median()
  .select(['Red', 'Green', 'Blue'])
  .clip(roi);

var visRGB = {
  bands: ['Red', 'Green', 'Blue'],
  min: 0.02,
  max: 0.30,
  gamma: 1.2
};

Map.addLayer(rgbA, visRGB, '真实彩色遥感影像 (2005–2010)', false);
Map.addLayer(rgbB, visRGB, '真实彩色遥感影像 (2020–2025)', false);

// ---------- 8. 数值统计 ----------
var statsA = periodA.reduceRegion({
  reducer: ee.Reducer.median(),
  geometry: roi,
  scale: 30,
  maxPixels: 1e8
});

var statsB = periodB.reduceRegion({
  reducer: ee.Reducer.median(),
  geometry: roi,
  scale: 30,
  maxPixels: 1e8
});

print('前期NDVI中位数 (2005–2010):', statsA);
print('后期NDVI中位数 (2020–2025):', statsB);

print('前后期NDVI变化量:', 
  ee.Number(statsB.get('NDVI'))
    .subtract(ee.Number(statsA.get('NDVI')))
);

// ---------- 9. 导出数据 ----------

// 9.1 导出NDVI变化图
Export.image.toDrive({
  image: change,
  description: 'EmeraldLake_NDVI_change',
  scale: 30,
  region: roi,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});

// 9.2 导出前后期NDVI图
Export.image.toDrive({
  image: periodA,
  description: 'EmeraldLake_NDVI_2005_2010',
  scale: 30,
  region: roi,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});

Export.image.toDrive({
  image: periodB,
  description: 'EmeraldLake_NDVI_2020_2025',
  scale: 30,
  region: roi,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});

// 9.3 导出前后期真实彩色遥感影像
Export.image.toDrive({
  image: rgbA.visualize(visRGB),
  description: 'EmeraldLake_RGB_2005_2010',
  scale: 30,
  region: roi,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});

Export.image.toDrive({
  image: rgbB.visualize(visRGB),
  description: 'EmeraldLake_RGB_2020_2025',
  scale: 30,
  region: roi,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF'
});

// 9.4 导出逐年NDVI统计表
Export.table.toDrive({
  collection: annualStats,
  description: 'EmeraldLake_NDVI_yearly_2001_2025',
  fileFormat: 'CSV'
});
