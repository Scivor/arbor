"""
tests/test_weekly_daemon.py
F821 回归: run_daemon 不再引用 main() 局部变量 args（output_format 显式传参）
"""


import pytest

import scripts.weekly_report_daemon as daemon


def test_run_daemon_passes_output_format(monkeypatch, tmp_path):
    """run_daemon 循环一次：output_format 必须显式传给 generate_weekly_report"""
    calls = {}

    def fake_generate(output_dir, forecast_offset, output_format):
        calls["output_dir"] = output_dir
        calls["forecast_offset"] = forecast_offset
        calls["output_format"] = output_format

    sleeps = {"n": 0}

    def fake_sleep(seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:  # 生成后的 60s sleep → 跳出无限循环
            raise StopIteration

    monkeypatch.setattr(daemon, "generate_weekly_report", fake_generate)
    monkeypatch.setattr(daemon.time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        daemon.run_daemon(tmp_path, cron_hour=3, cron_minute=0, output_format="pdf")

    assert calls["output_format"] == "pdf"
    assert calls["forecast_offset"] == 1
    assert calls["output_dir"] == tmp_path


def test_run_daemon_default_format_is_both():
    """默认参数保持 both（与 main() 不传参时的历史行为一致）"""
    import inspect
    sig = inspect.signature(daemon.run_daemon)
    assert sig.parameters["output_format"].default == "both"
