#!/usr/bin/env python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
import os
import sys
import uuid
from argparse import ArgumentParser
from staslib import defs

try:
    import hmac
    import hashlib
except (ImportError, ModuleNotFoundError):
    hmac = None
    hashlib = None


def read_from_file(fname, size):
    try:
        with open(fname) as f:
            data = f.read(size)
        if len(data) == size:
            return data
    except FileNotFoundError:
        pass

    return None

def get_machine_app_specific(app_id):
    ''' @brief Get a machine ID specific to an application. We use the
        value retrieved from /etc/machine-id. The documentation states that
        /etc/machine-id:
            "should be considered "confidential", and must not be exposed in
             untrusted environments, in particular on the network. If a stable
             unique identifier that is tied to the machine is needed for some
             application, the machine ID or any part of it must not be used
             directly. Instead the machine ID should be hashed with a crypto-
             graphic, keyed hash function, using a fixed, application-specific
             key. That way the ID will be properly unique, and derived in a
             constant way from the machine ID but there will be no way to
             retrieve the original machine ID from the application-specific one"

        @note systemd's C function sd_id128_get_machine_app_specific() was the
              inspiration for this code.

        @ref https://www.freedesktop.org/software/systemd/man/machine-id.html
    '''
    if not hmac:
        return None

    data = read_from_file('/etc/machine-id', 32)
    if not data:
        return None

    m = hmac.new(app_id, uuid.UUID(data).bytes, hashlib.sha256)
    id128_bytes = m.digest()[0:16]
    return str(uuid.UUID(bytes=id128_bytes, version=4))

def get_uuid_from_system():
    ''' @brief Try to find system UUID in the following order:
               1) /etc/machine-id
               2) /sys/class/dmi/id/product_uuid
               3) /proc/device-tree/ibm,partition-uuid
    '''
    uuid_str = get_machine_app_specific(b'$nvmexpress.org$')
    if uuid_str:
        return uuid_str

    # The following files are only readable by root
    if os.geteuid() != 0:
        sys.exit('Permission denied. Root privileges required.')

    id128 = read_from_file('/sys/class/dmi/id/product_uuid', 36)
    if id128:
        # Swap little-endian to network order per
        # DMTF SMBIOS 3.0 Section 7.2.1 System UUID.
        swapped = ''.join([id128[x] for x in (6,7,4,5,2,3,0,1,8,11,12,9,10,13,16,17,14,15)])
        return swapped + id128[18:]

    return read_from_file('/proc/device-tree/ibm,partition-uuid', 36)

def print_to_file_or_stdout(string, fname):
    if fname:
        with open(fname, 'w') as f:
            print(string, file=f)
    else:
        print(string)

def hostnqn(args):
    uuid_str = get_uuid_from_system() or str(uuid.uuid4())
    uuid_str = f'nqn.2014-08.org.nvmexpress:uuid:{uuid_str}'
    print_to_file_or_stdout(uuid_str, args.file)

def hostid(args):
    print_to_file_or_stdout(str(uuid.uuid4()), args.file)

def get_parser():
    parser = ArgumentParser(description='Utility program for STorage Appliance Services (STAS).')
    parser.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)

    subparser = parser.add_subparsers(title='Commands')

    prsr = subparser.add_parser('hostnqn', help='Generate host NQN')
    prsr.add_argument('-f', '--file', action='store', help='Optional file where to save the NQN. Print to screen when not specified.', type=str, metavar='FILE')
    prsr.set_defaults(cmd=hostnqn)

    prsr = subparser.add_parser('hostid', help='Generate host ID')
    prsr.add_argument('-f', '--file', action='store', help='Optional file where to save the ID. Print to screen when not specified.', type=str, metavar='FILE')
    prsr.set_defaults(cmd=hostid)

    return parser

PARSER = get_parser()
ARGS   = PARSER.parse_args()
if ARGS.version:
    print(f'{defs.PROJECT_NAME} {defs.VERSION}')
    sys.exit(0)

try:
    ARGS.cmd(ARGS)
except AttributeError as ex:
    print(str(ex))
    PARSER.print_usage()
