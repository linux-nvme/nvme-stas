# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module defines the Transport Identifier Object, which is used
throughout nvme-stas to uniquely identify a Controller'''

import hashlib
from staslib import conf


class TID:
    '''Transport Identifier'''

    RDMA_IP_PORT = '4420'
    DISC_IP_PORT = '8009'

    def __init__(self, cid: dict):
        '''@param cid: Controller Identifier. A dictionary with the following
        contents.
        {
            # Transport parameters
            'transport':   str, # [mandatory]
            'traddr':      str, # [mandatory]
            'subsysnqn':   str, # [mandatory]
            'trsvcid':     str, # [optional]
            'host-traddr': str, # [optional]
            'host-iface':  str, # [optional]
            'host-nqn':    str, # [optional]

            # Connection parameters
            'dhchap-secret':      str, # [optional]
            'dhchap-ctrl-secret': str, # [optional]
            'hdr-digest':         str, # [optional]
            'data-digest':        str, # [optional]
            'nr-io-queues':       str, # [optional]
            'nr-write-queues':    str, # [optional]
            'nr-poll-queues':     str, # [optional]
            'queue-size':         str, # [optional]
            'kato':               str, # [optional]
            'reconnect-delay':    str, # [optional]
            'ctrl-loss-tmo':      str, # [optional]
            'disable-sqflow':     str, # [optional]
        }
        '''
        self._cfg = {
            k: v
            for k, v in cid.items()
            if k not in ('transport', 'traddr', 'subsysnqn', 'trsvcid', 'host-traddr', 'host-iface')
        }
        self._transport = cid.get('transport', '')
        self._traddr = cid.get('traddr', '')
        self._trsvcid = ''
        if self._transport in ('tcp', 'rdma'):
            trsvcid = cid.get('trsvcid', None)
            self._trsvcid = (
                trsvcid if trsvcid else (TID.RDMA_IP_PORT if self._transport == 'rdma' else TID.DISC_IP_PORT)
            )
        sysconf = conf.SysConf()
        self._host_traddr = cid.get('host-traddr', '')
        self._host_iface = '' if conf.SvcConf().ignore_iface else cid.get('host-iface', '')
        self._host_nqn = cid.get('host-nqn', sysconf.hostnqn)
        self._subsysnqn = cid.get('subsysnqn', '')
        self._key = (
            self._transport,
            self._traddr,
            self._trsvcid,
            self._subsysnqn,
            self._host_traddr,
            self._host_iface,
            self._host_nqn,
        )
        self._hash = int.from_bytes(
            hashlib.md5(''.join(self._key).encode('utf-8')).digest(), 'big'
        )  # We need a consistent hash between restarts
        self._id = f'({self._transport}, {self._traddr}, {self._trsvcid}{", " + self._subsysnqn if self._subsysnqn else ""}{", " + self._host_iface if self._host_iface else ""}{", " + self._host_traddr if self._host_traddr else ""})'

    host_traddr = property(lambda self: self._host_traddr)
    host_iface = property(lambda self: self._host_iface)
    subsysnqn = property(lambda self: self._subsysnqn)
    transport = property(lambda self: self._transport)
    host_nqn = property(lambda self: self._host_nqn)
    trsvcid = property(lambda self: self._trsvcid)
    traddr = property(lambda self: self._traddr)
    cfg = property(lambda self: self._cfg)

    def as_dict(self):
        '''Return object members as a dictionary'''
        data = {
            'traddr': self.traddr,
            'trsvcid': self.trsvcid,
            'transport': self.transport,
            'subsysnqn': self.subsysnqn,
            'host-iface': self.host_iface,
            'host-traddr': self.host_traddr,
        }

        # When migrating an old last known config, some members may not
        # exist. Therefore retrieve them with getattr() to avoid a crash.
        cfg = getattr(self, '_cfg', None)
        if cfg:
            data.update(cfg)

        sysconf = conf.SysConf()
        data['host-nqn'] = getattr(self, '_host_nqn', sysconf.hostnqn)

        return data

    def __str__(self):
        return self._id

    def __repr__(self):
        return self._id

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self._key == other._key

    def __hash__(self):
        return self._hash
