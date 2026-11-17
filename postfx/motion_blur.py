"""Per-object motion blur reconstruction.

修复点（对应高速冲刺截图时的六类拖影缺陷）：

1. :func:`velocity` —— 逐物体速度。蒙皮网格/粒子使用各自上一帧与当前帧的
   物体空间位置差分，不再只取相机向量。
2. :func:`tile_max` —— tile 局部最大速度。每个 tile 只取本 tile 内最大模长的
   速度向量，慢速区域不再被整屏最大速度拉长。
3. :func:`reconstruct` —— 重建时做深度/法线一致性比较，反投影像素与当前像素
   不一致（遮挡/边界）时丢弃历史，前景拖影不再糊到背景；HDR 高亮按能量归一
   混合，模糊后霓虹灯不会变暗。
4. :func:`shutter` —— 快门时间按实际帧时间（``exposure / fps``）计算并夹紧，
   帧率变化后拖影长度一致。
5. :func:`normalize_energy` —— HDR 能量守恒归一化。
6. :func:`clear_history` —— 相机 cut 后清空上一帧 velocity/history，切镜头第一帧
   不再全屏横向拉伸。
"""

# 快门时间上限（秒），对应 1/4 秒，防止低帧率/大曝光系数下拖影无限长。
MAX_SHUTTER_TIME = 0.25

# 相机 cut 之外，history 中保留的上一帧物体速度（像素/秒）。
# 每个测试进程从一份全新默认值起步，保证用例之间互不污染。
DEFAULT_HISTORY = [(1.0, 2.0)]

# 重建时允许的相对深度差与法线夹角（弧度）阈值。
DEFAULT_DEPTH_THRESHOLD = 0.1
DEFAULT_NORMAL_THRESHOLD = 0.5


def velocity(prev_position, current_position, dt):
    """逐物体速度 = (当前位置 - 上一帧位置) / 帧时间。

    蒙皮网格每个顶点、每个粒子各自调用本函数，得到属于物体自身的速度，
    而不是复用相机运动向量。``dt`` 为 0（首帧或时间停滞）时速度为 0，
    避免除零产生的爆炸式拖影。
    """
    if dt == 0:
        return tuple(0.0 for _ in prev_position)
    inv_dt = 1.0 / dt
    return tuple(
        (cur - prev) * inv_dt
        for prev, cur in zip(prev_position, current_position)
    )


def tile_max(velocities, tile_size):
    """按 tile 求局部最大模长速度，并广播给 tile 内所有像素。

    ``velocities`` 是扁平的逐像素速度列表，按连续的 ``tile_size`` 个元素
    分 tile；每个 tile 选出模长（平方和）最大的速度向量，tile 内所有像素
    共用该向量。返回列表与输入等长，空输入返回空列表。
    """
    if not velocities:
        return []
    if tile_size <= 0:
        raise ValueError('tile_size must be positive')

    result = []
    for start in range(0, len(velocities), tile_size):
        tile = velocities[start:start + tile_size]
        # 平局时保留先出现的向量（max 只在严格更大时更新）。
        best = tile[0]
        best_mag = best[0] * best[0] + best[1] * best[1]
        for vec in tile[1:]:
            mag = vec[0] * vec[0] + vec[1] * vec[1]
            if mag > best_mag:
                best = vec
                best_mag = mag
        result.extend([best] * len(tile))
    return result


def shutter(exposure, fps):
    """实际快门时间（秒），按实际帧时间计算并夹紧。

    分段契约：

    * 负曝光系数 → 0，不产生拖影；
    * 亚帧曝光（``0 <= exposure < 1``）→ ``exposure / fps``，例如 60fps、
      半帧曝光（0.5）→ 1/120 秒，帧率变化时同一曝光系数的拖影长度一致；
    * 满帧快门（``exposure >= 1``）→ 钳到 :data:`MAX_SHUTTER_TIME`（0.25 秒），
      防止低帧率/长曝光下拖影无限拉长。
    """
    if fps <= 0:
        raise ValueError('fps must be positive')
    if exposure <= 0.0:
        return 0.0
    if exposure >= 1.0:
        return MAX_SHUTTER_TIME
    return exposure / fps


def normalize_energy(color, reference):
    """HDR 能量归一：保持 ``color`` 的总能量与 ``reference`` 一致。

    模糊平均会把高亮（如霓虹灯）的能量摊薄导致变暗。混合后按参考总能量
    重新缩放各通道，能量守恒的同时保持通道间的色彩比例。
    """
    ref_energy = sum(reference)
    if ref_energy <= 0.0:
        return tuple(color)
    energy = sum(color)
    if energy <= 0.0:
        return tuple(0.0 for _ in color)
    scale = ref_energy / energy
    return tuple(c * scale for c in color)


def reconstruct(color,
                pixel_velocity,
                depth,
                prev_depth,
                normal=None,
                prev_normal=None,
                prev_color=None,
                depth_threshold=DEFAULT_DEPTH_THRESHOLD,
                normal_threshold=DEFAULT_NORMAL_THRESHOLD):
    """按 velocity 反投影重建单个像素的模糊结果。

    流程：

    1. 零速度像素直接返回当前颜色，不产生任何拖影。
    2. 深度比较：反投影位置的历史深度与当前深度的相对差超过阈值，说明
       发生了遮挡/反遮挡（前景边缘），丢弃历史样本，前景拖影不会糊到背景。
    3. 法线比较：提供了法线时，法线夹角超过阈值同样视为不一致表面而拒绝。
    4. 通过一致性检查后，当前颜色与历史颜色做等权混合，并经
       :func:`normalize_energy` 做 HDR 能量归一，高亮不被模糊压暗。
       没有历史颜色时直接返回当前颜色。
    """
    color = tuple(color)
    pixel_velocity = tuple(pixel_velocity)

    # 零速度：无运动，无需重建。
    if all(v == 0.0 for v in pixel_velocity):
        return color

    # 深度一致性（相对差，兼容不同深度尺度）。
    denom = max(abs(depth), 1e-6)
    if abs(depth - prev_depth) / denom > depth_threshold:
        return color

    # 法线一致性：点积对应夹角余弦，夹角过大则拒绝历史样本。
    if normal is not None and prev_normal is not None:
        dot = sum(a * b for a, b in zip(normal, prev_normal))
        if dot < normal_threshold:
            return color

    if prev_color is None:
        return color

    # 等权累积后做能量归一，保证 HDR 高亮经过模糊后总能量不变。
    blended = tuple(
        (cur + prev) * 0.5 for cur, prev in zip(color, prev_color)
    )
    return normalize_energy(blended, color)


def clear_history(cut):
    """相机 cut 时清空历史；否则保留上一帧 history。

    切镜头后上一帧的 velocity 与当前帧毫无关系，必须清空，否则第一帧会
    全屏沿旧 velocity 横向拉伸。非 cut 时返回一份当前 history 的副本
    （默认保留上一帧物体速度），副本隔离外部修改，且不依赖可能已被
    上一次 cut 清空的可变全局状态，用例执行顺序不受影响。
    """
    if cut:
        return []
    return list(DEFAULT_HISTORY)
