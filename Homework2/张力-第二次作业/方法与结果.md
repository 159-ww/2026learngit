# 金鸡湖及周边NDWI：方法与结果

## 数据与研究范围

本次从Google Earth Engine重新下载四景2024年Sentinel-2地表反射率影像，四个导出文件均包含B2、B3、B4、B8、SCL、NDWI_EE六个波段。下载记录、文件大小和SHA-256保存在 `data/download_receipts.json`，完整影像ID保存在 `data/manifest.json`。

研究区为覆盖金鸡湖及周边的6×6km矩形，包含城市绿地、河道及部分独墅湖，不是金鸡湖精确湖岸。采用WGS84 / UTM 51N（EPSG:32651），网格为600×600、10m像元。左上边界为(278110,3469240)m。GeoJSON边界转换到WGS84经纬度时固定经度/纬度顺序，并沿边界每100m加密。

## 指标与处理步骤

1. 使用地表反射率集合 `COPERNICUS/S2_SR_HARMONIZED`，固定冬春夏秋四景的影像ID。
2. 根据SCL分类保留植被(4)、非植被(5)、水体(6)，排除云、云影等类别。SCL原始分辨率为20m，最近邻对齐到10m不会增加分类细节。
3. 计算 **NDWI=(B3−B8)/(B3+B8)**：B3为绿光，B8为近红外，均为10m。相同的0.0001比例因子在比值中抵消，分母必须>0。
4. 四期统计采用共同有效像元；稳定水体要求四期SCL均为6，稳定非水体要求四期均不为6。
5. 本地独立复算每个像元，与GEE导出的NDWI_EE波段核对；再导出GeoTIFF、PNG、CSV和离线HTML。

## 实际统计

| 季节 | 日期 | 全区共同像元均值 | 稳定非水体均值 | 稳定水体均值 |
|---|---|---:|---:|---:|
| 冬季 | 2024-01-13 | -0.0948 | -0.2553 | 0.4028 |
| 春季 | 2024-05-17 | -0.2659 | -0.4376 | 0.2499 |
| 夏季 | 2024-07-31 | -0.1690 | -0.3937 | 0.5222 |
| 秋季 | 2024-10-29 | -0.1684 | -0.4997 | 0.8627 |

共同有效像元为 **355,138** 个，覆盖研究区 **98.6494%**，投影面积 **35.5138 km²**。所有面积按10×10m投影像元计算，不是椭球面积。完整36km²投影矩形的WGS84椭球面积约为35.98625 km²。

水体通常呈较高正值，植被和许多非水体常为负值。全区均值受周边陆地比例影响，不能将全区均值直接称为金鸡湖水面均值。`NDWI>0`比例仅用于描述候选水体响应，不等同于实测湖泊面积。

## 质量和解释限制

| 日期 | 有效水体中B8=0且B3>0的像元数（NDWI=+1） |
|---|---:|
| 2024-01-13 | 0 |
| 2024-05-17 | 273 |
| 2024-07-31 | 813 |
| 2024-10-29 | 20133 |

B8为零而B3大于零时，NDWI会达到+1。本次保留可复现的原始计算结果，并记录这些像元数量；具体辐射处理成因未进行现场验证。NDWI高值或变化不能直接代表水质改善、污染程度或实际水量变化。

每季只使用一景日期快照，不是季节平均或长期趋势。城市建筑、阴影、浑浊水体、残余云及混合像元都可能影响结果。四期稳定水体分组来自SCL，不能当作独立实测真值。

地图E/N坐标轴单位为km，GN为网格北，并非真北。NDWI各图统一使用−1～1色标，差值图统一使用±0.6；超出差值显示范围的数值仅在颜色上饱和，GeoTIFF未截断。

## 查看和运行

- 双击 `outputs/金鸡湖NDWI可视化.html`，离线切换四期真彩色和NDWI，并查看空间分布、差值和统计。
- `outputs/ndwi_four_seasons.png` 可直接用于报告；`ndwi_means.png` 为真实日期间隔的均值曲线。
- 原始导出TIF没有NoData标签和波段名时，建议在GIS中打开 `data` 内同名VRT，它补充元数据而不改变原始像元。
- GEE 脚本 `gee_jinjihu_ndwi.js` 在网页编辑器（https://code.earthengine.google.com/）中运行。
- 本地 Python 脚本 `jinjihu_ndwi.py` 与 `download_from_manifest.py` 在本地 Python 环境运行。

## 数据来源与指标定义

- [Sentinel-2 SR HARMONIZED数据目录](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)。数据来源：European Union / ESA / Copernicus；Google Earth Engine。
- [绿光—近红外NDWI波段定义](https://github.com/sentinel-hub/custom-scripts/blob/main/sentinel-2/ndwi/README.md)。
- [GEE重投影和最近邻规则](https://developers.google.com/earth-engine/guides/resample)。
