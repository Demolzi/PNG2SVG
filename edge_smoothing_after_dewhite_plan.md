# 去白边后边缘不够平滑的修复方案

## 1. 问题判断

当前现象是：白边已经被去除，但目标边缘出现锯齿、毛糙、断裂或不自然的半透明边。

这说明当前算法已经解决了“背景残留”问题，但还缺少独立的 **alpha 边缘精修流程**。

需要注意：

- 去白边主要解决的是边缘颜色问题；
- 边缘平滑主要解决的是 mask 轮廓质量问题；
- 这两个问题不能只靠同一个步骤解决。

正确处理顺序应该是：

```text
粗 mask
→ 去小噪点
→ 形态学闭运算
→ 形态学开运算
→ 边缘轻微平滑
→ alpha 羽化
→ 去白边 / 去色溢出
→ 输出 RGBA
```

不建议先去白边再平滑。更合理的顺序是：**先优化 alpha mask，再处理边缘颜色。**

---

## 2. 目标

本次修复的目标是：

1. 减少导出图片边缘锯齿；
2. 减少边缘毛刺和小缺口；
3. 避免过度羽化导致边缘发虚；
4. 保留主体轮廓细节；
5. 去白边后边缘颜色更自然；
6. 不引入 AI 模型，继续使用 Pillow / OpenCV 可实现的传统图像处理方法。

---

## 3. 推荐处理流程

### 3.1 生成粗 mask

粗 mask 可以来自以下任意模式：

- 用户闭合区域 mask；
- 白底 / 浅色背景去除后的 foreground mask；
- Flood Fill 得到的前景 mask；
- GrabCut 得到的前景 mask。

粗 mask 通常会有以下问题：

- 边缘锯齿；
- 小孔洞；
- 小毛刺；
- 孤立噪点；
- 轮廓断裂。

所以不能直接把粗 mask 作为最终 alpha。

---

### 3.2 去除小噪点

在边缘平滑前，先做连通域过滤。

建议保留两个选项：

```text
去除小噪点：开启 / 关闭
最小噪点面积：默认 20 px²
```

可选增强：

```text
只保留最大连通域：开启 / 关闭
```

适用场景：

- 如果闭合区域内只有一个目标元素，可以开启“只保留最大连通域”；
- 如果闭合区域内本来有多个需要保留的零件，不要开启“只保留最大连通域”。

---

### 3.3 形态学闭运算

闭运算用于填补边缘的小裂缝、小孔洞。

逻辑：

```text
先膨胀，再腐蚀
```

Pillow 近似实现：

```python
from PIL import ImageFilter


def close_mask(mask, size=3):
    return mask.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))
```

建议参数：

| 图像类型 | size |
|---|---:|
| 小图标 / 线稿 | 3 |
| 普通产品图 | 3 |
| 边缘破碎明显的图片 | 5 |

第一版默认建议使用 `size=3`。

---

### 3.4 形态学开运算

开运算用于去除小毛刺、小突出点。

逻辑：

```text
先腐蚀，再膨胀
```

Pillow 近似实现：

```python
from PIL import ImageFilter


def open_mask(mask, size=3):
    return mask.filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))
```

建议默认：

```python
mask = close_mask(mask, 3)
mask = open_mask(mask, 3)
```

注意：

- 不建议默认用 `size=5` 或 `size=7`；
- 参数过大会吃掉细节；
- 对细线、尖角、齿轮、文字边缘尤其要谨慎。

---

### 3.5 GaussianBlur 生成柔和 alpha

形态学处理后，mask 轮廓会更整齐，但仍可能是硬边。需要用轻微模糊生成更自然的 alpha 过渡。

建议：

```python
mask = mask.filter(ImageFilter.GaussianBlur(radius=0.6))
```

参数建议：

| 图片类型 | blur radius |
|---|---:|
| 小图标 / 线稿 | 0.3 - 0.6 |
| 普通物体 | 0.6 - 1.2 |
| 边缘粗糙照片 | 1.0 - 1.5 |

不建议默认超过 `1.5`，否则边缘会明显发虚。

---

### 3.6 限制 alpha 不扩散到用户区域外

模糊后 alpha 可能扩散到用户闭合区域外，因此必须再和用户区域 mask 相交。

```python
from PIL import ImageChops

mask = ImageChops.multiply(mask, user_region_mask)
```

这样可以确保：

- 平滑后的边缘不会越过用户画的闭合区域；
- 导出的内容不会超出用户指定范围。

---

### 3.7 去白边 / 去色溢出

去白边应该放在 alpha mask 精修之后。

处理范围不应该是整个前景，而应该只处理半透明边缘区。

建议边缘区判断：

```text
20 < alpha < 250
```

只在这个范围内处理颜色。

不建议：

- 对 alpha = 255 的实心前景大面积改色；
- 对 alpha = 0 的透明背景处理；
- 过度向内腐蚀 2 到 3 px。

默认建议去白边内缩：

```text
1 px
```

只有白边特别明显时，再允许用户调到 2 px。

---

## 4. 推荐新增参数

建议在 UI 的导出设置中增加：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| 边缘平滑强度 | 2 | 控制形态学处理强度 |
| alpha 羽化半径 | 0.7 px | 控制边缘透明过渡 |
| 去白边强度 | 1 | 控制边缘颜色修正强度 |
| 去白边 alpha 下限 | 20 | 只处理半透明边缘 |
| 去白边 alpha 上限 | 250 | 避免影响纯前景 |

### 4.1 边缘平滑强度建议

| 平滑强度 | 处理方式 | 适用场景 |
|---|---|---|
| 0 | 不做形态学，只保留原 mask | 细节很多、怕损失轮廓 |
| 1 | close 3 + blur 0.4 | 轻微锯齿 |
| 2 | close 3 + open 3 + blur 0.7 | 默认推荐 |
| 3 | close 5 + open 3 + blur 1.0 | 边缘明显毛糙 |

---

## 5. 建议修改 `mask.py`

在 `combined_alpha` 生成后、`roi.putalpha(combined_alpha)` 之前，加入统一的 alpha 精修函数。

### 5.1 新增函数

```python
from PIL import ImageChops, ImageFilter


def refine_alpha_mask(
    mask,
    user_region_mask,
    smooth_level=2,
    feather_radius=0.7,
):
    mask = mask.convert("L")

    if smooth_level >= 1:
        # 闭运算：填补小孔洞、小裂缝
        mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))

    if smooth_level >= 2:
        # 开运算：去除小毛刺
        mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))

    if smooth_level >= 3:
        # 更强的闭运算，只建议在边缘很糙时使用
        mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))

    if feather_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=float(feather_radius)))

    # 防止模糊后的 alpha 扩散到用户闭合区域外
    mask = ImageChops.multiply(mask, user_region_mask)

    return mask
```

### 5.2 替换现有简单羽化逻辑

原逻辑可能类似：

```python
if options.feather_radius > 0:
    combined_alpha = combined_alpha.filter(
        ImageFilter.GaussianBlur(radius=float(options.feather_radius))
    )
    combined_alpha = ImageChops.multiply(combined_alpha, user_region_mask)
```

建议替换为：

```python
combined_alpha = refine_alpha_mask(
    combined_alpha,
    user_region_mask,
    smooth_level=options.edge_smooth_level,
    feather_radius=options.edge_feather_radius,
)
```

如果暂时不想改 `CutoutOptions`，可以先写死参数：

```python
combined_alpha = refine_alpha_mask(
    combined_alpha,
    user_region_mask,
    smooth_level=2,
    feather_radius=0.7,
)
```

---

## 6. 建议扩展 `CutoutOptions`

当前可以增加：

```python
@dataclass(frozen=True)
class CutoutOptions:
    feather_radius: float = 1.5
    white_threshold: int = 240
    near_white_tolerance: int = 15
    remove_small_components: bool = True
    min_component_area: int = 20
    keep_largest_component: bool = False

    edge_smooth_level: int = 2
    edge_feather_radius: float = 0.7
    decontaminate_edge: bool = True
    decontaminate_strength: int = 1
```

其中：

- `edge_smooth_level` 控制形态学平滑；
- `edge_feather_radius` 控制 alpha 过渡；
- `decontaminate_edge` 控制是否去白边；
- `decontaminate_strength` 控制去白边强度。

---

## 7. UI 修改建议

在右侧导出设置中增加：

```text
边缘平滑强度：0 / 1 / 2 / 3
边缘羽化半径：0.0 - 2.0
去白边：开启 / 关闭
去白边强度：0 / 1 / 2 / 3
```

默认值：

```text
边缘平滑强度：2
边缘羽化半径：0.7
去白边：开启
去白边强度：1
```

---

## 8. 验收标准

修复后应满足：

1. 白底背景仍然能透明；
2. 边缘锯齿明显减少；
3. 主体轮廓不明显变胖或变瘦；
4. 小孔洞、小毛刺明显减少；
5. 细节区域不会被大面积吃掉；
6. 边缘不会出现明显白边；
7. 边缘不会过度发虚；
8. 不会抠出用户闭合区域外的内容。

---

## 9. 推荐实施顺序

### 阶段 1：快速修复

实现：

- 增加 `refine_alpha_mask()`；
- 使用 `smooth_level=2`；
- 使用 `edge_feather_radius=0.7`；
- 保持去白边逻辑不变，但放到 alpha 精修之后。

目标：先让边缘不再明显毛糙。

---

### 阶段 2：参数化

实现：

- 扩展 `CutoutOptions`；
- UI 增加边缘平滑强度；
- UI 增加边缘羽化半径；
- UI 增加去白边强度。

目标：让不同图片可以调整不同参数。

---

### 阶段 3：边缘颜色精修

实现：

- 只处理 `20 < alpha < 250` 的边缘区；
- 减少白色污染；
- 避免改变主体实心区域颜色。

目标：让边缘颜色更自然。

---

## 10. 最终建议

当前问题不应该继续靠单纯加大羽化半径解决。

更推荐的方案是：

```text
先形态学修 mask 轮廓
→ 再轻微 GaussianBlur 做 alpha 过渡
→ 最后只在半透明边缘区做去白边
```

也就是：

```text
mask 边界平滑 + alpha 羽化 + 边缘颜色修正
```

三者分开处理，效果会比单纯“去白边”或单纯“模糊边缘”稳定得多。
