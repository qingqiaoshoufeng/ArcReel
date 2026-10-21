"""MiniMax H3 原生提示词投影：三段式结构、关键帧对齐指令、参考生视频三段论与台词说话人 ID。"""

from __future__ import annotations

from typing import Any

from lib.custom_provider.comfyui.request_builder import MediaInputs, build_workflow
from lib.prompts.h3_prompt import is_h3_video_workflow, project_reference_prompt_to_h3, project_video_prompt_to_h3
from lib.prompts.prompt_utils import split_avoid_lines, video_prompt_to_yaml
from tests.factories import comfyui_endpoint_definition


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


class TestIsH3VideoWorkflow:
    def test_a_minimax_h3_node_marks_the_workflow(self):
        assert is_h3_video_workflow({"1": {"class_type": "MiniMaxH3ImageToVideo"}})
        assert is_h3_video_workflow({"1": {"class_type": "MiniMaxH3ReferenceToVideo"}})

    def test_other_workflows_are_not_h3(self):
        assert not is_h3_video_workflow({})
        assert not is_h3_video_workflow({"1": {"class_type": "KSampler"}})
        assert not is_h3_video_workflow({"1": {"class_type": "MiniMaxTheorist"}})


class TestProjectBase:
    def test_a_structured_body_becomes_the_three_h3_fields(self):
        projected = project_video_prompt_to_h3(
            _structured_body(), has_start_image=True, has_end_image=False, duration_seconds=5.0
        )

        assert (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
            in projected
        )
        assert (
            "integrated_multimodal_description: [Shot 1] 老黄蹒跚前行，衣摆扫过枯草 The camera pushes in." in projected
        )
        assert "The shot lasts 5.00 seconds in total." in projected
        assert "overall_soundscape: 跛马蹄铁拖地的叩击声，远处旷野的风声。" in projected
        assert "non_diegetic_music: N/A" in projected

    def test_fl2va_writes_both_alignment_marks_with_the_duration(self):
        projected = project_video_prompt_to_h3(
            _structured_body(), has_start_image=True, has_end_image=True, duration_seconds=8.0
        )

        assert (
            "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
            "Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video."
        ) in projected

    def test_dialogue_gets_stable_speaker_ids_and_the_d_tag(self):
        body = _structured_body(
            dialogue=[{"speaker": "老黄", "line": "跟上。"}],
            voice_profiles=[{"Speaker": "老黄", "Voice_Style": "沙哑低沉的嗓音"}],
        )

        projected = project_video_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=5.0)

        assert "老黄（S1）以沙哑低沉的嗓音说：<d>[Chinese] 跟上。</d>" in projected

    def test_multiple_speakers_are_numbered_in_order_of_appearance(self):
        body = _structured_body(
            dialogue=[
                {"speaker": "老黄", "line": "跟上。"},
                {"speaker": "徐凤年", "line": "走。"},
                {"speaker": "老黄", "line": "慢些。"},
            ]
        )

        projected = project_video_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=5.0)

        assert "老黄（S1）说：<d>[Chinese] 跟上。</d>" in projected
        assert "徐凤年（S2）说：<d>[Chinese] 走。</d>" in projected
        assert projected.index("老黄（S1）说：<d>[Chinese] 跟上。</d>") < projected.index("徐凤年（S2）")
        assert projected.index("徐凤年（S2）") < projected.index("老黄（S1）说：<d>[Chinese] 慢些。</d>")

    def test_the_duration_sentence_lands_at_the_end_of_the_description(self):
        projected = project_video_prompt_to_h3(
            _structured_body(dialogue=[{"speaker": "老黄", "line": "跟上。"}]),
            has_start_image=True,
            has_end_image=False,
            duration_seconds=8.0,
        )

        description = projected.split("integrated_multimodal_description: ", 1)[1].split("\n\n", 1)[0]
        assert description.endswith("The shot lasts 8.00 seconds in total.")
        assert description.index("老黄（S1）说") < description.index("The shot lasts")

    def test_zero_duration_omits_the_sentence(self):
        projected = project_video_prompt_to_h3(
            _structured_body(), has_start_image=True, has_end_image=False, duration_seconds=0.0
        )

        assert "The shot lasts" not in projected

    def test_a_free_text_body_passes_through_untouched(self):
        body = "老黄蹒跚前行，镜头缓推。这不是 YAML。"

        assert project_video_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=5.0) == body

    def test_a_body_already_in_h3_form_passes_through_untouched(self):
        body = (
            "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully "
            "referenced.\n\nintegrated_multimodal_description: [Shot 1] ...\n\noverall_soundscape: ...\n\n"
            "non_diegetic_music: N/A"
        )

        assert project_video_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=5.0) == body

    def test_an_end_only_body_anchors_the_last_frame(self):
        projected = project_video_prompt_to_h3(
            _structured_body(), has_start_image=False, has_end_image=True, duration_seconds=5.0
        )

        assert "<Picture 1> (from [Shot 1]) aligns with the 5.00-second mark of the target video." in projected

    def test_a_camera_motion_outside_the_vocabulary_degrades_to_a_plain_sentence(self):
        body = _structured_body(camera_motion="未知运镜")

        projected = project_video_prompt_to_h3(body, has_start_image=True, has_end_image=False, duration_seconds=5.0)

        assert "The camera motion is 未知运镜." in projected


class TestProjectReference:
    """参考生视频三段论机器文本的 H3 投影。"""

    def _three_part_body(self) -> str:
        return "\n".join(
            [
                "<徐凤年>@图片1、<城墙外酒摊>@图片2。",
                "<徐凤年>的台词音色参考 @音频1，只取音色、语速与情绪，台词以正文为准，声音特征：清朗少年音。",
                "中景，轻微仰拍。<徐凤年> 在 <城墙外酒摊> 前驻足，<徐凤年>说 {这风比去年冷。}",
                "随后他低头望向远方，衣摆随风轻扬。",
                "Style: 古风水墨",
                "Visual style: 笔触克制、留白疏朗",
            ]
        )

    def test_the_three_part_prompt_becomes_the_three_h3_fields(self):
        projected = project_reference_prompt_to_h3(self._three_part_body())

        assert "integrated_multimodal_description: [Shot 1]" in projected
        assert "overall_soundscape: N/A" in projected
        assert "non_diegetic_music: N/A" in projected
        # 风格块织入描述开头
        assert "画面风格：古风水墨。" in projected
        assert "笔触克制、留白疏朗" in projected

    def test_bindings_become_picture_tags(self):
        projected = project_reference_prompt_to_h3(self._three_part_body())

        assert "<Picture 1> 在 <Picture 2> 前驻足" in projected
        assert "@图片" not in projected
        assert "<徐凤年>" not in projected

    def test_speech_marks_get_speaker_ids_and_the_d_tag(self):
        projected = project_reference_prompt_to_h3(self._three_part_body())

        assert "徐凤年（S1）以清朗少年音说：<d>[Chinese] 这风比去年冷。</d>" in projected
        # 声音声明行本身不下发
        assert "台词音色参考" not in projected

    def test_form_declarations_are_translated_before_the_description(self):
        body = "\n".join(
            [
                "<徐凤年>@图片1、<徐凤年/劲装>@图片2。",
                "<徐凤年>与<徐凤年/劲装>是同一角色的不同形态，各自按对应参考图呈现。",
                "<徐凤年> 拔剑，<徐凤年/劲装> 收势。",
            ]
        )

        projected = project_reference_prompt_to_h3(body)

        assert (
            "Pictures 1 and 2 show different appearances of the same character; each follows its own reference picture."
        ) in projected
        assert projected.index("Pictures 1 and 2") < projected.index("integrated_multimodal_description")
        assert "<Picture 1> 拔剑，<Picture 2> 收势。" in projected

    def test_unpictured_subjects_degrade_to_bare_names(self):
        body = "\n".join(
            [
                "<徐凤年>@图片1。",
                "<徐凤年> 回头，<画外老者>的叹息声起。",
            ]
        )

        projected = project_reference_prompt_to_h3(body)

        assert "<Picture 1> 回头，画外老者的叹息声起。" in projected

    def test_a_free_text_body_without_any_mark_passes_through(self):
        body = "一个人在雨中行走，镜头缓推。"

        assert project_reference_prompt_to_h3(body) == body

    def test_a_body_already_in_h3_form_passes_through(self):
        body = "integrated_multimodal_description: [Shot 1] ...\n\noverall_soundscape: N/A\n\nnon_diegetic_music: N/A"

        assert project_reference_prompt_to_h3(body) == body


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

    def test_an_h3_endpoint_projects_the_prompt_before_writing(self):
        body = _structured_body()
        built = build_workflow(
            self._h3_definition(),
            prompt=body + "\n\nAvoid: BGM、文字字幕、水印",
            aspect_ratio="16:9",
            duration_seconds=5,
            media=MediaInputs(start_image="start.png", end_image="end.png"),
        )

        written = built.workflow["1"]["inputs"]["prompt"]
        assert "integrated_multimodal_description: [Shot 1] 老黄蹒跚前行" in written
        assert "Picture 2 (from Shot 1) aligns with the 5.00-second mark" in written
        assert "Avoid:" not in written

    def test_a_reference_video_h3_endpoint_projects_the_three_part_prompt(self):
        definition = comfyui_endpoint_definition()
        definition["media_type"] = "video"
        definition["workflow"] = {
            "1": {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {
                    "clip": ["2", 0],
                    "prompt": ["3", 0],
                    "width": 1344,
                    "height": 768,
                    "length": 121,
                    "ref_images.ref_image_0": ["4", 0],
                },
            },
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl.safetensors", "type": "minimax"}},
            "3": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": ""}},
            "4": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
        }
        definition["bindings"] = {
            "prompt": [{"node": "3", "input": "value", "class_type": "PrimitiveStringMultiline", "title": "提示词"}],
            "frames": [{"node": "1", "input": "length", "class_type": "MiniMaxH3ReferenceToVideo", "step": 4}],
            "reference_images": [{"node": "4", "input": "image", "class_type": "LoadImage"}],
        }
        body = "<徐凤年>@图片1。\n<徐凤年> 拔剑。"

        built = build_workflow(
            definition,
            prompt=body + "\n\nAvoid: BGM",
            aspect_ratio="16:9",
            duration_seconds=5,
            media=MediaInputs(reference_images=["ref.png"]),
        )

        written = built.workflow["3"]["inputs"]["value"]
        assert "integrated_multimodal_description: [Shot 1] <Picture 1> 拔剑。" in written
        assert "overall_soundscape: N/A" in written
        assert "Avoid:" not in written

    def test_a_non_h3_endpoint_keeps_the_prompt_verbatim_even_with_keyframes(self):
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
