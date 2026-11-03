// 金鸡湖及周边：Sentinel-2地表反射率影像与NDWI。
// 在 https://code.earthengine.google.com/ 的编辑区粘贴本文件后点击Run。
// NDWI=(B3-B8)/(B3+B8)，B3为绿光，B8为近红外，均为10m。

// 1. 固定坐标系与输出网格。坐标单位为米，研究区为6×6km矩形。
var crs = 'EPSG:32651';
var grid = [10, 0, 278110, 0, -10, 3469240];
var roi = ee.Geometry.Rectangle([278110,3463240,284110,3469240],crs,false);
var prefix = 'COPERNICUS/S2_SR_HARMONIZED/';
var scenes = [
  {season:'winter',label:'冬季',date:'2024-01-13',id:'20240113T024051_20240113T024046_T51RTQ'},
  {season:'spring',label:'春季',date:'2024-05-17',id:'20240517T023529_20240517T024223_T51RTQ'},
  {season:'summer',label:'夏季',date:'2024-07-31',id:'20240731T023551_20240731T024818_T51RTQ'},
  {season:'autumn',label:'秋季',date:'2024-10-29',id:'20241029T023821_20241029T023824_T51RTQ'}
];
// 统一-1～1色标：负值为棕色，接近0为浅色，正值为蓝色。
var palette = ['8c510a','bf812d','dfc27d','f6e8c3','faf5e8','f7f7f7',
               'd1e5f0','92c5de','4393c3','2166ac','053061'];
var vis = {min:-1,max:1,palette:palette};
Map.centerObject(roi,13);

// 2. 根据SCL场景分类去除云、云影等，保留植被(4)、非植被(5)、水体(6)。
// SCL原始为20m，默认最近邻对齐到10m，不会增加分类细节。
function validMask(image) {
  var scl=image.select('SCL');
  return scl.eq(4).or(scl.eq(5)).or(scl.eq(6));
}
function calculateNDWI(image) {
  var denominator=image.select('B3').add(image.select('B8'));
  // 两个波段具有相同的0.0001比例因子，在归一化比值中会抵消。
  // 要求分母>0，避免除零；clip只保留研究区内的像元。
  return ee.Image(image.normalizedDifference(['B3','B8']).rename('NDWI_EE')
    .updateMask(validMask(image).and(denominator.gt(0))).clip(roi)
    .copyProperties(image,['system:time_start']));
}

// 3. 逐景显示真彩色和NDWI，记录完整影像ID和质量信息。
var raw=[],indices=[],metadata=[];
scenes.forEach(function(s,i) {
  var image=ee.Image(prefix+s.id);
  var ndwi=calculateNDWI(image);
  raw.push(image);indices.push(ndwi);
  var valid20=validMask(image).unmask(0,false).reduceRegion({
    reducer:ee.Reducer.mean(),geometry:roi,crs:crs,
    crsTransform:[20,0,278110,0,-20,3469240],maxPixels:1e7
  }).getNumber('SCL');
  metadata.push(ee.Feature(null,{season:s.season,label:s.label,date:s.date,
    asset_id:prefix+s.id,tile_cloud_pct:image.get('CLOUDY_PIXEL_PERCENTAGE'),
    roi_scl_valid_fraction_20m:valid20}));
  Map.addLayer(image.clip(roi),{bands:['B4','B3','B2'],min:0,max:3000,gamma:1.4},s.label+' 真彩色',false);
  Map.addLayer(ndwi,vis,s.label+' NDWI',i===2);
});

// 4. 固定四期共同有效像元，避免各期统计范围随云量变化。
var common=ee.ImageCollection.fromImages(indices.map(function(n){return n.mask();})).min().gt(0);
var land=common,water=common;
raw.forEach(function(image){land=land.and(image.select('SCL').neq(6));water=water.and(image.select('SCL').eq(6));});
var groups=[{name:'all_common',mask:common},{name:'stable_nonwater',mask:land},{name:'stable_water',mask:water}];
var rows=[];
scenes.forEach(function(s,i){
  groups.forEach(function(g){
    var values=indices[i].updateMask(g.mask).reduceRegion({
      reducer:ee.Reducer.mean().combine({reducer2:ee.Reducer.count(),sharedInputs:true}),
      geometry:roi,crs:crs,crsTransform:grid,maxPixels:1e7});
    rows.push(ee.Feature(null,{date:s.date,season:s.season,group:g.name,
      mean_NDWI:values.get('NDWI_EE_mean'),pixel_count:values.get('NDWI_EE_count')}));
  });
});
var statistics=ee.FeatureCollection(rows);
print('固定像元的NDWI统计',statistics);
print(ui.Chart.feature.groups(statistics,'date','mean_NDWI','group').setChartType('LineChart')
  .setOptions({title:'金鸡湖及周边四期NDWI',pointSize:5,lineWidth:2,
    hAxis:{title:'日期（类别轴，不代表等时间间隔）'},vAxis:{title:'NDWI',viewWindow:{min:-1,max:1}}}));
Map.addLayer(indices[2].subtract(indices[0]).updateMask(common),
  {min:-0.6,max:0.6,palette:['b2182b','f7f7f7','2166ac']},'夏季减冬季 NDWI',false);
// NDWI>0只是水体候选阈值，可能受建筑、阴影等影响，并不是实测湖岸。
Map.addLayer(indices[2].gt(0).selfMask(),{palette:['2185d0']},'夏季 NDWI>0 候选范围',false);
Map.addLayer(ee.FeatureCollection([ee.Feature(roi)]).style(
  {color:'ff9800',fillColor:'00000000',width:2}),{},'6×6km研究区');
var legend=ui.Panel({style:{position:'bottom-left',padding:'8px'}});
legend.add(ui.Label('NDWI = (B3-B8) / (B3+B8)'));
legend.add(ui.Thumbnail({image:ee.Image.pixelLonLat().select('longitude'),
  params:{bbox:[-1,0,1,.1],dimensions:'240x16',min:-1,max:1,palette:palette}}));
legend.add(ui.Label('−1（棕）       0       +1（蓝）'));
legend.add(ui.Label('NDWI不能直接用于判断水质；灰白空缺为无效观测'));
Map.add(legend);

// 5. 生成本次新的GeoTIFF下载链接，输出六个波段：B2/B3/B4/B8/SCL/NDWI_EE。
// evaluate把服务器端元数据取回浏览器，getDownloadURL的回调返回临时地址。
ee.FeatureCollection(metadata).evaluate(function(result,error){
  if(error){print('ERROR',error);return;}
  var manifest={collection:'COPERNICUS/S2_SR_HARMONIZED',
    source:'European Union/ESA/Copernicus; Google Earth Engine',project_id:'ndvindvi1',
    index:'NDWI',formula:'(B3-B8)/(B3+B8)',crs:crs,transform:grid,
    width:600,height:600,area_km2:36,nodata:-9999,reflectance_scale:0.0001,
    valid_scl:[4,5,6],bands:['B2','B3','B4','B8','SCL','NDWI_EE'],
    roi_description:'金鸡湖及周边6×6km矩形，不是官方湖岸边界',
    scenes:result.features.map(function(f){var s=f.properties;s.file='s2_ndwi_'+s.date+'_'+s.season+'.tif';return s;})};
  var remaining=manifest.scenes.length;
  manifest.scenes.forEach(function(s,i){
    // 统一数据类型和10m网格；缺测值填-9999；600×600对应完整36km²研究区。
    raw[i].select(['B2','B3','B4','B8','SCL']).addBands(indices[i]).toFloat().unmask(-9999,false)
      .getDownloadURL({name:'s2_ndwi_'+s.date+'_'+s.season,crs:crs,crs_transform:grid,
                      dimensions:[600,600],format:'GEO_TIFF',filePerBand:false},function(url,e){
        if(e){print('DOWNLOAD_ERROR '+s.season,e);return;}
        s.download_url=url;
        print(ui.Label({value:'下载 '+s.file,targetUrl:url}));
        remaining--;
        if(remaining===0){
          // 四个地址齐全后，复制下面文本框中的整段JSON，用于本地自动下载。
          print('DOWNLOAD_JSON：点击文本框，Ctrl+A全选后复制全部内容');
          print(ui.Textbox({value:JSON.stringify(manifest),style:{width:'450px'}}));
          print('DOWNLOAD_JSON_RAW '+JSON.stringify(manifest));
        }
      });
  });
});
