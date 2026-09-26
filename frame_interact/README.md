# frame_interact — 交互层

参数解析、菜单/向导、编排与展示。像素级渲染一律交给 `frame_render`。

| 文件 | 作用 |
|---|---|
| `runner.py` | 主编排：入口与模式分发 |
| `cli.py` | 命令行参数解析 |
| `wizard.py` | 参数向导（逐步问参） |
| `settings.py` | 设置中心 |
| `ai.py` | AI 模式编排 |
| `offline.py` | 离线底图 + 光照模式编排 |
| `tui.py` | 终端渲染工具箱（颜色 / 框线 / 表格） |
| `progress.py` | 进度显示 |
| `utils.py` | 公共工具 |
