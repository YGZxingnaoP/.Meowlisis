# -*- coding: utf-8 -*-
# 用你日常的 Edge profile 打开萌百，把已通过的会话(含 cf_clearance)存下来供抓取复用
# 用法: 先完全关闭 Edge，再运行本脚本
import io, os, sys, json, time, traceback
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, ROOT)
URL = sys.argv[1] if len(sys.argv) > 1 else 'https://mzh.moegirl.org.cn/%E5%AD%A4%E7%8B%AC%E6%91%87%E6%BB%9A%EF%BC%81'
_REAL = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Edge', 'User Data')
PROFILE = os.path.join(ROOT, '.temp', 'edge_profile')      # 复制出来的 profile，避免占用你正在用的 Edge


def _prep_profile():
    """复制真实 profile 的关键文件（cookie / 首选项 / Local State），Edge 开着也能复制"""
    import shutil
    os.makedirs(os.path.join(PROFILE, 'Default', 'Network'), exist_ok=True)
    items = ['Local State', 'First Run', 'Default/Preferences',
             'Default/Network/Cookies', 'Default/Network/Network Persistent State',
             'Default/Login Data', 'Default/Web Data', 'Default/Cookies']
    ok = 0
    for rel in items:
        s = os.path.join(_REAL, rel.replace('/', os.sep))
        d = os.path.join(PROFILE, rel.replace('/', os.sep))
        try:
            if os.path.isfile(s):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                ok += 1
        except Exception as e:
            print('  复制失败 %-36s %s' % (rel, str(e)[:60]))
    print('  已复制 profile 关键文件 %d 个 → %s' % (ok, PROFILE))
    return PROFILE


_prep_profile()
STORE = os.path.join(ROOT, '.temp', 'web_sessions.json')
from func.database.search.spider.selenium_spider import CatLearnSeleniumSpider
from func.database.search.spider.base import CatLearnBaseSpider
sp = CatLearnSeleniumSpider()
drv_path = sp.ensure_driver()
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
o = Options()
o.add_argument('--user-data-dir=' + PROFILE)          # ← 复用真实 profile
o.add_argument('--disable-blink-features=AutomationControlled')
o.add_experimental_option('excludeSwitches', ['enable-automation'])
o.add_experimental_option('useAutomationExtension', False)
try:
    drv = webdriver.Edge(service=Service(executable_path=drv_path), options=o)
except Exception as e:
    print('启动失败（最常见原因：Edge 还在运行，profile 被占用）')
    print('  请从托盘彻底退出 Edge（含“启动增强/后台常驻”），再重跑本脚本')
    print('  原始错误:', type(e).__name__, str(e)[:200])
    sys.exit(1)
drv.set_page_load_timeout(60)
try:
    drv.get(URL)
    time.sleep(4)
    src = drv.page_source or ''
    ua = drv.execute_script('return navigator.userAgent')
    print('HTML %d 字节  含孤独摇滚: %s  仍是挑战页: %s' % (len(src), '孤独摇滚' in src, sp._blocked(src)))
    if '孤独摇滚' in src and not sp._blocked(src):
        host = 'mzh.moegirl.org.cn'
        data = {}
        if os.path.exists(STORE):
            try:
                data = json.loads(io.open(STORE, encoding='utf-8').read())
            except Exception:
                data = {}
        data[host] = {'ua': ua, 'saved_at': time.time(),
                      'cookies': {c.get('name'): c.get('value') for c in drv.get_cookies()}}
        io.open(STORE, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=1))
        print('已保存会话 →', STORE, ' cookies:', len(data[host]['cookies']))
        print(' 关键 cookie:', [k for k in data[host]['cookies'] if 'clearance' in k or 'cf' in k.lower()])
        txt = CatLearnBaseSpider().extract_content(src)
        print('正文 %d 字 | %s' % (len(txt or ''), (txt or '')[:150].replace('\n', ' ')))
    else:
        print('这个 profile 也没通过 —— 说明该站对当前网络/客户端就是不放行')
finally:
    drv.quit()
