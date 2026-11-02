import requests
import pandas as pd
import time
import os
import matplotlib.pyplot as plt
from pyproj import Transformer

# ========== 0. 设置保存路径 ==========
SAVE_DIR = r"D:\A22\空间分析作业"
os.makedirs(SAVE_DIR, exist_ok=True)   # 不存在会自动创建

def path(filename):
    """返回拼接后的完整路径"""
    return os.path.join(SAVE_DIR, filename)

# ========== 1. 配置 ==========
KEY = ""   # 你的Key
URL = "https://restapi.amap.com/v3/place/text"
CITY = "杭州"
KEYWORDS = "大学"
MAX_PAGES = 10

# ========== 2. 下载POI数据 ==========
def download_pois(keywords, city, max_pages=10):
    all_pois = []
    for page in range(1, max_pages + 1):
        params = {
            "key": KEY,
            "keywords": keywords,
            "city": city,
            "offset": 25,
            "page": page,
            "output": "JSON",
            "extensions": "all"
        }
        resp = requests.get(URL, params=params)
        data = resp.json()

        if data.get("status") != "1":
            print(f"请求失败: {data.get('info')}")
            break

        pois = data.get("pois", [])
        if not pois:
            print(f"第{page}页无数据，结束")
            break

        all_pois.extend(pois)
        print(f"已下载第{page}页，本页{len(pois)}条")
        time.sleep(0.5)

    return all_pois

print("开始下载杭州市大学POI...")
raw_pois = download_pois(KEYWORDS, CITY, MAX_PAGES)

# ========== 3. 解析为DataFrame ==========
records = []
for poi in raw_pois:
    lon, lat = poi["location"].split(",")
    records.append({
        "name": poi.get("name"),
        "address": poi.get("address"),
        "lon": float(lon),
        "lat": float(lat),
        "type": poi.get("type"),
        "tel": poi.get("tel", "")
    })

df = pd.DataFrame(records)
csv_raw = path("hangzhou_universities.csv")
df.to_csv(csv_raw, index=False, encoding="utf-8_sig")
print(f"共保存 {len(df)} 条POI数据 → {csv_raw}")

# ========== 4. 投影转换（Web Mercator EPSG:3857） ==========
transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
df["x"], df["y"] = transformer.transform(df["lon"].values, df["lat"].values)

csv_proj = path("hangzhou_universities_projected.csv")
df.to_csv(csv_proj, index=False, encoding="utf-8_sig")
print(f"投影完成 → {csv_proj}")

# ========== 5. 绘制地图 ==========
plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False

plt.figure(figsize=(10, 8))
plt.scatter(df["x"], df["y"], c="red", s=30, alpha=0.7)
plt.title("杭州市大学POI分布图（Web Mercator投影）")
plt.xlabel("X (m)")
plt.ylabel("Y (m)")
plt.grid(True, alpha=0.3)
map_png = path("map.png")
plt.savefig(map_png, dpi=300, bbox_inches="tight")
plt.show()
print(f"地图已保存 → {map_png}")

# ========== 6. 绘制统计图 ==========
df["type_main"] = df["type"].str.split(";").str[0]
type_counts = df["type_main"].value_counts()

plt.figure(figsize=(8, 5))
type_counts.plot(kind="bar", color="skyblue")
plt.title("杭州市大学POI类型统计")
plt.xlabel("类型")
plt.ylabel("数量")
plt.xticks(rotation=45)
plt.tight_layout()
chart_png = path("chart.png")
plt.savefig(chart_png, dpi=300, bbox_inches="tight")
plt.show()
print(f"统计图已保存 → {chart_png}")

print("\n全部完成！文件都在：", SAVE_DIR)
