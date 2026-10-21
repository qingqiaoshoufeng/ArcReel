"""MiniMax H3 原生提示词投影。

H3 的文本编码器按官方 ``h3-prompt-writing`` skill 约定的结构消费提示词：关键帧对齐指令行
+ 三段核心字段（``integrated_multimodal_description`` / ``overall_soundscape`` /
``non_diegetic_music``）。ArcReel 的视频提示词正文是 :func:`lib.prompts.prompt_utils.video_prompt_to_yaml`
的 YAML 产物（Action / Camera_Motion / Ambiance_Audio / Dialogue），对 H3 端点在请求构造时
投影成原生结构；参考生视频的三段论机器文本（主体绑定 ``<X>@图片N`` / 单元正文 / 风格块，
见 ``lib.script.reference_video.prompt_render``）由 :func:`project_reference_prompt_to_h3`
投成同一套原生结构；两种都解析不出的自由文本原样透传。

关键帧对齐指令与 ``<Picture N>`` 标签沿用官方 ComfyUI 模板（``video_minimax_h3_r2v``）的
本地节点约定；镜头运动按官方词表写成自然英文句（"The camera pushes in."）；台词按说话人
首次出现顺序分配 ``（S1）`` 稳定 ID 并以 ``<d>[Chinese] …</d>`` 包裹。背景音乐恒为
``N/A``：ArcReel 的视频排除项禁 BGM，非画内音乐没有合法来源。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

#: workflow 里判定 H3 端点的节点类型前缀（MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo / …）。
_H3_CLASS_TYPE_PREFIX = "MiniMaxH3"

#: 正文已是 H3 结构时不再投影：用户手写或规划层直出的三段式原样提交。
_H3_BODY_MARKER = "integrated_multimodal_description"

#: ArcReel 的 camera_motion 枚举 → 官方词表的自然英文句（h3-prompt-writing §4.3）。
_CAMERA_SENTENCES: Mapping[str, str] = {
    "Static": "The camera holds a static shot.",
    "Pan Left": "The camera pans left.",
    "Pan Right": "The camera pans right.",
    "Tilt Up": "The camera tilts up.",
    "Tilt Down": "The camera tilts down.",
    "Zoom In": "The camera zooms in.",
    "Zoom Out": "The camera zooms out.",
    "Push In": "The camera pushes in.",
    "Pull Out": "The camera pulls out.",
    "Truck Left": "The camera trucks left.",
    "Truck Right": "The camera trucks right.",
    "Pedestal Up": "The camera pedestals up.",
    "Pedestal Down": "The camera pedestals down.",
    "Orbit": "The camera moves in an arc shot around the subject.",
    "Tracking Shot": "The camera tracks the moving subject.",
    "Shake": "The camera shakes slightly.",
}

#: 词表外运镜的兜底句式。
_UNKNOWN_CAMERA_SENTENCE = "The camera motion is {value}."


def _duration_sentence(duration_seconds: float) -> str:
    """时长声明句（官方 skill：描述须铺满视频时长，把时长写进文本给模型节奏锚点）。"""
    if duration_seconds <= 0:
        return ""
    return f"The shot lasts {duration_seconds:.2f} seconds in total."


def is_h3_video_workflow(workflow: Mapping[str, Any]) -> bool:
    """这份 workflow 是否为 MiniMax H3 端点的实发图：任一节点类型命中 H3 前缀即认。"""
    for node in workflow.values():
        if isinstance(node, Mapping) and str(node.get("class_type", "")).startswith(_H3_CLASS_TYPE_PREFIX):
            return True
    return False


def project_video_prompt_to_h3(
    body: str,
    *,
    has_start_image: bool,
    has_end_image: bool,
    duration_seconds: float,
) -> str:
    """把 ArcReel 视频提示词正文投影成 H3 原生结构；投影不动的情形原样返回。

    ``body`` 是最终文本：结构形态是 ``video_prompt_to_yaml`` 的 YAML 产物，文本形态是
    用户手写的自由 prose。只认结构形态——YAML 解析不出 ``Action`` 键、或正文已带 H3 三段
    字段时，这份正文按原样提交。``duration_seconds`` 是本次请求的有效时长（FL2VA 末帧
    对齐秒数按它写，格式化到两位小数）。
    """
    if _H3_BODY_MARKER in body:
        return body
    structured = _parse_structured_body(body)
    if structured is None:
        return body
    action = str(structured.get("Action", "") or "").strip()
    if not action:
        return body

    camera = str(structured.get("Camera_Motion", "") or "").strip()
    camera_sentence = _CAMERA_SENTENCES.get(camera, _UNKNOWN_CAMERA_SENTENCE.format(value=camera)) if camera else ""
    dialogue = _dialogue_sentences(structured)
    description = f"[Shot 1] {action}"
    if camera_sentence:
        description = f"{description} {camera_sentence}"
    if dialogue:
        description = f"{description} {dialogue}"
    duration_sentence = _duration_sentence(duration_seconds)
    if duration_sentence:
        description = f"{description} {duration_sentence}"

    soundscape = str(structured.get("Ambiance_Audio", "") or "").strip() or "N/A"
    instruction = _keyframe_instruction(
        has_start_image=has_start_image, has_end_image=has_end_image, duration_seconds=duration_seconds
    )
    sections = [f"{_H3_BODY_MARKER}: {description}", f"overall_soundscape: {soundscape}", "non_diegetic_music: N/A"]
    if instruction is not None:
        sections.insert(0, instruction)
    return "\n\n".join(sections)


def _parse_structured_body(body: str) -> Mapping[str, Any] | None:
    """把正文当 YAML 解析；不是映射、缺 ``Action`` 键即判非结构形态。"""
    try:
        parsed = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, Mapping) or "Action" not in parsed:
        return None
    return parsed


def _dialogue_sentences(structured: Mapping[str, Any]) -> str:
    """Dialogue + Voice_Profiles 投成官方台词句：说话人首次出现顺序分配 ``（S1）`` 稳定 ID。

    声明过的 Voice_Style 织入说话人介绍（官方要求首次出现时给出音色线索）；台词原文逐字
    保留在 ``<d>`` 内，语言标签按 ArcReel 剧本的对白语言写 ``[Chinese]``。
    """
    styles = {
        str(entry.get("Speaker", "")): str(entry.get("Voice_Style", "") or "").strip()
        for entry in (structured.get("Voice_Profiles") or [])
        if isinstance(entry, Mapping)
    }
    sentences: list[str] = []
    assigned: dict[str, str] = {}
    for entry in structured.get("Dialogue") or []:
        if not isinstance(entry, Mapping):
            continue
        speaker = str(entry.get("Speaker", "") or "").strip()
        line = str(entry.get("Line", "") or "").strip()
        if not speaker or not line:
            continue
        index = assigned.setdefault(speaker, f"S{len(assigned) + 1}")
        style = styles.get(speaker, "")
        intro = f"{speaker}（{index}）以{style}说" if style else f"{speaker}（{index}）说"
        sentences.append(f"{intro}：<d>[Chinese] {line}</d>")
    return " ".join(sentences)


def _keyframe_instruction(*, has_start_image: bool, has_end_image: bool, duration_seconds: float) -> str | None:
    """关键帧对齐指令行（官方 base-en.txt §2.1 的固定句式）；无关键帧即无指令行。"""
    if has_start_image and has_end_image:
        return (
            "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
            f"0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {duration_seconds:.2f}-second "
            "mark of the target video."
        )
    if has_start_image:
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    if has_end_image:
        return (
            "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the "
            f"{duration_seconds:.2f}-second mark of the target video."
        )
    return None


# ---------------------------------------------------------------------------
# 参考生视频三段论 → H3 原生结构
# ---------------------------------------------------------------------------
#
# 三段论的机器语法（``lib.script.reference_video.prompt_render`` 产出）：
#   <徐凤年>@图片1、<城墙外酒摊>@图片2。          —— 主体绑定行（图号 = 参考图顺序）
#   <A>与<B>是同一角色的不同形态，各自按对应参考图呈现。 —— 同角色多形态声明（≥2 形态才出现）
#   <徐凤年>的台词音色参考 @音频1，……，声音特征：清朗少年音。 —— 声音声明（听得到声音才出现）
#   <徐凤年>说 {台词}                              —— 正文里的发声记号
#   <徐凤年>                                       —— 正文里的主体记号
#   Style: … / Visual style: …                     —— 风格块（media_style partial）
# 其余自由行是单元正文与商品声明段。``@音频N`` 的音频绑定对 ComfyUI H3 端点没有对应输入
# （模型自行发声），投影时丢弃；声音特征织入台词介绍句。

_REFERENCE_BINDING_LINE = re.compile(r"^(?:<[^<>]+>@图片\d+[、]?)+。$")
_REFERENCE_BINDING_ITEM = re.compile(r"<([^<>]+)>@图片(\d+)")
_REFERENCE_FORM_LINE = re.compile(r"^(?:<[^<>]+>[、与])+<[^<>]+>是同一角色的不同形态，各自按对应参考图呈现。$")
_REFERENCE_FORM_LABEL = re.compile(r"<([^<>]+)>")
_REFERENCE_VOICE_LINE = re.compile(
    r"^<([^<>]+)>的(?:台词音色参考 @音频\d+，只取音色、语速与情绪，台词以正文为准)?[，,]?(?:声音特征：(.+?))?。$"
)
_REFERENCE_STYLE_LINE = re.compile(r"^(?:Style|Visual style):[ ]?(.*)$")
#: 同一把扫描里区分发声记号与主体记号：交替先试「<X>说 {…}」再回退「<X>」。替换产生的新文本
# （``<d>``、``<Picture N>``）不会被同一轮 re.sub 重扫，``<d>`` 不会误中主体分支。
_REFERENCE_MARK = re.compile(r"<([^<>]+)>说 \{([^{}]*)\}|<([^<>]+)>")


@dataclass
class _ReferenceParse:
    pictures: dict[str, int] = field(default_factory=dict)
    forms: list[list[str]] = field(default_factory=list)
    voice_styles: dict[str, str] = field(default_factory=dict)
    prose: list[str] = field(default_factory=list)
    tail: list[str] = field(default_factory=list)
    style: str = ""
    style_description: str = ""


def project_reference_prompt_to_h3(body: str, *, duration_seconds: float = 0.0) -> str:
    """把参考生视频的三段论机器文本投成 H3 原生三段式；机器语法认不出时原样返回。

    认得出的部分按官方 r2v 约定改写：``<X>@图片N`` 的图号落成正文里的 ``<Picture N>`` 标签，
    发声记号改写成 ``（S1）说：<d>[Chinese] …</d>``，风格块织入描述开头；``@音频N`` 音频绑定
    丢弃（ComfyUI H3 端点没有音频输入，发声由模型按 ``<d>`` 自产）。三段论是渲染期机械产物，
    这里的解析同样机械，不依赖 LLM 自觉；用户在编辑器里手写的自由正文（无任何记号）原样透传，
    其 H3 化由写作指南承担。``duration_seconds`` 转成描述尾部的时长声明句。
    """
    if _H3_BODY_MARKER in body:
        return body
    parsed = _parse_reference_prompt(body)
    if parsed is None:
        return body

    speaker_ids: dict[str, str] = {}
    description_parts: list[str] = []
    if parsed.style:
        description_parts.append(f"画面风格：{parsed.style}。")
    if parsed.style_description:
        description_parts.append(f"{parsed.style_description}")
    for line in parsed.prose + parsed.tail:
        transformed = _transform_reference_line(line, parsed, speaker_ids)
        if transformed:
            description_parts.append(transformed)
    duration_sentence = _duration_sentence(duration_seconds)
    if duration_sentence:
        description_parts.append(duration_sentence)
    if not description_parts:
        return body

    sections: list[str] = []
    for forms in parsed.forms:
        sentence = _form_sentence(forms, parsed.pictures)
        if sentence:
            sections.append(sentence)
    sections.append(f"{_H3_BODY_MARKER}: [Shot 1] " + " ".join(description_parts))
    sections.append("overall_soundscape: N/A")
    sections.append("non_diegetic_music: N/A")
    return "\n\n".join(sections)


def _parse_reference_prompt(body: str) -> _ReferenceParse | None:
    """逐行分类三段论的机器语法；一行记号都没有（纯自由文本）时返回 None。"""
    parsed = _ReferenceParse()
    in_style_block = False
    recognized = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _REFERENCE_BINDING_LINE.match(line):
            recognized = True
            for label, number in _REFERENCE_BINDING_ITEM.findall(line):
                parsed.pictures[label] = int(number)
            continue
        if _REFERENCE_FORM_LINE.match(line):
            recognized = True
            parsed.forms.append(_REFERENCE_FORM_LABEL.findall(line))
            continue
        voice = _REFERENCE_VOICE_LINE.match(line)
        if voice:
            recognized = True
            if voice.group(2):
                parsed.voice_styles[voice.group(1)] = voice.group(2).strip()
            continue
        style = _REFERENCE_STYLE_LINE.match(line)
        if style:
            recognized = True
            in_style_block = True
            if line.startswith("Style:"):
                parsed.style = style.group(1).strip()
            else:
                parsed.style_description = style.group(1).strip()
            continue
        if _REFERENCE_MARK.search(line):
            recognized = True
        (parsed.tail if in_style_block else parsed.prose).append(line)
    if not recognized:
        return None
    return parsed


def _transform_reference_line(line: str, parsed: _ReferenceParse, speaker_ids: dict[str, str]) -> str:
    """一行的记号改写：发声记号 → ``（S1）说：<d>``，主体记号 → ``<Picture N>`` 或裸名。"""

    def _replace(match: re.Match[str]) -> str:
        if match.group(2) is not None:
            label, text = match.group(1), match.group(2).strip()
            index = speaker_ids.setdefault(label, f"S{len(speaker_ids) + 1}")
            style = parsed.voice_styles.get(label, "")
            intro = f"{label}（{index}）以{style}说" if style else f"{label}（{index}）说"
            return f"{intro}：<d>[Chinese] {text}</d>"
        label = match.group(3)
        number = parsed.pictures.get(label)
        return f"<Picture {number}>" if number else label

    return _REFERENCE_MARK.sub(_replace, line)


def _form_sentence(forms: list[str], pictures: dict[str, int]) -> str:
    """多形态声明句的英文转写；没有参考图可指的形态组不产出句子。"""
    numbers = [pictures[label] for label in forms if label in pictures]
    if len(numbers) < 2:
        return ""
    head = (
        " and ".join((str(numbers[0]), str(numbers[1])))
        if len(numbers) == 2
        else ", ".join(str(n) for n in numbers[:-1]) + f" and {numbers[-1]}"
    )
    return f"Pictures {head} show different appearances of the same character; each follows its own reference picture."
