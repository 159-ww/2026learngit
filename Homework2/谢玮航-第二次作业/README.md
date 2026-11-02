# 杭州市 NDVI（第二次作业）

运行 PowerShell：

```powershell
cd D:\desktop\SpatialAnalysis
& '.\第二次作业\setup.ps1'
```

`setup.ps1` 使用现有的 uv 虚拟环境安装依赖并运行分析。已默认使用 `main.ipynb` 中授权的 GEE 项目 `prefab-imagery-512908-g2`；也可传入 `--project 你的项目ID`。已有 NDVI GeoTIFF 时，仅重新生成地图可传入 `--map-only`；下载分辨率可用 `--scale 20` 修改。

脚本使用 GAUL 2025 杭州市边界、2025 年 9–10 月 Sentinel-2 L2A 地表反射率，结合 Cloud Score+ 与 SCL 排除云和云影，取逐波段中位数合成。下载 30 米分辨率的红光 B4 与近红外 B8 GeoTIFF 后，按 `(B8-B4)/(B8+B4)` 逐块计算 NDVI。30 米为下载和存储时采用的重采样尺度；原始 B4/B8 波段为 10 米。

输出均保存在当前文件夹：

- `hangzhou_sentinel2_B4_B8_2025.tif`：双波段合成影像（B4、B8）。
- `hangzhou_ndvi_2025.tif`：单波段 NDVI，缺失值为 -9999。
- `hangzhou_ndvi_map.html`：可交互 NDVI 与杭州市边界图层；NDVI 图片已嵌入 HTML。
- `hangzhou_ndvi_preview.png`：可离线查看的 NDVI 图片。
- `hangzhou_ndvi_metadata.json`：数据来源与处理参数。

HTML 地图不使用 OpenStreetMap 底图，也不使用 Jupyter widget 或会过期的 GEE 瓦片链接；图中白色区域为杭州市范围以外或无有效影像的区域。地图的 Leaflet 前端库从 CDN 加载，因此首次打开 HTML 仍需联网。影像 GeoTIFF、NDVI GeoTIFF 和 PNG 预览可离线打开。
