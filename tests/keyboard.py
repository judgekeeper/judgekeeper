"""The fake keyboard's empty answer (Enter), with a limit: a test that asks more than it
answers fails at once instead of hanging at a question forever."""

LIMIT = 50
_empty = [0]


def enter() -> str:
    _empty[0] += 1
    if _empty[0] > LIMIT:
        raise RuntimeError(f"more than {LIMIT} questions left unanswered: is a menu number "
                           "in the test wrong?")
    return ""


def reset() -> None:
    _empty[0] = 0
