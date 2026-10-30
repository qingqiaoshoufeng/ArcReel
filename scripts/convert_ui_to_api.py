"""将 ComfyUI UI 图格式工作流转换为 ArcReel ComfyUI endpoint 定义（API 格式）。

处理步骤：
1. 解析 UI 格式（nodes/links 数组）
2. 解析 SetNode/GetNode（rgthree 变量传递）→ 直连
3. 解析 Reroute → bypass
4. 解析 bypass 的 LoraLoaderModelOnly → model 输入 pass-through
5. 激活 bypass 的 LoadImage（参考图槽位），跳过其余 mode=4 节点
6. 构建 API 格式 workflow（class_type/inputs 字典）
7. 打断 prompt/width/height/length 的连线，设为字面值以供 ArcReel 绑定
8. 从产物节点正向追溯，清理不可达的孤立节点
9. 手动设置 bindings
"""

import json
import os

INPUT_PATH = r"D:\gc\yz-wenwu\YZ金鱼-MiniMax_H3_终极篇-文武双全v1.json"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "YZ_H3_wenwu_comfyui_endpoint.json")

# 非执行节点类型 — 始终不出现在 API 格式中
ALWAYS_SKIP_TYPES = {"SetNode", "GetNode", "Reroute", "Note", "MarkdownNote", "Text", "忽略多组孤海"}

# mode=4 也需要激活的类型（其 bypass 不代表"关闭"，而是"未使用"）
ACTIVATE_DESPITE_BYPASS = {"LoadImage"}

# 非真实输入的 widget 名 — 排除出 API inputs
EXCLUDE_WIDGETS = {
    "upload",  # LoadImage 上传按钮
    "control_after_generate",  # 采样器 UI-only
    "Constant",  # SetNode/GetNode 变量名
    "guhai_ig",  # 忽略多组孤海
    "videopreview",  # VHS_VideoCombine 预览状态
}

# 打断后设为字面值的字段（在 MiniMaxH3ReferenceToVideo node 265 上）
LITERAL_OVERRIDES = {
    265: {  # MiniMaxH3ReferenceToVideo
        "prompt": "",
        "width": 1344,
        "height": 768,
        "length": 124,
    }
}


def load_ui(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_link_index(ui):
    """link_id -> {from_node, from_slot, to_node, to_slot, type}"""
    links = {}
    for link in ui["links"]:
        link_id, from_node, from_slot, to_node, to_slot, link_type = link
        links[link_id] = {
            "from_node": from_node,
            "from_slot": from_slot,
            "to_node": to_node,
            "to_slot": to_slot,
            "type": link_type,
        }
    return links


def build_setnode_map(ui, links):
    """constant_name -> (from_node, from_slot) — 从所有 SetNode（含 bypass）提取上游来源。"""
    set_sources = {}
    for node in ui["nodes"]:
        if node["type"] != "SetNode":
            continue
        wvn = node.get("widgets_values_named", {})
        const = wvn.get("Constant", "")
        if not const and node.get("widgets_values"):
            const = node["widgets_values"][0]
        for inp in node.get("inputs", []):
            if inp.get("link") is not None:
                link = links[inp["link"]]
                set_sources[const] = (link["from_node"], link["from_slot"])
                break
    return set_sources


def build_getnode_map(ui, set_sources):
    """getnode_id -> (from_node, from_slot) — GetNode 解析后的真实来源。"""
    getnode_map = {}
    for node in ui["nodes"]:
        if node["type"] != "GetNode":
            continue
        wvn = node.get("widgets_values_named", {})
        const = wvn.get("Constant", "")
        if not const and node.get("widgets_values"):
            const = node["widgets_values"][0]
        if const in set_sources:
            getnode_map[node["id"]] = set_sources[const]
    return getnode_map


def make_resolver(nodes_by_id, getnode_map, links):
    """返回 resolve_link 函数：沿 GetNode/Reroute/bypass-LoRA 链追溯到真实来源。"""

    def resolve_link(node_id, slot, _visited=None):
        if _visited is None:
            _visited = set()
        while node_id not in _visited:
            _visited.add(node_id)
            node = nodes_by_id.get(node_id)
            if node is None:
                break
            # GetNode → SetNode 的上游
            if node_id in getnode_map:
                node_id, slot = getnode_map[node_id]
                continue
            # Reroute → 输入 pass-through
            if node["type"] == "Reroute":
                found = False
                for inp in node.get("inputs", []):
                    if inp.get("link") is not None:
                        link = links[inp["link"]]
                        node_id = link["from_node"]
                        slot = link["from_slot"]
                        found = True
                        break
                if not found:
                    break
                continue
            # bypass 的 LoraLoaderModelOnly → model 输入 pass-through
            if node["type"] == "LoraLoaderModelOnly" and node.get("mode") == 4:
                model_inp = next(
                    (i for i in node.get("inputs", []) if i.get("name") == "model"),
                    None,
                )
                if model_inp and model_inp.get("link") is not None:
                    link = links[model_inp["link"]]
                    node_id = link["from_node"]
                    slot = link["from_slot"]
                    continue
                break
            break
        return node_id, slot

    return resolve_link


def determine_skipped(ui):
    """确定哪些节点不进入 API workflow。"""
    skipped = set()
    for node in ui["nodes"]:
        nid = node["id"]
        ntype = node["type"]
        mode = node.get("mode", 0)
        if ntype in ALWAYS_SKIP_TYPES or (mode == 4 and ntype not in ACTIVATE_DESPITE_BYPASS):
            skipped.add(nid)
    return skipped


def build_api_workflow(ui, links, resolve_link, skipped):
    """构建 API 格式 workflow 字典。"""
    api_workflow = {}

    for node in ui["nodes"]:
        nid = node["id"]
        if nid in skipped:
            continue

        node_id_str = str(nid)
        class_type = node["type"]
        inputs = {}

        # 1. 从 widgets_values_named 取字面值
        wvn = node.get("widgets_values_named", {})
        if wvn:
            for k, v in wvn.items():
                if k not in EXCLUDE_WIDGETS:
                    if isinstance(v, dict) and set(v.keys()) == {"__value__"}:
                        inputs[k] = v["__value__"]
                    else:
                        inputs[k] = v

        # 2. 有连线的 input 覆盖为 link 引用
        for inp in node.get("inputs", []):
            link_id = inp.get("link")
            if link_id is None:
                continue
            link = links.get(link_id)
            if link is None:
                continue
            from_node = link["from_node"]
            from_slot = link["from_slot"]
            # 追溯 GetNode/Reroute/bypass-LoRA 链
            resolved_node, resolved_slot = resolve_link(from_node, from_slot)
            # 跳过指向已移除节点的连线
            if resolved_node in skipped:
                continue
            input_name = inp.get("name", "")
            if input_name:
                inputs[input_name] = [str(resolved_node), resolved_slot]

        # 3. 应用字面值覆盖（打断 prompt/width/height/length 连线）
        if nid in LITERAL_OVERRIDES:
            inputs.update(LITERAL_OVERRIDES[nid])

        api_node = {"class_type": class_type, "inputs": inputs}
        title = node.get("title")
        if title:
            api_node["_meta"] = {"title": title}
        api_workflow[node_id_str] = api_node

    return api_workflow


def find_reachable(api_workflow, output_node_ids):
    """从产物节点出发，逆向追溯到所有可达节点。"""
    reachable = set()
    queue = list(output_node_ids)
    while queue:
        nid = queue.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        node = api_workflow.get(nid)
        if not node:
            continue
        queue.extend(
            v[0]
            for v in node.get("inputs", {}).values()
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)
        )
    return reachable


def remove_unreachable(api_workflow, output_node_ids):
    """移除从产物节点不可达的孤立节点。"""
    reachable = find_reachable(api_workflow, output_node_ids)
    removed = []
    for nid in list(api_workflow.keys()):
        if nid not in reachable:
            removed.append(f"  {nid} ({api_workflow[nid]['class_type']})")
            del api_workflow[nid]
    return removed


def build_bindings(nodes_by_id, links, resolve_link, skipped):
    """手动构建 bindings — 基于 workflow 结构分析。"""
    bindings = {
        "prompt": [
            {
                "node": "265",
                "input": "prompt",
                "class_type": "MiniMaxH3ReferenceToVideo",
                "direction": "write",
            }
        ],
        "negative_prompt": [],
        "start_image": [],
        "end_image": [],
        "reference_images": [],
        "width": [
            {
                "node": "265",
                "input": "width",
                "class_type": "MiniMaxH3ReferenceToVideo",
                "step": 32,
            }
        ],
        "height": [
            {
                "node": "265",
                "input": "height",
                "class_type": "MiniMaxH3ReferenceToVideo",
                "step": 32,
            }
        ],
        "frames": [
            {
                "node": "265",
                "input": "length",
                "class_type": "MiniMaxH3ReferenceToVideo",
                "fps": 24,
            }
        ],
        "fps": [
            {
                "node": "364",
                "input": "frame_rate",
                "class_type": "VHS_VideoCombine",
                "direction": "read",
            }
        ],
        "seed": [
            {
                "node": "397",
                "input": "seed",
                "class_type": "SelfLiftH3Sampler",
                "policy": "random",
            }
        ],
        "output": [
            {
                "node": "364",
                "class_type": "VHS_VideoCombine",
                "direction": "write",
            }
        ],
    }

    # reference_images: 追溯 9 个 ref_image 输入到 LoadImage 节点
    ref_node = nodes_by_id.get(265)
    if ref_node:
        for i in range(9):
            inp_name = f"ref_images.ref_image_{i}"
            inp = next(
                (x for x in ref_node.get("inputs", []) if x.get("name") == inp_name),
                None,
            )
            if not inp or inp.get("link") is None:
                continue
            link = links[inp["link"]]
            resolved_node, _ = resolve_link(link["from_node"], link["from_slot"])
            if resolved_node in skipped:
                continue
            resolved = nodes_by_id.get(resolved_node)
            if not resolved or resolved["type"] != "LoadImage":
                continue
            bindings["reference_images"].append(
                {
                    "node": str(resolved_node),
                    "input": "image",
                    "class_type": "LoadImage",
                    "direction": "write",
                    "consumer": {
                        "node": "265",
                        "input": inp_name,
                        "class_type": "MiniMaxH3ReferenceToVideo",
                    },
                }
            )

    return bindings


def main():
    ui = load_ui(INPUT_PATH)
    links = build_link_index(ui)
    nodes_by_id = {n["id"]: n for n in ui["nodes"]}

    set_sources = build_setnode_map(ui, links)
    getnode_map = build_getnode_map(ui, set_sources)
    resolve_link = make_resolver(nodes_by_id, getnode_map, links)

    skipped = determine_skipped(ui)
    api_workflow = build_api_workflow(ui, links, resolve_link, skipped)

    # 从产物节点(VHS_VideoCombine 364)出发清理不可达节点
    removed = remove_unreachable(api_workflow, ["364"])

    bindings = build_bindings(nodes_by_id, links, resolve_link, skipped)

    definition = {
        "kind": "comfyui",
        "schema_version": "1.0.0",
        "meta": {
            "name": "MiniMax H3 文武双全",
            "author": "YZ金鱼",
            "version": "1.0.0",
            "description": (
                "MiniMax H3 参考图/视频→视频生成工作流。含多模态参考输入（9图+3视频+3音频）、自举采样+超分、显存优化。"
            ),
        },
        "media_type": "video",
        "workflow": api_workflow,
        "bindings": bindings,
    }

    output_path = os.path.normpath(OUTPUT_PATH)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(definition, f, ensure_ascii=False, indent=2)

    # ── 汇报 ──
    print(f"输入: {INPUT_PATH}")
    print(f"输出: {output_path}")
    print(f"原始节点数: {len(ui['nodes'])}")
    print(f"跳过节点数: {len(skipped)}")
    print(f"清理不可达节点: {len(removed)}")
    if removed:
        for line in removed:
            print(line)
    print(f"API workflow 节点数: {len(api_workflow)}")
    print()
    print("Bindings 汇总:")
    for key, targets in bindings.items():
        if targets:
            desc = ", ".join(f"{t.get('node')}:{t.get('input', 'node')} ({t.get('class_type')})" for t in targets)
            print(f"  {key} ({len(targets)}): {desc}")
        else:
            print(f"  {key}: [] (不支持)")
    print()
    print("Workflow 节点类型统计:")
    type_counts = {}
    for node in api_workflow.values():
        ct = node["class_type"]
        type_counts[ct] = type_counts.get(ct, 0) + 1
    for ct, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {count:>3}  {ct}")


if __name__ == "__main__":
    main()
