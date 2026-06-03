# 批量闭合区域抠图导出 SVG

这是按 `BATCH_CUTOUT_SVG_PLAN.md` 开发的第一版本地桌面工具。用户导入图片，在图片上绘制闭合区域，软件按区域生成透明 PNG，并以内嵌 PNG 的方式导出独立 SVG 文件。

## 第一版功能

- 导入单张、多张 `.png` / `.jpg` / `.jpeg` 图片。
- 导入文件夹中的图片。
- 在每张图片上绘制矩形、椭圆、自由闭合曲线。
- 新增区域时检查面积、边界、自交、重叠、交叉、边界重合和包含关系。
- 区域重命名、选择、显示/隐藏、删除。
- 按每个区域单独导出 SVG，SVG 内嵌透明 PNG。
- 每张原图一个输出子目录，文件名自动清洗并避让重名。

## 运行

本项目使用工作区虚拟环境：

```powershell
.venv\Scripts\python.exe run_app.py
```

也可以用模块方式运行：

```powershell
.venv\Scripts\python.exe -m batch_cutout_svg.app
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest
```

## 依赖说明

当前第一版使用 `Tkinter + Pillow`，避免在当前沙箱环境中安装 PySide6/Shapely/svgwrite 失败导致软件不可运行。核心能力与计划一致：闭合区域绘制、几何校验、透明 PNG 抠图和内嵌 PNG 的 SVG 导出。

后续如果可以正常联网安装依赖，可逐步替换为计划中的 `PySide6 + Shapely + svgwrite`。

