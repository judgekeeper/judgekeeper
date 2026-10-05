"""pytest plugin: fail a test when `judgekeeper gate` would not pass a report.json.

Loaded through the `pytest11` entry point when judgekeeper is installed. Three ways in:

- the `judgekeeper_gate` fixture: `judgekeeper_gate("reports/x/report.json")`;
- the marker: `@pytest.mark.judgekeeper(report="reports/x/report.json")`, checked before the
  test body runs;
- the command line: `pytest --judgekeeper-report reports/x/report.json`, which adds one test.

Fixture and marker paths are relative to the pytest rootdir; command-line paths to the
directory pytest was started in. With no baseline or config, `.judgekeeper/baseline.json`
and `judgekeeper.toml` under the rootdir are used when present, as `judgekeeper gate` does.
The plugin only reads reports: it never calls a judge or an API, and writes nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ALLOW = ("PASS",)
FLAKY_AS = ("pass", "fail")


def _resolve(path, base: Path) -> Path | None:
    if path is None:
        return None
    path = Path(path)
    return path if path.is_absolute() else base / path


def _allowed(allow, flaky_as) -> set[str]:
    from judgekeeper.gate import FLAKY, STATUSES

    if flaky_as not in (None, *FLAKY_AS):
        pytest.fail(f"judgekeeper gate: flaky_as must be 'pass' or 'fail', not {flaky_as!r}",
                    pytrace=False)
    allowed = {allow} if isinstance(allow, str) else set(allow)
    unknown = sorted(allowed - set(STATUSES))
    if unknown:
        pytest.fail(f"judgekeeper gate: allow takes gate statuses ({', '.join(STATUSES)}), "
                    f"not {', '.join(unknown)}", pytrace=False)
    if flaky_as == "pass":
        allowed.add(FLAKY)
    elif flaky_as == "fail":
        allowed.discard(FLAKY)
    return allowed


def gate(report_path, baseline=None, config=None, allow=ALLOW, flaky_as=None, *,
         base: Path, root: Path) -> dict:
    """Run the gate on a report; pytest.fail with its markdown summary unless allowed."""
    from judgekeeper.gate import GateError, render_markdown, run_gate

    allowed = _allowed(allow, flaky_as)
    try:
        result = run_gate(_resolve(report_path, base), baseline=_resolve(baseline, base),
                          config=_resolve(config, base), root=root)
    except GateError as e:
        pytest.fail(f"judgekeeper gate: {e}", pytrace=False)
    if result["status"] not in allowed:
        pytest.fail(render_markdown(result), pytrace=False)
    return result


def pytest_addoption(parser):
    group = parser.getgroup("judgekeeper", "judgekeeper gate (reads report.json, no API calls)")
    group.addoption("--judgekeeper-report", metavar="PATH",
                    help="gate this report.json as one extra test")
    group.addoption("--judgekeeper-baseline", metavar="PATH",
                    help="baseline report for --judgekeeper-report (default "
                         ".judgekeeper/baseline.json under the rootdir, if present)")
    group.addoption("--judgekeeper-config", metavar="PATH",
                    help="gate thresholds TOML for --judgekeeper-report (default "
                         "judgekeeper.toml under the rootdir, if present)")
    group.addoption("--judgekeeper-flaky-as", choices=FLAKY_AS,
                    help="treat a FLAKY gate as a pass or a fail (default: fail)")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "judgekeeper(report, baseline=None, config=None, allow=('PASS',), flaky_as=None): "
        "fail the test unless `judgekeeper gate` allows the report (paths relative to the "
        "rootdir)")
    opt = config.option
    if opt.judgekeeper_report is None and (opt.judgekeeper_baseline or opt.judgekeeper_config
                                           or opt.judgekeeper_flaky_as):
        raise pytest.UsageError("--judgekeeper-baseline, --judgekeeper-config and "
                                "--judgekeeper-flaky-as need --judgekeeper-report")


@pytest.fixture
def judgekeeper_gate(request):
    """`judgekeeper_gate(report_path, baseline=None, config=None, allow=("PASS",),
    flaky_as=None)` gates a report.json and returns the gate result; the test fails with the
    gate's summary when the status is not allowed."""
    root = request.config.rootpath

    def run(report_path, baseline=None, config=None, allow=ALLOW, flaky_as=None) -> dict:
        return gate(report_path, baseline, config, allow, flaky_as, base=root, root=root)

    return run


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item):
    marker = item.get_closest_marker("judgekeeper")
    if marker is None:
        return
    kwargs = dict(marker.kwargs)
    if marker.args:
        kwargs.setdefault("report", marker.args[0])
    report = kwargs.pop("report", None)
    if report is None:
        pytest.fail("@pytest.mark.judgekeeper needs report=\"path/to/report.json\"",
                    pytrace=False)
    root = item.config.rootpath
    gate(report, **kwargs, base=root, root=root)


class GateItem(pytest.Item):
    """The test that --judgekeeper-report adds."""

    def runtest(self):
        opt = self.config.option
        base = self.config.invocation_params.dir
        gate(opt.judgekeeper_report, opt.judgekeeper_baseline, opt.judgekeeper_config,
             ALLOW, opt.judgekeeper_flaky_as, base=base, root=self.config.rootpath)

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, pytest.fail.Exception):
            return str(excinfo.value)
        return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.config.option.judgekeeper_report, None, "judgekeeper gate"


def pytest_collection_modifyitems(session, config, items):
    if config.option.judgekeeper_report is not None:
        items.append(GateItem.from_parent(session, name="judgekeeper-gate"))
