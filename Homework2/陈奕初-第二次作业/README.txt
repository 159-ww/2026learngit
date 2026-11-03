苏州大阳山翡翠湖矿坑 NDVI 年际变化分析（2001—2025）
Google Earth Engine (GEE) JavaScript 脚本说明
============================================================

一、项目简介
本脚本基于 Google Earth Engine 平台，利用Landsat系列卫星地表反射率数据，分析苏州大阳山翡翠湖矿坑周边区域 2001—2025 年植被 NDVI（归一化植被指数）的年际变化，并对比2005—2010年与2020—2025年前后两个时期的植被状况与空间差异。

二、研究区
中心点坐标：120.456080°E, 31.350040°N
投影：UTM 51N (EPSG:32651)
范围：以中心点为中心、边长约 1 km × 1 km 的正方形

三、数据来源
Landsat Collection 2 Level-2地表反射率产品：
Landsat 5 (2001—2011)、Landsat 7 (2001—2023)、Landsat 8 (2013—2025)、Landsat 9 (2022—2025)
2001—2012 年主要依赖 Landsat 5/7，2013 年起由 Landsat 8/9 补充。

四、处理方法
云掩膜：QA_PIXEL 低 6 位为 0，且 QA_RADSAT 为 0
反射率校正：原始值 × 0.0000275 − 0.2
NDVI 计算：NDVI = (NIR − Red) / (NIR + Red)
逐年合成：每年全部有效影像取中位数
区域统计：逐年 NDVI 取研究区空间范围中位数

五、主要输出图表：
2001—2025年逐年 NDVI 趋势折线图
EmeraldLake_NDVI_change.tif（NDVI变化图）
EmeraldLake_NDVI_2005_2010.tif（前期NDVI）
EmeraldLake_NDVI_2020_2025.tif（后期NDVI）
EmeraldLake_RGB_2005_2010.tif（前期真彩色影像）
EmeraldLake_RGB_2020_2025.tif（后期真彩色影像）
EmeraldLake_NDVI_yearly_2001_2025.csv（逐年 NDVI 统计表）

六、使用方法
打开https://code.earthengine.google.com/网站；
新建脚本，粘贴JS代码；
点击Run运行；
在Console查看图表与统计结果；
在Tasks面板中点击Run导出文件到Google Drive。


