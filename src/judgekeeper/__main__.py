"""`python -m judgekeeper`: the same entry point as the `judgekeeper` command.

For a machine where the install worked but the `judgekeeper` command is not on the PATH.
"""

import sys

from judgekeeper.cli import main

if __name__ == "__main__":
    sys.exit(main())
