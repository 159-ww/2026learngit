"""从GEE生成的JSON清单重新下载四景NDWI影像；不保存Google登录凭据。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

# 主程序先设置正确的PROJ数据路径，再导入栅格处理模块。
from jinjihu_ndwi import ROOT,CRS,GRID,SIZE,check_grid,write_json
import rasterio
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request_json',type=Path,help='GEE的DOWNLOAD_JSON输出保存成的UTF-8 JSON文件')
    args=parser.parse_args()
    manifest=json.loads(args.request_json.read_text(encoding='utf-8-sig'))
    # 检查指标、波段和网格，避免误下载其他区域或不同指标的数据。
    if (manifest.get('index')!='NDWI' or manifest.get('formula')!='(B3-B8)/(B3+B8)' or
        manifest.get('crs')!=CRS or manifest.get('transform')!=GRID or
        manifest.get('width')!=SIZE or manifest.get('height')!=SIZE or
        manifest.get('bands')!=['B2','B3','B4','B8','SCL','NDWI_EE']):
        raise ValueError('下载清单与当前NDWI研究区不一致。')
    if [s['season'] for s in manifest['scenes']]!=['winter','spring','summer','autumn']:
        raise ValueError('需要冬、春、夏、秋四景，且按此顺序排列。')
    data=ROOT/'data';data.mkdir(exist_ok=True)

    def one(scene):
        # 文件名必须是简单名称，下载网址只接受GEE官方HTTPS域名。
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.tif',scene['file']):
            raise ValueError('文件名不合法。')
        url=scene['download_url']
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='earthengine.googleapis.com':
            raise ValueError('下载地址不是GEE官方HTTPS地址。')
        target=data/scene['file'];part=target.with_suffix('.part')
        print('重新下载：'+target.name,flush=True)
        # 每次都实际发起HTTP GET。先写.part，读取校验通过后再改为正式文件。
        # GEE生成影像时偶尔会返回503；对临时服务错误和限流自动退避重试。
        session=requests.Session()
        retries=Retry(total=4,connect=3,read=2,status=4,backoff_factor=1,
                      status_forcelist=[429,500,502,503,504],allowed_methods=['GET'],
                      raise_on_status=False)
        session.mount('https://',HTTPAdapter(max_retries=retries))
        with session.get(url,stream=True,timeout=(30,300)) as response:
            if response.status_code!=200:
                raise RuntimeError(target.name+' 下载失败，HTTP '+str(response.status_code)+'；链接失效时需重新Run生成。')
            server_date=response.headers.get('Date')
            with part.open('wb') as f:
                for chunk in response.iter_content(1024*1024):f.write(chunk)
        with rasterio.open(part) as ds:check_grid(ds,manifest)
        part.replace(target)
        receipt={'file':target.name,'asset_id':scene['asset_id'],
                 'downloaded_at_utc':datetime.now(timezone.utc).isoformat(),
                 'server_response_date':server_date,'bytes':target.stat().st_size,
                 'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                 'method':'fresh HTTP GET from Google Earth Engine'}
        print('已保存：'+target.name,flush=True)
        return receipt

    # 最多并行四次下载；任何一景失败时，不把整个作业标记为下载完成。
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts=list(pool.map(one,manifest['scenes']))
    clean=dict(manifest)
    # 临时下载地址会失效，正式清单只保留稳定的影像ID和科学元数据。
    clean['scenes']=[{k:v for k,v in s.items() if k!='download_url'} for s in manifest['scenes']]
    clean['download_status']='complete'
    clean['download_method']='fresh Google Earth Engine GeoTIFF exports'
    write_json(data/'manifest.json',clean)
    write_json(data/'download_receipts.json',receipts)
    print('四景重新下载完成；可运行 jinjihu_ndwi.py --analyze-only。')


if __name__=='__main__':
    main()
