"""Write the synthetic sample inbox as a real .mbox file, dated relative to today.

Run: .venv/bin/python scripts/make_sample_mbox.py [output]
For the demo video: choose this file with "Choose email files" instead of the sample button, so the
upload is visible on screen. Run it again just before recording so "by Friday" lines stay current.
All people and addresses are made up.
"""

import sys
from datetime import date
from pathlib import Path

from kept.services.sample_inbox import write_sample_mbox

DEFAULT_PATH = Path("data/sample-inbox.mbox")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    print(f"Wrote {write_sample_mbox(path, date.today())} synthetic emails to {path}")


if __name__ == "__main__":
    main()
