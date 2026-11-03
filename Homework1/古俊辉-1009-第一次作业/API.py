# =========================================================
# 模块导入区：引入所需的第三方库和系统库
# =========================================================
import requests                          # 用于发送HTTP网络请求，调用高德API
import pandas as pd                      # 用于数据处理，将JSON转为DataFrame表格
import matplotlib.pyplot as plt          # 用于绘制静态统计图表（柱状图）
import folium                            # 用于生成交互式动态地图
import numpy as np                       # 用于复杂的数学计算（坐标转换公式）
import os                                # 用于操作系统文件路径（创建data文件夹）
import time                              # 备用：用于控制API请求频率，防止被封
import warnings                          # 用于忽略一些不重要的警告信息

# 忽略运行过程中可能出现的不影响结果的警告
warnings.filterwarnings('ignore')

# =========================================================
# 配置区：定义全局常量
# =========================================================
# 高德开放平台申请的Web服务API Key
AMAP_KEY = '' 
# 目标城市设定（本作业为南京）
TARGET_CITY = '南京'
# 搜索POI的关键词设定
POI_TYPES = ['大学']  

if not os.path.exists('data'):
    os.makedirs('data')

# 设置matplotlib绘图的中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
# 解决坐标轴负号无法正常显示的问题
plt.rcParams['axes.unicode_minus'] = False
# ==========================================

# =========================================================
# 1. 封装API调用函数：向高德地图请求POI数据
# =========================================================
def search_poi(keywords, city='南京', api_key=AMAP_KEY):
    url = 'https://restapi.amap.com/v5/place/text'
    
    # 构造请求参数
    params = {
        'key': api_key,          # API密钥
        'keywords': keywords,    # 搜索关键词（如“大学”）
        'region': city,          # v5版本推荐使用region来指定城市（取代了旧版的city）
        'output': 'json',        # 返回值格式设为JSON
        'page_size': 50,         # 单页返回条数（最大50条）
        'page_num': 1,           # 页码，这里只抓取第一页
        'show_fields': 'business,photos,children'  # 额外返回的字段信息
    }

    try:
        # 发起GET请求
        response = requests.get(url, params=params, timeout=10)
        
        # 判断HTTP请求是否成功（状态码200表示成功）
        if response.status_code == 200:
            # 将返回的内容解析为JSON格式（Python字典）
            data = response.json()
            
            # 检查高德API业务状态码（'1'代表成功，且'pois'字段存在）
            if data.get('status') == '1' and 'pois' in data:
                pois = data['pois']
                poi_list = []
                
                # 遍历获取到的每一个POI
                for poi in pois:
                    location = poi.get('location', '')
                    lon, lat = (None, None)
                    
            
                    if location:
                        lon, lat = location.split(',')
                    
                    # 提取我们需要的字段，封装成字典
                    poi_info = {
                        '名称': poi.get('name'),
                        '地址': poi.get('address'),
                        '经度_GCJ02': float(lon) if lon else None, # 高德原生坐标系
                        '纬度_GCJ02': float(lat) if lat else None,
                        '类型': poi.get('type'),
                        '行政区划': poi.get('adname'),
                    }
                    poi_list.append(poi_info)
                    
                print(f"✓ 搜索'{keywords}'成功，找到 {len(poi_list)} 个POI")
                # 将列表转为Pandas DataFrame格式，方便后续处理
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

# =========================================================
# 2. 坐标转换：将高德(GSJ-02)转为国际通用(WGS-84)
# =========================================================
def gcj02_to_wgs84(lng, lat):
    """
    高德(GSJ-02) -> WGS-84的转换
    """
    # 处理空值情况
    if pd.isna(lng) or pd.isna(lat):
        return None, None
        
    # 长半轴 a 和 椭球偏心率平方 ee
    a = 6378245.0
    ee = 0.00669342162296594323
    pi = 3.1415926535897932384626
    
    # 纬度转换子函数
    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * np.sqrt(abs(x))
        ret += (20.0 * np.sin(6.0 * x * pi) + 20.0 * np.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * np.sin(y * pi) + 40.0 * np.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * np.sin(y / 12.0 * pi) + 320 * np.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret

    # 经度转换子函数
    def transform_lng(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * np.sqrt(abs(x))
        ret += (20.0 * np.sin(6.0 * x * pi) + 20.0 * np.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * np.sin(x * pi) + 40.0 * np.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * np.sin(x / 12.0 * pi) + 300.0 * np.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret

    # 计算偏移量
    dLat = transform_lat(lng - 105.0, lat - 35.0)
    dLng = transform_lng(lng - 105.0, lat - 35.0)
    
    # 将偏移量应用到原坐标上（核心数学计算）
    radLat = lat / 180.0 * pi
    magic = np.sin(radLat)
    magic = 1 - ee * magic * magic
    sqrtMagic = np.sqrt(magic)
    dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * pi)
    dLng = (dLng * 180.0) / (a / sqrtMagic * np.cos(radLat) * pi)
    
    # 减去偏移量，得到WGS84坐标
    wgs_lat = lat - dLat
    wgs_lng = lng - dLng
    return wgs_lng, wgs_lat

def transform_data(df):
    """遍历DataFrame，对每一行执行坐标转换"""
    print("\n正在进行坐标转换 (GCJ-02 -> WGS-84)...")
    wgs_lng_list = []
    wgs_lat_list = []
    for idx, row in df.iterrows():
        # 调用转换函数
        wgs_lng, wgs_lat = gcj02_to_wgs84(row['经度_GCJ02'], row['纬度_GCJ02'])
        wgs_lng_list.append(wgs_lng)
        wgs_lat_list.append(wgs_lat)
    
    # 将转换后的坐标作为新列添加到DataFrame中
    df['经度_WGS84'] = wgs_lng_list
    df['纬度_WGS84'] = wgs_lat_list
    print("✓ 坐标转换完成")
    return df

# =========================================================
# 3. 主流程与可视化
# =========================================================
# 主程序入口
if __name__ == "__main__":
    print("=" * 50)
    print(f"开始搜索 {TARGET_CITY} 的 POI: {POI_TYPES}")
    print("=" * 50)
    
    # 3.1 下载数据
    # 调用search_poi函数，获取POI数据
    df_result = search_poi(POI_TYPES[0], city=TARGET_CITY)
    
    # 如果成功获取到数据（DataFrame不为空）
    if not df_result.empty:
        # 3.2 坐标转换
        df_result = transform_data(df_result)
        
        # 3.3 保存CSV数据文件
        csv_path = f'data/{TARGET_CITY}_{POI_TYPES[0]}_数据.csv'
        # encoding='utf-8-sig' 可以保证用Excel打开时中文不乱码
        df_result.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✓ 原始数据已保存: {csv_path}")
        
        # 3.4 绘制动态交互地图 (Folium)
        print("\n正在生成动态交互地图...")
        
        # 计算所有点的平均经纬度，作为地图初始中心点
        center_lat = df_result['纬度_GCJ02'].mean()
        center_lng = df_result['经度_GCJ02'].mean()
        
        # 创建Folium地图对象
        # 这里使用了高德的底图瓦片。因为底图是高德的，所以散点的坐标也必须用高德的GCJ-02坐标，否则会发生肉眼可见的偏移。
        # subdomains=['1','2','3','4'] 表示并行向四个服务器请求地图瓦片，加快加载速度。
        base_map = folium.Map(
            location=[center_lat, center_lng], 
            zoom_start=11,
            tiles='https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
            attr='高德地图',
            subdomains=['1', '2', '3', '4']
        )
        
        # 遍历DataFrame，将每个大学作为圆形标记添加到底图上
        for idx, row in df_result.iterrows():
            # 确保经纬度有值
            if pd.notna(row['经度_GCJ02']) and pd.notna(row['纬度_GCJ02']):
                folium.CircleMarker(
                    location=[row['纬度_GCJ02'], row['经度_GCJ02']], # 使用 GCJ-02 坐标配高德底图
                    radius=6,
                    color='blue',
                    fillColor='blue',
                    fillOpacity=0.7,
                    # 点击标记时弹出的对话框（包含名称、地址、行政区划）
                    popup=folium.Popup(f"<b>{row['名称']}</b><br>{row['地址']}<br>区划: {row['行政区划']}", max_width=300),
                    tooltip=row['名称'] # 鼠标悬停时显示的名称
                ).add_to(base_map)
        
        # 保存HTML文件
        map_path = f'data/{TARGET_CITY}_{POI_TYPES[0]}_动态地图.html'
        base_map.save(map_path)
        print(f"✓ 动态交互地图已保存: {map_path} (可用浏览器双击打开)")
        
        # 3.5 统计图：各区大学数量对比 (matplotlib)
        print("\n正在生成统计图...")
        if '行政区划' in df_result.columns:
            # 按行政区划进行分组计数，并降序排列
            district_counts = df_result['行政区划'].value_counts()
            
            # 创建画布大小
            fig, ax = plt.subplots(figsize=(10, 6))
            # 绘制柱状图
            bars = ax.bar(district_counts.index, district_counts.values, color='#4A90E2')
            
            # 遍历每个柱子，在柱子上方标注具体数值
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom', fontsize=12)
            
            # 设置坐标轴标签和标题
            ax.set_xlabel('行政区划', fontsize=12)
            ax.set_ylabel('大学数量', fontsize=12)
            ax.set_title(f'{TARGET_CITY}市各行政区大学数量统计', fontsize=14, fontweight='bold')
            ax.grid(axis='y', alpha=0.3) # 添加Y轴方向网格线，便于对比
            plt.xticks(rotation=45)      # X轴标签旋转45度，防止重叠
            
            plt.tight_layout()           # 自动调整子图参数，防止标签被截断
            chart_path = f'data/{TARGET_CITY}_{POI_TYPES[0]}_统计图.png'
            plt.savefig(chart_path, dpi=300, bbox_inches='tight') # 保存高清图片
            print(f"✓ 统计图表已保存: {chart_path}")
            plt.show() # 弹出图像窗口
            
        print("\n🎉 作业运行完成！请查看 data 文件夹。")
    else:
        print("✗ 未获取到数据，请检查API Key是否有效。")