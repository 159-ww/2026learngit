"""用 GEE/Geemap 下载杭州 Sentinel-2 合成影像，并计算、展示 NDVI。"""

from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
from pathlib import Path

import ee
import folium
import geemap
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
from PIL import Image
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds


OUTPUT_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT = "prefab-imagery-512908-g2"  # 已授权 notebook 中使用的项目
START_DATE = "2025-09-01"
END_DATE = "2025-11-01"  # GEE 的结束日期不包含当天
SCALE_METERS = 30  # 全市 10 m 文件很大；30 m 便于本地保存和作业展示
CRS = "EPSG:32650"
NDVI_NODATA = -9999.0


def get_hangzhou() -> ee.FeatureCollection:
    """GAUL 2025 的杭州地级市边界，约 1.66 万平方公里。"""
    boundary = (
        ee.FeatureCollection("FAO/GAUL/2025/level2")
        .filter(ee.Filter.eq("GAUL0_NAME", "China"))
        .filter(ee.Filter.eq("GAUL1_NAME", "Zhejiang Province"))
        .filter(ee.Filter.eq("GAUL2_NAME", "Hangzhou"))
    )
    if boundary.size().getInfo() != 1:
        raise RuntimeError("未能唯一定位杭州市边界，请检查 GAUL 数据集字段。")
    return boundary


def make_composite(roi: ee.Geometry) -> tuple[ee.Image, int]:
    """Cloud Score+ 加 SCL 排云/阴影，生成生长季中位数合成。"""
    cloud_score = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    scenes = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate(START_DATE, END_DATE)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 40))
    )
    count = scenes.size().getInfo()
    if count == 0:
        raise RuntimeError("指定日期内没有 Sentinel-2 影像。")

    def mask_clouds(image: ee.Image) -> ee.Image:
        scl = image.select("SCL")
        clear_scl = (
            scl.neq(0)  # 无数据
            .And(scl.neq(1))  # 饱和/故障
            .And(scl.neq(3))  # 云影
            .And(scl.neq(8))  # 中概率云
            .And(scl.neq(9))  # 高概率云
            .And(scl.neq(10))  # 卷云
            .And(scl.neq(11))  # 雪/冰
        )
        clear_score = image.select("cs_cdf").gte(0.60)
        return image.updateMask(clear_scl.And(clear_score)).select(
            ["B2", "B3", "B4", "B8"]
        )

    composite = scenes.linkCollection(cloud_score, ["cs_cdf"]).map(mask_clouds).median()
    return composite, count


def calculate_local_ndvi(source_path: Path, output_path: Path) -> None:
    """从下载的 B4/B8 波段逐块计算 NDVI，避免将全市影像读入内存。"""
    with rasterio.open(source_path) as source:
        if source.count != 2 or list(source.descriptions) != ["B4", "B8"]:
            raise RuntimeError("下载影像的波段顺序不是 B4、B8，已停止计算。")
        profile = source.profile.copy()
        profile.update(
            count=1,
            dtype="float32",
            nodata=NDVI_NODATA,
            compress="deflate",
            predictor=3,
            tiled=True,
        )
        with rasterio.open(output_path, "w", **profile) as target:
            target.set_band_description(1, "NDVI")
            for _, window in source.block_windows(1):
                red = source.read(1, window=window).astype(np.float32)
                nir = source.read(2, window=window).astype(np.float32)
                denominator = nir + red
                valid = (
                    (source.read_masks(1, window=window) > 0)
                    & (source.read_masks(2, window=window) > 0)
                    & (denominator > 0)
                )
                ndvi = np.full(red.shape, NDVI_NODATA, dtype=np.float32)
                np.divide(nir - red, denominator, out=ndvi, where=valid)
                target.write(ndvi, 1, window=window)


def save_preview(ndvi_path: Path, output_path: Path) -> None:
    """将 NDVI 栅格降采样为适合报告查看的离线图片。"""
    with rasterio.open(ndvi_path) as source:
        width = min(source.width, 1800)
        height = round(source.height * width / source.width)
        values = source.read(
            1, out_shape=(height, width), masked=True, resampling=Resampling.average
        )
    colors = ["#8b3a3a", "#e6a947", "#f7e8a3", "#c7dc79", "#5d9f50", "#166a3a"]
    cmap = LinearSegmentedColormap.from_list("ndvi", colors)
    cmap.set_bad("white")
    fig, ax = plt.subplots(figsize=(10, 7), dpi=180)
    image = ax.imshow(values, cmap=cmap, vmin=-0.2, vmax=0.9, interpolation="nearest")
    ax.set_title("Hangzhou NDVI | Sep–Oct 2025", fontsize=16, pad=12)
    ax.axis("off")
    fig.colorbar(image, ax=ax, label="NDVI", orientation="horizontal", fraction=0.045, pad=0.025)
    fig.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def save_map(boundary: ee.FeatureCollection, ndvi_path: Path, output_path: Path) -> None:
    """将本地 NDVI 栅格嵌入 Leaflet HTML，不使用 Jupyter widget 或临时 GEE 瓦片。"""
    with rasterio.open(ndvi_path) as source:
        full_transform, full_width, full_height = calculate_default_transform(
            source.crs, "EPSG:3857", source.width, source.height, *source.bounds
        )
        width = min(full_width, 2400)
        height = round(full_height * width / full_width)
        transform = full_transform * Affine.scale(full_width / width, full_height / height)
        values = np.full((height, width), NDVI_NODATA, dtype=np.float32)
        reproject(
            source=rasterio.band(source, 1),
            destination=values,
            src_nodata=NDVI_NODATA,
            dst_nodata=NDVI_NODATA,
            dst_transform=transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
        )

    palette = ["#8b3a3a", "#e6a947", "#f7e8a3", "#c7dc79", "#5d9f50", "#166a3a"]
    cmap = LinearSegmentedColormap.from_list("ndvi-map", palette)
    scaled = np.clip((values + 0.2) / 1.1, 0, 1)
    rgba = (cmap(scaled) * 255).astype(np.uint8)
    rgba[values == NDVI_NODATA, 3] = 0
    png = BytesIO()
    Image.fromarray(rgba).save(png, format="PNG", optimize=True)
    image_uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode("ascii")

    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    west, south, east, north = transform_bounds(
        "EPSG:3857", "EPSG:4326", left, bottom, right, top
    )
    bounds = [[south, west], [north, east]]

    map_view = folium.Map(location=[29.87, 119.45], tiles=None, zoom_start=9, control_scale=True)
    folium.raster_layers.ImageOverlay(
        image=image_uri,
        bounds=bounds,
        name="NDVI（2025 年 9–10 月）",
        overlay=True,
        show=True,
        opacity=1,
    ).add_to(map_view)
    folium.GeoJson(
        boundary.geometry().simplify(300).getInfo(),
        name="杭州市边界",
        style_function=lambda _: {"color": "#202020", "fillOpacity": 0, "weight": 2},
    ).add_to(map_view)
    folium.LayerControl(collapsed=False).add_to(map_view)
    map_view.fit_bounds(bounds)
    legend = (
        '<div style="position:fixed;bottom:24px;right:24px;z-index:9999;'
        'background:white;padding:10px 12px;border-radius:5px;'
        'box-shadow:0 1px 6px #777;font:13px sans-serif">'
        '<b>NDVI</b><br><div style="width:180px;height:14px;'
        'background:linear-gradient(to right,#8b3a3a,#e6a947,#f7e8a3,'
        '#c7dc79,#5d9f50,#166a3a)"></div>-0.2'
        '<span style="float:right">0.9</span></div>'
    )
    map_view.get_root().html.add_child(folium.Element(legend))
    map_view.save(str(output_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="GEE 云项目 ID")
    parser.add_argument("--scale", type=int, default=SCALE_METERS, help="下载分辨率（米）")
    parser.add_argument("--map-only", action="store_true", help="只生成交互地图")
    args = parser.parse_args()
    if args.scale <= 0:
        parser.error("--scale 必须为正数")

    ee.Initialize(project=args.project)
    boundary = get_hangzhou()
    roi = boundary.geometry().simplify(100)
    composite, scene_count = make_composite(roi)
    print(f"杭州市边界：{roi.area().divide(1e6).getInfo():.0f} km²")
    print(f"Sentinel-2 候选影像：{scene_count} 景")

    source_path = OUTPUT_DIR / "hangzhou_sentinel2_B4_B8_2025.tif"
    ndvi_path = OUTPUT_DIR / "hangzhou_ndvi_2025.tif"
    preview_path = OUTPUT_DIR / "hangzhou_ndvi_preview.png"
    if not args.map_only:
        if source_path.exists():
            with rasterio.open(source_path) as existing:
                if abs(existing.res[0] - args.scale) > 0.1:
                    source_path.unlink()
        # geemap 调用 geedim 自动分块下载，并拼成一个 GeoTIFF。
        if not source_path.exists():
            partial_path = OUTPUT_DIR / "hangzhou_sentinel2_B4_B8_2025.partial.tif"
            partial_path.unlink(missing_ok=True)
            try:
                geemap.download_ee_image(
                    composite.select(["B4", "B8"]).clip(roi),
                    filename=str(partial_path),
                    region=roi,
                    crs=CRS,
                    scale=args.scale,
                    dtype="uint16",
                    num_threads=4,
                    max_tile_size=4,
                    unmask_value=0,
                )
                with rasterio.open(partial_path, "r+") as source:
                    if source.count != 2:
                        raise RuntimeError("下载影像波段数不是 2。")
                    source.set_band_description(1, "B4")
                    source.set_band_description(2, "B8")
                partial_path.replace(source_path)
            finally:
                partial_path.unlink(missing_ok=True)
        calculate_local_ndvi(source_path, ndvi_path)
        save_preview(ndvi_path, preview_path)
        print(f"红光/近红外合成影像：{source_path}")
        print(f"NDVI GeoTIFF：{ndvi_path}")
        print(f"NDVI 预览图：{preview_path}")
    elif not ndvi_path.exists():
        raise FileNotFoundError("尚无 NDVI GeoTIFF，请先运行不带 --map-only 的完整分析。")

    map_path = OUTPUT_DIR / "hangzhou_ndvi_map.html"
    print("生成独立 HTML 地图...", flush=True)
    save_map(boundary, ndvi_path, map_path)
    print(f"交互地图：{map_path}")

    saved_scale = None
    saved_crs = None
    if source_path.exists():
        with rasterio.open(source_path) as saved_image:
            saved_scale = saved_image.res[0]
            saved_crs = str(saved_image.crs)

    metadata = {
        "study_area": "Hangzhou, Zhejiang, China",
        "boundary_asset": "FAO/GAUL/2025/level2",
        "boundary_filter": {"GAUL1_NAME": "Zhejiang Province", "GAUL2_NAME": "Hangzhou"},
        "image_asset": "COPERNICUS/S2_SR_HARMONIZED",
        "cloud_score_asset": "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
        "start_date_inclusive": START_DATE,
        "end_date_exclusive": END_DATE,
        "candidate_scene_count": scene_count,
        "composite": "cloud-masked median B4/B8",
        "ndvi_formula": "(B8 - B4) / (B8 + B4)",
        "download_scale_m": saved_scale,
        "download_crs": saved_crs,
    }
    (OUTPUT_DIR / "hangzhou_ndvi_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
