# -*- coding: utf-8 -*-
"""
相册同步脚本：把本地 albums/ 文件夹发布为网页相册资源。

做什么：
  1. 遍历 albums/ 下每个文件夹，把其中的图片压缩（最长边 1000px、JPEG 质量 80，
     自动按拍摄方向摆正）输出到 assets/albums/<文件夹>/<同名>.jpg；
  2. 生成 assets/albums/index.json 与 assets/albums/albums.json：
     - index.json 为“文件夹+照片”列表（旧格式，保留兼容）；
     - albums.json 为照片书配置：每个相册含名称、描述、封面图、图片数组，
       供主页相册轮播组件读取（描述来自 album_descriptions.json，
       英文名称/描述来自 album_translations.json，均可直接编辑）。

怎么用：
  python build_album.py
  添加/删除照片后重新运行本脚本，然后 git add -A && git commit && git push。

注意：
  · 仅处理 jpg/jpeg/png/gif/webp，NEF 等 RAW 和视频会被自动跳过；
  · 原图始终保留在本地 albums/，不会上传到 GitHub；
  · 若删除了某个文件夹，重新运行脚本会同步清理 assets/albums/ 里对应的输出。
"""

import json
import os
import shutil
from PIL import Image, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))
ALBUMS = os.path.join(BASE, "albums")
OUT = os.path.join(BASE, "assets", "albums")

MAX_SIDE = 1000      # 压缩后最长边（像素）
QUALITY = 80         # JPEG 质量
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def load_descriptions():
    """读取相册描述（album_descriptions.json，键为文件夹名，值为 markdown 文本）。"""
    path = os.path.join(BASE, "album_descriptions.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def load_translations():
    """读取相册英文翻译（album_translations.json）。
    键为文件夹名，值为 { name: 英文名, description: 英文描述 }。"""
    path = os.path.join(BASE, "album_translations.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def main():
    os.makedirs(OUT, exist_ok=True)
    descriptions = load_descriptions()
    translations = load_translations()

    # 收集源文件夹
    src_folders = {
        name for name in os.listdir(ALBUMS)
        if os.path.isdir(os.path.join(ALBUMS, name)) and not name.startswith(".")
    }

    # 清理已删除源文件夹对应的输出
    for name in os.listdir(OUT):
        if name == "index.json":
            continue
        if name not in src_folders:
            shutil.rmtree(os.path.join(OUT, name), ignore_errors=True)
            print("清理已删除的文件夹输出:", name)

    result = []
    for folder in sorted(src_folders):
        src_dir = os.path.join(ALBUMS, folder)
        out_dir = os.path.join(OUT, folder)
        os.makedirs(out_dir, exist_ok=True)

        photos = []
        for name in sorted(os.listdir(src_dir)):
            src = os.path.join(src_dir, name)
            if not os.path.isfile(src):
                continue
            if os.path.splitext(name)[1].lower() not in ALLOWED_EXT:
                continue
            out_name = os.path.splitext(name)[0] + ".jpg"
            out_path = os.path.join(out_dir, out_name)
            try:
                with Image.open(src) as im:
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((MAX_SIDE, MAX_SIDE))
                    im.convert("RGB").save(out_path, "JPEG", quality=QUALITY, optimize=True)
            except Exception as e:
                print("跳过(处理失败):", folder, name, e)
                continue
            photos.append(out_name)

        if photos:
            result.append({"name": folder, "photos": photos})
        print(folder, "->", len(photos), "张")

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"folders": result}, f, ensure_ascii=False, indent=1)

    # 轮播配置：名称 / 描述 / 封面（第一张）/ 图片数组（路径相对 assets/albums/）
    book_albums = []
    for folder in result:
        rel = [folder["name"] + "/" + p for p in folder["photos"]]
        tr = translations.get(folder["name"], {})
        book_albums.append({
            "name": folder["name"],
            "description": descriptions.get(folder["name"], ""),
            "name_en": tr.get("name", ""),
            "description_en": tr.get("description", ""),
            "cover": rel[0] if rel else "",
            "images": rel,
        })
    with open(os.path.join(OUT, "albums.json"), "w", encoding="utf-8") as f:
        json.dump({"albums": book_albums}, f, ensure_ascii=False, indent=1)

    total = sum(len(f["photos"]) for f in result)
    print("完成：%d 个文件夹，%d 张照片 -> assets/albums/" % (len(result), total))


if __name__ == "__main__":
    main()
