"""tools/impact: change-impact engine (T-83).

Generic engine: no project paths, names or tables live in this package. Project
configuration is read from `impact.yml` and the registry it names.

Requires Python 3.13 or later: path matching uses `pathlib.PurePath.full_match`
(and the migration test uses `glob.translate`), both added in 3.13. Portability
to older Pythons is a T-93 concern.
"""

import sys

if sys.version_info < (3, 13):
    raise ImportError("tools.impact requires Python 3.13 or later (uses pathlib.PurePath.full_match)")

__version__ = "0.1.0"
