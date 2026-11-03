"""What the browser check says next, as the tool would: too few answers for a first result,
a file cut short, and the extra the tool needs for Inspect AI and MLflow."""

import sqlite3
import zipfile
from contextlib import closing

import pytest

from tests.test_freecheck_examples import _page_state, _text
from tests.test_freecheck_parity import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")

FEW = ("Next: a first result needs at least 30 answers, so run your eval to make more answers "
       "first (that makes model calls), then run judgekeeper in your project folder. You can "
       "mark these now: your marks are kept for when more answers come.")
MANY = ("Next: to see how often your LLM-as-a-judge agrees with you, run judgekeeper in your "
        "project folder and mark some answers.")
CUT_OFF = ("This file is cut off or damaged (it ends in the middle). Save it again from your "
           "eval tool.")
INSPECT = ('Inspect AI logs are read by the full tool, with its inspect extra: run '
           'uvx --from "judgekeeper[inspect]" judgekeeper in your project.')
MLFLOW = ('MLflow results are read by the full tool, with its mlflow extra: run '
          'uvx --from "judgekeeper[mlflow]" judgekeeper in your project.')
FULL_TOOL_NEXT = "Next: pick another file, or run that command in your project."


@pytest.mark.parametrize("example", ["promptfoo-results.json", "two-llm-as-a-judge-metrics.json"])
def test_an_example_with_too_few_answers_says_a_first_result_needs_30(example):
    (state,) = _page_state(f"click:{example}")
    assert state["output"].endswith(FEW) and "mark some answers" not in state["output"]


def test_an_example_with_enough_answers_says_to_mark_some():
    (state,) = _page_state("click:shop-answers.csv")
    assert state["output"].endswith(MANY)


def test_a_file_of_one_answer_says_a_first_result_needs_30(tmp_path):
    own = tmp_path / "results.csv"
    own.write_text("input,output,verdict\nq1,a1,pass\n", encoding="utf-8")
    (state,) = _page_state(f"file:{own}")
    assert state["output"].endswith(FEW)


def test_a_file_cut_short_says_so_as_the_tool_does(tmp_path):
    cut = tmp_path / "results.json"
    cut.write_text(_text("promptfoo-results.json")[:9000], encoding="utf-8")
    (state,) = _page_state(f"file:{cut}")
    assert CUT_OFF in state["output"] and "isn't valid JSON" not in state["output"]


def test_a_file_that_is_whole_but_not_json_says_it_is_not_json(tmp_path):
    bad = tmp_path / "results.json"
    bad.write_text('{"results": [1, 2,, 3]}', encoding="utf-8")
    (state,) = _page_state(f"file:{bad}")
    assert "This file isn't valid JSON that judgekeeper can read." in state["output"]


def test_an_inspect_log_names_the_command_with_its_extra(tmp_path):
    path = tmp_path / "2026-10-01_task.eval"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("header.json", '{"eval": {"task": "task"}}')
    (state,) = _page_state(f"file:{path}")
    assert INSPECT in state["output"] and state["output"].endswith(FULL_TOOL_NEXT)


def test_an_mlflow_store_names_the_command_with_its_extra(tmp_path):
    path = tmp_path / "mlflow.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE experiments (experiment_id INTEGER)")
        db.commit()
    (state,) = _page_state(f"file:{path}")
    assert MLFLOW in state["output"] and state["output"].endswith(FULL_TOOL_NEXT)
