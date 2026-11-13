"""BETA-PUB Q6 (owner, 2026-11-12): on x86-64 the wide and the AVX2 Stockfish builds both
ship; the AVX2 one runs when the CPU reports AVX2 and it passes a probe search, and
anything else falls back to the wide build. These fail on the code before it (one build,
no choice)."""

import sys
from pathlib import Path

import pytest

import zugzwang.config as C
from zugzwang.core import engine_choice, engine_locator


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    engine_choice.choose.cache_clear()
    monkeypatch.delenv("ZUGZWANG_ENGINE_BUILD", raising=False)
    monkeypatch.delenv("ZUGZWANG_STOCKFISH", raising=False)
    yield
    engine_choice.choose.cache_clear()


def _builds(tmp_path):
    wide, fast = tmp_path / "stockfish", tmp_path / "stockfish-avx2"
    for p in (wide, fast):
        p.write_text("")
        p.chmod(0o755)
    return wide, fast


def _cpu(monkeypatch, avx2: bool, probe_ok: bool = True):
    seen = []
    monkeypatch.setattr(engine_choice, "cpu_has_avx2", lambda: avx2)
    monkeypatch.setattr(engine_choice, "probe", lambda p: seen.append(p) or probe_ok)
    return seen


def test_avx2_cpu_runs_the_avx2_build(tmp_path, monkeypatch):
    wide, fast = _builds(tmp_path)
    seen = _cpu(monkeypatch, True)
    assert engine_choice.choose(wide, fast)[0] == fast
    assert seen == [fast]


def test_no_avx2_falls_back_to_the_wide_build_without_running_the_other(tmp_path, monkeypatch):
    wide, fast = _builds(tmp_path)
    seen = _cpu(monkeypatch, False)
    path, why = engine_choice.choose(wide, fast)
    assert path == wide and "does not report AVX2" in why
    assert seen == []                       # never started on a CPU that lacks it


def test_a_failed_probe_falls_back_to_the_wide_build(tmp_path, monkeypatch):
    wide, fast = _builds(tmp_path)
    _cpu(monkeypatch, True, probe_ok=False)
    path, why = engine_choice.choose(wide, fast)
    assert path == wide and "failed its probe" in why


def test_the_tester_can_force_the_wide_build(tmp_path, monkeypatch):
    wide, fast = _builds(tmp_path)
    _cpu(monkeypatch, True)
    monkeypatch.setenv("ZUGZWANG_ENGINE_BUILD", "wide")
    assert engine_choice.choose(wide, fast)[0] == wide


def test_one_build_is_used_as_is(tmp_path, monkeypatch):
    wide, _ = _builds(tmp_path)
    seen = _cpu(monkeypatch, True)
    assert engine_choice.choose(wide, None) == (wide, "single build")
    assert seen == []


def test_find_stockfish_uses_the_choice(tmp_path, monkeypatch):
    wide, fast = _builds(tmp_path)
    _cpu(monkeypatch, True)
    monkeypatch.setattr(C, "BUNDLED_STOCKFISH", wide)
    monkeypatch.setattr(C, "BUNDLED_FAST_STOCKFISH", fast)
    assert engine_locator.find_stockfish() == fast
    engine_choice.choose.cache_clear()
    _cpu(monkeypatch, False)
    assert engine_locator.find_stockfish() == wide


@pytest.mark.parametrize("layout", ["macos", "windows"])
def test_the_packaged_avx2_build_is_found_beside_the_wide_one(monkeypatch, tmp_path, layout):
    exe_suffix = ".exe" if layout == "windows" else ""
    if layout == "macos":
        exe = tmp_path / "Z.app/Contents/Resources/sidecar/zugzwang-sidecar"
        sf = tmp_path / "Z.app/Contents/MacOS/stockfish-avx2"
        monkeypatch.setattr(C.sys, "platform", "darwin")
    else:
        exe = tmp_path / "Zugzwang/sidecar/zugzwang-sidecar.exe"
        sf = tmp_path / "Zugzwang/stockfish-avx2.exe"
        monkeypatch.setattr(C.sys, "platform", "win32")
    exe.parent.mkdir(parents=True)
    sf.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    sf.write_text("")
    sf.chmod(0o755)
    monkeypatch.setattr(C, "FROZEN", True)
    monkeypatch.setattr(C.sys, "executable", str(exe))
    assert C._bundled_fast_stockfish() == sf
    assert sf.name == f"stockfish-avx2{exe_suffix}"


def test_both_builds_are_pinned_by_hash_and_share_the_wide_builds_targets():
    assert set(C.STOCKFISH_FAST_ASSETS) == {("darwin", "x86_64"), ("windows", "x86_64")}
    for spec in C.STOCKFISH_FAST_ASSETS.values():
        assert "avx2" in spec["asset"] and len(spec["binary_sha256"]) == 64


def test_the_probe_rejects_something_that_is_not_an_engine():
    assert engine_choice.probe(Path(sys.executable), timeout=30) is False


def test_the_probe_accepts_the_real_engine():
    sf = C.BUNDLED_STOCKFISH
    if sf is None:
        pytest.skip("no Stockfish in stockfish/ (tools/get_stockfish.py)")
    assert engine_choice.probe(sf) is True


def test_avx2_detection_answers_a_bool():
    assert engine_choice.cpu_has_avx2() in (True, False)
