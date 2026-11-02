# 南京市租车 POI：下载、投影与空间分析

## 文件说明

`car_rent.ipynb` Notebook执行下载、坐标转换、分析与可视化。 
`requirements.txt` 固定的 Python 3.13 / macOS Apple Silicon 依赖版本。 
`data/‘ 下载的csv格式pois
`analysis/` 代码生成的地图、统计图、投影后明细和摘要。

## 运行要求

- macOS；
- Python 3.13
- 高德开放平台 Web API Key



## 坐标系处理

高德 Web 服务 `location` 按 **GCJ-02** 处理。GCJ-02 不是米制投影坐标，不能直接用于距离分析或直接叠加到 Folium/OSM 的 WGS84 底图。

处理过程：
高德 location（GCJ-02 经/纬度）
  → 近似反算 WGS84（用于 Folium 地图）
  → EPSG:32650 / WGS 84 UTM zone 50N（用于米制距离和密度）

南京经度约为 118–119°E，位于 UTM 50N（114–120°E）带内。Notebook 会自动检查原始经纬度和投影后的 Easting/Northing 范围；断言失败时，请先检查输入 POI，勿继续做距离分析。

## 输出

`data/nanjing_car_rental_pois.csv`根据高德api搜索到的租车行poi合集

运行完成后 `analysis/` 会包含：

`nanjing_car_rental_map.html`租车点、热力图、高铁/铁路站、地铁站的交互地图；
`nanjing_car_rental_statistics.png`区县分布、最近高铁/铁路站距离、最近地铁站距离、地铁可达性与同业密度图；
`rental_poi_enriched_projected.csv`GCJ-02、WGS84、UTM 坐标与距离/密度指标；
`summary.json`核心统计与坐标系说明。
`nanjing_car_rental_dbscan_clusters`聚类分析数据和可视化
注：高铁和地铁指标是基于 UTM 坐标计算的直线距离，不是驾车距离或公交时间。



