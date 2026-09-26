#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 `docs/参数总表.md`（从注册表，单一事实源）。

用法：
    python tools/gen_params_doc.py            # 写入 docs/参数总表.md
    python tools/gen_params_doc.py --check    # 只校验是否与磁盘一致
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ownrender.core import params as PR       # noqa: E402

KIND_LABEL = {"physical": "物理常数", "derived": "推导量", "tunable": "工程/数值"}


def render_md() -> str:
    L = []
    p = L.append
    counts = PR.aspect_counts()
    total = sum(counts.values())
    tun = [k for k, v in PR.all_params().items() if v.kind == "tunable"]
    p("# 参数总表（自动生成 —— 勿手改）")
    p("")
    p("> 来源：`ownrender/core/params.py`（单一事实源）。")
    p("> 重新生成：`python tools/gen_params_doc.py`；一致性由 CI/自测守门。")
    p("")
    p("- 方面数：**%d**" % len(counts))
    p("- 参数总数：**%d**" % total)
    p("- 每方面 ≥15：**%s**" % ("✅ 全部满足" if all(
        v >= 15 for v in counts.values()) else "❌ 有不足"))
    p("- 工程/数值参数（`tunable`）共 **%d** 个：%s"
      % (len(tun), ", ".join("`%s`" % t for t in tun)))
    p("- 其余全部是**物理常数**或**由物理量推导**；禁止「天气→亮度」式风格表。")
    p("")
    p("## 方面概览")
    p("")
    p("| 方面 | 参数数 | 说明 |")
    p("|---|---|---|")
    for k, v in counts.items():
        p("| `%s` | %d | %s |" % (k, v, READS.get(k, "")))
    p("")
    for aspect, lst in PR.ASPECTS.items():
        p("## %s（%d 个）" % (aspect, len(lst)))
        p("")
        p("| 键 | 单位 | 默认 | 范围 | 类型 | 出处 |")
        p("|---|---|---|---|---|---|")
        for q in lst:
            rng = "[%g, %g]" % (q.lo, q.hi)
            p("| `%s` | %s | %g | %s | %s | %s |"
              % (q.key, q.unit, q.default, rng,
                 KIND_LABEL.get(q.kind, q.kind), q.src))
        p("")
    return "\n".join(L) + "\n"


READS = {
    "sun": "面光源：视直径→半影、临边昏暗、分波长透过",
    "sky": "穹顶光源：CIE 分布 + 等立体角离散 + 与漫射照度能量一致",
    "cloud": "覆盖加权直射透过 + 云修正因子 + 阵雨时变",
    "atmos": "Rayleigh/Mie/臭氧/水汽/折射/色散",
    "precip": "水膜、雪态、雨幕、风斜",
    "geo": "太阳角度、角速度、日轨、昼长",
    "room": "6 面 + 开口几何（真实尺寸）",
    "material": "PBR 材质（反照率/粗糙度/折射率/次表面）",
    "mirror": "镜面专用（含「禁 6 面全镜面」）",
    "ground": "地面反照率与回照（雪/湿/干）",
    "night": "月亮/星空/城市光害",
    "transport": "直接光 + 天空积分 + 互反射（辐射度）",
    "camera": "虚拟相机：曝光/白平衡/光学缺陷",
    "defect": "裂缝/污渍自动检测与光渗",
    "ink": "叠字：年代感、墨水浓度、颜料",
    "color": "色彩管线与输出",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "参数总表.md"))
    a = ap.parse_args()

    md = render_md()
    out = Path(a.out)
    if a.check:
        ok = out.is_file() and out.read_text(encoding="utf-8") == md
        print("参数总表：%s" % ("一致 ✅" if ok else "不一致 ❌（请重新生成）"))
        print("方面 %d / 参数 %d" % (len(PR.aspect_counts()),
                                    sum(PR.aspect_counts().values())))
        return 0 if ok else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print("已写出 %s（%d 字节）" % (out, len(md.encode())))
    print("方面 %d / 参数 %d" % (len(PR.aspect_counts()),
                                sum(PR.aspect_counts().values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())