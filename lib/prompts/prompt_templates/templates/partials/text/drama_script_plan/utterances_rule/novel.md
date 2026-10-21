按口播出现顺序产出发声序列，台词（dialogue）的 speaker 必须出现在 characters_in_scene。叙述、心理独白等不靠画面演出的内容，可按剧情语境判断写为画外音（voiceover）。分镜无口播则留空。

**单一发声归属（硬约束）**：一个分镜的 utterances 只能全为 dialogue、全为 voiceover、或全为空——**禁止在同一分镜里混写 dialogue 与 voiceover**。混合发声会让视频模型把画外音演成角色台词或无主游声，与原生音轨混在一起无法分离，因此会被下游校验标 `needs_replan` 阻断生成。原文里同一时间既有角色台词又有旁白解说时，按发生先后拆成相邻的两个分镜：一个承载角色台词（dialogue），一个承载旁白（voiceover），各自选合适的 duration_seconds。