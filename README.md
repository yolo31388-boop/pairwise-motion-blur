# pairwise-motion-blur

高速冲刺截图时，角色边缘出现方向错误的拖影：per-object motion blur 只用了相机向量，蒙皮和粒子没有自己的 velocity；tile max 把整屏最大速度套到所有像素，慢速区域也被拉长；重建时没有做深度比较，前景拖影糊到背景；快门时间按固定 0.5 帧，帧率变化后拖影长度不一致；HDR 高亮经过模糊后能量不守恒，霓虹灯变暗；相机 cut 后上一帧 velocity 没清，切镜头第一帧全屏横向拉伸。postfx/motion_blur.py 是核心，tests/test_motion_blur.py 15个红。要修的是：逐物体 velocity；按 tile 局部最大速度；重建做深度/法线比较；快门按实际帧时间；HDR 能量归一；相机 cut 清 history。

## 运行

```bash
python -m pytest tests -q
```

初始状态：15 个用例失败。修复实现使全部用例通过，不要修改 `tests/` 下的测试。

语言/框架：Python 3, pytest；环境可复现等级：无外部依赖。
