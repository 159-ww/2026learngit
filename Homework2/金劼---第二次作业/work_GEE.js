// ================================================
// 苏州四季地表温度：城区、郊区、南大苏州校区及周边
// ================================================


// 1. 创建5个样区

// 姑苏老城区
var urban1 = ee.Geometry.Rectangle(
  [120.605, 31.305, 120.625, 31.325]
);

// 狮山建成区
var urban2 = ee.Geometry.Rectangle(
  [120.535, 31.285, 120.555, 31.305]
);

// 北部乡村候选区
var rural1 = ee.Geometry.Rectangle(
  [120.575, 31.445, 120.595, 31.465]
);

// 西北部乡村候选区
var rural2 = ee.Geometry.Rectangle(
  [120.435, 31.425, 120.455, 31.445]
);

// 南大苏州校区及周边：近似范围，不是精确校界
var campus = ee.Geometry.Rectangle(
  [120.365, 31.338, 120.398, 31.368]
);

var zones = ee.FeatureCollection([
  ee.Feature(urban1, {zone: 'Urban1', type: 'Urban'}),
  ee.Feature(urban2, {zone: 'Urban2', type: 'Urban'}),
  ee.Feature(rural1, {zone: 'Rural1', type: 'Rural'}),
  ee.Feature(rural2, {zone: 'Rural2', type: 'Rural'}),
  ee.Feature(campus, {zone: 'NJU', type: 'Campus'})
]);

// 自动生成研究范围，包含全部样区
var roi = zones.geometry().bounds().buffer(2000).bounds();

Map.setOptions('SATELLITE');
Map.centerObject(roi, 11);


// 2. 去云与温度换算
function getTemperature(image) {
  // 排除填充值、云、云影、卷云和雪
  var clear = image.select('QA_PIXEL')
    .bitwiseAnd(63)
    .eq(0);

  var unsaturated = image.select('QA_RADSAT').eq(0);

  return image.select('ST_B10')
    .multiply(0.00341802)
    .add(149)
    .subtract(273.15)
    .rename('LST')
    .updateMask(clear)
    .updateMask(unsaturated)
    .copyProperties(image, ['system:time_start']);
}


// 3. Landsat 8、9地表温度数据
var landsat = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
  .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
  .filterBounds(roi)
  .filter(ee.Filter.eq('PROCESSING_LEVEL', 'L2SP'))
  .map(getTemperature);


// 4. 四季时间
var seasons = [
  {name: 'Winter', start: '2023-12-01', end: '2024-03-01'},
  {name: 'Spring', start: '2024-03-01', end: '2024-06-01'},
  {name: 'Summer', start: '2024-06-01', end: '2024-09-01'},
  {name: 'Autumn', start: '2024-09-01', end: '2024-12-01'}
];

// 每个像元至少需要3次有效温度观测
var minObservations = 3;

var temperatureStyle = {
  min: 0,
  max: 45,
  palette: [
    '313695', '74add1', 'ffffbf', 'f46d43', 'a50026'
  ]
};

var sampleTables = [];
var summaryRows = [];


// 5. 分季节计算
seasons.forEach(function(season, index) {

  var images = landsat.filterDate(season.start, season.end);

  print(season.name + '候选影像数量', images.size());

  // 有效观测次数
  var count = images.count()
    .unmask(0)
    .clip(roi)
    .rename('valid_count');

  var enough = count.gte(minObservations);

  // 季节晴空观测平均温度
  var temperature = images.mean()
    .updateMask(enough)
    .clip(roi)
    .rename('LST');

  // 有效覆盖：1为满足条件，0为不满足
  var coverage = enough
    .toFloat()
    .rename('coverage');

  // 温度图
  Map.addLayer(
    temperature,
    temperatureStyle,
    season.name + ' LST',
    index === 2
  );

  // 观测次数图：默认关闭，可在Layers中打开
  Map.addLayer(
    count,
    {
      min: 0,
      max: 15,
      palette: ['ffffff', 'fee08b', '1a9850']
    },
    season.name + ' observation count',
    false
  );

  // 各样区统计
  var stats = temperature
    .addBands(coverage)
    .addBands(count)
    .reduceRegions({
      collection: zones,
      reducer: ee.Reducer.mean(),
      scale: 30,
      crs: 'EPSG:32651'
    })
    .map(function(feature) {
      return ee.Feature(null, {
        order: index,
        season: season.name,
        zone: feature.get('zone'),
        type: feature.get('type'),
        LST: feature.get('LST'),
        coverage: feature.get('coverage'),
        valid_count: feature.get('valid_count')
      });
    });

  sampleTables.push(stats);

  var urbanStats = stats.filter(
    ee.Filter.eq('type', 'Urban')
  );

  var ruralStats = stats.filter(
    ee.Filter.eq('type', 'Rural')
  );

  // 两个城区样区等权平均
  var urbanMean = ee.Algorithms.If(
    urbanStats.filter(ee.Filter.notNull(['LST'])).size().eq(2),
    urbanStats.aggregate_mean('LST'),
    null
  );

  // 两个郊区样区等权平均
  var ruralMean = ee.Algorithms.If(
    ruralStats.filter(ee.Filter.notNull(['LST'])).size().eq(2),
    ruralStats.aggregate_mean('LST'),
    null
  );

  var campusMean = stats
    .filter(ee.Filter.eq('type', 'Campus'))
    .first()
    .get('LST');

  // 城区减郊区温度
  var difference = ee.Algorithms.If(
    ee.Algorithms.IsEqual(urbanMean, null),
    null,
    ee.Algorithms.If(
      ee.Algorithms.IsEqual(ruralMean, null),
      null,
      ee.Number(urbanMean).subtract(ee.Number(ruralMean))
    )
  );

  summaryRows.push(ee.Feature(null, {
    order: index,
    season: season.name,
    urban_C: urbanMean,
    rural_C: ruralMean,
    campus_C: campusMean,
    difference_C: difference
  }));

  // 导出温度与观测次数两个波段
  Export.image.toDrive({
    image: temperature
      .addBands(count)
      .toFloat()
      .unmask(-9999),
    description: 'Suzhou_LST_' + season.name + '_2024',
    folder: 'Suzhou_LST',
    region: roi,
    scale: 30,
    crs: 'EPSG:32651',
    maxPixels: 1e9,
    fileFormat: 'GeoTIFF',
    formatOptions: {noData: -9999}
  });
});


// 6. 汇总统计表
var sampleTable = ee.FeatureCollection(sampleTables)
  .flatten()
  .sort('order');

var summaryTable = ee.FeatureCollection(summaryRows)
  .sort('order');

print('5个样区四季详细统计', sampleTable);
print('城区、郊区与校园汇总', summaryTable);

print(
  '南大校区及周边覆盖情况',
  sampleTable.filter(ee.Filter.eq('zone', 'NJU'))
);


// 7. 显示研究范围和样区边框
Map.addLayer(
  ee.FeatureCollection([ee.Feature(roi)]).style({
    color: 'ffffff',
    fillColor: '00000000',
    width: 1
  }),
  {},
  'Study area'
);

function showZones(type, color, title) {
  Map.addLayer(
    zones.filter(ee.Filter.eq('type', type)).style({
      color: color,
      fillColor: '00000000',
      width: 3
    }),
    {},
    title
  );
}

showZones('Urban', 'ff3333', 'Urban samples');
showZones('Rural', '00ff00', 'Rural samples');
showZones('Campus', 'ffff00', 'NJU campus and surroundings');


// 8. 五个样区四季温度图
var sampleChart = ui.Chart.feature.groups({
  features: sampleTable,
  xProperty: 'order',
  yProperty: 'LST',
  seriesProperty: 'zone'
})
  .setChartType('LineChart')
  .setOptions({
    title: 'Seasonal LST of five sample areas',
    hAxis: {
      title: 'Season',
      ticks: [
        {v: 0, f: 'Winter'},
        {v: 1, f: 'Spring'},
        {v: 2, f: 'Summer'},
        {v: 3, f: 'Autumn'}
      ]
    },
    vAxis: {title: 'LST (°C)'},
    lineWidth: 2,
    pointSize: 5
  });

print(sampleChart);


// 9. 城区、郊区、校园对比图
var groupChart = ui.Chart.feature.byFeature(
  summaryTable,
  'season',
  ['urban_C', 'rural_C', 'campus_C']
)
  .setChartType('LineChart')
  .setOptions({
    title: 'Urban, rural and NJU seasonal LST',
    hAxis: {title: 'Season'},
    vAxis: {title: 'LST (°C)'},
    series: {
      0: {color: '#d73027'},
      1: {color: '#1a9850'},
      2: {color: '#4575b4'}
    },
    lineWidth: 3,
    pointSize: 6
  });

print(groupChart);


// 10. 城乡温差图
var differenceChart = ui.Chart.feature.byFeature(
  summaryTable,
  'season',
  ['difference_C']
)
  .setChartType('ColumnChart')
  .setOptions({
    title: 'Urban minus rural LST',
    hAxis: {title: 'Season'},
    vAxis: {title: 'Temperature difference (°C)'},
    colors: ['#e67e22'],
    legend: {position: 'none'}
  });

print(differenceChart);


// 11. 导出各样区详细统计
Export.table.toDrive({
  collection: sampleTable,
  description: 'Suzhou_LST_all_samples',
  folder: 'Suzhou_LST',
  fileFormat: 'CSV',
  selectors: [
    'season', 'zone', 'type',
    'LST', 'coverage', 'valid_count'
  ]
});


// 12. 导出汇总统计
Export.table.toDrive({
  collection: summaryTable,
  description: 'Suzhou_LST_group_summary',
  folder: 'Suzhou_LST',
  fileFormat: 'CSV',
  selectors: [
    'season', 'urban_C', 'rural_C',
    'campus_C', 'difference_C'
  ]
});


// 13. 导出样区边界
Export.table.toDrive({
  collection: zones,
  description: 'Suzhou_sample_boundaries',
  folder: 'Suzhou_LST',
  fileFormat: 'GeoJSON'
});