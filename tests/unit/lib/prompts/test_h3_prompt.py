"""H3 六字段投影、参考主体来源及请求构造回归测试。"""

from __future__ import annotations

import re
from typing import Any

import pytest

from lib.custom_provider.comfyui.request_builder import MediaInputs, build_workflow
from lib.prompts.h3_prompt import (
    is_h3_video_workflow,
    project_hybrid_prompt_to_h3,
    project_reference_prompt_to_h3,
    project_video_prompt_to_h3,
)
from lib.prompts.prompt_utils import split_avoid_lines, video_prompt_to_yaml
from tests.factories import comfyui_endpoint_definition

FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)


def _fields(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"^(" + "|".join(FIELDS) + r"): ", body, re.MULTILINE))
    assert [match.group(1) for match in matches] == list(FIELDS)
    return {
        match.group(1): body[match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(body)].strip()
        for i, match in enumerate(matches)
    }


def _structured_body(**overrides: Any) -> str:
    prompt: dict[str, Any] = {
        "action": "老黄蹒跚前行，衣摆扫过枯草",
        "camera_motion": "Push In",
        "ambiance_audio": "跛马蹄铁拖地的叩击声，远处旷野的风声。",
        "dialogue": [],
        "voice_profiles": [],
    }
    prompt.update(overrides)
    return video_prompt_to_yaml(prompt)


def _video(body: str) -> str:
    return project_video_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=5.0)


@pytest.mark.parametrize("project", [_video, project_reference_prompt_to_h3])
def test_complete_native_fields_pass_through_verbatim(project):
    body = "关键帧对齐说明\n\n" + "\n\n".join(f"{field}: 原始内容" for field in FIELDS)
    assert project(body) == body


@pytest.mark.parametrize("project", [_video, project_reference_prompt_to_h3])
def test_legacy_fields_migrate_and_preserve_audio_and_alignment(project):
    description = "[Shot 1] 0.00 秒 <d>[Chinese] 别走！</d>\n[Shot 2] At 00:03.500, 空镜。"
    prefix = "For the target video, <Picture 1> is fully referenced.\n\n"
    body = (
        prefix
        + f"integrated_multimodal_description: {description}\n\noverall_soundscape: 风声\n\nnon_diegetic_music: 钢琴"
    )
    projected = project(body)
    fields = _fields(projected)
    assert projected.startswith(prefix)
    assert "integrated_multimodal_description" not in projected
    assert fields["detailed_description"] == description
    assert fields["overall_soundscape"] == "风声"
    assert fields["non_diegetic_music"] == "钢琴"
    assert fields["subject_definitions"] == fields["retention_analysis"] == "N/A"


@pytest.mark.parametrize("project", [_video, project_reference_prompt_to_h3])
@pytest.mark.parametrize(
    "body",
    [
        "一个人在雨中行走，镜头缓推。",
        "请解释 integrated_multimodal_description 的意义。",
        "integrated_multimodal_description: 只是讨论一个字段，并非三字段提示词",
    ],
)
def test_free_text_is_unchanged(project, body):
    assert project(body) == body


def test_workflow_detection():
    assert is_h3_video_workflow({"1": {"class_type": "MiniMaxH3ImageToVideo"}})
    assert is_h3_video_workflow({"1": {"class_type": "MiniMaxH3ReferenceToVideo"}})
    assert not is_h3_video_workflow({})
    assert not is_h3_video_workflow({"1": {"class_type": "KSampler"}})
    assert not is_h3_video_workflow({"1": {"class_type": "MiniMaxTheorist"}})


@pytest.mark.parametrize(
    ("start", "end", "alignment"),
    [
        (True, False, "<Picture 1> (from [Shot 1]) is fully referenced."),
        (False, True, "<Picture 1> (from [Shot 1]) aligns with the 5.00-second mark"),
        (True, True, "<Picture 2> (from [Shot 1]) aligns with the 5.00-second mark"),
        (False, False, None),
    ],
)
def test_keyframes_are_full_frames_not_subject_definitions(start, end, alignment):
    projected = project_video_prompt_to_h3(
        _structured_body(),
        has_start_image=start,
        has_end_image=end,
        duration_seconds=5.0,
    )
    fields = _fields(projected)
    assert fields["subject_definitions"] == fields["retention_analysis"] == "N/A"
    assert fields["summary"] == "老黄蹒跚前行，衣摆扫过枯草"
    assert fields["detailed_description"].startswith("[Shot 1] 老黄蹒跚前行，衣摆扫过枯草 The camera pushes in.")
    assert fields["detailed_description"].endswith("The shot lasts 5.00 seconds in total.")
    assert fields["overall_soundscape"] == "跛马蹄铁拖地的叩击声，远处旷野的风声。"
    assert fields["non_diegetic_music"] == "N/A"
    if alignment:
        assert alignment in projected
    else:
        assert "Picture" not in projected


def test_video_preserves_shots_timestamps_dialogue_and_voice():
    action = "[Shot 1] 老黄前行。\n[Shot 2] At 00:03.500, 徐凤年回头。"
    projected = _video(
        _structured_body(
            action=action,
            dialogue=[
                {"speaker": "老黄", "line": "跟上。"},
                {"speaker": "徐凤年", "line": "走。"},
                {"speaker": "老黄", "line": "慢些。"},
            ],
            voice_profiles=[{"Speaker": "老黄", "Voice_Style": "沙哑低沉的嗓音"}],
        )
    )
    description = _fields(projected)["detailed_description"]
    assert description.startswith(action)
    assert description.count("[Shot 1]") == 1
    assert "老黄（S1）以沙哑低沉的嗓音说：<d>[Chinese] 跟上。</d>" in description
    assert "徐凤年（S2）说：<d>[Chinese] 走。</d>" in description
    assert "老黄（S1）以沙哑低沉的嗓音说：<d>[Chinese] 慢些。</d>" in description


def test_unknown_camera_and_zero_duration():
    projected = project_video_prompt_to_h3(
        _structured_body(camera_motion="未知运镜"),
        has_start_image=False,
        has_end_image=False,
        duration_seconds=0,
    )
    assert "The camera motion is 未知运镜." in projected
    assert "The shot lasts" not in projected


def test_action_containing_legacy_marker_still_projects():
    fields = _fields(_video(_structured_body(action="招牌写着 integrated_multimodal_description。")))
    assert fields["detailed_description"].startswith("[Shot 1] 招牌写着")


def _hybrid_body(action: str) -> str:
    yaml_body = video_prompt_to_yaml(
        {
            "action": action,
            "camera_motion": "Tracking Shot",
            "ambiance_audio": "荒道风声。",
            "dialogue": [{"speaker": "徐凤年", "line": "走吧。"}],
            "voice_profiles": [{"Speaker": "徐凤年", "Voice_Style": "慵懒嗓音"}],
        }
    )
    return "<徐凤年>@图片1、<老黄>@图片2。\n" + yaml_body


def test_hybrid_projection_shifts_bindings_and_locks_subjects():
    body = _hybrid_body("0—3秒，<徐凤年>牵着跛马前行，<老黄>说 {走吧。}")
    projected = project_hybrid_prompt_to_h3(body, has_start_image=True, has_end_image=True, duration_seconds=12.0)
    fields = _fields(projected)
    assert "<Subject 3> is 徐凤年 from <Picture 3>." in fields["subject_definitions"]
    assert "<Subject 4> is 老黄 from <Picture 4>." in fields["subject_definitions"]
    assert "<Subject 3>牵着跛马前行，<Subject 4>（S1）说：<d>[Chinese] 走吧。</d>" in fields["detailed_description"]
    assert "<Subject 3>（S1）以慵懒嗓音说：<d>[Chinese] 走吧。</d>" in fields["detailed_description"]
    assert "<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark" in projected
    assert "<Picture 2> (from [Shot 1]) aligns with the 12.00-second mark" in projected
    assert fields["retention_analysis"].splitlines() == [
        "<Subject 3> (appears in [Shot 1]): fully_preserved - 徐凤年 from <Picture 3>, retained as shown in the reference picture.",
        "<Subject 4> (appears in [Shot 1]): fully_preserved - 老黄 from <Picture 4>, retained as shown in the reference picture.",
    ]
    assert fields["overall_soundscape"] == "荒道风声。"
    assert fields["detailed_description"].endswith("The shot lasts 12.00 seconds in total.")


def test_hybrid_projection_start_only_offsets_by_one():
    body = _hybrid_body("0—3秒，<徐凤年>牵着跛马前行。")
    projected = project_hybrid_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=12.0)
    fields = _fields(projected)
    assert "<Subject 2> is 徐凤年 from <Picture 2>." in fields["subject_definitions"]
    assert "<Picture 1> (from [Shot 1]) is fully referenced." in projected
    assert "(from [Shot 1]) aligns with the 12.00-second mark" not in projected


def test_video_projection_drops_binding_lines_without_reference_slots():
    projected = _video(_hybrid_body("0—3秒，<徐凤年>牵着跛马前行。"))
    assert "@图片" not in projected
    assert "<Subject" not in projected
    assert "<徐凤年>" not in projected
    assert "徐凤年（S1）以慵懒嗓音说：<d>[Chinese] 走吧。</d>" in projected
    assert "<Picture 1> (from [Shot 1]) is fully referenced." in projected


def test_asset_marks_are_stripped_in_video_projection():
    projected = _video(_structured_body(action="@[老黄]牵着@[跛马]前行，@[徐凤年]跟随"))
    assert "@[" not in projected
    assert "老黄牵着跛马前行，徐凤年跟随" in projected
    assert "<Picture 1> (from [Shot 1]) is fully referenced." in projected


def test_asset_marks_are_stripped_in_reference_projection():
    body = "\n".join(
        [
            "<老者>@图片4。",
            "[Shot 1] 空巷，@[老者]回头，<老者>说 {回来。}",
        ]
    )
    fields = _fields(project_reference_prompt_to_h3(body))
    assert "@[" not in fields["detailed_description"]
    assert "空巷，老者回头，<Subject 4>（S1）说：<d>[Chinese] 回来。</d>" in fields["detailed_description"]
    assert fields["retention_analysis"].splitlines() == [
        "<Subject 4> (appears in [Shot 1]): fully_preserved - 老者 from <Picture 4>, retained as shown in the reference picture.",
    ]


def test_reference_bindings_voice_and_style():
    body = "\n".join(
        [
            "<徐凤年>@图片1、<城墙外酒摊>@图片2。",
            "<徐凤年>的台词音色参考 @音频1，只取音色、语速与情绪，台词以正文为准，声音特征：清朗少年音。",
            "中景。<徐凤年> 在 <城墙外酒摊> 前驻足，<徐凤年>说 {这风比去年冷。}",
            "随后他低头望向远方。",
            "Style: 古风水墨",
            "Visual style: 笔触克制、留白疏朗",
        ]
    )
    projected = project_reference_prompt_to_h3(body, duration_seconds=5)
    fields = _fields(projected)
    assert "<Subject 1> is 徐凤年 from <Picture 1>." in fields["subject_definitions"]
    assert "<Subject 2> is 城墙外酒摊 from <Picture 2>." in fields["subject_definitions"]
    assert "<Subject 1> 在 <Subject 2> 前驻足" in fields["detailed_description"]
    assert "<Subject 1>（S1）以清朗少年音说：<d>[Chinese] 这风比去年冷。</d>" in fields["detailed_description"]
    assert fields["retention_analysis"].splitlines() == [
        "<Subject 1> (appears in [Shot 1]): fully_preserved - 徐凤年 from <Picture 1>, retained as shown in the reference picture.",
        "<Subject 2> (appears in [Shot 1]): fully_preserved - 城墙外酒摊 from <Picture 2>, retained as shown in the reference picture.",
    ]
    assert not re.search(r"(?<!<)(?:Subject|Picture) \d+", projected)
    assert "画面风格：古风水墨。" in fields["detailed_description"]
    assert "笔触克制、留白疏朗" in fields["detailed_description"]
    assert fields["detailed_description"].endswith("The shot lasts 5.00 seconds in total.")
    assert "@图片" not in projected
    assert "台词音色参考" not in projected


def test_reference_retention_uses_each_shots_explicit_subjects_only():
    body = "\n".join(
        [
            "<甲>@图片1、<乙>@图片2、<未出场>@图片3。",
            "[Shot 4] <甲>回头，<甲>停步，<画外老者>叹息。",
            "[Shot 2] At 00:03.500, <乙>说 {  别走！  }，<甲>转身。",
            "[Shot 3] At 00:04.500, 空镜。",
            "[Shot 4] <甲>说 {慢些。}",
        ]
    )
    fields = _fields(project_reference_prompt_to_h3(body))
    assert fields["retention_analysis"].splitlines() == [
        "<Subject 1> (appears in [Shot 4], [Shot 2]): fully_preserved - 甲 from <Picture 1>, retained as shown in the reference picture.",
        "<Subject 2> (appears in [Shot 2]): fully_preserved - 乙 from <Picture 2>, retained as shown in the reference picture.",
    ]
    description = fields["detailed_description"]
    assert "[Shot 1]" not in description
    assert description.count("[Shot 4]") == 2
    assert "[Shot 2] At 00:03.500, <Subject 2>（S1）说：<d>[Chinese]   别走！  </d>" in description
    assert "<Subject 1>回头，<Subject 1>停步，<画外老者>叹息。" in description
    assert "[Shot 4] <Subject 1>（S2）说：<d>[Chinese] 慢些。</d>" in description
    assert "<Subject 3>" not in description


def test_reference_forms_keep_distinct_subject_and_picture_numbers():
    body = "\n".join(
        [
            "<徐凤年>@图片2、<徐凤年/劲装>@图片5。",
            "<徐凤年>与<徐凤年/劲装>是同一角色的不同形态，各自按对应参考图呈现。",
            "[Shot 1] <徐凤年>拔剑。\n[Shot 2] <徐凤年/劲装>收势。",
        ]
    )
    fields = _fields(project_reference_prompt_to_h3(body))
    assert "<Subject 2> is 徐凤年 from <Picture 2>." in fields["subject_definitions"]
    assert "<Subject 5> is 徐凤年/劲装 from <Picture 5>." in fields["subject_definitions"]
    assert (
        "<Subject 2> and <Subject 5> show different appearances of the same character" in fields["subject_definitions"]
    )
    assert fields["detailed_description"] == "[Shot 1] <Subject 2>拔剑。\n[Shot 2] <Subject 5>收势。"
    assert fields["retention_analysis"].splitlines() == [
        "<Subject 2> (appears in [Shot 1]): fully_preserved - 徐凤年 from <Picture 2>, retained as shown in the reference picture.",
        "<Subject 5> (appears in [Shot 2]): fully_preserved - 徐凤年/劲装 from <Picture 5>, retained as shown in the reference picture.",
    ]


def test_reference_voiceover_does_not_claim_visual_appearance():
    body = "\n".join(
        [
            "<老者>@图片4。",
            "[Shot 2] At 00:03.500, 空巷，画外<老者>说 {回来。}",
            "[Shot 3] 他的声音渐远。",
        ]
    )
    fields = _fields(project_reference_prompt_to_h3(body))
    assert fields["subject_definitions"] == "<Subject 4> is 老者 from <Picture 4>."
    assert fields["retention_analysis"] == (
        "<Subject 4> (appears in [Shot 2]): fully_preserved - 老者 from <Picture 4>, retained as shown in the reference picture."
    )
    assert fields["detailed_description"] == (
        "[Shot 2] At 00:03.500, 空巷，画外<Subject 4>（S1）说：<d>[Chinese] 回来。</d>\n[Shot 3] 他的声音渐远。"
    )


def test_bound_subject_without_explicit_reference_has_no_retention():
    body = "<老者>@图片4。\n<老者>的声音特征：低沉。\n[Shot 2] 空巷，他的声音渐远。"
    fields = _fields(project_reference_prompt_to_h3(body))
    assert fields["subject_definitions"] == "<Subject 4> is 老者 from <Picture 4>. 声音特征：低沉。"
    assert fields["retention_analysis"] == "N/A"
    assert fields["detailed_description"] == "[Shot 2] 空巷，他的声音渐远。"


def test_no_binding_does_not_invent_subject():
    fields = _fields(project_reference_prompt_to_h3("<老者>说 {回来。}"))
    assert fields["subject_definitions"] == "N/A"
    assert fields["retention_analysis"] == "N/A"
    assert "<老者>（S1）说：<d>[Chinese] 回来。</d>" in fields["detailed_description"]


class TestRequestBuilderIntegration:
    def _h3_definition(self) -> dict[str, Any]:
        definition = comfyui_endpoint_definition()
        definition["media_type"] = "video"
        definition["workflow"] = {
            "1": {
                "class_type": "MiniMaxH3ImageToVideo",
                "inputs": {
                    "clip": ["2", 0],
                    "prompt": "",
                    "width": 1248,
                    "height": 704,
                    "length": 121,
                    "first_frame": ["4", 0],
                    "last_frame": ["5", 0],
                },
            },
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl.safetensors", "type": "minimax"}},
            "3": {"class_type": "MiniMaxH3AVDecodeT8", "inputs": {"av_latent": ["1", 1]}},
            "4": {"class_type": "LoadImage", "inputs": {"image": "start.png"}},
            "5": {"class_type": "LoadImage", "inputs": {"image": "end.png"}},
        }
        definition["bindings"] = {
            "prompt": [{"node": "1", "input": "prompt", "class_type": "MiniMaxH3ImageToVideo", "title": "H3"}],
            "frames": [{"node": "1", "input": "length", "class_type": "MiniMaxH3ImageToVideo", "step": 17}],
            "start_image": [{"node": "4", "input": "image", "class_type": "LoadImage"}],
            "end_image": [{"node": "5", "input": "image", "class_type": "LoadImage"}],
            "output": [{"node": "3", "class_type": "MiniMaxH3AVDecodeT8"}],
        }
        return definition

    def test_h3_endpoint_projects_before_writing(self):
        built = build_workflow(
            self._h3_definition(),
            prompt=_structured_body() + "\n\nAvoid: BGM、文字字幕、水印",
            aspect_ratio="16:9",
            duration_seconds=5,
            media=MediaInputs(start_image="start.png", end_image="end.png"),
        )
        written = built.workflow["1"]["inputs"]["prompt"]
        assert _fields(written)["detailed_description"].startswith("[Shot 1] 老黄蹒跚前行")
        assert "<Picture 2> (from [Shot 1]) aligns with the 5.00-second mark" in written
        assert "Avoid:" not in written

    def test_reference_endpoint_projects_subjects(self):
        definition = self._h3_definition()
        definition["workflow"]["1"]["class_type"] = "MiniMaxH3ReferenceToVideo"
        definition["workflow"]["1"]["inputs"]["ref_images.ref_image_0"] = ["4", 0]
        definition["bindings"]["prompt"][0]["class_type"] = "MiniMaxH3ReferenceToVideo"
        definition["bindings"]["frames"][0].update(class_type="MiniMaxH3ReferenceToVideo", step=4)
        definition["bindings"].pop("start_image")
        definition["bindings"].pop("end_image")
        definition["bindings"]["reference_images"] = [{"node": "4", "input": "image", "class_type": "LoadImage"}]
        built = build_workflow(
            definition,
            prompt="<徐凤年>@图片1。\n<徐凤年> 拔剑。\n\nAvoid: BGM",
            aspect_ratio="16:9",
            duration_seconds=5,
            media=MediaInputs(reference_images=["ref.png"]),
        )
        written = built.workflow["1"]["inputs"]["prompt"]
        assert _fields(written)["detailed_description"].startswith("[Shot 1] <Subject 1> 拔剑。")
        assert "Avoid:" not in written

    def test_non_h3_keeps_original_prompt(self):
        definition = comfyui_endpoint_definition()
        definition["bindings"]["start_image"] = [{"node": "11", "input": "image", "class_type": "LoadImage"}]
        body = _structured_body()
        built = build_workflow(
            definition,
            prompt=body,
            aspect_ratio="9:16",
            duration_seconds=5,
            media=MediaInputs(start_image="start.png"),
        )
        expected, _ = split_avoid_lines(body)
        assert built.workflow["6"]["inputs"]["text"] == expected
