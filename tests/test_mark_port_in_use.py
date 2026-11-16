"""`mark` whose page can't open on the port given: the Next line runs `mark` again, on any free
port."""

from __future__ import annotations

import socket

from tests.start_projects import split, table_project
from tests.test_front import flat, run


def test_mark_on_a_port_in_use_says_to_run_mark_on_any_free_port(tmp_path, capsys,
                                                                 monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    table_project(tmp_path, split(30, 30))
    monkeypatch.chdir(tmp_path)
    assert run(capsys, "--no-browser", "--port", "0")[0] == 0
    with socket.socket() as held:  # another program holds it
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        _code, out, err = run(capsys, "mark", "--port", str(port), "--no-browser")
    said = flat(out + err)
    assert f"Port {port} is in use" in said, said
    assert "`judgekeeper mark --port 0 --no-browser`" in said, said
