# 第一次作业：杭州市大学POI下载与投影可视化

## 数据来源
- 高德地图搜索POI API（关键字搜索）
- 城市：杭州
- 关键词：大学
- 共获取117条POI数据

## 坐标系
- 原始坐标系：GCJ-02（高德默认）
- 投影坐标系：Web Mercator（EPSG:3857）

## 文件说明
| 文件 | 说明 |
|---|---|
| download_poi.py | 下载与绘图脚本 |
| hangzhou_universities.csv | 原始POI数据 |
| hangzhou_universities_projected.csv | 投影后数据 |
| map.png | 杭州市大学分布地图 |
| chart.png | POI类型统计图 |