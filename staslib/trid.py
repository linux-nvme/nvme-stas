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


class TID:  # pylint: disable=too-many-instance-attributes
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

            # Connection parameters
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
        self._host_traddr = cid.get('host-traddr', '')
        self._host_iface = '' if conf.SvcConf().ignore_iface else cid.get('host-iface', '')
        self._subsysnqn = cid.get('subsysnqn', '')
        self._key = (self._transport, self._traddr, self._trsvcid, self._subsysnqn, self._host_traddr, self._host_iface)
        self._hash = int.from_bytes(
            hashlib.md5(''.join(self._key).encode('utf-8')).digest(), 'big'
        )  # We need a consistent hash between restarts
        self._id = f'({self._transport}, {self._traddr}, {self._trsvcid}{", " + self._subsysnqn if self._subsysnqn else ""}{", " + self._host_iface if self._host_iface else ""}{", " + self._host_traddr if self._host_traddr else ""})'  # pylint: disable=line-too-long

    @property
    def transport(self):  # pylint: disable=missing-function-docstring
        return self._transport

    @property
    def traddr(self):  # pylint: disable=missing-function-docstring
        return self._traddr

    @property
    def trsvcid(self):  # pylint: disable=missing-function-docstring
        return self._trsvcid

    @property
    def host_traddr(self):  # pylint: disable=missing-function-docstring
        return self._host_traddr

    @property
    def host_iface(self):  # pylint: disable=missing-function-docstring
        return self._host_iface

    @property
    def subsysnqn(self):  # pylint: disable=missing-function-docstring
        return self._subsysnqn

    @property
    def cfg(self):  # pylint: disable=missing-function-docstring
        return self._cfg

    def as_dict(self):
        '''Return object members as a dictionary'''
        data = {
            'transport': self.transport,
            'traddr': self.traddr,
            'subsysnqn': self.subsysnqn,
            'trsvcid': self.trsvcid,
            'host-traddr': self.host_traddr,
            'host-iface': self.host_iface,
        }
        data.update(self._cfg)
        return data

    def __str__(self):
        return self._id

    def __repr__(self):
        return self._id

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self._key == other._key

    def __ne__(self, other):
        return not isinstance(other, self.__class__) or self._key != other._key

    def __hash__(self):
        return self._hash
