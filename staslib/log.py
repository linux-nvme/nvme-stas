# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''nvme-stas logging module'''

import sys
import logging
from staslib import defs


def init(syslog: bool):
    '''Init log module
    @param syslog: True to send messages to the syslog,
                   False to send messages to stdout.
    '''
    log = logging.getLogger()
    log.propagate = False

    if syslog:
        try:
            # Try journal logger first
            import systemd.journal

            handler = systemd.journal.JournalHandler(SYSLOG_IDENTIFIER=defs.PROG_NAME)
        except ModuleNotFoundError:
            # Go back to standard syslog handler
            from logging.handlers import SysLogHandler

            handler = SysLogHandler(address="/dev/log")
            handler.setFormatter(logging.Formatter(f'{defs.PROG_NAME}: %(message)s'))
    else:
        # Log to stdout
        handler = logging.StreamHandler(stream=sys.stdout)

    log.handlers.clear()  # Remove any pre-existing handlers before adding the new one
    log.addHandler(handler)
    log.setLevel(logging.INFO if syslog else logging.DEBUG)


def level() -> str:
    '''@brief return current log level'''
    logger = logging.getLogger()
    return str(logging.getLevelName(logger.getEffectiveLevel()))


def set_level_from_tron(tron):
    '''Set log level based on TRON'''
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if tron else logging.INFO)
