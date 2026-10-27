# shuohao-skills 分镜工艺参考（vendor）

出处：[eternityspring/shuohao-skills](https://github.com/eternityspring/shuohao-skills)（Apache-2.0），vendor 自 `skills/novel-storyboard/references/`。这些文档描述一套**独立的分镜工作流**（段 → 切 → 分镜图，JSON 产出、Node.js 质量门），ArcReel **不执行它的脚本、不采用它的 JSON 结构**——在这里它们只作为写作方法论参考。

## 什么时候读

- 用户请你打磨、审阅某条分镜的 `image_prompt` / `video_prompt`（patch_episode_script 之前）
- 用户问视频提示词该怎么写、为什么成片动作不对 / 台词被吞 / 运镜乱叠
- 解释 H3 端点的原生提示词结构（ArcReel 的 `lib/prompts/h3_prompt.py` 在生成端已实现同一套投影，这里是对应的手写方法论）

## 三份文档的分工

| 文档 | 内容 | 在 ArcReel 的对应物 |
|---|---|---|
| [shot-writing.md](shot-writing.md) | 协议无关的镜头正文写法：一切一个运镜、动作要做得完、台词逐字、声音三层、构图量化 | `partials/shared/action_writing_guide.md`、`ambiance_audio_writing_guide.md`（生成端已内化核心规则） |
| [frame.md](frame.md) | 分镜图提示词与参考图挂载合同：挂图按「画面里有什么」、位置状态必须写明 | `partials/shared/image_prompt_writing_guide.md`、`templates/storyboard/image.md` 的 Reference_Images 段 |
| [h3-prompt.md](h3-prompt.md) | MiniMax H3 官方提示词语法：对齐指令、`<d>` 台词块、声景/配乐分层、禁角色名 | `lib/prompts/h3_prompt.py`（执行期投影） |

## 边界

- ArcReel 的分镜粒度是「一次生成一个 segment/scene」（image_prompt + video_prompt 成对），没有 shuohao 的「切（cut）」概念；文档里关于切点时刻、[Shot k] 逐字对账的规则在 ArcReel 里由 `h3_prompt.py` 的投影逻辑承接，不要让用户手写。
- 写作冲突时以 ArcReel 自己的模板规范为准（`partials/shared/*`），shuohao 文档只补充它们没讲的工艺细节（挂图合同、验收口径、通用身份 vs 直呼其名的两侧差异）。
