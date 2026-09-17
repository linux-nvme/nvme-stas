# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module defines the Transport Identifier Object, which is used
throughout nvme-stas to uniquely identify a Controller'''

import inspect
import hashlib
from staslib import conf

# usedforsecurity was added to hashlib.md5 in Python 3.9. Pass it when available
# to suppress FIPS-mode rejection of MD5 (used here as a non-cryptographic hash).
# Using **_MD5_KWARGS avoids a static 3.9-only kwarg that would break older Python.
_MD5_KWARGS = {'usedforsecurity': False} if 'usedforsecurity' in inspect.signature(hashlib.md5).parameters else {}


def _hostid_from_hostnqn(hostnqn: str) -> str:
    '''Recover a host ID already encoded in a uuid:-form host NQN. This is
    a spec-based policy for nvme-stas only. nvme-cli/nvme-discoverd may
    behave differently.

    NVMe Base Specification 4.7's UUID-based NQN format embeds a 128-bit
    RFC 9562 UUID - the same type and size Fabrics requires for a Host
    Identifier (TP4110). TP4126 generates both fields from that same System
    UUID, so the two values are the same UUID by construction whenever the
    host NQN takes this form. This is not borrowing an identity from
    elsewhere; it is reading the one the host NQN already carries.

    Return '' if hostnqn has no "uuid:" component to recover one from.
    '''
    _, sep, uuid = hostnqn.partition('uuid:')
    return uuid if sep else ''


def _host_identity(cid: dict):
    '''Resolve the host NQN, host ID, and host symbolic name for a connection.

    If the connection specifies a host NQN, it defines its own host identity.
    In this case, use the host ID and symbolic name from the same connection
    configuration without falling back to the system defaults. A host ID
    missing from that same configuration may still be recovered from a
    uuid:-form host NQN (see _hostid_from_hostnqn()); if it cannot be, the
    host ID is left blank and the connection will fail at connect time with
    no fallback - a host NQN configured on its own is otherwise an incomplete
    identity, not a request to invent the rest of one.

    Otherwise, use the default identity from the main configuration. The host
    NQN and host ID are resolved independently, with each falling back to the
    corresponding /etc/nvme/hostnqn or /etc/nvme/hostid file.

    The host symbolic name follows the source of the host NQN. It is used only
    when the host NQN comes from the main configuration, and is not set when
    the NQN falls back to /etc/nvme/hostnqn.
    '''
    hostnqn = cid.get('hostnqn', '')
    if hostnqn:
        hostid = cid.get('hostid', '') or _hostid_from_hostnqn(hostnqn)
        return hostnqn, hostid, cid.get('hostsymname', '')

    conn_conf = conf.ConnConf()
    sysconf = conf.SysConf()
    hostid = conn_conf.hostid or sysconf.hostid
    if conn_conf.hostnqn:
        return conn_conf.hostnqn, hostid, conn_conf.hostsymname or ''

    return sysconf.hostnqn, hostid, ''


class TID:
    '''Transport Identifier'''

    RDMA_IP_PORT = '4420'
    DISC_IP_PORT = '8009'

    def __init__(self, cid: dict):
        '''Construct a TID from a controller identifier dict with the following keys:
        {
            # Transport parameters
            'transport':   str, # [mandatory]
            'traddr':      str, # [mandatory]
            'subsysnqn':   str, # [mandatory]
            'trsvcid':     str, # [optional]
            'host-traddr': str, # [optional]
            'host-iface':  str, # [optional]
            'hostnqn':     str, # [optional]
            'hostid':      str, # [optional]

            # Connection parameters
            'kxchap-secret':      str, # [optional]
            'kxchap-ctrl-secret': str, # [optional]
            'hdr-digest':         str, # [optional]
            'data-digest':        str, # [optional]
            'nr-io-queues':       str, # [optional]
            'nr-write-queues':    str, # [optional]
            'nr-poll-queues':     str, # [optional]
            'queue-size':         str, # [optional]
            'keep-alive-tmo':     str, # [optional]
            'reconnect-delay':    str, # [optional]
            'ctrl-loss-tmo':      str, # [optional]
            'disable-sqflow':     str, # [optional]
            'hostsymname':        str, # [optional]
        }
        '''
        self._cfg = {
            k: v
            for k, v in cid.items()
            if k
            not in (
                'transport',
                'traddr',
                'subsysnqn',
                'trsvcid',
                'host-traddr',
                'host-iface',
                'hostnqn',
                'hostid',
                'hostsymname',
            )
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
        self._hostnqn, self._hostid, hostsymname = _host_identity(cid)
        if hostsymname:
            # Unlike hostnqn/hostid, hostsymname is a display label with no
            # bearing on the connection - it stays a connection parameter,
            # not a dedicated field, and plays no part in _key.
            self._cfg['hostsymname'] = hostsymname
        self._subsysnqn = cid.get('subsysnqn', '')
        self._key = (
            self._transport,
            self._traddr,
            self._trsvcid,
            self._subsysnqn,
            self._host_traddr,
            self._host_iface,
            self._hostnqn,
            self._hostid,
        )
        self._hash = int.from_bytes(
            hashlib.md5(''.join(self._key).encode('utf-8'), **_MD5_KWARGS).digest(), 'big'
        )  # We need a consistent hash between restarts

        parts = [self._transport, self._traddr, self._trsvcid]
        if self._subsysnqn:
            parts.append(self._subsysnqn)
        if self._host_iface:
            parts.append(self._host_iface)
        if self._host_traddr:
            parts.append(self._host_traddr)
        self._id = '(' + ', '.join(parts) + ')'

    host_traddr = property(lambda self: self._host_traddr)
    host_iface = property(lambda self: self._host_iface)
    subsysnqn = property(lambda self: self._subsysnqn)
    transport = property(lambda self: self._transport)
    hostnqn = property(lambda self: self._hostnqn)
    hostid = property(lambda self: self._hostid)
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

        data['hostnqn'] = self._hostnqn if hasattr(self, '_hostnqn') else conf.SysConf().hostnqn

        # hostid used to live in _cfg rather than as its own field. A TID
        # pickled from that era already had it merged into data above by the
        # _cfg update; only fall further back to '' for a TID pickled before
        # hostid was tracked at all. hostsymname still lives in _cfg, so it
        # needs no equivalent handling here.
        data['hostid'] = getattr(self, '_hostid', data.get('hostid', ''))

        return data

    def __str__(self):
        return self._id

    def __repr__(self):
        return self._id

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self._key == other._key

    def __hash__(self):
        return self._hash
