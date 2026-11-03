import os
import rasterio
import numpy as np
import matplotlib.pyplot as plt

# 1. 设置路径
data_dir = r"D:\A11code\空间分析作业\第三次\data"
out_dir = r"D:\A11code\空间分析作业\第三次"

tif_files = [f for f in os.listdir(data_dir) if f.endswith('.tif')]
print(f"找到 {len(tif_files)} 个TIF文件，准备计算NDVI...\n")

plt.rcParams['font.sans-serif'] = ['SimHei'] 
plt.rcParams['axes.unicode_minus'] = False

for tif_name in tif_files:
    tif_path = os.path.join(data_dir, tif_name)
    
    with rasterio.open(tif_path) as src:
        num_bands = src.count
        print(f"正在处理: {tif_name} (包含 {num_bands} 个波段)")
        
        # 针对你的 6 波段数据进行修改
        if num_bands == 6:
            # 假设第3波段是红光，第4波段是近红外
            # （如果算出结果不对，可以尝试换成 read(2) 和 read(4) 或者其他组合）
            red = src.read(3).astype('float32')
            nir = src.read(4).astype('float32')
        elif num_bands >= 8:
            # 兼容完整的 Sentinel-2 原始数据
            red = src.read(4).astype('float32')
            nir = src.read(8).astype('float32')
        else:
            print(f"  -> 警告: 波段数({num_bands})不符合当前逻辑，跳过。")
            continue

        # 计算 NDVI
        np.seterr(divide='ignore', invalid='ignore') 
        ndvi = (nir - red) / (nir + red)
        ndvi = np.nan_to_num(ndvi)
        
        print(f"  -> NDVI 计算结果: 最小值 = {ndvi.min():.4f}, 最大值 = {ndvi.max():.4f}, 均值 = {ndvi.mean():.4f}\n")

        # 可视化并保存
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1) 
        ax.set_title(f"NDVI - {tif_name}", fontsize=14)
        ax.axis('off')
        fig.colorbar(im, ax=ax, label='NDVI')
        
        save_name = tif_name.replace('.tif', '_NDVI.png')
        save_path = os.path.join(out_dir, save_name)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close() 

print(f"所有文件处理完成！NDVI 图像已保存在: {out_dir}")