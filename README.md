# PNG2SVG v1.1

Windows 桌面工具，用于批量导入 PNG/JPG/JPEG 图片，在图片上绘制闭合区域，然后导出为内嵌透明 PNG 的 SVG 文件。

v1.1 重点优化了非 AI 抠图算法：白底/浅色背景去除、边缘平滑、主体筛选和 OpenCV GrabCut 分割模式。

## 功能概览

- 支持导入单张、多张图片，也支持导入文件夹。
- 支持矩形、椭圆、自由闭合曲线区域。
- 支持选择、拖动、显示/隐藏、重命名、删除区域。
- 支持勾选多个区域并批量导出 SVG。
- 导出结果为透明背景 PNG 内嵌到 SVG 中，不做矢量化路径转换。
- 导出后保留当前选择、区域高亮和区域导出次数。

## v1.1 抠图算法优化

抠图模式：

- 仅区域裁剪：只按用户闭合区域裁剪，保留区域内全部像素。
- 白底/浅色背景去除：默认模式，适合白底产品图、图标、插画、截图。
- GrabCut 分割（非 AI）：使用 OpenCV 传统分割算法，适合背景不纯白但主体边界较清晰的图片。

核心算法：

- 边界 Flood Fill：只移除与 ROI 边界连通的白底/浅色背景，尽量避免误删目标内部白色细节。
- 浅色背景增强：支持近白、低饱和浅色、边界背景采样判断。
- 连通域过滤：删除小噪点，可保留最大主体或最大主体及近邻部件。
- 主体筛选：减少远离主体的黑条、文字、边框残留和孤立杂物。
- Alpha 边缘精修：先平滑 mask，再做轻微 alpha 羽化，防止边缘锯齿和毛刺。
- 去白边/去色溢出：只处理半透明边缘区域，减少白边且避免污染实心主体颜色。
- GrabCut 失败回退：OpenCV 不可用或分割结果异常时，自动回退到白底/浅色背景去除模式。

右侧导出设置默认只需要选择：

- 抠图模式
- 处理强度：保守 / 标准 / 强力

高级参数可展开调整白底阈值、近白容差、主体筛选模式、边缘平滑强度、GrabCut 迭代次数等。

## 运行源码版

```powershell
.venv\Scripts\python.exe run_app.py
```

或：

```powershell
.venv\Scripts\python.exe -m batch_cutout_svg.app
```

## 运行 EXE 版

打包后的目录结构：

```text
dist\PNG2SVG\PNG2SVG.exe
```

发布给其他电脑时，需要保留整个 `PNG2SVG` 文件夹，不能只复制单独的 `PNG2SVG.exe`，因为依赖文件在旁边的 `_internal` 目录中。

压缩包：

```text
dist\PNG2SVG_v1.1.zip
```

解压后运行：

```text
PNG2SVG\PNG2SVG.exe
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest
```

当前测试覆盖几何校验、图片导入、透明抠图、SVG 导出、区域移动、主体筛选、边缘平滑、白底去除和 OpenCV GrabCut 路径。

## 打包

项目使用 PyInstaller 打包，配置文件为：

```text
PNG2SVG.spec
```

重新打包命令：

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm --clean PNG2SVG.spec
```

当前采用 `onedir` 目录式打包，适合 PySide6 桌面程序，启动速度和稳定性都比单文件模式更可控。

## 主要依赖

- PySide6：桌面界面。
- Pillow：图片读取、透明 PNG、mask 和边缘处理。
- Shapely：闭合区域几何校验。
- svgwrite：SVG 文件生成。
- opencv-python-headless：GrabCut 非 AI 分割模式。
- PyInstaller：Windows exe 打包。

## 日志

程序可能生成以下调试日志：

- `import_debug.log`：记录图片导入阶段信息。
- `app_errors.log`：记录界面回调异常。

这些日志用于排查导入、界面回调或导出问题。
