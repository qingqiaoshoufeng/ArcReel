"""MiniMax H3 六字段提示词投影；仅在请求构造时转换，非结构化正文原样透传。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

_H3_CLASS_TYPE_PREFIX = "MiniMaxH3"
_H3_FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
_H3_LEGACY_FIELD = "integrated_multimodal_description"
_H3_FIELD_LINE = re.compile(r"^(" + "|".join((*_H3_FIELDS, _H3_LEGACY_FIELD)) + r"):[ \t]*", re.MULTILINE)
_SHOT = re.compile(r"\[Shot \d+\]")
_ASSET_MARK = re.compile(r"@\[([^\[\]]*)\]")
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
_UNKNOWN_CAMERA_SENTENCE = "The camera motion is {value}."


def _duration_sentence(duration_seconds: float) -> str:
    if duration_seconds <= 0:
        return ""
    return f"The shot lasts {duration_seconds:.2f} seconds in total."


def _strip_asset_marks(body: str) -> str:
    """剥掉分镜图生成遗留的 @[资产] 绑定标记；H3 只按首帧与文本理解画面。"""
    return _ASSET_MARK.sub(r"\1", body)


def _six_fields(
    description: str,
    *,
    subjects: str = "N/A",
    summary: str = "N/A",
    retention: str = "N/A",
    soundscape: str = "N/A",
    music: str = "N/A",
) -> str:
    values = (subjects, summary, retention, description, soundscape, music)
    return "\n\n".join(f"{name}: {value}" for name, value in zip(_H3_FIELDS, values, strict=True))


def _native_prompt(body: str) -> str | None:
    """只识别独立字段行；保留原生六字段及旧格式的关键帧前缀。"""
    matches = list(_H3_FIELD_LINE.finditer(body))
    names = {match.group(1) for match in matches}
    if set(_H3_FIELDS) <= names:
        return body
    if not {_H3_LEGACY_FIELD, "overall_soundscape", "non_diegetic_music"} <= names:
        return None
    values = {
        match.group(1): body[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(body)
        ].strip()
        for index, match in enumerate(matches)
    }
    description = values[_H3_LEGACY_FIELD]
    prefix = body[: matches[0].start()]
    return prefix + _six_fields(
        description,
        summary=description or "N/A",
        soundscape=values["overall_soundscape"],
        music=values["non_diegetic_music"],
    )


def _with_shot(description: str) -> str:
    return description if _SHOT.search(description) else f"[Shot 1] {description}"


_RESERVED_MARK = re.compile(r"<(?:Subject|Picture) \d+>")
_CHARACTER_MARK = re.compile(r"<([^<>]+)>")


def _unwrap_character_marks(text: str) -> str:
    """剥掉正文里的 ``<名字>`` 标记；``Subject`` / ``Picture`` 保留标记原样留下。

    只用于没有参考图槽的投影路径：标记与绑定行成对出现，绑定行已被剥除时标记无主，
    留着只会让模型读到裸尖括号。
    """
    return _CHARACTER_MARK.sub(
        lambda match: match.group(0) if _RESERVED_MARK.fullmatch(match.group(0)) else match.group(1), text
    )


def is_h3_video_workflow(workflow: Mapping[str, Any]) -> bool:
    """任一节点类型命中 MiniMax H3 前缀即认。"""
    return any(
        isinstance(node, Mapping) and str(node.get("class_type", "")).startswith(_H3_CLASS_TYPE_PREFIX)
        for node in workflow.values()
    )


def strip_h3_only_marks(body: str) -> str:
    """非 H3 工作流剥除仅 H3 消费的标记：角色绑定行与 ``<名字>`` 标记还原成普通名字。

    渲染层对 drama 分镜无条件注入绑定行与名字标记（四出口同构），只有 H3 混合投影消费
    它们；其余工作流正文里留着只会是裸尖括号与不存在的图号。
    """
    _, remaining = _split_reference_binding_lines(body)
    return _unwrap_character_marks(remaining)


def project_video_prompt_to_h3(
    body: str,
    *,
    has_start_image: bool,
    has_end_image: bool,
    duration_seconds: float,
) -> str:
    """将视频 YAML 投影为六字段；完整关键帧不推断为单一主体，@[资产] 标记剥成普通名字。

    正文前置的角色绑定行在此剥除不采用：本路径只带首尾帧、没有参考图槽，绑定号对模型
    是不存在的图，留下只会误导（混合投影见 :func:`project_hybrid_prompt_to_h3`）。
    """
    _, body = _split_reference_binding_lines(body)
    native = _native_prompt(body)
    if native is not None:
        return native
    structured = _parse_structured_body(body)
    if structured is None:
        return body
    action = str(structured.get("Action", "") or "").strip()
    if not action:
        return body
    action = _unwrap_character_marks(action)
    camera = str(structured.get("Camera_Motion", "") or "").strip()
    camera_sentence = _CAMERA_SENTENCES.get(camera, _UNKNOWN_CAMERA_SENTENCE.format(value=camera)) if camera else ""
    description = " ".join(
        part
        for part in (
            _with_shot(action),
            camera_sentence,
            _dialogue_sentences(structured),
            _duration_sentence(duration_seconds),
        )
        if part
    )
    projected = _six_fields(
        description,
        summary=action,
        soundscape=str(structured.get("Ambiance_Audio", "") or "").strip() or "N/A",
    )
    instruction = _keyframe_instruction(
        has_start_image=has_start_image,
        has_end_image=has_end_image,
        duration_seconds=duration_seconds,
    )
    return _strip_asset_marks(f"{instruction}\n\n{projected}" if instruction else projected)


def _parse_structured_body(body: str) -> Mapping[str, Any] | None:
    try:
        parsed = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, Mapping) or "Action" not in parsed:
        return None
    return parsed


def _split_reference_binding_lines(body: str) -> tuple[dict[str, int], str]:
    """拆出前置的角色绑定行；返回 ``（名字 -> 逻辑图号, 其余正文）``。

    绑定行形如 ``<老黄>@图片1、<徐凤年>@图片2。``，由渲染层按分镜出场角色序机械拼装，
    图号是**逻辑号**（从 1 起）；实际编号由调用方按本次请求携带的关键帧数前移。
    """
    bindings: dict[str, int] = {}
    prose_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if _REFERENCE_BINDING_LINE.match(line):
            for label, number in _REFERENCE_BINDING_ITEM.findall(line):
                bindings[label] = int(number)
            continue
        prose_lines.append(raw_line)
    return bindings, "\n".join(prose_lines)


def project_hybrid_prompt_to_h3(
    body: str,
    *,
    has_start_image: bool,
    has_end_image: bool,
    duration_seconds: float,
) -> str:
    """首尾帧与角色参考图并存的混合投影（文武双全式）。

    参考图槽序是「首帧、尾帧、角色图」：关键帧占 Picture 1/2 做首尾帧对齐锚，角色绑定
    号前移关键帧占位后与模型读到的图序一致。角色锁定由参考图本体保证，正文与对白沿用
    同一 `<Subject N>` 编号，retention 按镜汇总。
    """
    offset = (1 if has_start_image else 0) + (1 if has_end_image else 0)
    logical, remaining = _split_reference_binding_lines(body)
    bindings = {label: number + offset for label, number in logical.items()}
    if not bindings:
        return project_video_prompt_to_h3(
            body, has_start_image=has_start_image, has_end_image=has_end_image, duration_seconds=duration_seconds
        )
    structured = _parse_structured_body(remaining)
    if structured is None:
        return body
    action = str(structured.get("Action", "") or "").strip()
    if not action:
        return body
    camera = str(structured.get("Camera_Motion", "") or "").strip()
    camera_sentence = _CAMERA_SENTENCES.get(camera, _UNKNOWN_CAMERA_SENTENCE.format(value=camera)) if camera else ""
    transformed = _transform_reference_line(action, _ReferenceParse(pictures=bindings), {})
    description = " ".join(
        part
        for part in (
            _with_shot(transformed),
            camera_sentence,
            _dialogue_sentences(structured, subjects=bindings),
            _duration_sentence(duration_seconds),
        )
        if part
    )
    definitions = "\n".join(
        f"<Subject {number}> is {label} from <Picture {number}>." for label, number in bindings.items()
    )
    projected = _six_fields(
        description,
        subjects=definitions,
        summary=transformed,
        retention=_retention_analysis(_with_shot(action), bindings),
        soundscape=str(structured.get("Ambiance_Audio", "") or "").strip() or "N/A",
    )
    instruction = _keyframe_instruction(
        has_start_image=has_start_image,
        has_end_image=has_end_image,
        duration_seconds=duration_seconds,
    )
    return _strip_asset_marks(f"{instruction}\n\n{projected}" if instruction else projected)


def _dialogue_sentences(structured: Mapping[str, Any], *, subjects: Mapping[str, int] | None = None) -> str:
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
        line = str(entry.get("Line", "") or "")
        if not speaker or not line.strip():
            continue
        index = assigned.setdefault(speaker, f"S{len(assigned) + 1}")
        style = styles.get(speaker, "")
        speaker_label = f"<Subject {subjects[speaker]}>" if subjects and speaker in subjects else speaker
        intro = f"{speaker_label}（{index}）以{style}说" if style else f"{speaker_label}（{index}）说"
        sentences.append(f"{intro}：<d>[Chinese] {line}</d>")
    return " ".join(sentences)


def _keyframe_instruction(*, has_start_image: bool, has_end_image: bool, duration_seconds: float) -> str | None:
    if has_start_image and has_end_image:
        return (
            "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the "
            f"0.00-second mark of the target video; <Picture 2> (from [Shot 1]) aligns with the {duration_seconds:.2f}-second "
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


_REFERENCE_BINDING_LINE = re.compile(r"^(?:<[^<>]+>@图片\d+[、]?)+。$")
_REFERENCE_BINDING_ITEM = re.compile(r"<([^<>]+)>@图片(\d+)")
_REFERENCE_FORM_LINE = re.compile(r"^(?:<[^<>]+>[、与])+<[^<>]+>是同一角色的不同形态，各自按对应参考图呈现。$")
_REFERENCE_FORM_LABEL = re.compile(r"<([^<>]+)>")
_REFERENCE_VOICE_LINE = re.compile(
    r"^<([^<>]+)>的(?:台词音色参考 @音频\d+，只取音色、语速与情绪，台词以正文为准)?[，,]?(?:声音特征：(.+?))?。$"
)
_REFERENCE_STYLE_LINE = re.compile(r"^(?:Style|Visual style):[ ]?(.*)$")
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


def _retention_analysis(prose: str, pictures: dict[str, int]) -> str:
    """按主体汇总正文显式引用到的镜头，不从全局声明推断出镜。"""
    shots = list(_SHOT.finditer(prose))
    references: dict[str, list[str]] = {label: [] for label in pictures}
    for index, shot in enumerate(shots):
        text = prose[shot.end() : shots[index + 1].start() if index + 1 < len(shots) else len(prose)]
        labels = {match.group(1) or match.group(3) for match in _REFERENCE_MARK.finditer(text)}
        for label in labels:
            if label in references and shot.group() not in references[label]:
                references[label].append(shot.group())
    lines = [
        f"<Subject {number}> (appears in {', '.join(references[label])}): "
        f"fully_preserved - {label} from <Picture {number}>, retained as shown in the reference picture."
        for label, number in pictures.items()
        if references[label]
    ]
    return "\n".join(lines) or "N/A"


def project_reference_prompt_to_h3(body: str, *, duration_seconds: float = 0.0) -> str:
    """参考图绑定定义 Subject；正文和对白沿用同一编号，保留分镜及多形态。"""
    native = _native_prompt(body)
    if native is not None:
        return native
    parsed = _parse_reference_prompt(body)
    if parsed is None:
        return body
    prose = "\n".join(parsed.prose + parsed.tail)
    if not prose:
        return body
    speaker_ids: dict[str, str] = {}
    transformed = _transform_reference_line(prose, parsed, speaker_ids)
    description_parts = []
    if parsed.style:
        description_parts.append(f"画面风格：{parsed.style}。")
    if parsed.style_description:
        description_parts.append(parsed.style_description)
    description_parts.append(transformed)
    description = _with_shot("\n".join(description_parts))
    duration = _duration_sentence(duration_seconds)
    if duration:
        description += " " + duration
    definitions = []
    for label, number in parsed.pictures.items():
        definition = f"<Subject {number}> is {label} from <Picture {number}>."
        if label in parsed.voice_styles:
            definition += f" 声音特征：{parsed.voice_styles[label]}。"
        definitions.append(definition)
    for forms in parsed.forms:
        sentence = _form_sentence(forms, parsed.pictures)
        if sentence:
            definitions.append(sentence)
    return _strip_asset_marks(
        _six_fields(
            description,
            subjects="\n".join(definitions) or "N/A",
            summary=transformed,
            retention=_retention_analysis(_with_shot(prose), parsed.pictures),
        )
    )


def _parse_reference_prompt(body: str) -> _ReferenceParse | None:
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
    return parsed if recognized else None


def _transform_reference_line(line: str, parsed: _ReferenceParse, speaker_ids: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        label = match.group(1) if match.group(2) is not None else match.group(3)
        number = parsed.pictures.get(label)
        subject = f"<Subject {number}>" if number is not None else f"<{label}>"
        if match.group(2) is not None:
            text = match.group(2)
            index = speaker_ids.setdefault(label, f"S{len(speaker_ids) + 1}")
            style = parsed.voice_styles.get(label, "")
            intro = f"{subject}（{index}）以{style}说" if style else f"{subject}（{index}）说"
            return f"{intro}：<d>[Chinese] {text}</d>"
        return subject

    return _REFERENCE_MARK.sub(_replace, line)


def _form_sentence(forms: list[str], pictures: dict[str, int]) -> str:
    numbers = [pictures[label] for label in forms if label in pictures]
    if len(numbers) < 2:
        return ""
    subjects = " and ".join(f"<Subject {number}>" for number in numbers)
    return f"{subjects} show different appearances of the same character; each follows its own reference picture."
