"""统一的 JSON 读写工具，提供严格加载与原子写入。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

# Windows 上目标文件的并发读句柄不带 FILE_SHARE_DELETE，os.replace 会以 PermissionError
# (WinError 5) 失败——例如前端轮询项目详情时正读着 project.json。读者关句柄通常在毫秒级，
# 按这份退避序列短暂重试即可跨过；序列耗尽后最后一次尝试把真实异常抛给调用方。
# POSIX 上 rename 不受打开句柄影响，重试循环不会触发。
_REPLACE_RETRY_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


def load_json(path: Path) -> Any:
    """严格加载 JSON。异常直接抛出，调用方按业务需要做 try/except。"""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@contextmanager
def domain_error_on_value_error(
    factory: Callable[[ValueError], BaseException],
    *,
    extra_passthrough: tuple[type[BaseException], ...] = (),
) -> Generator[None]:
    """把业务解析调用抛出的 ``ValueError`` 转换为调用方指定的领域错误。

    ``json.JSONDecodeError`` 是 ``ValueError`` 子类，须先于通用 ``ValueError`` 分支放行——
    它代表 JSON 文件本身损坏（语法错误），与业务级非法值（如路径穿越、非法项目名）语义不同，
    不能被误判为后者、进而返回一个误导性的 4xx。放行后由调用方外层自行收口。
    `extra_passthrough` 追加调用方需要按同一理由豁免的其它 ``ValueError`` 子类（如读取非
    UTF-8 剧本文件时的 ``UnicodeDecodeError``，或调用方另有专属分支处理的领域异常）。
    """
    try:
        yield
    except (json.JSONDecodeError, *extra_passthrough):
        raise
    except ValueError as exc:
        raise factory(exc) from exc


def load_json_or_none(path: Path) -> Any | None:
    """容错加载 JSON：读取或解析失败返回 None。"""
    try:
        return load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def replace_with_retry(
    tmp_path: Path,
    path: Path,
    retry_delays: Sequence[float] = _REPLACE_RETRY_DELAYS,
) -> None:
    """``os.replace``，Windows 上目标被并发读句柄短暂占用时按 ``retry_delays`` 退避重试。"""
    for delay in retry_delays:
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(tmp_path, path)


def atomic_write_json(
    path: Path,
    data: Any,
    *,
    replace_retry_delays: Sequence[float] = _REPLACE_RETRY_DELAYS,
) -> None:
    """同目录 tempfile + os.replace 原子写入 JSON。

    替换前 fsync 临时文件：否则断电时目标可能被换成尚未落盘的空文件或半截文件，
    项目文件、剧本与版本记录读不出会拒绝整个项目（``docs/adr/0098``）。
    """
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".project.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        replace_with_retry(tmp_path, path, replace_retry_delays)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink()


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    replace_retry_delays: Sequence[float] = _REPLACE_RETRY_DELAYS,
) -> None:
    """同目录 tempfile + ``os.replace`` 原子恢复文件字节。

    多文件补偿事务在后续写入失败时需要逐字恢复已经替换的旧文件；重新序列化 JSON 会改变
    空白与键序，无法证明恢复的是提交前的 durable state，因此回滚走字节快照。
    """
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix=".rollback.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        replace_with_retry(tmp_path, path, replace_retry_delays)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with suppress(OSError):
                tmp_path.unlink()
