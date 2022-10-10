# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

if readthedocs
    configure_file(
        input:         'conf.py.in',
        output:        'conf.py',
        configuration: conf,
    )
    foreach component : [ 'api.rst', 'index.rst', 'installation.rst', 'Makefile', 'quickstart.rst' ]
        configure_file(
            input:         component,
            output:        component,
            configuration: conf,
        )
    endforeach
endif
