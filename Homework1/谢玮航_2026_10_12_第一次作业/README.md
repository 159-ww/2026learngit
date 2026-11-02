# 苏州高校周边 POI 空间分析（第二版）

## 运行

从工作区根目录通过已有的 `mytorch_3_10` 环境执行：

```powershell
conda activate mytorch_3_10
python .\myfirsthomework\第二版\scripts\suzhou_campus_poi.py
```

脚本从工作区根目录 `.env` 读取 `AMAP_API_KEY`，不在源码或数据中保存密钥。绘图使用 matplotlib `Agg` 后端，不会打开 GUI 窗口。

## 范围与坐标

- 每个校区中心周围 1,000 m；目标包括餐厅、咖啡厅、超市/便利店和书店。
- 覆盖苏州本科高校校区，并额外纳入南京大学苏州校区、中国人民大学苏州校区。
- POI 原始坐标为高德 GCJ-02；先近似转换为 WGS84，再转为中国 Albers 等积圆锥投影（标准纬线 25°N、47°N，中央经线 105°E，单位米）。
- 行政区界从高德行政区查询接口获取；街道底图来自 Esri World Street Map，图上保留来源标注。底图瓦片缓存放在本文件夹的 `data/tile_cache/`。

## 输出

- `data/`：GCJ-02 原始 CSV、Albers CSV/GPKG、WGS84 GeoJSON、校区中心点、类别统计、苏州市区县行政边界及底图瓦片缓存。
- `maps/`：带道路底图和行政区划边界的 Albers 投影 POI 分布图。
- `charts/`：类别数量柱状图、校区类别对比图、六边形空间密度图、距校区距离直方图。

只需重出地图和统计图、不再次请求 POI 时，可执行：

```powershell
python .\myfirsthomework\第二版\scripts\suzhou_campus_poi.py --reuse-data
```

行政区划范围参照[江苏省教育厅 2026 年普通高校名单](https://jyt.jiangsu.gov.cn/art/2026/3/5/art_77627_10220590.html)。高德行政区边界字段与接口参数见[官方文档](https://lbs.amap.com/api/webservice/guide/api/district/)；地图中保留底图供应方标注。

