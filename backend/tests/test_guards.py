""""测试: 死循环检测 + 工具超时"""
import pytest
import asyncio
from app.services.guards import detect_dead_loop, get_tool_fingerprint, get_tool_timeout


class TestDeadLoopDetection:
    def test_no_loop_short_history(self):
        history = ["fp_a", "fp_b"]
        assert detect_dead_loop(history) is False

    def test_no_loop_varied(self):
        history = ["fp_a", "fp_b", "fp_c", "fp_d"]
        assert detect_dead_loop(history) is False

    def test_dead_loop_detected(self):
        history = ["fp_a", "fp_a", "fp_a"]
        assert detect_dead_loop(history) is True

    def test_dead_loop_mixed(self):
        history = ["fp_a", "fp_b", "fp_a", "fp_a", "fp_a"]
        assert detect_dead_loop(history) is True


class TestToolFingerprint:
    def test_same_args_same_fingerprint(self):
        tc1 = {"name": "recall", "args": {"query": "天气"}}
        tc2 = {"name": "recall", "args": {"query": "天气"}}
        assert get_tool_fingerprint(tc1) == get_tool_fingerprint(tc2)

    def test_different_args_different_fingerprint(self):
        tc1 = {"name": "recall", "args": {"query": "天气"}}
        tc2 = {"name": "recall", "args": {"query": "咖啡"}}
        assert get_tool_fingerprint(tc1) != get_tool_fingerprint(tc2)


class TestToolTimeout:
    def test_known_timeout(self):
        assert get_tool_timeout("recall") == 60.0
        assert get_tool_timeout("query_sql") == 120.0

    def test_unknown_default(self):
        assert get_tool_timeout("unknown_tool") == 60.0
