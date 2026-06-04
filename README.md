# 批量闭合区域抠图导出 SVG

这是一个 Windows 桌面工具，用于导入 PNG/JPG 图片，在图片上绘制闭合区域，软件会在区域内去除白底或浅色连通背景，生成带透明通道的 PNG，并以内嵌透明 PNG 的方式导出为独立 SVG。

**配合GPT生图功能，从图片中提取可编辑的元素**

当前版本已迁移为 `PySide6 + Shapely + svgwrite + Pillow`。

## 当前功能

- 支持导入单张、多张 `.png` / `.jpg` / `.jpeg` 图片。
- 支持导入文件夹中的图片。
- 支持矩形、椭圆、自由闭合曲线区域。
- 支持选择工具点击区域、区域列表点击高亮区域。
- 支持高亮区域拖动移动。
- 支持手形工具平移缩放后的图片视图。
- 支持鼠标滚轮缩放、适应窗口。
- 支持区域重命名、显示/隐藏、删除单个区域。
- 支持顶部按钮一键删除当前图片的全部区域。
- 支持区域列表勾选，多选后批量导出选中区域。
- 支持保留勾选状态，删除某个区域后其他区域的勾选状态不丢失。
- 支持导出后继续选择、高亮、删除和绘制区域。
- 右侧区域列表显示每个区域的成功导出次数。
- 左侧图片列表支持收起/展开：
  - 展开时显示序号、文件名、区域数、是否导出。
  - 收起时只显示图片序号。
- 顶部“导出所有文件”会导出所有已导入图片的全部区域。
- 右侧“导出当前图片全部 SVG”只导出当前图片的全部区域。
- 右侧“导出选中 SVG”只导出当前图片中勾选的区域。

## 抠图与导出

- 区域几何校验使用 Shapely，包括面积、边界、自交、重叠和包含关系。
- 抠图使用 Pillow 生成 mask，并保留 RGBA alpha 通道。
- 白底/浅色背景去除使用边界 Flood Fill，避免简单阈值误删内部浅色细节。
- 支持导出参数：
  - 羽化半径
  - 白底阈值
  - 近白容差
  - 最小噪点面积
  - 去除小噪点
  - 只保留最大连通域
- SVG 使用 svgwrite 生成，结构为内嵌透明 PNG，不做真正矢量化。

## 运行源码版

```powershell
.venv\Scripts\python.exe run_app.py
```

也可以用模块方式运行：

```powershell
.venv\Scripts\python.exe -m batch_cutout_svg.app
```

## 运行 EXE 版

已生成目录式 Windows 程序：

```text
dist\PNG2SVG\PNG2SVG.exe
```

发布给其他电脑时，需要保留整个 `dist\PNG2SVG` 文件夹，不能只复制单独的 `PNG2SVG.exe`，因为运行依赖在旁边的 `_internal` 目录中。

也已生成压缩包：

```text
dist\PNG2SVG_exe.zip
```

解压后运行：

```text
PNG2SVG\PNG2SVG.exe
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest
```

当前测试覆盖核心几何校验、图片导入、抠图透明度、SVG 导出、区域移动、区域 ID 生成和导出次数累计。

## 打包

项目使用 PyInstaller 打包，配置文件为：

```text
PNG2SVG.spec
```

重新打包命令：

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm --clean PNG2SVG.spec
```

当前采用 `onedir` 目录式打包，原因是 PySide6 程序目录式更稳定，启动速度也比单文件模式更可控。

## 日志

程序可能生成以下调试日志：

- `import_debug.log`：记录图片导入阶段信息。
- `app_errors.log`：记录界面回调异常。

这些日志用于排查导入、界面回调或导出问题。

## 主要依赖

- PySide6：桌面界面。
- Shapely：闭合区域几何校验和命中判断。
- svgwrite：SVG 文件生成。
- Pillow：图片读取、透明 PNG 抠图和 mask 处理。
- PyInstaller：Windows exe 打包。
