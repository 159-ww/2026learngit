"""Earth Engine 下载 + 本地独立复算/制图。默认研究区为金鸡湖及周边 6×6 km。"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import os
from pathlib import Path
from datetime import datetime, timezone

# 将绘图缓存放在项目目录；这项设置必须在导入 matplotlib 之前执行。
os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).parent / '.mplconfig'))
# 修正 PROJ 数据目录：系统 PROJ_LIB 可能指向 PostgreSQL 附带的旧版 proj.db，
# 与当前 PROJ 版本不兼容，会导致 EPSG 代码无法解析、CRS 校验失败。
# 必须在导入 rasterio/pyproj 之前设置，优先使用虚拟环境自带的 PROJ 数据。
import sysconfig
_proj_data = Path(sysconfig.get_paths()['purelib']) / 'pyproj' / 'proj_dir' / 'share' / 'proj'
if (_proj_data / 'proj.db').is_file():
    os.environ['PROJ_LIB'] = os.environ['PROJ_DATA'] = str(_proj_data)
import numpy as np
import rasterio
from rasterio.transform import Affine
from pyproj import Transformer

# 一、统一配置：GEE 下载和本地分析必须使用相同的研究区、像元网格和波段顺序。
# ROOT 始终指向本脚本所在文件夹，避免从其他工作目录运行时找错 data/outputs。
ROOT = Path(__file__).resolve().parent
# 苏州使用 WGS84 / UTM 51N，投影坐标的单位为米。
CRS = 'EPSG:32651'
# 仿射变换：[像元宽度, 横向旋转, 左上角X, 纵向旋转, 像元高度, 左上角Y]。
# -10 表示数组向下增加一行时，地图北向坐标减少 10 m。
GRID = [10, 0, 278110, 0, -10, 3469240]
# BOUNDS=[最小X, 最小Y, 最大X, 最大Y]，对应 6×6 km 范围。
BOUNDS = [278110, 3463240, 284110, 3469240]
# 每边 600 像元 × 10 m = 6000 m；NODATA 是导出栅格的无效值标记。
SIZE = 600
COLLECTION = 'COPERNICUS/S2_SR_HARMONIZED'
NODATA = -9999.0
# 每个时间窗选择一景，不计算季节合成；结束日期不包含在筛选范围内。
PERIODS = [
    dict(season='winter', label='冬季', start='2024-01-01', end='2024-03-01'),
    dict(season='spring', label='春季', start='2024-04-01', end='2024-06-01'),
    dict(season='summer', label='夏季', start='2024-07-01', end='2024-09-01'),
    dict(season='autumn', label='秋季', start='2024-10-01', end='2024-12-01'),
]
# 四期共用一套配色与统计范围名称，便于比较地图和表格。
PALETTE = ['#8c510a','#bf812d','#dfc27d','#f6e8c3','#faf5e8','#f7f7f7',
           '#d1e5f0','#92c5de','#4393c3','#2166ac','#053061']
GROUP_LABELS = {'all_common': '全区共同有效像元', 'stable_nonwater': '四期稳定非水体',
                'stable_water': '四期稳定水体'}


# 写入 UTF-8 JSON，保留中文；禁止 NaN，避免产生其他程序无法解析的数据清单。
def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


# 二、导出研究区边界：把以米为单位的 UTM 坐标转换成 GeoJSON 使用的经纬度。
def prepare():
    # always_xy=True 固定顺序为 X/Y，即转换后为“经度、纬度”。
    t = Transformer.from_crs(CRS, 4326, always_xy=True)
    x0, y0, x1, y1 = BOUNDS
    # UTM中的直线转换成经纬度后略有弯曲。沿四条边每100m加一个点，
    # 避免GeoJSON只连接四角时，以经纬度直线代替投影矩形的实际边界。
    corners = np.array([(x0,y0),(x1,y0),(x1,y1),(x0,y1)], dtype='float64')
    ring = []
    for i, start in enumerate(corners):
        end = corners[(i+1)%4]
        steps = int(np.ceil(np.linalg.norm(end-start)/100))
        for fraction in np.linspace(0, 1, steps, endpoint=False):
            x, y = start + fraction*(end-start)
            ring.append(list(t.transform(x, y)))
    ring.append(ring[0])
    write_json(ROOT / 'roi.geojson', {'type':'FeatureCollection', 'features':[
        {'type':'Feature','properties':{'name':'金鸡湖及周边教学研究区','area_km2':36,
         'area_basis':'EPSG:32651 projected grid', 'boundary_sampling_m':100,
         'note':'6×6 km投影矩形，不是官方湖岸边界'},'geometry':{'type':'Polygon','coordinates':[ring]}}]})


# 三、初始化 GEE：网页登录和 Python 授权相互独立，project 是云项目 ID。
def initialize(project, authenticate=False):
    import ee
    if authenticate:
        # Google 登录和授权确认由用户在浏览器中完成；不读取浏览器 Cookie。
        ee.Authenticate(auth_mode='localhost')
    try:
        ee.Initialize(project=project)
    except Exception as e:
        raise RuntimeError('Earth Engine 初始化失败。需要已注册的 Cloud Project ID 和 Python 授权。'
                           '可从作业根目录运行：runtime\\python\\python.exe 金鸡湖NDWI\\jinjihu_ndwi.py '
                           '--project 项目ID --authenticate\n原始错误：' + str(e)) from e
    return ee


# 四、从 GEE 下载四景影像；如已有 manifest，则优先复用其中的固定影像 ID。
def download(project, authenticate=False):
    import requests
    ee = initialize(project, authenticate)
    roi = ee.Geometry.Rectangle(BOUNDS, CRS, False)
    data = ROOT / 'data'
    data.mkdir(exist_ok=True)

    # SCL 场景分类中保留 4=植被、5=非植被、6=水体，其余类别排除。
    # 这里返回服务器端的 0/1 掩膜影像，不是已经下载到本地的 NumPy 数组。
    def valid(image):
        s = image.select('SCL')
        return s.eq(4).Or(s.eq(5)).Or(s.eq(6))

    def score(image):
        # 有效掩膜的平均值就是研究区有效率；缺测位置填 0，不能漏计无效区域。
        # 使用 SCL 的原始 20 m 尺度选景；最终 NDWI 和下载网格仍为 10 m。
        fraction = valid(image).unmask(0, False).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi, crs=CRS,
            crsTransform=[20,0,BOUNDS[0],0,-20,BOUNDS[3]], maxPixels=10_000_000).getNumber('SCL')
        # 有效率是主要评分依据；整景云量和拍摄时间只提供较小的排序修正。
        value = fraction.multiply(1e6).subtract(ee.Number(image.get('CLOUDY_PIXEL_PERCENTAGE')).multiply(.001))
        value = value.subtract(ee.Number(image.get('system:time_start')).divide(1e16))
        return image.set({'roi_valid_fraction_20m':fraction, 'selection_score':value})

    manifest_path = data / 'manifest.json'
    if manifest_path.exists():
        # 复用清单可以避免每次重新选到不同的影像；读取后先检查研究区是否匹配。
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if manifest['crs'] != CRS or manifest['transform'] != GRID or manifest['width'] != SIZE:
            raise ValueError('已有 manifest 与当前研究区不一致；请使用单独目录，避免覆盖数据。')
    else:
        # 尚无清单时，创建记录数据源、网格、波段和选景结果的 manifest。
        manifest = dict(collection=COLLECTION, source='European Union/ESA/Copernicus; Google Earth Engine',
            crs=CRS, transform=GRID, width=SIZE, height=SIZE, area_km2=36,
            bands=['B2','B3','B4','B8','SCL','NDWI_EE'], nodata=NODATA,
            reflectance_scale=.0001, valid_scl=[4,5,6], scenes=[],
            roi_description='金鸡湖及周边6km教学矩形，不是官方湖岸边界',
            created_at_utc=datetime.now(timezone.utc).isoformat())
        for p in PERIODS:
            print('筛选', p['label'], flush=True)
            # 空间筛选 → 时间筛选 → 整景云量<80% → 计算局部质量分数。
            candidates = (ee.ImageCollection(COLLECTION).filterBounds(roi)
                          .filterDate(p['start'],p['end'])
                          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',80)).map(score))
            # getInfo 将服务器端计算结果取回本地；没有候选影像时立即停止。
            count = candidates.size().getInfo()
            if count == 0:
                raise RuntimeError(p['label']+'没有候选影像，请扩大时间窗口。')
            image = ee.Image(candidates.sort('selection_score',False).first())
            # 保存完整影像 ID 和拍摄日期，保证后续下载与结果可以追溯。
            info = ee.Dictionary({'asset_id': ee.String(COLLECTION+'/').cat(ee.String(image.get('system:index'))), 'date':image.date().format('YYYY-MM-dd'),
                'tile_cloud_pct':image.get('CLOUDY_PIXEL_PERCENTAGE'),
                'roi_valid_fraction_20m':image.get('roi_valid_fraction_20m')}).getInfo()
            info.update(season=p['season'],label=p['label'],window_start=p['start'],
                        window_end_exclusive=p['end'],candidate_count=count)
            info['file'] = f"s2_{info['date']}_{p['season']}.tif"
            manifest['scenes'].append(info)
        write_json(manifest_path, manifest)
    # 清单已确定四景影像，下面逐景检查或下载，而不再改变选景结果。
    for s in manifest['scenes']:
        target = data / s['file']
        if target.exists():
            with rasterio.open(target) as ds:
                check_grid(ds, manifest)
            print('复用已下载影像', target.name, flush=True)
            continue
        image = ee.Image(s['asset_id'])
        # B3 为绿光、B8 为近红外，二者均为 10 m。
        # NDWI=(B3-B8)/(B3+B8)，相同的反射率缩放系数会在比值中抵消。
        denominator = image.select('B3').add(image.select('B8'))
        ndwi = (image.normalizedDifference(['B3','B8']).rename('NDWI_EE')
                .updateMask(valid(image).And(denominator.gt(0))).clip(roi))
        # 同一 GeoTIFF 保存五个原始波段和 GEE 计算的 NDWI，共六个波段。
        # 统一为 float32；NDWI 无效位置填 -9999，但保留原始波段用于本地复算。
        bundle = image.select(['B2','B3','B4','B8','SCL']).addBands(ndwi).toFloat().unmask(NODATA,False)
        params = dict(name=target.stem, crs=CRS, crs_transform=GRID,
                      dimensions=[SIZE,SIZE],format='GEO_TIFF',filePerBand=False)
        print('下载', target.name, flush=True)
        # 只保存影像，不把临时签名下载 URL 写进日志或交付文件。
        url = bundle.getDownloadURL(params)
        temporary = target.with_suffix('.part')
        # 用 .part 临时文件接收数据，按 1 MB 分块写入，避免一次性占用较多内存。
        with requests.get(url, stream=True, timeout=(30,300)) as response:
            response.raise_for_status()
            with temporary.open('wb') as f:
                for chunk in response.iter_content(1024*1024):
                    f.write(chunk)
        # 下载完成后验证网格，再将临时文件改为正式名称；防止误用残缺或错位数据。
        with rasterio.open(temporary) as ds:
            check_grid(ds, manifest)
        temporary.replace(target)
    manifest['download_status'] = 'complete'
    write_json(manifest_path, manifest)


# 五、校验栅格：四景影像只有投影、尺寸和左上角网格完全一致，才能逐像元比较。
# ds 是 rasterio 打开的数据集，manifest 是描述预期数据结构的字典。
def check_grid(ds, manifest):
    expected = Affine(*manifest['transform'])
    if (ds.crs is None or ds.crs.to_string() != manifest['crs'] or ds.width != manifest['width'] or
            ds.height != manifest['height'] or not ds.transform.almost_equals(expected) or ds.count != 6):
        raise ValueError(f'栅格网格或波段数与 manifest 不符：{ds.name}')


# 六、本地独立复算 NDWI，并逐像元核对下载文件中的 GEE NDWI_EE 波段。
# 返回：原始六波段数组、栅格空间信息、本地 NDWI 数组、逐景质量检查记录。
def read_scenes(data, manifest):
    arrays, profiles, ndwis, checks = [], [], [], []
    for s in manifest['scenes']:
        path = data / s['file']
        with rasterio.open(path) as ds:
            check_grid(ds, manifest)
            a, profile = ds.read().astype('float32'), ds.profile.copy()
        # a 的形状是 (6, 行数, 列数)，按清单规定的波段顺序展开。
        # 先转浮点数再做减法，避免无符号整数在 B3<B8 时发生数值溢出。
        blue, green, red, nir, scl, gee_ndwi = a
        # 排除云、云影、缺测、负反射率和分母为零的像元，与 GEE 掩膜条件对齐。
        valid = (np.isin(scl,[4,5,6]) & np.isfinite(green) & np.isfinite(nir) &
                 (green>=0) & (nir>=0) & (green+nir>0))
        # 内存中用 NaN 表示无效值；where=valid 只在有效位置做除法，避免除零。
        n = np.full(green.shape,np.nan,dtype='float32')
        np.divide(green-nir,green+nir,out=n,where=valid)
        # GEE 下载中 -9999 表示无效值；合法 NDWI 必须为有限数且处于 [-1,1]。
        ee_valid = np.isfinite(gee_ndwi) & (gee_ndwi>=-1) & (gee_ndwi<=1)
        if not np.array_equal(valid, ee_valid):
            raise ValueError(f'{path.name} 的本地与GEE有效掩膜不一致。')
        if not valid.any():
            raise ValueError(f'{path.name} 没有有效NDWI像元。')
        # 有效范围必须一致，数值误差还必须低于浮点容差，才能确认复算通过。
        max_error = float(np.max(np.abs(n[valid]-gee_ndwi[valid])))
        if max_error > 2e-6:
            raise ValueError(f'{path.name} 本地NDWI与GEE差异过大：{max_error}')
        # 记录有效率和反射率零值；例如 B8=0、B3>0 会得到 NDWI=+1，需谨慎解释。
        # SHA-256 是文件摘要，可用于确认以后使用的是否仍是同一份影像文件。
        checks.append(dict(file=path.name, valid_pixels=int(valid.sum()),
            valid_fraction=float(valid.mean()), max_abs_error_local_vs_GEE=max_error,
            valid_nir_zero_pixels=int(np.sum(valid & (nir==0))),
            valid_green_zero_pixels=int(np.sum(valid & (green==0))),
            water_nir_zero_pixels=int(np.sum(valid & (scl==6) & (nir==0))),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        arrays.append(a); profiles.append(profile); ndwis.append(n)
    return arrays, profiles, ndwis, checks


# 七、写出单波段 GeoTIFF：继承输入的投影和网格，将 NaN 换成显式 NoData。
def write_raster(path, a, profile, description):
    path.parent.mkdir(exist_ok=True,parents=True)
    p = profile.copy()
    # 无损压缩和分块只影响存储方式，不改变 NDWI 数值。
    p.update(driver='GTiff',count=1,dtype='float32',nodata=NODATA,compress='deflate',
             tiled=True,blockxsize=256,blockysize=256)
    with rasterio.open(path,'w',**p) as ds:
        ds.write(np.where(np.isfinite(a),a,NODATA).astype('float32'),1)
        ds.set_band_description(1,description)


# 八、正式分析入口：读取四景 → 固定共同像元 → 分组统计 → 导出栅格、图表和网页。
def analyze():
    data, out = ROOT/'data', ROOT/'outputs'
    m = json.loads((data/'manifest.json').read_text(encoding='utf-8-sig'))
    # 固定冬、春、夏、秋顺序，因为后续差值按 ns[2]（夏）减 ns[0]（冬）计算。
    if len(m['scenes'])!=4 or [s['season'] for s in m['scenes']] != ['winter','spring','summer','autumn']:
        raise ValueError('manifest 必须包含冬春夏秋四期，且按此顺序排列。')
    if m['crs'] != CRS or m['transform'] != GRID:
        raise ValueError('输入并非本项目金鸡湖研究区，拒绝将其他地区数据标记为金鸡湖。')
    arrays, profiles, ns, checks = read_scenes(data,m)
    # common 是四期有效掩膜的交集，保证每个日期的均值都来自相同地面位置。
    common = np.logical_and.reduce([np.isfinite(n) for n in ns])
    # arrays 中每景的第 5 个波段（下标 4）是 SCL。
    # 稳定非水体要求四期均不为水体，稳定水体要求四期均为水体。
    land = common & np.logical_and.reduce([a[4]!=6 for a in arrays])
    water = common & np.logical_and.reduce([a[4]==6 for a in arrays])
    if not common.any():
        raise ValueError('四期没有共同有效像元，不能计算可比统计。')
    groups = {'all_common':common,'stable_nonwater':land,'stable_water':water}
    out.mkdir(exist_ok=True)
    rows = []
    # 逐景保存本地 NDWI，再按三种固定范围分别统计，共生成 4×3=12 条记录。
    for s,a,n,p,c in zip(m['scenes'],arrays,ns,profiles,checks):
        write_raster(out/f"ndwi_{s['date']}_{s['season']}.tif",n,p,'NDWI_local')
        for name,mask in groups.items():
            # mask 选择一组固定像元；用 float64 统计，减少大量像元累加的舍入误差。
            v = n[mask].astype('float64')
            # 每像元面积=10×10 m²=0.0001 km²；p05/p95 分别是第5/95百分位数。
            # NDWI>0 的比例只是候选阈值描述，不等同于实测水体面积。
            row = dict(date=s['date'],season=s['season'],label=s['label'],group=name,
                group_label=GROUP_LABELS[name],pixel_count=int(mask.sum()),area_km2=float(mask.sum()*.0001),
                mean_NDWI=float(v.mean()) if v.size else None,
                median_NDWI=float(np.median(v)) if v.size else None,
                p05=float(np.percentile(v,5)) if v.size else None,
                p95=float(np.percentile(v,95)) if v.size else None,
                ndwi_gt_0_fraction=float((v>0).mean()) if v.size else None,
                nir_zero_fraction=float((a[3][mask]==0).mean()) if v.size else None,
                green_zero_fraction=float((a[1][mask]==0).mean()) if v.size else None,
                scene_valid_fraction=c['valid_fraction'])
            rows.append(row)
    # 差值只在共同有效范围计算：正值为夏季高于冬季，负值为夏季低于冬季。
    delta = np.where(common,ns[2]-ns[0],np.nan)
    write_raster(out/'ndwi_summer_minus_winter.tif',delta,profiles[0],'NDWI_summer_minus_winter')
    for name,mask in groups.items():
        # 掩膜文件用 1 标记属于该范围，0 标记不属于，方便在 GIS 中复用统计范围。
        write_raster(out/(name+'_mask.tif'),mask.astype('float32'),profiles[0],name)
    with (out/'ndwi_statistics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        # utf-8-sig 带 BOM，便于 Excel 直接正确识别中文列值。
        writer = csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    quality = dict(status='passed',common_pixels=int(common.sum()),
        common_fraction=float(common.mean()),stable_nonwater_pixels=int(land.sum()),
        stable_water_pixels=int(water.sum()),other_common_pixels=int((common&~land&~water).sum()),
        local_vs_GEE=checks,delta_mean=float(np.mean(delta[common],dtype='float64')))
    quality['spatial_reference'] = {'crs': CRS, 'transform': GRID,
        'pixel_area_m2':abs(profiles[0]['transform'].a*profiles[0]['transform'].e
                            -profiles[0]['transform'].b*profiles[0]['transform'].d),
        'area_basis':'projected grid area, not ellipsoidal area',
        'map_up':'grid north (GN), not true north'}
    # 数学复算通过不代表不存在影像辐射或分类误差；将解释限制一并保存。
    quality['interpretation_note'] = ('通过表示网格、掩膜和NDWI数值复算通过，不表示辐射质量无问题。'
        'B8=0且B3>0的有效水体像元会得到NDWI=+1；具体日期和数量见local_vs_GEE记录，'
        '不据此推断水质、水污染或长期水生态变化。')
    write_json(out/'quality_checks.json',quality)
    write_json(out/'statistics.json',rows)
    # 生成静态 PNG 供报告使用，再将图片和统计嵌入可离线打开的 HTML 页面。
    make_figures(m,arrays,ns,common,delta,rows,out)
    make_html(m,rows,quality,out)
    print('完成：',out/'金鸡湖NDWI可视化.html')
    print(json.dumps(quality,ensure_ascii=False,indent=2))


# 九、绘图：四期地图使用统一尺度；统计曲线使用共同像元；差值另用发散色带。
# m=影像清单，arrays=六波段数组，ns=NDWI列表，rows=统计记录，out=输出目录。
def make_figures(m,arrays,ns,common,delta,rows,out):
    import matplotlib
    # Agg 后端直接保存文件，无须弹出图形窗口，适合批量运行。
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib import dates as mdates
    from matplotlib.ticker import MultipleLocator
    from matplotlib.colors import LinearSegmentedColormap
    plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
                         'axes.unicode_minus':False,'figure.facecolor':'white','font.size':11})
    cmap = LinearSegmentedColormap.from_list('jinjihu_ndwi',PALETTE)
    cmap.set_bad('#eceff1')
    # 从GeoTIFF仿射变换计算真实UTM边界，再以km显示；不把米制坐标误标成经纬度。
    t = Affine(*m['transform'])
    left, top = t*(0,0)
    right, bottom = t*(m['width'],m['height'])
    extent = (left/1000,right/1000,bottom/1000,top/1000)
    x0, _, y0, _ = extent

    # 为每张地图统一添加坐标轴、1 km 比例尺和投影网格北向箭头。
    def map_axis(ax):
        ax.set(xlabel='东向坐标 E / km (UTM 51N)',ylabel='北向坐标 N / km')
        ax.ticklabel_format(style='plain',useOffset=False)
        ax.xaxis.set_major_locator(MultipleLocator(1))
        ax.yaxis.set_major_locator(MultipleLocator(1))
        ax.tick_params(labelsize=9)
        ax.plot([x0+.35,x0+1.35],[y0+.35,y0+.35],color='#202b34',lw=3)
        ax.text(x0+.85,y0+.45,'1 km',ha='center',fontsize=9,color='#202b34',
                bbox=dict(facecolor='white',edgecolor='none',alpha=.8,pad=1))
        # 直向上的箭头是投影网格北（GN）；研究区真北相对网格北约顺时针偏1.20°。
        ax.annotate('GN',xy=(x0+5.6,y0+5.6),xytext=(x0+5.6,y0+5.1),ha='center',
                    arrowprops=dict(arrowstyle='->',color='#202b34'),fontsize=10)

    # 图1：四期 NDWI 总览。仅显示共同有效范围，色标固定为 -1～1。
    fig, axes = plt.subplots(2,2,figsize=(12,11),layout='constrained')
    for ax,s,n in zip(axes.flat,m['scenes'],ns):
        im=ax.imshow(np.ma.masked_invalid(np.where(common,n,np.nan)),extent=extent,cmap=cmap,vmin=-1,vmax=1,
                     origin='upper',interpolation='nearest')
        ax.set_title(s['label']+'  '+s['date'],fontweight='bold');map_axis(ax)
    fig.colorbar(im,ax=axes.ravel().tolist(),label='NDWI = (B3 − B8) / (B3 + B8)',shrink=.8,pad=.025)
    fig.suptitle('金鸡湖及周边｜2024 年四期 NDWI\nWGS84 / UTM 51N (EPSG:32651) · GN=网格北',
                 fontsize=16,fontweight='bold')
    fig.savefig(out/'ndwi_four_seasons.png',dpi=180);plt.close(fig)

    # 单期小图供 HTML 切换使用；每期保留各自的有效范围。
    for i,(s,a,n) in enumerate(zip(m['scenes'],arrays,ns)):
        # 原数组顺序为 B2/B3/B4/B8/SCL/NDWI，取 [2,1,0] 得到红/绿/蓝。
        # 将通道轴从最前面移至最后面，得到 imsave 要求的 (高,宽,3)。
        # 除以3000、截断和gamma校正只用于显示，不参与 NDWI 或统计计算。
        rgb = np.moveaxis(np.clip(a[[2,1,0]]/3000,0,1)**(1/1.4),0,-1)
        rgb[~np.isfinite(n)] = [.925,.937,.945]
        plt.imsave(out/f"rgb_{s['season']}.png",rgb,origin='upper')
        plt.imsave(out/f"ndwi_{s['season']}.png",np.ma.masked_invalid(n),cmap=cmap,vmin=-1,vmax=1,origin='upper')
    # 图2：四期真彩色总览，灰色位置表示该期 NDWI 无效的观测。
    fig,axes = plt.subplots(2,2,figsize=(12,11),layout='constrained')
    for ax,s,a,n in zip(axes.flat,m['scenes'],arrays,ns):
        rgb=np.moveaxis(np.clip(a[[2,1,0]]/3000,0,1)**(1/1.4),0,-1)
        rgb[~np.isfinite(n)]=[.925,.937,.945]
        ax.imshow(rgb,extent=extent,origin='upper',interpolation='nearest')
        ax.set_title(s['label']+'  '+s['date']);map_axis(ax)
    fig.suptitle('金鸡湖及周边｜Sentinel-2 真彩色（有效观测）\nWGS84 / UTM 51N (EPSG:32651) · GN=网格北',
                 fontsize=16,fontweight='bold')
    fig.savefig(out/'rgb_four_seasons.png',dpi=180);plt.close(fig)

    # 图3：按三个固定范围分别绘制均值曲线，不能把四个日期理解为连续长期趋势。
    fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
    for group,color in [('all_common','#376c9c'),('stable_nonwater','#287a57'),('stable_water','#a77540')]:
        rs=[r for r in rows if r['group']==group]
        ax.plot([datetime.fromisoformat(r['date']) for r in rs],[r['mean_NDWI'] for r in rs],
                '-o',color=color,label=GROUP_LABELS[group],lw=2)
    # 使用真实日期坐标，而非把不等间隔的四个日期画成等距类别。
    ax.set_xticks([datetime.fromisoformat(s['date']) for s in m['scenes']])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.axhline(0,lw=.7,color='#9ba8b0');ax.grid(alpha=.15)
    ax.set(title='四期 NDWI 均值｜各组使用固定像元',xlabel='拍摄日期（各季一景）',ylabel='NDWI 均值',ylim=(-1,1))
    ax.legend(loc='best');fig.savefig(out/'ndwi_means.png',dpi=180);plt.close(fig)

    # 图4：夏季减冬季的差值。统一显示范围 ±0.6，超过范围的值以端点颜色显示。
    fig,ax=plt.subplots(figsize=(8,7),layout='constrained')
    delta_cmap=plt.get_cmap('RdBu').copy()
    delta_cmap.set_bad('#eceff1')  # 无效值用灰色，与接近0的白色区分。
    im=ax.imshow(np.ma.masked_invalid(delta),extent=extent,cmap=delta_cmap,vmin=-.6,vmax=.6,
                 origin='upper',interpolation='nearest')
    ax.set_title('夏季 − 冬季 NDWI｜共同有效像元\nEPSG:32651 · GN=网格北');map_axis(ax)
    fig.colorbar(im,ax=ax,label='ΔNDWI；红色降低，蓝色升高（超出±0.6以端点色显示）')
    fig.savefig(out/'ndwi_change.png',dpi=180);plt.close(fig)


# 生成离线网页：图片嵌入HTML，分享整个文件夹或单个HTML均可查看结果。
def make_html(m,rows,q,out):
    def uri(name):
        return 'data:image/png;base64,'+base64.b64encode((out/name).read_bytes()).decode('ascii')
    scenes=m['scenes']
    images={s['season']:{'rgb':uri('rgb_'+s['season']+'.png'),
                         'index':uri('ndwi_'+s['season']+'.png')} for s in scenes}
    buttons=''.join('<button id="b'+str(i)+'" onclick="show('+str(i)+')">'+s['label']+'</button>' for i,s in enumerate(scenes))
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in
        [r['label'],r['date'],r['group_label'],f"{r['mean_NDWI']:.4f}" if r['mean_NDWI'] is not None else '无有效值',
         r['pixel_count'],f"{r['area_km2']:.3f}",f"{r['ndwi_gt_0_fraction']:.2%}" if r['ndwi_gt_0_fraction'] is not None else '—'])+'</tr>' for r in rows)
    sources=''.join('<li>'+html.escape(s['date']+' · '+s['asset_id'])+'</li>' for s in scenes)
    checks={c['file']:c for c in q['local_vs_GEE']}
    zero_notes='；'.join(s['date']+'：'+format(checks[s['file']]['water_nir_zero_pixels'],',')+'个'
                        for s in scenes if checks[s['file']]['water_nir_zero_pixels']>0)
    zero_text=('有效SCL水体像元中，B8=0且B3>0的数量为'+zero_notes+'，因此NDWI=+1。'
               if zero_notes else '本次没有B8=0且B3>0的有效SCL水体像元。')
    legend='linear-gradient(90deg,'+','.join(PALETTE)+')'
    doc='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>金鸡湖NDWI · 2024</title><style>
*{box-sizing:border-box}body{margin:0;background:#f0f5f8;color:#173247;font:16px/1.7 "Microsoft YaHei",sans-serif}
main{max-width:1180px;margin:auto;padding:32px 24px}h1{margin:4px 0 8px;font-size:36px}h2{font-size:23px;margin-top:0}.lead,small{color:#537183}
.card{padding:24px;margin:24px 0;background:white;border:1px solid #d7e2e9;border-radius:16px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
button{border:1px solid #b1c9db;background:white;color:#195f8f;padding:9px 22px;border-radius:20px;margin:3px;cursor:pointer;font:inherit}button.active{background:#195f8f;color:white}
.pill{display:inline-block;background:#dcecf7;border-radius:20px;padding:4px 14px;margin:4px}.map,.wide{width:100%;display:block}.legend{height:17px;background:__LEGEND__;border-radius:4px}.ticks{display:flex;justify-content:space-between;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:9px;border-bottom:1px solid #dce6ec}th{background:#edf4f8}.scroll{overflow-x:auto}li{font-size:12px;overflow-wrap:anywhere}
@media(max-width:700px){main{padding:18px 12px}.card{padding:16px}.grid{grid-template-columns:1fr}h1{font-size:28px}}
</style><main><small>GOOGLE EARTH ENGINE / SENTINEL-2</small><h1>金鸡湖及周边 · NDWI</h1>
<p class="lead">2024年四期观测｜10米网格｜绿光与近红外的归一化差异</p>
<span class="pill">NDWI = (B3 − B8) / (B3 + B8)</span><span class="pill">共同有效率 __COVER__</span>
<section class="card"><h2>逐期查看</h2>__BUTTONS__<p id="date"></p><div class="grid">
<div><b>真彩色 · B4 / B3 / B2</b><img id="rgb" class="map"></div>
<div><b>NDWI</b><img id="index" class="map"><div class="legend"></div><div class="ticks"><span>−1 棕色</span><span>0</span><span>+1 蓝色</span></div></div></div>
<small>灰色为无效观测。逐期图采用各期有效范围；四期总览与统计采用共同有效范围。</small></section>
<section class="card"><h2>四期空间分布</h2><img class="wide" src="__OVERVIEW__"></section>
<section class="card"><h2>固定像元的NDWI均值</h2><img class="wide" src="__MEANS__"></section>
<section class="card"><h2>夏季减冬季</h2><img class="wide" src="__DELTA__"><p>正值表示所选夏季日期的NDWI更高；水位、混合像元、光照和反射率处理都会影响差值，不能直接解释为水质变化。</p></section>
<section class="card"><h2>统计结果</h2><div class="scroll"><table><thead><tr><th>季节</th><th>日期</th><th>统计范围</th><th>均值</th><th>像元数</th><th>面积 km²</th><th>NDWI&gt;0比例</th></tr></thead><tbody>__TABLE__</tbody></table></div></section>
<section class="card"><h2>方法和解释</h2><p>本次NDWI为绿光B3与近红外B8的归一化差异，两波段原始分辨率均为10m。相同比例因子在比值中抵消。保留SCL=4/5/6并要求B3+B8&gt;0；SCL原始为20m，最近邻对齐到10m不会增加分类细节。</p>
<p>较高正值通常有助于识别开放水面，负值常见于植被和其他非水体。NDWI&gt;0只是描述性候选阈值，城市建筑、阴影和浑浊水体等会影响结果，不能把阈值面积当作实测湖泊面积。</p>
<p>研究区为金鸡湖及周边6×6km矩形，包含城市绿地、河道和部分独墅湖，不是金鸡湖精确湖岸。稳定水体与稳定非水体由四期SCL共同分类确定，不能当作独立实测真值。</p>
<p>采用WGS84 / UTM 51N（EPSG:32651），图中E/N轴为km，GN为网格北。面积按10×10m投影像元计算。每季只取一景，不是季节平均或长期变化趋势。</p>
<h2>质量说明</h2><p>__ZERO_NOTE__极值可能受低反射率像元及产品处理影响，不代表水质优良或污染程度。本地计算与GEE波段一致，只能证明计算和掩膜一致，不能代替现场验证。</p>
<h2>数据溯源</h2><ul>__SOURCES__</ul><p>数据来源：European Union / ESA / Copernicus；Google Earth Engine。</p>
<p><a href="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED">数据目录</a> · <a href="https://custom-scripts.sentinel-hub.com/custom-scripts/sentinel-2/ndwi/">NDWI波段定义</a></p></section></main>
<script>const scenes=__SCENES__,images=__IMAGES__;function show(i){const s=scenes[i];document.getElementById('date').textContent=s.label+' · '+s.date;for(const type of ['rgb','index'])document.getElementById(type).src=images[s.season][type];scenes.forEach((_,j)=>document.getElementById('b'+j).classList.toggle('active',i===j))}show(2)</script></html>'''
    for key,value in {'LEGEND':legend,'COVER':f"{q['common_fraction']:.2%}",'BUTTONS':buttons,
        'OVERVIEW':uri('ndwi_four_seasons.png'),'MEANS':uri('ndwi_means.png'),'DELTA':uri('ndwi_change.png'),
        'TABLE':table,'ZERO_NOTE':html.escape(zero_text),'SOURCES':sources,
        'SCENES':json.dumps(scenes,ensure_ascii=False),'IMAGES':json.dumps(images)}.items():
        doc=doc.replace('__'+key+'__',value)
    (out/'金鸡湖NDWI可视化.html').write_text(doc,encoding='utf-8')


# 十一、命令行入口。已有 data 中的影像时，最常用命令为：
# python jinjihu_ndwi.py --analyze-only
# 需要重新联网下载时：python jinjihu_ndwi.py --project 项目ID --authenticate
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',help='已注册 Earth Engine 的 Google Cloud Project ID')
    parser.add_argument('--authenticate',action='store_true',help='由用户完成本机 Python OAuth 授权')
    parser.add_argument('--analyze-only',action='store_true',help='分析 data 中从 GEE 编辑器下载的影像')
    parser.add_argument('--prepare-only',action='store_true',help='仅生成研究区 GeoJSON')
    args=parser.parse_args()
    # 无论选择何种模式，都先生成研究区 GeoJSON；下面按命令行参数选择执行分支。
    prepare()
    if args.prepare_only: return
    # --analyze-only 跳过云端下载，直接使用已有文件复算和制图。
    if not args.analyze_only:
        if args.project:
            # 明确提供项目 ID 时，执行云端下载；已有影像仍会按原逻辑复用。
            download(args.project,args.authenticate)
        else:
            # 在 VS Code 点击“运行 Python 文件”通常不会附加命令行参数。
            # 若本地四景影像齐全，默认离线复算，方便直接运行且无需重复登录 GEE。
            manifest_path = ROOT/'data'/'manifest.json'
            local_manifest = (json.loads(manifest_path.read_text(encoding='utf-8-sig'))
                              if manifest_path.exists() else {})
            scenes = local_manifest.get('scenes', [])
            local_ready = len(scenes)==4 and all(
                (ROOT/'data'/scene['file']).is_file() for scene in scenes)
            if not local_ready:
                parser.error('未找到完整本地四景影像；请恢复 data 文件夹，'
                             '或使用 --project 项目ID --authenticate 从 GEE 下载。')
            print('已检测到完整本地影像，执行离线 NDWI 复算与制图。')
    analyze()


# 直接运行脚本时执行 main；被其他脚本 import 时仅提供函数，不自动开始下载。
if __name__=='__main__':
    main()
