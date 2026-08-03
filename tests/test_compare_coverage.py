from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.compare_coverage import main


def write_coverage_report(path: Path, files: dict[str, list[int]]) -> None:
    classes = []
    for filename, hits in files.items():
        lines = "".join(
            f'<line number="{number}" hits="{hit}"/>'
            for number, hit in enumerate(hits, start=1)
        )
        classes.append(f'<class filename="{filename}"><lines>{lines}</lines></class>')
    path.write_text("<coverage><classes>" + "".join(classes) + "</classes></coverage>")


class CoverageComparisonTest(unittest.TestCase):
    def test_removed_plugins_are_excluded_from_both_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            baseline = directory / "baseline.xml"
            head = directory / "head.xml"
            write_coverage_report(
                baseline,
                {
                    "plugins/retained/src/plugin.py": [1, 0],
                    "plugins/removed/src/plugin.py": [1, 1],
                },
            )
            write_coverage_report(
                head,
                {"plugins/retained/src/plugin.py": [1, 0]},
            )
            output = io.StringIO()

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "compare_coverage.py",
                        "--baseline",
                        str(baseline),
                        "--head",
                        str(head),
                    ],
                ),
                redirect_stdout(output),
            ):
                main()

        self.assertIn("Comparable head coverage: 0.5000", output.getvalue())
        self.assertIn("Baseline coverage: 0.5000", output.getvalue())
        self.assertIn(
            "Removed plugins excluded from baseline comparison: removed",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
