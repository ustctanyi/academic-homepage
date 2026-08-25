"""
相册后端服务（零依赖，Python 3.8+ 即可运行，无需 pip 安装任何包）
================================================================

用途：
    让个人主页（phd-homepage.html）里的相册支持“文件夹 + 上传 + 删除”。
    前端展开相册时自动调用本服务的 /api/* 接口。

本地运行：
    python album_server.py
    然后浏览器打开 http://localhost:8000

部署到服务器 / 云主机：
    1. 把本文件、phd-homepage.html、assets/ 一起上传；
    2. 在服务器上执行 python album_server.py（可用 systemd / supervisor 托管）；
    3. 通过 Nginx 等反代到本服务端口，或直接用本服务的 8000 端口。

注意：
    · 照片保存在本目录下的 albums/ 文件夹中，请定期备份；
    · 这是一个面向个人使用的最小实现，没有做登录鉴权，
      如需公开部署建议加一层访问密码或放在内网。
    · 只支持静态托管时无法上传/删除（GitHub Pages 等），
      必须运行本服务或接入其他云存储后端。
"""

import base64
import json
import mimetypes
import os
import re
import shutil
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote

# 项目根目录 = 本文件所在目录
ROOT = os.path.dirname(os.path.abspath(__file__))
ALBUM_DIR = os.path.join(ROOT, "albums")

MAX_SIZE = 10 * 1024 * 1024          # 单张照片上限 10MB（与前端一致）
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

os.makedirs(ALBUM_DIR, exist_ok=True)

# 可选依赖：安装 Pillow 后自动生成网页缩略图；未安装时退回原图
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def safe_name(name, default=""):
    """清洗文件夹名 / 文件名：去路径、去非法字符，防止路径穿越。"""
    name = unquote(name or "")
    name = os.path.basename(name.strip().replace("\\", "/"))
    name = re.sub(r"[^\w\u4e00-\u9fff.\- ]", "_", name)
    name = name.strip(" .")
    return name or default


def clean_name(name, default=""):
    """查找用清洗：只去掉路径部分，保留 & 等特殊字符（配合路径校验防穿越）。"""
    name = unquote(name or "")
    name = os.path.basename(name.strip().replace("\\", "/"))
    return name or default


class Handler(SimpleHTTPRequestHandler):
    """同时承担两件事：
       1) 提供 /api/* 接口（相册增删改查）；
       2) 用 SimpleHTTPRequestHandler 托管静态文件（HTML、图片等）。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    # ---------------- 工具方法 ----------------

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message, status=400):
        self._send_json({"error": message}, status)

    # ---------------- 路由 ----------------

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/albums":
            self._list_albums()
            return
        if path == "/api/thumbs":
            self._serve_thumbnail(parse_qs(parsed.query))
            return
        if path.startswith("/api/"):
            self._send_error("接口不存在", 404)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/upload":
            self._upload_photo()
        elif path == "/api/folder":
            self._create_folder()
        else:
            self._send_error("接口不存在", 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/photo":
            self._delete_photo(qs)
        elif parsed.path == "/api/folder":
            self._delete_folder(qs)
        else:
            self._send_error("接口不存在", 404)

    # ---------------- 相册 API 实现 ----------------

    def _list_albums(self):
        """返回全部文件夹及照片列表。"""
        folders = []
        for name in sorted(os.listdir(ALBUM_DIR)):
            if name.startswith("."):          # 跳过 .thumbs 等隐藏目录
                continue
            folder = os.path.join(ALBUM_DIR, name)
            if not os.path.isdir(folder):
                continue
            photos = sorted(
                f for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
                and os.path.splitext(f)[1].lower() in ALLOWED_EXT
            )
            folders.append({"name": name, "photos": photos})
        self._send_json({"folders": folders})

    def _serve_thumbnail(self, qs):
        """返回压缩后的缩略图（最长边 800px），加速网页相册加载。
           未安装 Pillow 或缩略图生成失败时，自动退回原图。
           缩略图缓存在 albums/.thumbs/ 下。"""
        folder = clean_name(qs.get("folder", [""])[0])
        name = clean_name(qs.get("name", [""])[0])
        if not folder or not name:
            return self._send_error("缺少 folder / name 参数")

        folder_path = os.path.abspath(os.path.join(ALBUM_DIR, folder))
        source = os.path.abspath(os.path.join(folder_path, name))
        if os.path.dirname(source) != folder_path or not os.path.isfile(source):
            return self._send_error("图片不存在", 404)

        body, ctype = self._thumbnail_or_original(source, folder, name)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _thumbnail_or_original(self, source, folder, name):
        """优先返回缩略图；无 Pillow、权限异常或图片损坏时退回原图。"""
        if HAS_PIL:
            thumb_dir = os.path.join(ALBUM_DIR, ".thumbs", folder)
            cache = os.path.join(thumb_dir, os.path.splitext(name)[0] + ".jpg")
            try:
                if (not os.path.exists(cache)
                        or os.path.getmtime(cache) < os.path.getmtime(source)):
                    os.makedirs(thumb_dir, exist_ok=True)
                    with Image.open(source) as im:
                        im.thumbnail((800, 800))      # 最长边不超过 800px
                        im.convert("RGB").save(cache, "JPEG", quality=82)
                with open(cache, "rb") as f:
                    return f.read(), "image/jpeg"
            except Exception:
                traceback.print_exc()   # 记录失败原因，继续走原图分支
        with open(source, "rb") as f:
            return f.read(), (mimetypes.guess_type(source)[0] or "application/octet-stream")

    def _upload_photo(self):
        """接收 JSON：{folder, filename, data(base64)}，保存图片。"""
        data = self._read_json()
        folder = clean_name(data.get("folder"), "未分类")
        filename = safe_name(data.get("filename"), "photo.jpg")
        raw = data.get("data", "")

        try:
            content = base64.b64decode(raw)
        except Exception:
            return self._send_error("图片数据格式错误")

        if len(content) > MAX_SIZE:
            return self._send_error("图片超过 10MB 上限")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXT:
            return self._send_error("仅支持 jpg / png / gif / webp 图片")

        folder_path = os.path.join(ALBUM_DIR, folder)
        os.makedirs(folder_path, exist_ok=True)

        # 同名文件自动加序号，避免覆盖
        target = os.path.join(folder_path, filename)
        if os.path.exists(target):
            stem, ext = os.path.splitext(filename)
            i = 1
            while os.path.exists(os.path.join(folder_path, "%s_%d%s" % (stem, i, ext))):
                i += 1
            target = os.path.join(folder_path, "%s_%d%s" % (stem, i, ext))
            filename = os.path.basename(target)

        with open(target, "wb") as f:
            f.write(content)
        self._send_json({"ok": True, "folder": folder, "filename": filename})

    def _create_folder(self):
        """接收 JSON：{name}，新建文件夹。"""
        data = self._read_json()
        name = safe_name(data.get("name"), "")
        if not name:
            return self._send_error("文件夹名称不能为空")
        os.makedirs(os.path.join(ALBUM_DIR, name), exist_ok=True)
        self._send_json({"ok": True, "name": name})

    def _delete_photo(self, qs):
        """删除指定文件夹下的单张照片。"""
        folder = clean_name(qs.get("folder", [""])[0])
        name = clean_name(qs.get("name", [""])[0])
        if not folder or not name:
            return self._send_error("缺少 folder / name 参数")

        folder_path = os.path.abspath(os.path.join(ALBUM_DIR, folder))
        target = os.path.abspath(os.path.join(folder_path, name))

        # 双重校验，防止路径逃逸
        if os.path.dirname(target) != folder_path or not os.path.isfile(target):
            return self._send_error("文件不存在", 404)
        os.remove(target)
        # 同步清理缩略图缓存
        thumb = os.path.join(ALBUM_DIR, ".thumbs", folder, os.path.splitext(name)[0] + ".jpg")
        if os.path.isfile(thumb):
            os.remove(thumb)
        self._send_json({"ok": True})

    def _delete_folder(self, qs):
        """删除空文件夹；非空时提示先清空照片（防止误删）。"""
        name = clean_name(qs.get("name", [""])[0])
        if not name:
            return self._send_error("缺少 name 参数")
        folder = os.path.join(ALBUM_DIR, name)
        if not os.path.isdir(folder):
            return self._send_error("文件夹不存在", 404)
        if os.listdir(folder):
            return self._send_error("文件夹不为空，请先清空其中的照片")
        os.rmdir(folder)
        # 同步清理缩略图缓存
        shutil.rmtree(os.path.join(ALBUM_DIR, ".thumbs", name), ignore_errors=True)
        self._send_json({"ok": True})

    # 关闭目录浏览（防止直接列出相册目录）
    def list_directory(self, path):
        self.send_error(403, "Directory listing is disabled.")
        return None


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("个人主页服务已启动：http://localhost:%d" % port)
    print("相册目录：%s" % ALBUM_DIR)
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    main()
