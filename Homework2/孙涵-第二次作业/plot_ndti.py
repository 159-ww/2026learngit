"""Render the exported Lake Taihu NDTI rasters and write reproducible summary stats.

Usage: python plot_ndti.py [--data-dir data] [--output-dir results]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import rasterio


SOURCE_NAME = "taihu_2025_10_s2_source.tif"
NDTI_NAME = "taihu_2025_10_ndti.tif"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    source_path = args.data_dir / SOURCE_NAME
    ndti_path = args.data_dir / NDTI_NAME
    for path in (source_path, ndti_path):
        if not path.is_file():
            parser.error(f"Missing GEE export: {path}")

    with rasterio.open(source_path) as src:
        if src.count != 4:
            raise ValueError("Source GeoTIFF must have B2, B3, B4, clear_count")
        blue, green, red, count = src.read(masked=True)
        source_crs, source_transform = src.crs, src.transform
        bounds = src.bounds
    with rasterio.open(ndti_path) as src:
        if src.count != 1:
            raise ValueError("NDTI GeoTIFF must have exactly one band")
        ndti = src.read(1, masked=True)
        if (src.crs != source_crs or src.transform != source_transform
                or src.shape != red.shape):
            raise ValueError("Source and NDTI rasters are not on the same grid")

    valid = (~np.ma.getmaskarray(ndti)) & np.isfinite(ndti.data)
    if not valid.any():
        raise ValueError("NDTI raster has no valid lake pixels")
    values = ndti.data[valid]
    if values.min() < -1.001 or values.max() > 1.001:
        raise ValueError("NDTI values must be within [-1, 1]")

    rgb = np.stack([red.filled(0), green.filled(0), blue.filled(0)], axis=-1)
    rgb = np.clip(rgb.astype(np.float32) / 2500.0, 0, 1) ** (1 / 1.3)
    rgb_mask = np.ma.getmaskarray(red) | np.ma.getmaskarray(green) | np.ma.getmaskarray(blue)
    rgb[rgb_mask] = 1

    cmap = LinearSegmentedColormap.from_list(
        "ndti", ["#164b91", "#4fa9c6", "#d8e7dc", "#f2c879", "#c75b3a"]
    )
    cmap.set_bad("#f2f2ee")
    extent = [bounds.left / 1000, bounds.right / 1000,
              bounds.bottom / 1000, bounds.top / 1000]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5),
                             gridspec_kw={"width_ratios": [1, 1, 0.82]},
                             layout="constrained")
    axes[0].imshow(rgb, extent=extent, origin="upper")
    axes[0].set_title("Sentinel-2 true color", fontweight="bold")
    im = axes[1].imshow(ndti, extent=extent, origin="upper", cmap=cmap,
                        vmin=-0.30, vmax=-0.05)
    axes[1].set_title("Lake Taihu / Meiliang Bay: NDTI", fontweight="bold")
    fig.colorbar(im, ax=axes[1], label="NDTI (unitless)", shrink=0.82)
    for ax in axes[:2]:
        ax.set_xlabel("Easting (km, UTM 51N)")
        ax.set_ylabel("Northing (km, UTM 51N)")
    axes[2].hist(values, bins=45, color="#c75b3a", alpha=0.88)
    axes[2].axvline(values.mean(), color="#243849", linestyle="--",
                    label=f"Mean {values.mean():.3f}")
    axes[2].set_xlim(-0.5, 0.5)
    axes[2].set_xlabel("NDTI (unitless)")
    axes[2].set_ylabel("Valid 10 m pixels")
    axes[2].set_title("Lake-pixel distribution", fontweight="bold")
    axes[2].legend(frameon=False)
    fig.suptitle("October 2025 cloud-masked median composite", fontsize=14)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    figure_path = args.output_dir / "taihu_2025_10_ndti_map.png"
    fig.savefig(figure_path, dpi=180, facecolor="white")
    plt.close(fig)

    report = {
        "source_file": SOURCE_NAME,
        "ndti_file": NDTI_NAME,
        "crs": str(source_crs),
        "pixel_size_m": [abs(source_transform.a), abs(source_transform.e)],
        "valid_lake_pixels": int(valid.sum()),
        "valid_lake_area_km2": float(valid.sum() * abs(source_transform.a * source_transform.e) / 1e6),
        "ndti_mean": float(values.mean()),
        "ndti_std": float(values.std()),
        "ndti_min": float(values.min()),
        "ndti_median": float(np.median(values)),
        "ndti_max": float(values.max()),
        "clear_observation_count_min": int(count.data[valid].min()),
        "clear_observation_count_median": float(np.median(count.data[valid])),
        "clear_observation_count_max": int(count.data[valid].max()),
    }
    report_path = args.output_dir / "summary.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved {figure_path} and {report_path}")


if __name__ == "__main__":
    main()
