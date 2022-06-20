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

LOG = logging.getLogger(__name__)  # Singleton
LOG.propagate = False


def get_log_handler(syslog: bool):
    '''Instantiate and return a log handler
    @param syslog: True to send messages to the syslog,
                   False to send messages to stdout.
    '''
    if syslog:
        try:
            # Try journal logger first
            import systemd.journal  # pylint: disable=redefined-outer-name,import-outside-toplevel

            handler = systemd.journal.JournalHandler(SYSLOG_IDENTIFIER=defs.PROG_NAME)
        except ModuleNotFoundError:
            # Go back to standard syslog handler
            from logging.handlers import SysLogHandler  # pylint: disable=import-outside-toplevel

            handler = SysLogHandler(address="/dev/log")
            handler.setFormatter(
                logging.Formatter('{}: %(message)s'.format(defs.PROG_NAME))  # pylint: disable=consider-using-f-string
            )
    else:
        # Log to stdout
        handler = logging.StreamHandler(stream=sys.stdout)

    return handler


def level() -> str:
    '''@brief return current log level'''
    return str(logging.getLevelName(LOG.getEffectiveLevel()))


def set_level_from_tron(tron: bool):
    '''@brief Set log level based on whether Tracing is ON (TRON)'''
    LOG.setLevel(logging.DEBUG if tron else logging.INFO)


# ******************************************************************************
def init(syslog: bool):
    '''Init log module'''
    LOG.addHandler(get_log_handler(syslog))
    LOG.setLevel(logging.INFO if syslog else logging.DEBUG)


def clean():
    '''Clean up log module'''
    global LOG  # pylint: disable=global-statement
    LOG = None
    logging.shutdown()
