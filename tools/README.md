# tools — 构建与辅助脚本

| 文件 | 作用 |
|---|---|
| `build_nuitka.py` | Nuitka 打包驱动（CI / 本地通用），产物落 `dist/` |
| `create_structure.py` | 生成项目空白骨架 |

```bash
python tools/build_nuitka.py --name OwnRender-linux-x86_64 --onefile
```
