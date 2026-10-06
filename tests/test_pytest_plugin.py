"""The pytest plugin: gate a report.json from a test, a marker or the command line.

Runs pytest inside pytest with `pytester`. The plugin is loaded through its `pytest11` entry
point, as it is for users; it only reads reports and never calls a judge.
"""

import shutil
from pathlib import Path

import pytest

GATE = Path(__file__).parent / "fixtures" / "gate"


@pytest.fixture
def reports(pytester):
    """The gate fixtures copied under the pytester root as reports/<name>.json."""
    dst = pytester.path / "reports"
    shutil.copytree(GATE, dst)
    return dst


def test_plugin_is_registered(pytester):
    result = pytester.runpytest("--help")
    result.stdout.fnmatch_lines(["*--judgekeeper-report*", "*--judgekeeper-baseline*"])
    result = pytester.runpytest("--markers")
    result.stdout.fnmatch_lines(["@pytest.mark.judgekeeper(report*"])


def test_fixture_pass(pytester, reports):
    pytester.makepyfile("""
        def test_judge(judgekeeper_gate):
            result = judgekeeper_gate("reports/pass.json")
            assert result["status"] == "PASS"
    """)
    pytester.runpytest().assert_outcomes(passed=1)


def test_fixture_fail_shows_the_gate_summary(pytester, reports):
    pytester.makepyfile("""
        def test_judge(judgekeeper_gate):
            judgekeeper_gate("reports/passes-everything.json")
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*## judgekeeper gate: FAIL*", "*Kappa mean 0.00 is below*",
                                 "*| kappa |*"])


def test_fixture_with_baseline_and_config(pytester, reports):
    pytester.makepyfile("""
        def test_drop(judgekeeper_gate):
            judgekeeper_gate("reports/kappa-drop-outside-band.json",
                             baseline="reports/baseline.json")

        def test_drop_with_loose_band(judgekeeper_gate):
            judgekeeper_gate("reports/kappa-drop-outside-band.json",
                             baseline="reports/baseline.json", config="loose.toml")
    """)
    pytester.makefile(".toml", loose="[gate]\nmin_band = 0.2\n")
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*test_drop FAILED*", "*dropped below 0.76*"])


@pytest.mark.parametrize("kwargs, outcome", [
    ("", "failed"),
    ("allow=('PASS', 'FLAKY')", "passed"),
    ("flaky_as='pass'", "passed"),
    ("flaky_as='fail'", "failed"),
])
def test_fixture_flaky(pytester, reports, kwargs, outcome):
    pytester.makepyfile(f"""
        def test_judge(judgekeeper_gate):
            judgekeeper_gate("reports/two-runs.json", {kwargs})
    """)
    result = pytester.runpytest()
    result.assert_outcomes(**{outcome: 1})
    if outcome == "failed":
        result.stdout.fnmatch_lines(["*judgekeeper gate: FLAKY*"])


def test_fixture_missing_report(pytester):
    pytester.makepyfile("""
        def test_judge(judgekeeper_gate):
            judgekeeper_gate("reports/nope.json")
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*judgekeeper gate: cannot read*nope.json*"])


def test_fixture_bad_option(pytester, reports):
    pytester.makepyfile("""
        def test_judge(judgekeeper_gate):
            judgekeeper_gate("reports/pass.json", flaky_as="maybe")
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*flaky_as must be*"])


def test_marker(pytester, reports):
    pytester.makepyfile("""
        import pytest

        @pytest.mark.judgekeeper(report="reports/pass.json")
        def test_good():
            pass

        @pytest.mark.judgekeeper(report="reports/passes-everything.json")
        def test_bad():
            raise AssertionError("the test body must not run when the gate fails")

        @pytest.mark.judgekeeper(report="reports/two-runs.json", flaky_as="pass")
        def test_flaky_allowed():
            pass

        @pytest.mark.judgekeeper(report="reports/kappa-drop-outside-band.json",
                                 baseline="reports/baseline.json")
        def test_drop():
            pass

        @pytest.mark.judgekeeper(report="reports/missing.json")
        def test_missing():
            pass
    """)
    result = pytester.runpytest("-v", "--strict-markers")
    result.assert_outcomes(passed=2, failed=3)
    result.stdout.fnmatch_lines(["*test_good PASSED*", "*test_bad FAILED*",
                                 "*test_flaky_allowed PASSED*", "*test_drop FAILED*",
                                 "*test_missing FAILED*"])
    result.stdout.no_fnmatch_line("*the test body must not run*")


def test_marker_paths_are_relative_to_the_rootdir(pytester, reports):
    sub = pytester.mkpydir("evals")
    (sub / "test_judge.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.judgekeeper(report='reports/pass.json')\n"
        "def test_good():\n    pass\n", encoding="utf-8")
    pytester.makeini("[pytest]\n")
    pytester.chdir()
    result = pytester.runpytest("evals")
    result.assert_outcomes(passed=1)


def test_marker_needs_a_report(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.mark.judgekeeper()
        def test_judge():
            pass
    """)
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*needs report=*"])


@pytest.mark.parametrize("args, outcome", [
    (["--judgekeeper-report", "reports/pass.json"], "passed"),
    (["--judgekeeper-report", "reports/passes-everything.json"], "failed"),
    (["--judgekeeper-report", "reports/kappa-drop-outside-band.json",
      "--judgekeeper-baseline", "reports/baseline.json"], "failed"),
    (["--judgekeeper-report", "reports/kappa-drop-inside-band.json",
      "--judgekeeper-baseline", "reports/baseline.json"], "passed"),
    (["--judgekeeper-report", "reports/two-runs.json"], "failed"),
    (["--judgekeeper-report", "reports/two-runs.json", "--judgekeeper-flaky-as", "pass"],
     "passed"),
    (["--judgekeeper-report", "reports/missing.json"], "failed"),
])
def test_command_line_gate_without_a_test(pytester, reports, args, outcome):
    result = pytester.runpytest(*args, "-v")
    result.assert_outcomes(**{outcome: 1})
    result.stdout.fnmatch_lines([f"*judgekeeper-gate {outcome.upper()}*"])
    if outcome == "failed":
        result.stdout.fnmatch_lines(["*judgekeeper gate*"])


def test_command_line_gate_runs_next_to_other_tests(pytester, reports):
    pytester.makepyfile("def test_other():\n    pass\n")
    result = pytester.runpytest("--judgekeeper-report", "reports/pass.json", "-v")
    result.assert_outcomes(passed=2)


def test_baseline_option_needs_a_report(pytester):
    result = pytester.runpytest("--judgekeeper-baseline", "b.json")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--judgekeeper-baseline*need --judgekeeper-report*"])


def test_default_baseline_is_picked_up(pytester, reports):
    """As with `judgekeeper gate`, .judgekeeper/baseline.json under the rootdir is the
    default baseline."""
    (pytester.path / ".judgekeeper").mkdir()
    shutil.copy(reports / "baseline.json", pytester.path / ".judgekeeper" / "baseline.json")
    pytester.makepyfile("""
        def test_drop(judgekeeper_gate):
            judgekeeper_gate("reports/kappa-drop-outside-band.json")
    """)
    pytester.runpytest().assert_outcomes(failed=1)
