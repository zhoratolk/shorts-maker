# Testing Patterns

**Analysis Date:** 2026-07-07

## Test Framework

**Runner:**
- pytest `>=7.4.0` (`requirements-dev.txt`)
- Config: `pyproject.toml` `[tool.pytest.ini_options]`:
  ```toml
  [tool.pytest.ini_options]
  pythonpath = ["."]
  testpaths = ["tests"]
  markers = [
      "integration: real-ffmpeg smoke tests, no mocked subprocess - slower, needs ffmpeg on PATH",
  ]
  ```
  `pythonpath = ["."]` is what makes `from scripts.diarize import ...`-style imports work from `tests/` without an installed package or `src/`-layout.

**Assertion Library:** Plain `assert` (pytest's rewritten asserts) — no `unittest.TestCase`, no third-party assertion libs.

**Run Commands:**
```bash
pytest                      # everything, including real-ffmpeg integration tests (~30-40s extra)
pytest -m "not integration" # fast day-to-day loop, skips tests/test_integration_ffmpeg.py
```
(from `README.md`, "Running the tests" section)

## Environment Quirk — Cyrillic Windows Username Breaks pytest Defaults

**Not currently encoded anywhere in this repo** (no `pytest.ini`/`conftest.py`/CI config sets `--basetemp` or `-p no:cacheprovider`, and no mention in `README.md` or `docs/`) — but this is a known, real gotcha for this machine/environment and should be applied manually when running tests here:

- pytest's default cache (`.pytest_cache`) and `tmp_path` fixture both resolve through Windows' temp-file APIs, which can choke when the OS username contains non-ASCII (Cyrillic) characters — encoding/codepage mismatches surface as `UnicodeDecodeError`/`OSError`/permission errors when pytest tries to create its cache dir or a `tmp_path` under `C:\Users\<Cyrillic name>\AppData\Local\Temp\...`.
- **Workaround:** run pytest with the cache provider disabled and an explicit repo-local `--basetemp`:
  ```bash
  pytest -p no:cacheprovider --basetemp=.pytest_tmp
  ```
  (`.pytest_tmp` or similar should stay untracked/gitignored — it's disposable per-run scratch space.)
- If a future session hits `tmp_path`-related failures or `.pytest_cache` write errors under this repo, apply this flag combination before assuming it's a real test bug. Worth adding to `README.md`'s "Running the tests" section and/or a `tests/conftest.py`/`pytest.ini` `addopts` if it recurs, since it isn't codified yet.

## Test File Organization

**Location:** Separate `tests/` directory (not co-located with `scripts/`), mirroring module names:
```
scripts/diarize.py         -> tests/test_diarize.py
scripts/audio_energy.py    -> tests/test_audio_energy.py
scripts/transcribe.py      -> tests/test_transcribe.py
scripts/config.py          -> tests/test_config.py
scripts/setup.py           -> tests/test_setup.py
...
```
Plus two cross-cutting files:
- `tests/test_integration.py` — broader in-process integration test across modules (mocked subprocess).
- `tests/test_integration_ffmpeg.py` — real-ffmpeg smoke tests, marked `integration`, skip themselves if `ffmpeg`/`ffprobe` aren't on `PATH`.
- `tests/test_config_example.py` — validates `config.example.yaml` itself loads/parses correctly (config-as-data contract test).

**Naming:** `test_<module>.py` files; test functions `test_<unit_under_test>_<scenario>()`, e.g. `test_check_gpu_returns_cuda_when_nvidia_smi_succeeds`, `test_load_whisper_model_falls_back_to_cpu_on_gpu_failure`. Names read as full sentences describing behavior, not just the function name.

**Structure:** Flat — no test classes, just module-level `def test_...():` functions grouped by the function they exercise (adjacent in file order matching `scripts/*.py` definition order).

## Test Structure

**Suite Organization** (from `tests/test_setup.py`):
```python
from scripts.setup import (
    check_ffmpeg,
    check_gpu,
    check_python_deps,
    install_ffmpeg,
    install_python_deps,
)


def test_check_ffmpeg_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:/ffmpeg/ffmpeg.exe")
    assert check_ffmpeg() is True


def test_check_gpu_returns_cuda_when_nvidia_smi_succeeds():
    class FakeResult:
        returncode = 0

    def fake_runner(command, capture_output, check):
        return FakeResult()

    assert check_gpu(runner=fake_runner) == "cuda"
```

**Patterns:**
- No shared fixtures/`conftest.py` detected beyond pytest's built-ins (`tmp_path`, `monkeypatch`, `capsys`) — each test is self-contained.
- Arrange/act/assert with no explicit comments delineating sections; tests are short enough (3-10 lines) that the structure is implicit.
- Multiple small `test_X_scenario` functions per behavior rather than one parametrized mega-test, though direct value-table cases could use `@pytest.mark.parametrize` if introduced later (none currently in use — not a convention to break from without reason, but also not forbidden).

## Mocking

**Framework:** Pure pytest builtins — `monkeypatch` fixture. No `unittest.mock`/`pytest-mock` dependency in `requirements-dev.txt`.

**Patterns:**
1. **Injectable runner parameter** (preferred where the function signature allows it) — pass a fake callable directly instead of monkeypatching:
   ```python
   # scripts/diarize.py: extract_audio_wav(video_path, output_wav_path, runner=subprocess.run)
   def test_extract_audio_wav_invokes_ffmpeg():
       calls = []
       extract_audio_wav("in.mp4", "out.wav", runner=lambda *a, **k: calls.append((a, k)))
   ```
2. **`monkeypatch.setattr` on module attributes** for things without an injection point, e.g. `monkeypatch.setattr("shutil.which", lambda name: "C:/ffmpeg/ffmpeg.exe")`, `monkeypatch.setattr(transcribe_module.sys, "platform", "linux")`, `monkeypatch.setattr("scripts.setup.check_gpu", lambda: "cuda")`.
3. **`monkeypatch.setitem(sys.modules, ...)`** to fake optional/heavy third-party imports without installing them, e.g. `tests/test_transcribe.py`:
   ```python
   monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
   monkeypatch.setitem(sys.modules, "nvidia", None)  # simulate "package not installed"
   ```
   This is the standard way this codebase tests the lazy/deferred-import pattern (see CONVENTIONS.md) without needing `pyannote.audio`, `torch`, `nvidia-*`, or `faster_whisper` actually installed in the test environment.
4. **Fake result/exception classes** for subprocess-style call shapes, e.g. `class FakeResult: returncode = 0` in `tests/test_setup.py`, or raising `subprocess.CalledProcessError`/`FileNotFoundError` directly from a fake runner to simulate real failure modes.
5. **`capsys`** to assert on printed `[warn] ...` messages (fail-open paths), e.g. `test_load_whisper_model_falls_back_to_cpu_on_gpu_failure(monkeypatch, capsys)`.

**What to Mock:** subprocess calls (`ffmpeg`, `nvidia-smi`), optional third-party packages not required for the unit under test (`pyannote.audio`, `torch`, `nvidia`, `faster_whisper`), filesystem/platform facts (`sys.platform`, `shutil.which`).

**What NOT to Mock:** ffmpeg's actual filter-graph behavior for rendering correctness — that's explicitly *not* mocked in `tests/test_integration_ffmpeg.py`, which runs real ffmpeg because "a broken filter_complex/expression syntax ... a string assertion can't catch" bugs that mocked-subprocess unit tests would miss.

## Fixtures and Factories

**Test Data:** No dedicated fixtures directory or factory library. Test data is constructed inline per-test using `tmp_path` (pytest builtin) to create real temp files/dirs, and inline dicts/lists for transcript/segment fixtures, e.g.:
```python
def test_is_cached_true_when_present(tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    ...
```

**Location:** N/A — no `tests/fixtures/` or `tests/factories.py` present.

## Coverage

**Requirements:** None enforced — no coverage tool (`pytest-cov`, `coverage.py`) in `requirements-dev.txt`, no coverage config/badge/threshold anywhere in the repo.

**View Coverage:**
```bash
# Not currently supported out of the box; would require adding pytest-cov first:
pip install pytest-cov
pytest --cov=scripts --cov-report=term-missing
```

## Test Types

**Unit Tests:** The overwhelming majority — one `tests/test_<module>.py` per `scripts/<module>.py`, exercising pure functions and mocked-subprocess/mocked-import boundaries.

**Integration Tests:**
- `tests/test_integration.py` — broader cross-module flow, still with mocked subprocess.
- `tests/test_integration_ffmpeg.py` — marked `integration` via `pyproject.toml`'s pytest marker; runs real `ffmpeg`/`ffprobe` end-to-end for filter-graph correctness that string-assertion unit tests can't catch. Self-skips if `ffmpeg`/`ffprobe` aren't on `PATH`. Excluded from the fast loop via `pytest -m "not integration"`.

**E2E Tests:** Not used — the actual end-to-end pipeline is orchestrated by Claude Code reading `SKILL.md` and shelling out to these scripts; there's no automated E2E harness for that orchestration layer.

## Common Patterns

**Async Testing:** Not applicable — no async code in this codebase (`faster-whisper`, `subprocess`, `pyannote.audio` calls are all synchronous/blocking).

**Error/Exit-code Testing (argparse-style):**
```python
# pattern used for scripts/*.py CLI validation errors, e.g. diarize.py main()'s
# parser.error(...) calls — test via SystemExit and captured stderr, or by testing
# the underlying pure function directly instead of going through main()/argparse.
```

**Fail-open Warning Testing:**
```python
# tests/test_transcribe.py: test_load_whisper_model_falls_back_to_cpu_on_gpu_failure(monkeypatch, capsys)
# forces the GPU path to raise, then asserts:
#   - CPU fallback build_and_warm_up("cpu", "int8") was actually invoked
#   - captured stdout contains the "[warn] failed to load Whisper model on GPU" message
# This is the standard shape for testing any fail-open behavior in this codebase:
# force the failure, assert the degraded-but-successful return value, assert the
# warning text was printed.
```

---

*Testing analysis: 2026-07-07*
