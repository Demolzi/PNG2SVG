# 批量闭合区域抠图导出 SVG

本工具用于导入 PNG/JPG 图片，在图片上绘制闭合区域，并将区域内的目标内容抠出为带透明通道的 PNG，再以内嵌 PNG 的方式导出为独立 SVG。

## 当前功能

- 导入单张或多张 `.png` / `.jpg` / `.jpeg` 图片。
- 导入文件夹中的图片。
- 在每张图片上绘制矩形、椭圆、自由闭合曲线。
- 使用 Shapely 校验区域面积、边界、自交、重叠和包含关系。
- 区域重命名、选择、高亮、移动、显示/隐藏、删除。
- 区域列表支持勾选，支持导出选中区域，同时保留导出全部。
- 导出时使用边界 Flood Fill 去除区域内连通白底或浅色背景。
- 支持白底阈值、近白容差、羽化、最小噪点面积和保留最大连通域参数。
- 使用 svgwrite 生成 SVG，SVG 内嵌透明 PNG。

## 运行

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

## 主要依赖

- PySide6：桌面界面。
- Shapely：闭合区域几何校验和命中判断。
- svgwrite：SVG 文件生成。
- Pillow：图片读取、透明 PNG 抠图和 mask 处理。
