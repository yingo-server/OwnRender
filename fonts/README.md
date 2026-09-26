# 字体

`.ttf` / `.otf` / `.ttc` 放进本目录即被自动发现（支持中文文件名）。

```bash
python main.py --list-fonts
```

叠字依赖 Pillow；中文文件名在非 UTF-8 locale 下由 `config.ensure_utf8_stdio()`
自动还原转义，不会乱码。
