#!/usr/bin/python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Dell Inc. or its subsidiaries.  All rights reserved.
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

'''Report which run-time Python modules nvme-stas needs are missing.

Invoked by the meson "check-deps" target (meson compile check-deps, or
ninja check-deps) with alternating module-name/install-hint pairs taken
from meson.build's py_modules_reqd list. Always exits 0: this is a report
for a human to read, not a gate - a missing module is not this script's
failure to report.
'''

import sys

modules = list(zip(sys.argv[1::2], sys.argv[2::2]))
missing = []
for name, hint in modules:
    try:
        __import__(name)
    except ImportError:
        missing.append((name, hint))

if not missing:
    print('All required run-time Python modules are installed.')
    sys.exit(0)

print('Missing run-time Python modules:')
for name, hint in missing:
    print(f'  {name}: {hint}')

apt_pkgs = ' '.join(f'python3-{name}' for name, _hint in missing)
print(f'\nOn Debian/Ubuntu, this should cover it:\n  sudo apt install {apt_pkgs}')
