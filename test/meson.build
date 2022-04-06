# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

if modules_to_lint.length() != 0
    rcfile = join_paths(meson.current_source_dir(), 'pylint.rc')

    if pylint.found()
        test('pylint', pylint, args: ['--rcfile=' + rcfile] + modules_to_lint, env: stas_test_env)
    endif
    if pyflakes.found()
        test('pyflakes', pyflakes, args: modules_to_lint, env: stas_test_env)
    endif
endif

foreach module: modules_to_test
    fname = fs.name('@0@'.format(module))
    test('Unit test ' + fname, python3, args: module, env: stas_test_env)
endforeach
