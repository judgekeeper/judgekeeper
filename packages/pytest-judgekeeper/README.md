# pytest-judgekeeper

This package has no code: it installs [judgekeeper](https://github.com/judgekeeper/judgekeeper), whose pytest plugin (the `judgekeeper_gate` fixture, the `judgekeeper` marker and `--judgekeeper-report`) is registered by judgekeeper itself.
It exists so the plugin shows up under its `pytest-` name on the pytest plugin list; `pip install judgekeeper` gives you the same thing.
