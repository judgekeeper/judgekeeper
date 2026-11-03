"""An Inspect AI .eval log written with inspect_ai's own write_eval_log may list no sample ids
in its header (a log built by hand: real runs list them). inspect_ai reads such a log, so
judgekeeper reads it too: the samples the log holds. A log that lists ids still reads only
those, so one cut short is still caught."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")

from judgekeeper.readers import inspect_logs


def _write(path: Path, n: int, ids: list | None) -> Path:
    from inspect_ai.log import (
        EvalConfig,
        EvalDataset,
        EvalLog,
        EvalSample,
        EvalSpec,
        write_eval_log,
    )
    from inspect_ai.scorer import Score

    dataset = EvalDataset(name="arith", samples=n, **({} if ids is None else {"sample_ids": ids}))
    spec = EvalSpec(task="arith", model="mockllm/model", created="2026-11-03T11:00:00+00:00",
                    dataset=dataset, config=EvalConfig())
    samples = [EvalSample(id=i, epoch=1, input=f"What is {i} + {i}?", target=str(2 * i),
                          scores={"model_graded_qa": Score(value="C" if i % 3 else "I",
                                                           explanation=f"graded {i}")})
               for i in range(1, n + 1)]
    write_eval_log(EvalLog(eval=spec, samples=samples), str(path), format="eval")
    return path


@pytest.mark.parametrize("ids", [None, []], ids=["no-ids", "empty-ids"])
def test_a_log_written_by_inspect_with_no_sample_ids_is_read(tmp_path, ids):
    from inspect_ai.log import read_eval_log

    log = _write(tmp_path / "x.eval", 45, ids)
    assert len(read_eval_log(str(log)).samples) == 45  # inspect_ai's own reader reads it
    records = inspect_logs.read_inspect(log)
    assert len({r.target_id for r in records}) == 45
    assert [r.target_id for r in records] == [str(i) for i in range(1, 46)]
    assert Counter(r.label for r in records) == {"C": 30, "I": 15}


def test_a_log_that_lists_sample_ids_reads_only_those(tmp_path):
    log = _write(tmp_path / "x.eval", 10, list(range(1, 11)))
    assert len({r.target_id for r in inspect_logs.read_inspect(log)}) == 10
    short = _write(tmp_path / "short.eval", 10, list(range(1, 4)))
    assert len({r.target_id for r in inspect_logs.read_inspect(short)}) == 3
