# 太湖北部梅梁湾 NDTI 可视化

本作业以太湖北部梅梁湾（经度 120.02–120.27°E、纬度 31.31–31.55°N）为研究区，使用 **2025 年 10 月重新选取的 Sentinel‑2 L2A 地表反射率影像**，计算归一化差异浑浊度指数（NDTI），并制作真彩色对照图、NDTI 分布图和直方图。此目录不读取或复用仓库中已有的南京影像。

**运行状态：** 已在 GEE 中执行脚本并完成三个导出任务；GeoTIFF、CSV、PNG 和 JSON 均已放入本目录。12 景影像参与合成；研究区内符合条件的湖水约 402.43 平方公里，NDTI 平均值约 −0.166。地图使用 −0.30 至 −0.05 的色标来突出湖内差异，超过色标两端的值会显示为端点颜色。

## 指标与方法

\[\mathrm{NDTI} = \frac{B4_{red}-B3_{green}}{B4_{red}+B3_{green}}\]

两个波段的原始空间分辨率均为 10 米。Sentinel‑2 SR 产品的 DN 乘以 0.0001 才是地表反射率；同一比例因子在上述比值中抵消。结果是**无量纲的相对水色指标**，颜色偏暖表示 NDTI 较高。没有太湖同期采样与校准数据时，不能把 NDTI 数值解读为 NTU 浊度或水质等级。

GEE 脚本先按月份和覆盖范围筛选影像，使用 SCL 分类去除云、云影和无效像元，然后对 B2/B3/B4 逐波段取中位数。为了统计湖内水色，只保留 JRC 历史水面出现频率至少 80%、离岸约 30 米且至少有 2 次清晰观测的像元。JRC 水面数据统计截至 2021 年，只用于限定分析区域；近岸与近年水位变化可能导致部分水域被排除。月合成图的不同像元可能来自不同拍摄日期，因此不能用于解释某一天的瞬时水质。

## 文件

| 路径 | 内容 |
|---|---|
| `gee_taihu_ndti.js` | GEE Code Editor 代码：筛选、掩膜、计算、可视化、统计、导出 |
| `data/taihu_2025_10_s2_source.tif` | GEE 导出的 B2/B3/B4 DN 及清晰观测次数 |
| `data/taihu_2025_10_ndti.tif` | GEE 导出的 NDTI 栅格 |
| `data/taihu_2025_10_scene_manifest.csv` | 实际参与合成的 Sentinel‑2 影像 ID 与日期 |
| `plot_ndti.py` | 用上述两个栅格制作结果图和统计摘要 |
| `results/taihu_2025_10_ndti_map.png` | 真彩色、NDTI、直方图三联图 |
| `results/summary.json` | 有效像元数、NDTI 均值等 |

## 运行与下载

1. 登录 [GEE Code Editor](https://code.earthengine.google.com/)，将 `gee_taihu_ndti.js` 全文粘贴并点击 **Run**。
2. 检查 Console 中的参与影像数、ID、NDTI 统计值和直方图；检查地图中的真彩色和 NDTI 图层。
3. 打开 **Tasks**，分别启动 `Taihu_2025_10_S2_source`、`Taihu_2025_10_NDTI` 和 `Taihu_2025_10_scene_manifest` 三个导出任务。文件会进入 Google Drive 的 `Taihu_NDTI_2025_10` 文件夹。
4. 将三个导出文件下载到本目录的 `data/` 下，并按上表文件名保存。GEE 的 Run 只创建任务，**不会自动下载文件**。
5. 在本目录运行：

   ```bash
   uv venv .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   .venv/bin/python plot_ndti.py
   ```

6. 检查 `results/` 中的 PNG 图和 JSON 统计，再将本目录内的代码、三个数据文件和两个结果文件提交到 Git。目前最大的单文件约 44 MB，低于 GitHub 的 100 MB 单文件限制。

## 数据与参考

- [Sentinel‑2 SR HARMONIZED，GEE 数据目录](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)
- [JRC Global Surface Water v1.4，GEE 数据目录](https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater)
- [NDTI 的红光/绿光公式及水体应用，Powers 等，2023](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/2023JG007650)
- [GEE 导出 GeoTIFF 的操作说明](https://developers.google.com/earth-engine/apidocs/export-image-todrive)

数据来源：European Union / ESA / Copernicus，经 Google Earth Engine 提供；水面掩膜来源：EC JRC / Google。
