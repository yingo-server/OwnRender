# OwnRender（agnes-render）— 未脱敏全量版

本目录是**开发 / 生产全量版**：含运行期配置（`config/`）、产物（`output/`）、
构建工具（`tools/`）、CI（`.github/`）与完整文档（`docs/`）。

> 与"脱敏开源版"的区别：开源版不含 `config/*.json`（其中有 API token 等敏感项），
> 引擎代码与之一致。

## 快速开始

```bash
python main.py                  # 交互菜单
python main.py --list-backgrounds
python main.py --offline-bg 大理石 -t 红砖墙 --time 12:00 -y --no-color
python main.py --help
```

依赖：`python >= 3.9`、`numpy`、`pillow`（可选，文字叠字用）。

| 目录 | 作用 |
|---|---|
| `frame_interact/` | 交互层：TUI、菜单、CLI、向导、编排 |
| `frame_light/`    | 光照层：太阳位置、辐照度、天气、定位 |
| `frame_render/`   | 渲染层：几何、材质、叠字、导出 |
| `background/`     | 内置底图（12 张） |
| `fonts/`          | 字体 |
| `docs/`           | 文档（`docs/en/` 英文） |
| `tools/`          | 构建与辅助脚本 |
| `config/`         | 运行期配置（首次运行自动生成） |
| `output/`         | 渲染产物 |
