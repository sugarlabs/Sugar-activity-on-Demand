# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared test configuration.

The runtime smoke gate spawns a GTK subprocess for every accepted
source, which would slow the whole suite and make unrelated pipeline
tests display-dependent.  Keep it off by default; the runtime tests
that exercise the gate re-enable it explicitly.
"""

import os

os.environ.setdefault('AOD_RUNTIME_CHECK', 'off')
