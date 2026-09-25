# 素材来源与版权声明 / Credits & Third-Party Notices

> 本项目**代码与文档**采用 [OwnRender License v1.0](LICENSE)：非商业免费、
> 衍生必须开源、商业需另行联系授权。
> 本文件列出的是**第三方素材**（字体、底图），它们**不属于**上述协议覆盖范围，
> 各自版权归原作者所有。

---

## 1. 字体 / Fonts

位于 `fonts/` 目录。**全部来源于网络公开渠道，仅用于非商业学习与研究。**

| 文件 | 名称 | 来源 | 授权状态 |
|---|---|---|---|
| `AaXiuKai-2.ttf` | Aa 秀楷 | 网络搜集 | 非商业使用；版权归原字库厂商所有 |
| `QuanHengDuLiang-v0.1.ttf` | 全衡度量 | 网络搜集 | 非商业使用；版权归原作者所有 |
| `草檀斋毛泽东字体(8).ttf` | 草檀斋毛泽东字体 | 网络搜集 | 非商业使用；版权归原作者所有 |

**共同声明：**

- 上述字体**来源于网络**，本项目**未获得任何商业授权**。
- 仅限**个人学习、研究、非商业**用途使用。
- **商业使用请自行联系各字库的版权方**取得授权。
- 本项目**不主张**对以上字体的任何权利。
- **侵删**：如您是上述字体的版权所有者且不希望其在本仓库中出现，
  请提交 Issue 或联系作者，我们将在确认后**立即移除**。

> 若你要用于正式发布，强烈建议替换为授权明确的字体（如思源黑体 /
> Noto Sans CJK，SIL OFL 许可）。详见 `fonts/README.md`。

---

## 2. 底图 / Background textures

位于 `background/` 目录，共 16 张材质贴图。

- **生成方式**：由 AI 图像模型（Agnes Image）依提示词生成，
  生成参数与提示词记录在 `background/README.md`。
- **用途**：作为渲染管线的「平光材质底图」输入。
- **声明**：AI 生成内容的法律定性因司法辖区而异，本项目不对其可版权性
  或第三方权利作任何保证；如用于正式发布请自行评估。
- **侵删**：如其中任何一张与您的既有作品实质性相似，请联系我们移除。

---

## 3. 参考实现 / Reference

本项目早期版本（V21）的**单窗物理光照 + 离线叠字**思路作为算法演进的参考，
代码为完全重写；字体的年代感参数（噪声/扩散/氧化尺度）参考了该实现的经验值。

---

## 4. 联系方式 / Contact

- 商业授权、素材申诉：请通过仓库 **Issues** 联系作者。
- 素材侵权申诉，请在 Issue 标题注明 `[DMCA]` 或 `[素材申诉]`。

---

# English (summary)

- **Code & docs** are licensed under [OwnRender License v1.0](LICENSE):
  free for non-commercial use, derivatives **must** be open-sourced under the
  same license, commercial use requires separate authorization.
- **Fonts** in `fonts/` were **collected from the public internet** and are
  included **for non-commercial study only**. Copyright belongs to their
  original foundries. We claim no rights. Commercial use requires a license
  from the respective foundry. **We will remove any asset on request** —
  please open an Issue.
- **Background textures** were produced with an AI image model; prompts are
  documented in `background/README.md`.
