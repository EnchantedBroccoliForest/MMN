"""The loop-selection helper must be safe and report a known loop family."""

from mmn.runtime import active_loop_name


def test_active_loop_name_is_known():
    assert active_loop_name() in ("uvloop", "asyncio")


def test_active_loop_name_is_stable():
    assert active_loop_name() == active_loop_name()
