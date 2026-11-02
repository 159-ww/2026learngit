import pandas as pd
import matplotlib.pyplot as plt
import os

SAVE_DIR = r"D:\A22\空间分析作业"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]   # 改成微软雅黑
plt.rcParams["axes.unicode_minus"] = False

def path(f):
    return os.path.join(SAVE_DIR, f)

# ===== 读取投影后的CSV =====
df = pd.read_csv(path("hangzhou_universities_projected.csv"))

# ===== 1. 地图 =====
plt.figure(figsize=(10, 8))
plt.scatter(df["x"], df["y"], c="red", s=30, alpha=0.7)
plt.title("杭州市大学POI分布图（Web Mercator投影）")
plt.xlabel("X (m)")
plt.ylabel("Y (m)")
plt.grid(True, alpha=0.3)
plt.savefig(path("map.png"), dpi=300, bbox_inches="tight")
plt.close()   # 关掉，避免阻塞
print("地图已保存：", path("map.png"))

# ===== 2. 统计图 =====
df["type_main"] = df["type"].str.split(";").str[0]
type_counts = df["type_main"].value_counts()

plt.figure(figsize=(8, 5))
type_counts.plot(kind="bar", color="skyblue")
plt.title("杭州市大学POI类型统计")
plt.xlabel("类型")
plt.ylabel("数量")
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(path("chart.png"), dpi=300, bbox_inches="tight")
plt.close()
print("统计图已保存：", path("chart.png"))