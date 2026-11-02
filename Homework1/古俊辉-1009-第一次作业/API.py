import requests
import pandas as pd
import matplotlib.pyplot as plt
import folium
import numpy as np
import os
import time
import warnings

# 忽略警告
warnings.filterwarnings('ignore')

# ================= 配置区 =================
AMAP_KEY = '521b148d8a776a6c78c62bca473cbcf6' 
TARGET_CITY = '南京'
POI_TYPES = ['大学']  

if not os.path.exists('data'):
    os.makedirs('data')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
# ==========================================

# ================= 1. 封装API调用函数 =================
def search_poi(keywords, city='南京', api_key=AMAP_KEY):
    url = 'https://restapi.amap.com/v5/place/text'
    params = {
        'key': api_key,
        'keywords': keywords,
        'region': city,
        'output': 'json',
        'page_size': 50,
        'page_num': 1,
        'show_fields': 'business,photos,children'
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == '1' and 'pois' in data:
                pois = data['pois']
                poi_list = []
                for poi in pois:
                    location = poi.get('location', '')
                    lon, lat = (None, None)
                    if location:
                        lon, lat = location.split(',')
                    
                    poi_info = {
                        '名称': poi.get('name'),
                        '地址': poi.get('address'),
                        '经度_GCJ02': float(lon) if lon else None,
                        '纬度_GCJ02': float(lat) if lat else None,
                        '类型': poi.get('type'),
                        '行政区划': poi.get('adname'),
                    }
                    poi_list.append(poi_info)
                print(f"✓ 搜索'{keywords}'成功，找到 {len(poi_list)} 个POI")
                return pd.DataFrame(poi_list)
            else:
                print(f"✗ API返回错误: {data.get('info', '未知错误')}")
                return pd.DataFrame()
        else:
            print(f"✗ HTTP请求失败: {response.status_code}")
            return pd.DataFrame()
    except Exception as e:
        print(f"✗ 发生错误: {str(e)}")
        return pd.DataFrame()

# ================= 2. 坐标转换 (GCJ-02 -> WGS-84) =================
def gcj02_to_wgs84(lng, lat):
    """
    高德(GSJ-02) -> WGS-84的转换
    作业要求必须包含坐标转换，保留此函数用于生成CSV数据
    """
    if pd.isna(lng) or pd.isna(lat):
        return None, None
    a = 6378245.0
    ee = 0.00669342162296594323
    pi = 3.1415926535897932384626
    
    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * np.sqrt(abs(x))
        ret += (20.0 * np.sin(6.0 * x * pi) + 20.0 * np.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * np.sin(y * pi) + 40.0 * np.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * np.sin(y / 12.0 * pi) + 320 * np.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lng(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * np.sqrt(abs(x))
        ret += (20.0 * np.sin(6.0 * x * pi) + 20.0 * np.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * np.sin(x * pi) + 40.0 * np.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * np.sin(x / 12.0 * pi) + 300.0 * np.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret

    dLat = transform_lat(lng - 105.0, lat - 35.0)
    dLng = transform_lng(lng - 105.0, lat - 35.0)
    radLat = lat / 180.0 * pi
    magic = np.sin(radLat)
    magic = 1 - ee * magic * magic
    sqrtMagic = np.sqrt(magic)
    dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * pi)
    dLng = (dLng * 180.0) / (a / sqrtMagic * np.cos(radLat) * pi)
    wgs_lat = lat - dLat
    wgs_lng = lng - dLng
    return wgs_lng, wgs_lat

def transform_data(df):
    print("\n正在进行坐标转换 (GCJ-02 -> WGS-84)...")
    wgs_lng_list = []
    wgs_lat_list = []
    for idx, row in df.iterrows():
        wgs_lng, wgs_lat = gcj02_to_wgs84(row['经度_GCJ02'], row['纬度_GCJ02'])
        wgs_lng_list.append(wgs_lng)
        wgs_lat_list.append(wgs_lat)
    df['经度_WGS84'] = wgs_lng_list
    df['纬度_WGS84'] = wgs_lat_list
    print("✓ 坐标转换完成")
    return df

# ================= 3. 主流程与可视化 =================
if __name__ == "__main__":
    print("=" * 50)
    print(f"开始搜索 {TARGET_CITY} 的 POI: {POI_TYPES}")
    print("=" * 50)
    
    # 3.1 下载数据
    df_result = search_poi(POI_TYPES[0], city=TARGET_CITY)
    
    if not df_result.empty:
        # 3.2 坐标转换
        df_result = transform_data(df_result)
        
        # 3.3 保存CSV
        csv_path = f'data/{TARGET_CITY}_{POI_TYPES[0]}_数据.csv'
        df_result.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✓ 原始数据已保存: {csv_path}")
        
        # 3.4 绘制动态交互地图 (Folium)
        print("\n正在生成动态交互地图...")
        center_lat = df_result['纬度_GCJ02'].mean()
        center_lng = df_result['经度_GCJ02'].mean()
        
        # 使用高德标准底图，完美解决灰色和偏移问题
        base_map = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=11,
            tiles='https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
            attr='高德地图',
            subdomains=['1', '2', '3', '4']
        )
        
        # 将POI作为标记添加到地图上
        for idx, row in df_result.iterrows():
            if pd.notna(row['经度_GCJ02']) and pd.notna(row['纬度_GCJ02']):
                folium.CircleMarker(
                    location=[row['纬度_GCJ02'], row['经度_GCJ02']],
                    radius=6,
                    color='blue',
                    fillColor='blue',
                    fillOpacity=0.7,
                    popup=folium.Popup(f"<b>{row['名称']}</b><br>{row['地址']}<br>区划: {row['行政区划']}", max_width=300),
                    tooltip=row['名称']
                ).add_to(base_map)
        
        map_path = f'data/{TARGET_CITY}_{POI_TYPES[0]}_动态地图.html'
        base_map.save(map_path)
        print(f"✓ 动态交互地图已保存: {map_path} (可用浏览器双击打开)")
        
        # 3.5 统计图：各区大学数量对比 (matplotlib)
        print("\n正在生成统计图...")
        if '行政区划' in df_result.columns:
            district_counts = df_result['行政区划'].value_counts()
            fig, ax = plt.subplots(figsize=(10, 6))
            bars = ax.bar(district_counts.index, district_counts.values, color='#4A90E2')
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom', fontsize=12)
            ax.set_xlabel('行政区划', fontsize=12)
            ax.set_ylabel('大学数量', fontsize=12)
            ax.set_title(f'{TARGET_CITY}市各行政区大学数量统计', fontsize=14, fontweight='bold')
            ax.grid(axis='y', alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            chart_path = f'data/{TARGET_CITY}_{POI_TYPES[0]}_统计图.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            print(f"✓ 统计图表已保存: {chart_path}")
            plt.show()
            
        print("\n🎉 作业运行完成！请查看 data 文件夹。")
    else:
        print("✗ 未获取到数据，请检查API Key是否有效。")