# frame_render — 渲染层

| 文件 | 作用 |
|---|---|
| `pipeline.py` | 渲染编排（光线追踪版） |
| `compose.py` | 主合成 + 相机效果 |
| `patch.py` | 光斑 mask 渲染（15 层） |
| `material.py` | PBR 五通道材质提取 |
| `retinex.py` | Retinex 分解 + 材质分析 |
| `text.py` | 文字渲染（Pillow FreeType） |
| `utils.py` | 公共工具 |

只依赖 `config` 与 `frame_light` 的数据结构，不反向依赖交互层。
