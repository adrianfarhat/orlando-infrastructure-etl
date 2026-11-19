"""tools/impact: change-impact engine (T-83).

Generic engine: no project paths, names or tables live in this package. Project
configuration is read from `impact.yml` and the registry it names.

Requires Python 3.13 or later: path matching uses `pathlib.PurePath.full_match`
(and the migration test uses `glob.translate`), both added in 3.13. The command
line (`python -m tools.impact`) checks the version and exits with code 2 on an
older Python; the check is not done here, because an exception raised while
importing the package would make Python exit with code 1, which means "ERROR
findings". Portability to older Pythons is a T-93 concern.
"""

__version__ = "0.1.0"
REQUIRES_PYTHON = (3, 13)
