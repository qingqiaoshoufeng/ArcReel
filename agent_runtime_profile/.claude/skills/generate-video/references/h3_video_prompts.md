# H3 视频提示词写作指南

面向 MiniMax H3 视频端点的 `video_prompt` 写作规则。ArcReel 在请求构造时由
`lib/prompts/h3_prompt.py` 把这里产出的 YAML 投影成 H3 原生三段式
（`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`）+
关键帧对齐指令行。投影只识别 YAML 结构；自由散文式 prompt **不会被投影**，直通模型，
原生三段式不生效，质量显著下降。

> 写作原则沿用 MiniMax 官方 `h3-prompt-writing` skill 的 `references/base-en.txt`，
> 本指南只补充 ArcReel 投影逻辑强约束的部分。

## 1. 必须产出 YAML 结构

LLM 产出的 `video_prompt` 必须是 YAML，键序固定：

```yaml
Voice_Profiles:                # 有对白才出现；每个说话人一行
  - Speaker: 徐凤年
    Voice_Style: 清朗少年音
Action: |                       # 主体描述，按镜头分段
  [Shot 1] ...
Camera_Motion: Push In          # 必须在词表内（见 §3）
Ambiance_Audio: |               # 环境声/动作声/非语言人声，1-4 句
  ...
Dialogue:                       # 有对白才出现
  - Speaker: 徐凤年
    Line: ...
```

任一字段缺失或写成散文，`h3_prompt.py` 的 `_parse_structured_body` 返回 `None`，
正文原样透传给 H3 模型，三段式投影失效。

## 2. Action：动作 / 画面主体

按镜头分段，每镜一段。每镜按下列七维度展开，**逐项可见可听**，不要写成剧情梗概：

1. **构图**：镜头类型（medium-wide shot / close-up / extreme close-up）
2. **主体外观与位置**：角色登记名、年龄感、发型、服饰色、签名道具、当前站位
3. **环境与光照**：场景、关键道具、光源（侧逆光 / 霓虹绿 / 漫散射）
4. **动作与状态变化**：具体动作动词（攥紧 / 踉跄后退 / 抬眼望向），不要 "interacts with"
5. **摄影机运动**：写进 `Camera_Motion` 字段；如要在 Action 里点明运镜目的，用
   "The camera pushes in toward the folded letter in her hands." 这类自然句
6. **当前声音**：画内声（对白、歌词、画内乐器、画内收音机）写在 Action 里
7. **引用内容出现点**：参考图、参考视频在镜中首次出现的位置（参见生成端 Reference_Images 行）

### 2.1 镜头编号与切换

- `[Shot 1]` 无时间戳，是开场
- 后续镜用 `[Shot N] At 00:03.500, the camera cuts to ...`，cut 时间在视频时长内严格递增
- 普通切换用 `the camera cuts to` / `the shot cuts to` / `the shot transitions to`
- `cross-dissolve` / `fade` / `wipe` 仅在用户显式要求时使用

### 2.2 禁用抽象词

H3 文本编码器对抽象形容词响应弱。**禁止**：`cinematic`、`beautiful`、`stunning`、
`gorgeous`、`epic`、`atmospheric`、`breathtaking`。

改写示例：

- ❌ `A cinematic beautiful sunset over a stunning city.`
- ✅ `A wide shot frames a low sun casting long shadows across slate rooftops; the western sky holds saturated orange above indigo bands. Sunlight catches the dust on the rooftop railings.`

### 2.3 时长对齐

描述时长须铺满编排秒数：

- 4 秒镜不要写 30 秒动作链
- 多镜切换时所有 cut 时间相加 ≤ 视频总时长
- `h3_prompt.py` 会自动追加 `The shot lasts {duration:.2f} seconds in total.` 声明句，
  不要在 Action 里再写"持续 X 秒"

### 2.4 关键帧衔接（I2VA，分镜图生视频的核心模式）

分镜图在 H3 I2VA 模式下是 [Shot 1] 的 0.00 秒首帧。Action 必须遵循：

**首帧锚定 → 动作起始 → 连续发展 → 结果或反应**

- 首句先建立分镜图已有的风格、主体、构图、场景锚定
- 再写从首帧向前的动作路径
- 角色身份、服饰、颜色、关键道具、空间关系保持一致

参考结构（来自 base-en.txt §3.1）：

```
[Shot 1] <风格>, <镜头类型>, 分镜图中的<主体>保持<外观/服饰/站位/场景布局>。
<动作起始>。<连续发展>。<结果或反应>。镜头<运镜>。
```

### 2.5 屏内文字

画面里可见的招牌、字幕、霓虹文字用英文双引号包裹原文，不翻译：

```
A red neon sign reading "营业中" glows above the doorway.
```

## 3. Camera_Motion：镜头运动

必须在 [h3_prompt.py `_CAMERA_SENTENCES`](../../../../../lib/prompts/h3_prompt.py) 词表内，
否则投影写不出官方句式，模型收到的运镜描述失真：

| 值 | 投影为 |
|---|---|
| `Static` | The camera holds a static shot. |
| `Pan Left` / `Pan Right` | The camera pans left / right. |
| `Tilt Up` / `Tilt Down` | The camera tilts up / down. |
| `Zoom In` / `Zoom Out` | The camera zooms in / out. |
| `Push In` / `Pull Out` | The camera pushes in / pulls out. |
| `Truck Left` / `Truck Right` | The camera trucks left / right. |
| `Pedestal Up` / `Pedestal Down` | The camera pedestals up / down. |
| `Orbit` | The camera moves in an arc shot around the subject. |
| `Tracking Shot` | The camera tracks the moving subject. |
| `Shake` | The camera shakes slightly. |

- 无运镜时填 `Static`，不要留空
- 幅度与速度（base-en.txt §4.3 的 `with small amplitude at slow speed`）写进 Action
  自然句里，不要塞进 `Camera_Motion` 字段

## 4. Ambiance_Audio：环境声 / 动作声 / 非语言人声

1-4 句英文，连续段落，覆盖三类：

- **环境声**：风声、雨声、交通声、机器轰鸣
- **物理动作声**：脚步声、布料摩擦声、撞击声、纸张翻动声
- **非语言人声**：呼吸、笑声、喘息、叹息

**对白、歌词、画内音乐归入 Action**，不在 Ambiance_Audio 重复。

完全静音时写 `N/A`（仅当用户明确要求全片静默）。

```
Ambiance_Audio: |
  Steady rain taps against the café windows while low room ambience continues
  underneath. The entrance bell rings once, followed by wet footsteps and the
  soft scrape of a chair.
```

## 5. Dialogue：对白

每行 `Speaker` + `Line`：

- `Speaker` 用角色登记名（与剧本 `characters_in_scene` 等字段一致），
  `h3_prompt.py` 按首次出现顺序分配 `(S1)` `(S2)` 稳定 ID
- `Line` **逐字保留台词原文**，不要翻译、改写或增删标点
- 画外音：Action 里写 `says in an off-screen voiceover`，对白仍走 Dialogue
- 台词跨镜：在 Action 里加 `<scenetrans>` 标注衔接点；台词被视频末尾截断用 `<cutoff>`

```
Dialogue:
  - Speaker: 徐凤年
    Line: 我下站就下车。
  - Speaker: 路人甲
    Line: 等等我！
```

## 6. Voice_Profiles：音色声明

每个说话角色一行 `Speaker` + `Voice_Style`：

- `Voice_Style` 给出音色线索（清朗少年音 / 低沉男声 / 沙哑老妇 / 紧绷的女声）
- 仅在有对白的镜出现
- 不在 Action / Ambiance_Audio 里重复音色描述

```
Voice_Profiles:
  - Speaker: 徐凤年
    Voice_Style: 清朗少年音
  - Speaker: 路人甲
    Voice_Style: 喘息的少年声
```

## 7. 不要写的内容

- **视频时长**（如 "8 秒"）——`h3_prompt.py` 自动追加时长声明句
- **宽高比**（如 "16:9"、"9:16"）——API 参数设置，不进 prompt
- **BGM 描述**——ArcReel 视频排除项禁 BGM，`non_diegetic_music` 恒为 `N/A`，
  不要在 Action / Ambiance_Audio 里写背景乐
- **字幕 / 水印禁止项**——生成端在 prompt 末尾自动追加，不要重复
- **否定句式**——不要写 "no walls"、"without text"，直接列出要保留的内容

## 8. 完整示例（I2VA 分镜图生视频，4 秒）

分镜图：少年立于雨后青石巷口，手持折纸船。

```yaml
Voice_Profiles:
  - Speaker: 少年
    Voice_Style: 清朗少年音
Action: |
  [Shot 1] Stylized 3D cartoon render, medium-wide shot. The boy shown in the
  reference image retains his bowl-cut hair, slate-blue raincoat, and stance at
  the rain-soaked bluestone alley mouth. He crouches and places the folded paper
  boat into a shallow puddle; the boat drifts forward along the current. The boy
  straightens and lifts his gaze toward the far end of the alley as the camera
  trucks right with small amplitude at slow speed, following the drifting boat.
  Rain drips from the eaves; the boy (S1) says: "走吧，去看看它要漂到哪去。"
Camera_Motion: Truck Right
Ambiance_Audio: |
  Rain drips in scattered taps from tile eaves onto the puddle, accompanied by
  the soft splash of the paper boat's hull and the boy's quiet breathing.
Dialogue:
  - Speaker: 少年
    Line: 走吧，去看看它要漂到哪去。
```

投影后 H3 模型收到：

```
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Stylized 3D cartoon render, medium-wide shot. The boy shown in the reference image retains his bowl-cut hair, slate-blue raincoat, and stance at the rain-soaked bluestone alley mouth. He crouches and places the folded paper boat into a shallow puddle; the boat drifts forward along the current. The boy straightens and lifts his gaze toward the far end of the alley as the camera trucks right with small amplitude at slow speed, following the drifting boat. Rain drips from the eaves; the boy (S1) says: <d>[Chinese] 走吧，去看看它要漂到哪去。</d> The shot lasts 4.00 seconds in total.

overall_soundscape: Rain drips in scattered taps from tile eaves onto the puddle, accompanied by the soft splash of the paper boat's hull and the boy's quiet breathing.

non_diegetic_music: N/A
```

## 9. 自检清单

- [ ] `video_prompt` 是 YAML，含 `Action` 键
- [ ] `Camera_Motion` 在词表内
- [ ] 无 `cinematic` / `beautiful` / `stunning` 等抽象词
- [ ] 描述时长与编排秒数匹配
- [ ] 分镜图生视频首句锚定分镜图主体外观与场景
- [ ] 对白逐字保留原文，Speaker 用登记名
- [ ] 无时长数字、无宽高比、无 BGM 描述、无字幕/水印禁止项
