# 导入图片后程序未响应问题诊断与修复方案

## 1. 问题现象

当前现象：

- 点击“导入图片”后可以选择文件；
- 选择文件后程序立刻显示“未响应”；
- 画布上没有显示图片；
- `import_debug.log` 中已经记录 `loaded 1 image(s), failures 0: []`。

这说明：**图片选择、路径解析、去重、Pillow 读取图片这几步已经成功完成**。程序卡住的位置大概率不在 `image_loader.py` 的文件读取阶段，而是在读取完成后的 UI 更新阶段。

---

## 2. 当前导入流程分析

`main_window.py` 中导入图片的大致流程是：

```python
raw_paths = filedialog.askopenfilenames(...)
paths = _coerce_dialog_paths(raw_paths, self.tk.splitlist)
self._load_paths(paths)
```

`_load_paths()` 中的关键流程是：

```python
result = load_images_with_report(new_paths)
loaded = result.items
self.images.extend(loaded)
self.image_list.set_images(self.images)
self.select_image(loaded[0].path)
self.image_list.select_path(loaded[0].path, notify=False)
```

日志显示已经执行到：

```text
loaded 1 image(s), failures 0: []
```

因此卡住点很可能在下面几处之一：

1. `self.image_list.set_images(self.images)`；
2. `self.select_image(loaded[0].path)`；
3. `self.canvas_view.set_image_item(image)`；
4. `canvas.redraw()` 中的图片缩放和 `ImageTk.PhotoImage` 创建；
5. `Treeview` 选择事件重复触发造成 UI 回调循环。

---

## 3. 已检查模块结论

### 3.1 `image_loader.py`

`image_loader.py` 中 `load_image()` 会执行：

```python
with Image.open(path) as source:
    image = source.convert("RGBA").copy()
```

这一步确实可能在超大图片上造成短暂阻塞，但从日志看，图片已经成功加载并返回，所以它不是当前最主要的卡死点。

结论：

> `image_loader.py` 不是首要怀疑对象，但后续仍建议加入图片尺寸限制和缩略图机制。

---

### 3.2 `main_window.py`

`_load_paths()` 在加载成功后，立即同步更新图片列表、选择图片、刷新画布。这些操作全部发生在 Tkinter 主线程中。

如果后续 `canvas.redraw()` 进行大图缩放，主线程会被阻塞，窗口就会显示“未响应”。

结论：

> `main_window.py` 需要增加更细的日志，确认卡在 `image_list.set_images()`、`select_image()` 还是 `canvas_view.set_image_item()`。

---

### 3.3 `canvas.py`

这是当前最可疑的模块。

`CanvasView.redraw()` 中每次重绘都会执行：

```python
scaled = image.resize((scaled_width, scaled_height), resampling)
self._tk_image = ImageTk.PhotoImage(scaled)
```

问题在于：

1. 这一步在 Tkinter 主线程执行；
2. 使用 `LANCZOS` 缩放大图时可能很慢；
3. `<Configure>`、`fit_to_window()`、`set_image_item()` 都可能触发 `redraw()`；
4. 没有预览缓存，每次重绘都重新 resize；
5. 如果导入图片尺寸较大，会导致界面短时间或长时间无响应。

结论：

> 当前最优先修复点是 `canvas.py` 的同步大图缩放与无缓存重绘问题。

---

### 3.4 `image_list.py`

`image_list.py` 的 `set_images()` 会删除所有 Treeview 项再重新插入：

```python
for iid in self.tree.get_children():
    self.tree.delete(iid)
for item in items:
    self.tree.insert(...)
```

单张图片时这一步不太可能造成卡死。

不过 `select_path()` 中有一点需要注意：

```python
if not notify:
    self._suppress_selection_callback = True
self.tree.selection_set(iid)
```

如果 `selection_set()` 没有触发 `<<TreeviewSelect>>`，`_suppress_selection_callback` 可能会残留为 `True`，导致下一次真实选择事件被误抑制。它通常不会导致未响应，但可能造成选择行为异常。

结论：

> `image_list.py` 不是卡死首因，但建议增强 `notify=False` 的写法，避免抑制标志残留。

---

### 3.5 `region_panel.py`

刚导入图片时区域列表为空，`set_regions(image.regions, None)` 基本只会清空 Treeview 和清空名称输入框。

结论：

> `region_panel.py` 卡死可能性较低。

---

## 4. 最可能原因排序

### 第一可疑原因：画布同步 resize 大图

导入后程序会调用：

```python
self.canvas_view.set_image_item(image)
```

然后触发：

```python
fit_to_window()
redraw()
image.resize(...)
ImageTk.PhotoImage(...)
```

如果图片较大，或者重绘被触发多次，程序会直接卡住。

### 第二可疑原因：导入后 UI 更新缺少分阶段日志

当前日志只记录到 `loaded`，没有记录 UI 更新阶段，因此无法确认到底卡在图片列表、画布还是区域面板。

### 第三可疑原因：Treeview 选择事件重复触发

`image_list.select_path()` 和 `TreeviewSelect` 事件可能造成额外的选择回调。虽然目前代码有 `_suppress_selection_callback`，但仍建议改得更稳。

---

## 5. 建议立即执行的诊断步骤

### 5.1 给 `_load_paths()` 增加阶段日志

在 `main_window.py` 的 `_load_paths()` 中，将加载成功后的部分改为：

```python
loaded = result.items

self._log_import("before extend images")
self.images.extend(loaded)
self._log_import("after extend images")

self._log_import("before image_list.set_images")
self.image_list.set_images(self.images)
self._log_import("after image_list.set_images")

if loaded:
    self._log_import("before select_image")
    self.select_image(loaded[0].path)
    self._log_import("after select_image")

    self._log_import("before image_list.select_path")
    self.image_list.select_path(loaded[0].path, notify=False)
    self._log_import("after image_list.select_path")
```

### 5.2 给 `select_image()` 增加阶段日志

```python
def select_image(self, path: Path) -> None:
    self._log_import(f"select_image start: {path}")
    image = next((item for item in self.images if item.path == path), None)
    if image is None:
        self._log_import("select_image image not found")
        return

    self.current_image = image
    self.selected_region_id = None

    self._log_import("before canvas_view.set_image_item")
    self.canvas_view.set_image_item(image)
    self._log_import("after canvas_view.set_image_item")

    self._log_import("before region_panel.set_regions")
    self.region_panel.set_regions(image.regions, None)
    self._log_import("after region_panel.set_regions")

    self._update_status()
    self._log_import("select_image done")
```

### 5.3 判断日志停在哪里

重新运行程序并导入图片后，看 `import_debug.log` 最后一行：

| 最后一行 | 说明 |
|---|---|
| `before image_list.set_images` | 卡在图片列表刷新 |
| `before select_image` | 卡在选择图片之前的某个 UI 状态 |
| `before canvas_view.set_image_item` | 卡在画布设置图片 |
| `before region_panel.set_regions` | 卡在区域面板刷新 |
| `after select_image` 但未响应 | 可能卡在 `image_list.select_path` 或后续事件 |

---

## 6. 核心修复方案一：给画布预览增加缓存

### 6.1 修改 `CanvasView.__init__()`

在 `canvas.py` 中加入：

```python
self._preview_cache_key: tuple[int, int, int] | None = None
self._preview_cache_image: Image.Image | None = None
```

建议放在：

```python
self._tk_image: ImageTk.PhotoImage | None = None
```

后面。

---

### 6.2 修改 `set_image_item()`

切换图片时清空缓存：

```python
def set_image_item(self, image_item: ImageItem | None) -> None:
    self.image_item = image_item
    self.selected_region_id = None
    self._preview_cache_key = None
    self._preview_cache_image = None
    self._reset_drawing()
    ...
```

---

### 6.3 修改 `redraw()` 中的缩放逻辑

将原来的：

```python
resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
scaled = image.resize((scaled_width, scaled_height), resampling)
self._tk_image = ImageTk.PhotoImage(scaled)
```

替换为：

```python
cache_key = (id(image), scaled_width, scaled_height)

if self._preview_cache_key == cache_key and self._preview_cache_image is not None:
    scaled = self._preview_cache_image
else:
    resampling = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
    scaled = image.resize((scaled_width, scaled_height), resampling)
    self._preview_cache_key = cache_key
    self._preview_cache_image = scaled

self._tk_image = ImageTk.PhotoImage(scaled)
```

说明：

- 预览阶段不建议使用 `LANCZOS`；
- `BILINEAR` 速度更快，预览质量足够；
- 导出时再使用高质量处理即可；
- 缓存可以避免每次鼠标移动、选择区域、窗口事件都重新缩放图片。

---

## 7. 核心修复方案二：限制预览图最大尺寸

即使有缓存，首次导入超大图片时仍可能卡住。建议给预览图设置最大像素边长。

### 7.1 增加预览最大边长常量

在 `canvas.py` 顶部加入：

```python
MAX_PREVIEW_SIDE = 2400
```

### 7.2 在 `redraw()` 中限制缩放尺寸

在计算 `scaled_width`、`scaled_height` 后加入：

```python
max_side = max(scaled_width, scaled_height)
if max_side > MAX_PREVIEW_SIDE:
    factor = MAX_PREVIEW_SIDE / max_side
    scaled_width = max(1, int(scaled_width * factor))
    scaled_height = max(1, int(scaled_height * factor))
```

注意：这只是限制显示预览，不改变原图数据。绘制坐标仍应基于原图坐标。

如果要严格保证坐标对应，建议更稳的方式是维护一个单独的 `preview_image` 和 `preview_scale`。但第一版可以先通过缓存和 BILINEAR 解决卡死问题。

---

## 8. 核心修复方案三：导入后延迟渲染画布

Tkinter 的文件选择对话框关闭后，立即执行大量 UI 操作容易造成窗口假死。可以把选中图片后的画布渲染延迟到事件循环空闲时执行。

在 `_load_paths()` 中将：

```python
if loaded:
    self.select_image(loaded[0].path)
    self.image_list.select_path(loaded[0].path, notify=False)
```

改成：

```python
if loaded:
    first_path = loaded[0].path
    self.image_list.select_path(first_path, notify=False)
    self.status_var.set("图片已读取，正在准备预览...")
    self.after(10, lambda path=first_path: self.select_image(path))
```

这样可以让 Tkinter 先恢复事件循环，再进入画布渲染。

---

## 9. 修复 `image_list.py` 的选择抑制逻辑

当前 `select_path()` 中：

```python
if not notify:
    self._suppress_selection_callback = True
self.tree.selection_set(iid)
```

建议改成：

```python
def select_path(self, path: Path, notify: bool = True) -> None:
    iid = str(path)
    if iid not in self.tree.get_children():
        return

    if not notify:
        self._suppress_selection_callback = True
        try:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        finally:
            self.after_idle(self._clear_selection_suppression)
    else:
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)
```

这样即使 `selection_set()` 没有触发 `<<TreeviewSelect>>`，抑制标志也会在空闲时自动清除。

---

## 10. 建议增加临时开关快速定位

为了确认是不是画布问题，可以临时在 `select_image()` 中注释掉：

```python
self.canvas_view.set_image_item(image)
```

如果注释后导入图片不再未响应，则可以确认问题在 `canvas.py` 的渲染链路。

也可以临时改成：

```python
self.status_var.set("图片已加载，但暂不渲染画布。")
```

然后观察图片列表是否正常出现。

---

## 11. 推荐最终修复顺序

### P0：先加日志

先加 `_load_paths()` 和 `select_image()` 的分段日志，确认卡死点。

### P1：修 `canvas.py`

必须完成：

1. 预览缓存；
2. `LANCZOS` 改为 `BILINEAR`；
3. 切换图片时清空缓存；
4. 避免重复 resize。

### P2：延迟渲染

把导入后的 `select_image()` 放进 `after(10, ...)`。

### P3：修 `image_list.py`

优化 `notify=False` 的选择抑制逻辑。

### P4：大图保护

后续增加图片尺寸提示：

- 如果图片超过 6000×6000，弹窗提示可能较慢；
- 如果图片超过某个像素总数，比如 50MP，询问是否继续；
- 画布只使用预览图，导出仍使用原图。

---

## 12. 推荐验收标准

修复后应满足：

1. 导入 `111.png` 后窗口不再未响应；
2. 图片能显示到画布；
3. `import_debug.log` 能记录到 `select_image done`；
4. 反复导入不同图片不会卡死；
5. 改变窗口大小不会明显卡顿；
6. 切换图片时不会持续占用 CPU；
7. 后续绘制矩形、椭圆、自由曲线时不会因为反复 resize 卡顿。

---

## 13. 最终判断

当前问题不是“安装包问题”，也不是“Pillow 无法读图”。

更准确的判断是：

> 图片已经成功读取，程序卡在导入后的主线程 UI 渲染阶段，最可能是 `canvas.redraw()` 中同步大图 resize 和 `ImageTk.PhotoImage` 创建导致 Tkinter 主线程阻塞。

因此现在应优先修复：

1. `canvas.py` 预览缓存；
2. 降低预览缩放质量；
3. 导入后延迟渲染；
4. 增加阶段日志；
5. 优化图片列表选择事件。
