"""
Sophia Chat 桌面版入口
使用 pywebview 将 Web 应用包装为原生桌面窗口
"""

import sys
import os
import threading
import time

os.environ['PYTHONIOENCODING'] = 'utf-8'  # 对子进程生效
# PyInstaller 无控制台模式时 stdout/stderr 为 None，需判空
for stream_name in ('stdout', 'stderr'):
    s = getattr(sys, stream_name, None)
    if s is not None and hasattr(s, 'encoding') and s.encoding != 'utf-8':
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


# ============================================================
# 路径兼容：PyInstaller 打包后切换工作目录
# ============================================================
if getattr(sys, 'frozen', False):
    # 打包后：工作目录切换到 exe 所在目录
    os.chdir(os.path.dirname(sys.executable))

import webview
from waitress import serve


def start_server(host: str, port: int):
    """在后台线程中启动 Waitress 服务器"""
    from app import app
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
    serve(app, host=host, port=port, threads=8, channel_timeout=300)


def wait_for_server(host: str, port: int, timeout: int = 10) -> bool:
    """等待服务器就绪"""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def main():
    host = "127.0.0.1"
    port = 5000

    # 后台启动 Flask 服务器
    server_thread = threading.Thread(
        target=start_server,
        args=(host, port),
        daemon=True
    )
    server_thread.start()

    # 等待服务器就绪
    print(f"  正在启动服务器 {host}:{port} ...")
    if not wait_for_server(host, port, timeout=15):
        print("  [ERROR] 服务器启动超时")
        sys.exit(1)
    print(f"  服务器已就绪")

    # 创建桌面窗口
    window = webview.create_window(
        title='Sophia Chat - 多模型AI助手',
        url=f'http://{host}:{port}',
        width=1200,
        height=800,
        min_size=(800, 600),
        text_select=True,
        zoomable=True,
    )

    # 启动窗口（阻塞直到窗口关闭）
    webview.start(debug=False)


if __name__ == '__main__':
    main()
