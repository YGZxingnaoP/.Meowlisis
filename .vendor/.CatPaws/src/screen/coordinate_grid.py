from .screen_receiver import ScreenReceiver
from .coordinate_system import coord_system
import base64


def generate_screen_page(receiver: ScreenReceiver) -> str:
    img_bytes = receiver.get_latest_image()
    if not img_bytes:
        return """<html><body style="text-align:center;font-family:sans-serif;padding:60px;">
            <h2>还没有收到手机截图</h2>
            <p>请确保手机已连接并推送截图</p>
        </body></html>"""

    img_base64 = base64.b64encode(img_bytes).decode()
    w, h = receiver.get_dimensions()
    scale = coord_system.scale
    lw, lh = coord_system.logical_size

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>手机屏幕 · 坐标布点</title>
    <style>
        body {{ margin:0; display:flex; flex-direction:column; align-items:center; font-family:sans-serif; }}
        .info-bar {{
            background:#f5f5f5; padding:10px 20px; border-radius:8px;
            font-size:14px; color:#333; margin:10px 0;
        }}
        .info-bar code {{ background:#e8e8e8; padding:2px 6px; border-radius:3px; }}
        #container {{ position:relative; display:inline-block; margin:20px; }}
        #screen-img {{ display:block; max-width:90vw; height:auto; cursor:crosshair; }}
        #grid-overlay {{
            position:absolute; top:0; left:0; width:100%; height:100%;
            background-image: linear-gradient(rgba(255,255,255,0.2) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(255,255,255,0.2) 1px, transparent 1px);
            background-size: 20px 20px;
            pointer-events:none;
        }}
        #coords {{ margin-top:10px; font-size:18px; line-height:1.8; }}
        .coord-pixel {{ color:#666; }}
        .coord-point {{ color:#2196F3; font-weight:bold; }}
        #snack {{ visibility:hidden; position:fixed; bottom:30px; left:50%; transform:translateX(-50%);
                  background:#333; color:#fff; padding:10px 25px; border-radius:8px; font-size:16px; }}
        #snack.show {{ visibility:visible; animation: fade 2s; }}
        @keyframes fade {{ 0%{{opacity:0}} 10%{{opacity:1}} 80%{{opacity:1}} 100%{{opacity:0}} }}
    </style>
</head>
<body>
    <h2>📱 手机实时画面（点击获取坐标）</h2>

    <div class="info-bar">
        📐 截图尺寸：<code>{w}×{h} px</code> &nbsp;|&nbsp;
        逻辑尺寸：<code>{lw}×{lh} pt</code> &nbsp;|&nbsp;
        缩放因子：<code>{scale}x</code>
    </div>

    <div id="container">
        <img id="screen-img" src="data:image/png;base64,{img_base64}" alt="phone screen">
        <div id="grid-overlay"></div>
    </div>

    <div id="coords">👆 点击画面任意位置，显示像素坐标和逻辑点坐标</div>
    <div id="snack">✅ 逻辑坐标已复制</div>

    <script>
        const img = document.getElementById('screen-img');
        const coordsDiv = document.getElementById('coords');
        const snack = document.getElementById('snack');
        const originalWidth = {w};
        const originalHeight = {h};
        const scale = {scale};

        img.addEventListener('click', function(e) {{
            const rect = img.getBoundingClientRect();
            const scaleX = originalWidth / rect.width;
            const scaleY = originalHeight / rect.height;

            // 像素坐标（截图原始分辨率）
            const px = Math.round((e.clientX - rect.left) * scaleX);
            const py = Math.round((e.clientY - rect.top) * scaleY);

            // 逻辑点坐标（除以 scale，WDA 使用的坐标系）
            const lx = Math.round(px / scale);
            const ly = Math.round(py / scale);

            coordsDiv.innerHTML =
                `<span class="coord-pixel">📷 像素坐标：x=${{px}}, y=${{py}}</span><br>` +
                `<span class="coord-point">🎯 逻辑坐标：x=${{lx}}, y=${{ly}}</span>` +
                `<span style="color:#999;font-size:13px;">（WDA 使用此坐标，点击复制）</span>`;

            // 复制逻辑坐标（WDA 直接使用）
            navigator.clipboard.writeText(`${{lx}},${{ly}}`).then(() => {{
                snack.classList.add('show');
                setTimeout(() => snack.classList.remove('show'), 2000);
            }});
        }});
    </script>
</body>
</html>"""
    return html
