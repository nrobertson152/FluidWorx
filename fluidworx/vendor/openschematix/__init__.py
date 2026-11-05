"""OpenSchematix - free and open-source electrical, hydraulic and pneumatic schematic editor.

Copyright (C) 2026 Nate Robertson

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See the LICENSE file for details.
"""

APP_NAME = "OpenSchematix"
__version__ = "1.2.0"
VERSION = __version__
COPYRIGHT = "Copyright © 2026 Nate Robertson"
LICENSE_NAME = "GNU General Public License v3.0 or later"
LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"
DONATE_URL = "https://ko-fi.com/nr270343"

# Legacy single-drawing format (.osch, pre-1.0 development builds). 1.0 reads schema 1
# and can export a sheet as schema 2; projects use the .schematix container
# (see openschematix.projectio and docs/FILE_FORMAT.md).
FILE_FORMAT = "OpenSchematix"
FILE_SCHEMA = 3          # = model.SHEET_SCHEMA (3 adds boundary fills; written only when used)
FILE_EXTENSION = ".osch"
PROJECT_EXTENSION = ".schematix"
