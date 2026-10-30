# H3 视频提示词写作指南

面向 MiniMax H3 视频端点。`lib/prompts/h3_prompt.py` 在最终请求构造时，将视频 YAML 或参考生视频机器文本投影成六字段。非 H3 输入模型保持原有结构，自由文本原样透传。

## 1. 最终六字段

按以下顺序组织 H3 原生提示词，关键帧对齐指令可以放在字段之前：

| 字段 | 内容与来源 |
|---|---|
| `subject_definitions` | 有可靠参考绑定的主体定义，格式为 `<Subject N> is {现有主体标签} from <Picture N>.`。不得虚构身份、服饰、颜色等外观信息。无可靠主体来源时写 `N/A`。 |
| `summary` | 基于已有动作或正文概述，不补写情节；机械投影可直接复用已有正文。 |
| `retention_analysis` | 按 `<Subject N>` 汇总正文显式引用到的 `[Shot N]`，使用 `appears in` 列出镜头，以 `fully_preserved - {主体标签} from <Picture N>, {从已有画面资料复述的外观}, retained as {角色或形态描述}.` 表达生成约束；外观只复述参考图或正文已有的身份、服饰与角色信息，不编造未提供的细节。没有可靠信息时写 `N/A`。 |
| `detailed_description` | 完整镜头描述、动作、运镜、对白、时间戳及音色。 |
| `overall_soundscape` | 已有环境声、动作声、非语言人声；缺省 `N/A`。 |
| `non_diegetic_music` | 默认 `N/A`；用户明确要求配乐时可写其音乐意图。不得自行添加配乐。 |

完整六字段输入原样透传。旧三字段输入会将 `integrated_multimodal_description` 迁移到 `detailed_description`，保留已有声音、音乐和关键帧对齐说明。仅在自由文本中提到字段名称不会触发迁移。

首帧、尾帧均是完整画面，不能因为存在 `<Picture 1>` 就将它解释为单一角色。分镜图生视频没有独立主体绑定时，`subject_definitions` 和 `retention_analysis` 可以为 `N/A`，关键帧对齐说明仍保留。

## 2. 视频 YAML 输入

继续使用已有输入字段，非 H3 数据模型不增加六字段：

```yaml
Voice_Profiles:
  - Speaker: 徐凤年
    Voice_Style: 清朗少年音
Action: |
  [Shot 1] 中景。徐凤年立在巷口，向前迈步。
  [Shot 2] At 00:03.500, the camera cuts to 手中折纸船的特写。
Camera_Motion: Push In
Ambiance_Audio: |
  雨滴敲打瓦檐，脚步踏过积水。
Dialogue:
  - Speaker: 徐凤年
    Line: 走吧，去看看它要漂到哪去。
```

投影识别含非空 `Action` 的 YAML 映射。对白和音色字段可省略；缺少 `Action` 或无法解析为该结构时原样透传。分镜图生成的 `@[资产]` 绑定标记不进入 H3 提示词：投影把 `@[X]` 剥成普通名字 `X`，视频 YAML 里直接写普通名字。

Action 每镜一段，写清构图、已有主体外观和位置、环境光照、动作变化、声音出现点及参考内容。外观只能来自已有资料或画面信息，不能为补齐字段而编造。

- 保留已有 `[Shot N]` 分段及时间戳，不重复添加 `[Shot 1]`。
- 后续镜可用 `[Shot N] At 00:03.500, the camera cuts to ...`，切换时间递增且不超过总时长。
- 普通切换使用 `cuts to` 或 `transitions to`；淡入淡出、叠化等只在用户要求时使用。
- 动作规模与时长匹配。投影自动追加时长声明，不必重复。
- 使用具体可见、可听的动作与细节，避免 `cinematic`、`beautiful`、`stunning` 等抽象形容词。
- 屏内文字用英文双引号包裹原文，不翻译。

### 2.1 首尾帧与角色图并存（混合）

端点的参考图槽序为「首帧、尾帧、角色图」时（如文武双全 Ref2VA：槽 0=首帧、槽 1=尾帧、
槽 2-8=角色设定图），分镜正文前置角色绑定行 `<老黄>@图片1、<徐凤年>@图片2。`。绑定行由
渲染层按分镜 `characters_in_scene` 序机械拼装，图号是逻辑号（从 1 起）；混合投影按本次
请求携带的关键帧数把绑定号前移（首帧占 Picture 1、尾帧占 Picture 2、角色从 Picture 3
起），正文 `<名字>` 标记替换为 `<Subject N>`，对白 Speaker 同编号，retention 按镜汇总，
关键帧对齐说明锚 Picture 1/2。角色一致性由参考图本体保证，正文不复述外观也不虚构。
没有参考图槽的端点剥除绑定行与 `<名字>` 标记，退化为普通首尾帧投影。

## 3. 参考生视频主体与多形态

参考渲染器提供 `<名字>@图片N` 绑定。图号来自随请求发送的参考图顺序，投影不重新编号：

```text
<徐凤年>@图片1、<徐凤年/劲装>@图片2。
<徐凤年>与<徐凤年/劲装>是同一角色的不同形态，各自按对应参考图呈现。
[Shot 1] <徐凤年>拔剑。
[Shot 2] At 00:03.500, <徐凤年/劲装>说 {走。}
```

对应六字段示意：

```text
subject_definitions: <Subject 1> is 徐凤年 from <Picture 1>.
<Subject 2> is 徐凤年/劲装 from <Picture 2>.
<Subject 1> and <Subject 2> show different appearances of the same character; each follows its own reference picture.

summary: [Shot 1] <Subject 1>拔剑。
[Shot 2] At 00:03.500, <Subject 2>（S1）说：<d>[Chinese] 走。</d>

retention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved - 徐凤年 from <Picture 1>, retained as shown in the reference picture.
<Subject 2> (appears in [Shot 2]): fully_preserved - 徐凤年/劲装 from <Picture 2>, retained as shown in the reference picture.

detailed_description: [Shot 1] <Subject 1>拔剑。
[Shot 2] At 00:03.500, <Subject 2>（S1）说：<d>[Chinese] 走。</d>

overall_soundscape: N/A

non_diegetic_music: N/A
```

定义、正文、对白、多形态声明及 retention 均使用 `<Subject N>`，图片引用使用 `<Picture N>`。多形态仍分别对应自己的参考图，并保留同角色声明。没有图像绑定的主体保留 `<名字>` 标签，不虚构编号。

retention 按主体汇总正文中的显式主体记号，镜头去重并按正文原顺序排列。例如，同一主体在两镜中被显式引用时写 `<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - 徐凤年 from <Picture 1>, retained as shown in the reference picture.`。`fully_preserved` 表达生成约束，不是已生成视频的核验结果。`appears in` 表示正文显式引用：画外音也可能显式引用主体，因此不要求主体可见出镜，保留要求也不要求画外主体出镜。外观描述复述参考图或正文已有的身份、服饰与角色信息，不编造未提供的细节。未在正文显式引用的主体不列入 retention；不根据全局绑定表、代词或猜测推断出镜，也不补写动作或身份。

## 4. 关键帧与分镜承接

分镜图生视频遵循“首帧锚定 → 动作起始 → 连续发展 → 结果或反应”。首句建立画面已有的构图、风格、人物与场景关系，再展开动作。

首帧对齐 0.00 秒，尾帧对齐本次请求的有效时长。首尾帧组合分别对齐两个时刻；这些对齐说明描述完整画面，不构成角色定义。

每镜 `ending_state` 记录结束位置、姿态、手持物、表情及环境状态。该字段保留在剧本 JSON，不进入 YAML。非首镜且无 `segment_break` 时，Action 起始状态承接上一镜末态；新场景可断开承接链。

## 5. 运镜

`Camera_Motion` 使用现有词表：

| 值 | 动作 |
|---|---|
| `Static` | 固定镜头 |
| `Pan Left` / `Pan Right` | 左右摇摄 |
| `Tilt Up` / `Tilt Down` | 上下俯仰 |
| `Zoom In` / `Zoom Out` | 变焦推近或拉远 |
| `Push In` / `Pull Out` | 推进或后拉 |
| `Truck Left` / `Truck Right` | 左右横移 |
| `Pedestal Up` / `Pedestal Down` | 升降 |
| `Orbit` | 环绕 |
| `Tracking Shot` | 跟拍 |
| `Shake` | 轻微晃动 |

无运镜时填 `Static`。幅度、速度和运镜目的写进 Action。词表外值会使用通用句式投影。

## 6. 声音、对白与音乐

`Ambiance_Audio` 用简洁段落描述环境声、物理动作声和非语言人声。对白、歌词及画内音乐的出现点写在 Action；不要在多个位置重复完整台词。

`Dialogue` 的 `Speaker` 使用角色登记名，`Line` 逐字保留原文、标点和语言。投影按首次发言顺序分配稳定的 `（S1）`、`（S2）`，中文对白包在 `<d>[Chinese] …</d>` 中。参考生视频的说话主体同时使用对应 Subject 编号。

`Voice_Profiles` 的 `Voice_Style` 保留音色、语速和情绪线索。参考文本中的声音特征也会保留；`@音频N` 绑定本身不下发，因为此 ComfyUI H3 端点没有音频输入。

画外音在 Action 中标明 `says in an off-screen voiceover`。台词跨镜可用 `<scenetrans>`，末尾截断可用 `<cutoff>`。

背景音乐默认 `N/A`。用户明确要求音乐时，可在完整原生六字段的 `non_diegetic_music` 中写明；投影保留已有原生或旧三字段中的音乐。不要为此给非 H3 输入模型添加字段。

## 7. 自检

- 最终 H3 结构包含六字段，缺少可靠来源的内容为 `N/A`。
- `<Subject N>` 编号与 `<Picture N>` 绑定一致，多形态与音色未丢失。
- retention 按主体列出正文显式引用的镜头和保留约束，`appears in` 不将画外音引用声称为可见出镜，外观只复述已有资料，不虚构或宣称已核验生成结果。
- 首尾帧作为完整画面对齐，不强行定义单一角色。
- Shot 分段、时间戳、台词和中文标签保留，无重复开场编号。
- 运镜、动作规模及切换时刻与视频时长匹配。
- 不重复写宽高比、字幕或水印禁止项；音乐仅来自用户明确意图。
