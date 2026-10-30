import json
import os
import threading

import pytest

from lib.infra import json_io
from lib.infra.json_io import atomic_write_bytes, atomic_write_json


def test_atomic_write_json_fsyncs_temp_file_before_replace(tmp_path, monkeypatch):
    """替换前临时文件必须已落盘：断电时目标不会被换成空文件或半截文件。"""
    target = tmp_path / "project.json"
    target.write_text('{"old": true}', encoding="utf-8")
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def recording_fsync(fd):
        events.append("fsync")
        real_fsync(fd)

    def recording_replace(src, dst):
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(json_io.os, "fsync", recording_fsync)
    monkeypatch.setattr(json_io.os, "replace", recording_replace)

    atomic_write_json(target, {"title": "新内容"})

    assert events == ["fsync", "replace"]
    assert json.loads(target.read_text(encoding="utf-8")) == {"title": "新内容"}
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_json_retries_replace_on_permission_error(tmp_path, monkeypatch):
    """Windows 并发读句柄会让 os.replace 抛 PermissionError：应按退避重试直到读者放手。"""
    target = tmp_path / "project.json"
    target.write_text('{"old": true}', encoding="utf-8")
    real_replace = os.replace
    attempts: list[int] = []

    def flaky_replace(src, dst):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(5, "拒绝访问。")
        real_replace(src, dst)

    monkeypatch.setattr(json_io.os, "replace", flaky_replace)

    atomic_write_json(target, {"title": "新内容"}, replace_retry_delays=(0.0, 0.0))

    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"title": "新内容"}
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_json_raises_after_retries_exhausted(tmp_path, monkeypatch):
    """重试序列耗尽后真实异常照常抛出，目标不被破坏，临时文件不残留。"""
    target = tmp_path / "project.json"
    target.write_text('{"old": true}', encoding="utf-8")

    def always_denied(src, dst):
        raise PermissionError(5, "拒绝访问。")

    monkeypatch.setattr(json_io.os, "replace", always_denied)

    with pytest.raises(PermissionError):
        atomic_write_json(target, {"title": "新内容"}, replace_retry_delays=(0.0, 0.0))

    assert target.read_text(encoding="utf-8") == '{"old": true}'
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_bytes_retries_replace_on_permission_error(tmp_path, monkeypatch):
    """字节原子恢复与 JSON 写入共用重试路径。"""
    target = tmp_path / "data.bin"
    target.write_bytes(b"old")
    real_replace = os.replace
    attempts: list[int] = []

    def flaky_replace(src, dst):
        attempts.append(1)
        if len(attempts) < 2:
            raise PermissionError(5, "拒绝访问。")
        real_replace(src, dst)

    monkeypatch.setattr(json_io.os, "replace", flaky_replace)

    atomic_write_bytes(target, b"new", replace_retry_delays=(0.0,))

    assert len(attempts) == 2
    assert target.read_bytes() == b"new"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name != "nt", reason="只有 Windows 的并发读句柄会阻塞 os.replace")
def test_atomic_write_json_beats_concurrent_reader_lock_on_windows(tmp_path, monkeypatch):
    """前端轮询项目详情时正持有 project.json 的读句柄：写入方重试后应成功而非整单失败。"""
    target = tmp_path / "project.json"
    target.write_text('{"old": true}', encoding="utf-8")
    reader = open(target, "rb")  # noqa: SIM115 - 句柄要活到握手线程里再关，不能用 with 收口
    first_attempt_denied = threading.Event()
    real_replace = os.replace

    def replace_and_signal(src, dst):
        try:
            real_replace(src, dst)
        except PermissionError:
            first_attempt_denied.set()
            raise

    monkeypatch.setattr(json_io.os, "replace", replace_and_signal)
    outcome: list[BaseException | None] = []

    def write():
        try:
            atomic_write_json(target, {"title": "新内容"})
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)

    def close_reader_when_first_attempt_denied():
        first_attempt_denied.wait(timeout=10)
        reader.close()

    writer = threading.Thread(target=write)
    closer = threading.Thread(target=close_reader_when_first_attempt_denied)
    writer.start()
    closer.start()
    writer.join(timeout=30)
    closer.join(timeout=30)

    assert first_attempt_denied.is_set(), "读句柄没有触发 PermissionError，锁场景未复现"
    assert not writer.is_alive()
    assert not closer.is_alive()
    assert outcome == [None]
    assert json.loads(target.read_text(encoding="utf-8")) == {"title": "新内容"}
