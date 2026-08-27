# 谭义 · 博士生个人主页

一个纯 HTML/CSS/少量 JavaScript 的静态学术主页，无任何框架，可部署到 GitHub Pages。

## 本地预览

直接用浏览器打开 `index.html` 即可（相册等折叠板块需要点击展开）。

## 部署到 GitHub Pages

1. 在 GitHub 网页上新建一个仓库（例如 `academic-homepage`），不要勾选“Add a README”。
2. 在本目录执行（把 `你的用户名` 和 `仓库名` 换成实际的）：

   ```bash
   git remote add origin https://github.com/你的用户名/仓库名.git
   git branch -M main
   git push -u origin main
   ```

3. 打开 GitHub 仓库页面 → Settings → Pages：
   - Source 选择 **Deploy from a branch**
   - Branch 选择 **main**，目录选择 **/ (root)**
   - 点击 Save
4. 稍等一两分钟，网站地址为：

   `https://你的用户名.github.io/仓库名/`

## 修改说明

- 全文搜索「【」即可找到需要替换的占位内容（姓名、论文、项目、荣誉等）。
- 相册（照片书模式）：照片放在本地 `albums/` 文件夹（按文件夹分类，支持中文名）。
  新增或删除照片后，运行 `python build_album.py` 重新生成网页相册资源
  （自动压缩图片，输出 `assets/albums/<文件夹>/` 与两份索引
  `index.json`、`albums.json`），然后提交推送即可。
- 相册描述：编辑根目录 `album_descriptions.json`（键为相册名，值为简短
  markdown 文本，支持 `**加粗**`、`*斜体*`、`- 列表`），会显示在照片书的扉页。
- 头像与头部风景图：替换 `assets/` 下的图片后，修改 `index.html` 中的路径。

## 更新相册的完整流程

```bash
python build_album.py            # 1. 压缩照片并生成索引（index.json + albums.json）
git add -A
git commit -m "更新相册"
git push                         # 2. 推送后 GitHub Pages 自动重新部署
```

> 提示：`albums.json` 是照片书组件的唯一数据源（含名称、描述、封面、图片数组），
> 封面默认取相册第一张图；如果手动维护该文件，请保持图片路径为
> `assets/albums/` 下的相对路径。
