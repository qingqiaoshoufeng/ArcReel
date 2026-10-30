"""将转换后的 endpoint 定义导入 ArcReel 数据库。

插入两表：
1. custom_endpoint — 端点定义（kind=comfyui, media_type=video）
2. custom_provider_model — 关联到 ComfyUI provider (id=1) 的模型记录

端点 key 格式：ce-{custom_endpoint.id}
"""

import json
import sqlite3
from datetime import UTC, datetime

DB_PATH = "projects/arcreel.db"
DEFINITION_PATH = "YZ_H3_wenwu_comfyui_endpoint.json"
DISPLAY_NAME = "MiniMax H3 文武双全 Ref2VA 终极版（参考生视频）"
MODEL_ID = "MiniMax H3 文武双全 Ref2VA 终极版"
PROVIDER_ID = 1  # ComfyUI (192.168.110.90)
ENTRY_BINDING = "minimax/MiniMax-H3"


def main():
    with open(DEFINITION_PATH, encoding="utf-8") as f:
        definition = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 检查是否已存在同名端点
    cur.execute(
        "SELECT id FROM custom_endpoint WHERE display_name = ?",
        (DISPLAY_NAME,),
    )
    existing = cur.fetchone()
    if existing:
        print(f"端点已存在: id={existing['id']}, 覆盖更新定义...")
        endpoint_id = existing["id"]
        cur.execute(
            """UPDATE custom_endpoint
               SET definition = ?, kind = ?, schema_version = ?, media_type = ?,
                   display_name = ?, updated_at = ?
               WHERE id = ?""",
            (
                json.dumps(definition, ensure_ascii=False),
                definition["kind"],
                definition["schema_version"],
                definition["media_type"],
                DISPLAY_NAME,
                datetime.now(UTC).isoformat(),
                endpoint_id,
            ),
        )
    else:
        now = datetime.now(UTC).isoformat()
        cur.execute(
            """INSERT INTO custom_endpoint
               (definition, kind, schema_version, media_type, display_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                json.dumps(definition, ensure_ascii=False),
                definition["kind"],
                definition["schema_version"],
                definition["media_type"],
                DISPLAY_NAME,
                now,
                now,
            ),
        )
        endpoint_id = cur.lastrowid
        print(f"新端点已创建: id={endpoint_id}")

    endpoint_key = f"ce-{endpoint_id}"
    print(f"端点 key: {endpoint_key}")

    # 检查 provider model 是否已存在
    cur.execute(
        "SELECT id FROM custom_provider_model WHERE endpoint = ?",
        (endpoint_key,),
    )
    existing_model = cur.fetchone()

    # 能力覆盖：支持 1-15 秒时长
    capability_overrides = json.dumps({"durations": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]})

    now = datetime.now(UTC).isoformat()
    if existing_model:
        print(f"模型记录已存在: id={existing_model['id']}, 更新...")
        cur.execute(
            """UPDATE custom_provider_model
               SET model_id = ?, display_name = ?, capability_overrides = ?,
                   entry_binding = ?, updated_at = ?
               WHERE id = ?""",
            (MODEL_ID, MODEL_ID, capability_overrides, ENTRY_BINDING, now, existing_model["id"]),
        )
    else:
        cur.execute(
            """INSERT INTO custom_provider_model
               (provider_id, model_id, display_name, is_default, is_enabled,
                created_at, updated_at, endpoint, capability_overrides,
                path_overrides, multiplier, entry_binding)
               VALUES (?, ?, ?, 0, 1, ?, ?, ?, ?, 'null', 1.0, ?)""",
            (PROVIDER_ID, MODEL_ID, MODEL_ID, now, now, endpoint_key, capability_overrides, ENTRY_BINDING),
        )
        model_id = cur.lastrowid
        print(f"模型记录已创建: id={model_id}")

    conn.commit()

    # 验证
    cur.execute("SELECT id, display_name, kind, media_type FROM custom_endpoint WHERE id = ?", (endpoint_id,))
    row = cur.fetchone()
    print(f"\n端点验证: id={row['id']} name={row['display_name']} kind={row['kind']} media={row['media_type']}")

    cur.execute(
        """SELECT id, provider_id, model_id, display_name, endpoint, is_enabled, capability_overrides
           FROM custom_provider_model WHERE endpoint = ?""",
        (endpoint_key,),
    )
    row = cur.fetchone()
    print(
        f"模型验证: id={row['id']} provider={row['provider_id']} model={row['model_id']} endpoint={row['endpoint']} enabled={row['is_enabled']}"
    )
    print(f"  capability_overrides: {row['capability_overrides']}")

    # 列出所有端点
    print("\n=== 所有 ComfyUI 端点 ===")
    cur.execute(
        """SELECT ce.id, ce.display_name, cpm.endpoint, cpm.model_id, cpm.is_default
           FROM custom_endpoint ce
           LEFT JOIN custom_provider_model cpm ON cpm.endpoint = 'ce-' || ce.id
           WHERE ce.kind = 'comfyui'
           ORDER BY ce.id"""
    )
    for row in cur.fetchall():
        default = " [默认]" if row["is_default"] else ""
        print(f"  ce-{row['id']}: {row['display_name']} ({row['model_id']}){default}")

    conn.close()
    print(f"\n导入完成！重启 ArcReel 服务后即可在端点列表中看到 '{DISPLAY_NAME}'。")


if __name__ == "__main__":
    main()
