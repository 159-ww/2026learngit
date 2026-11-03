# 南京市 NDBI 建筑指数提取与可视化（Google Earth Engine）

## 作业目标

利用 GEE 下载 Landsat 9 遥感影像，计算南京市 **NDBI 建筑指数**（Normalized Difference Built-up Index），并对结果进行统计与可视化。

## 数据与方法

| 项目 | 内容 |
|---|---|
| 影像数据 | Landsat 9 Collection 2 Level 2 地表反射率（`LANDSAT/LC09/C02/T1_L2`） |
| 时间范围 | 2025-04-01 ~ 2025-10-31（春—秋，多时相中值合成抑制云影） |
| 云筛选 | 单景云量 < 30%，QA_PIXEL 波段（bit1-4：膨胀云/卷云/云/云影）逐像元去云 |
| 研究区 | 南京市中心（新街口 118.779°E, 32.042°N）15 km 缓冲区，约 30 km × 30 km |
| 分辨率 | 30 m（Landsat 原生分辨率） |
| 坐标系 | EPSG:32650（WGS 84 / UTM zone 50N，南京所在投影带，单位：米） |

### NDBI 计算公式

$$NDBI = \frac{SWIR - NIR}{SWIR + NIR} = \frac{SR\_B6 - SR\_B5}{SR\_B6 + SR\_B5}$$

- **NDBI > 0**：建成区（建筑物、裸地）——图中红色
- **NDBI ≈ 0**：过渡带——灰色中点
- **NDBI < 0**：水体、植被——图中蓝色

## 结果

GeoTIFF 有效像元 96.8%（其余为去云掩膜空洞）。

### 区域统计（[results/ndbi_nanjing_stats.csv](results/ndbi_nanjing_stats.csv)）

| 指标 | NDBI |
|---|---|
| 最小值 | -0.7560 |
| 最大值 | 0.5783 |
| 均值 | -0.1944 |
| 标准差 | 0.1413 |

补充：NDBI > 0.1（建成区）像元占 1.2%，NDBI < -0.15（水体/植被）占 60.3%。

### 结果解读

- **高值区（红）**：老城（新街口邻域最大 0.21）、河西、南京南站沿线呈斑块
  分布；建成区像元整体偏浅，原因是 30 m 混合像元（行道树与建筑混在同一
  像元）把 NDBI 拉向 0——这也是 NDBI 在高绿化城市的已知局限。
- **低值区（蓝）**：紫金山植被 ≈ -0.41（研究区最深负值）、玄武湖 ≈ -0.27；
  长江江面 ≈ -0.04，负值偏浅，因含沙量高（浊水）增强短波红外反射所致。
- **均值 -0.19**：60.3% 的像元为水体/植被，山水空间占比远大于建成区，
  与南京「山水城林」的城市格局一致。

### 可视化输出

| 文件 | 说明 |
|---|---|
| [results/ndbi_nanjing_2025.png](results/ndbi_nanjing_2025.png) | 静态专题图（300 dpi，含地物标注） |
| [data/ndbi_nanjing_2025.tif](data/ndbi_nanjing_2025.tif) | NDBI 栅格数据（GeoTIFF，EPSG:32650 UTM 50N，30 m） |

### 色带设计（发散型）

NDBI 是有正负极性的指标，采用「双色 + 中性灰中点」的发散型色带，
两支等长、亮度单调：

```
负值（水体/植被）  #0d366b → #2a78d6 → #cde2fb → #f0efec ← 0（中点）
正值（建成区）     #f0efec → #f2b6b2 → #e34948 → #882c2b
```

### 已知问题：Code Editor 底图偏移

Code Editor 的 Google 底图在中国大陆使用 GCJ-02 加密坐标，与 WGS84 影像
存在数百米偏移，**影像本身坐标是正确的**（可用脚本中叠加的 GAUL 边界验证）。
导出的 GeoTIFF 在 QGIS 中与天地图等 WGS84 数据可正常对齐。

## 如何复现

**方式一：GEE Code Editor（网页版，推荐，无需本地安装任何东西）**

1. 挂 VPN，浏览器打开 https://code.earthengine.google.com 登录
2. 新建脚本，粘贴 [gee_ndbi_nanjing.js](gee_ndbi_nanjing.js) 全部内容，点 Run
3. 地图即时显示 NDBI，Console 输出景数、统计值与三个验证点读数
4. 右侧 Tasks 面板 Run 导出任务 → GeoTIFF 存入 Google Drive
5. 从 Drive 下载后放入 data/ 文件夹

**方式二：Python（本机终端，完整流程）**

```bash
pip install earthengine-api rasterio folium pandas numpy matplotlib requests
earthengine authenticate   # 浏览器登录 Google 账号（国内需挂 VPN）
python gee_ndbi_nanjing.py
```

输出：data/ 的 GeoTIFF、results/ 的静态图 / 交互地图 / 统计 CSV。

## 文件结构

```
袁名扬-第二次作业/
├── gee_ndbi_nanjing.js          # Code Editor 版（推荐）
├── gee_ndbi_nanjing.py          # Python 完整流程版
├── README.md                    # 本说明
├── requirements.txt             # Python 依赖清单
├── data/
│   └── ndbi_nanjing_2025.tif
└── results/
    ├── ndbi_nanjing_2025.png
    └── ndbi_nanjing_stats.csv
```
