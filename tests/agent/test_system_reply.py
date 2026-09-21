from nanobot.agent import system_reply


def test_format_duration() -> None:
    assert system_reply.format_duration(0) == "0分钟"
    assert system_reply.format_duration(65) == "1分钟"
    assert system_reply.format_duration(3_900) == "1小时5分钟"
    assert system_reply.format_duration(90_000) == "1天1小时"


def test_fmt_bytes() -> None:
    assert system_reply.fmt_bytes(512) == "512 B"
    assert system_reply.fmt_bytes(1024) == "1.0 KiB"
    assert system_reply.fmt_kib(1024) == "1.0 MiB"


def test_format_memory_report_uses_runtime_sections(monkeypatch) -> None:
    monkeypatch.setattr(
        system_reply,
        "read_meminfo",
        lambda: {"MemTotal": 2 * 1024 * 1024, "MemAvailable": 1024 * 1024},
    )
    monkeypatch.setattr(system_reply, "read_cgroup_memory", lambda: (512 * 1024 * 1024, 1024 * 1024 * 1024))
    monkeypatch.setattr(system_reply, "read_process_rss", lambda: 128 * 1024)
    monkeypatch.setattr(system_reply.time, "time", lambda: 3_900)

    text = system_reply.format_memory_report(
        "test-model",
        0,
        {"prompt_tokens": 10, "cached_tokens": 5, "completion_tokens": 2},
    )

    assert "内存直查（未调用 LLM）" in text
    assert "宿主机：1.0 GiB / 2.0 GiB" in text
    assert "容器：512.0 MiB / 1.0 GiB" in text
    assert "nanobot 进程 RSS：128.0 MiB" in text
    assert "运行时长：1小时5分钟" in text
    assert "模型：test-model" in text
    assert "prompt 10" in text
