from nanobot.exp.agent import warmup_runtime


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _close_all(coros):
    for coro in coros:
        coro.close()


def test_env_flag_accepts_common_true_values() -> None:
    assert warmup_runtime.env_flag("FLAG", env={"FLAG": "true"})
    assert warmup_runtime.env_flag("FLAG", env={"FLAG": "ON"})
    assert not warmup_runtime.env_flag("FLAG", env={"FLAG": "0"})


def test_external_warmup_not_scheduled_when_disabled() -> None:
    scheduled = []

    started = warmup_runtime.schedule_external_llm_warmup(
        already_started=False,
        schedule_background=scheduled.append,
        logger=_Logger(),
        env={"NANOBOT_LLM_WARMUP": "0"},
    )

    assert started is False
    assert scheduled == []


def test_external_warmup_schedules_once_when_enabled() -> None:
    scheduled = []

    started = warmup_runtime.schedule_external_llm_warmup(
        already_started=False,
        schedule_background=scheduled.append,
        logger=_Logger(),
        env={"NANOBOT_LLM_WARMUP": "1", "NANOBOT_LLM_WARMUP_DELAY_S": "0"},
        executable="python3",
    )
    started_again = warmup_runtime.schedule_external_llm_warmup(
        already_started=started,
        schedule_background=scheduled.append,
        logger=_Logger(),
        env={"NANOBOT_LLM_WARMUP": "1"},
    )

    assert started is True
    assert started_again is True
    assert len(scheduled) == 1
    _close_all(scheduled)


def test_tokenizer_warmup_schedules_once() -> None:
    scheduled = []

    started = warmup_runtime.schedule_tokenizer_warmup(
        already_started=False,
        schedule_background=scheduled.append,
        logger=_Logger(),
    )
    started_again = warmup_runtime.schedule_tokenizer_warmup(
        already_started=started,
        schedule_background=scheduled.append,
        logger=_Logger(),
    )

    assert started is True
    assert started_again is True
    assert len(scheduled) == 1
    _close_all(scheduled)
