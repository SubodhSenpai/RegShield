"""``python -m regression_shield``: the same as the ``regshield`` command."""

import sys

from regression_shield.cli import main

if __name__ == "__main__":
    sys.exit(main())
