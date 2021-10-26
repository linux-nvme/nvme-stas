#!/usr/bin/env python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' STorage Appliance Finder Daemon
'''
import os
import sys
from argparse import ArgumentParser
from staslib import defs

DBUS_IDL = '''
<node>
    <interface name="%s.debug">
        <property name="tron" type="b" access="readwrite"/>
        <property name="log_level" type="s" access="read"/>
        <method name="process_info">
            <arg direction="out" type="s" name="info_json"/>
        </method>
        <method name="controller_info">
            <arg direction="in" type="s" name="transport"/>
            <arg direction="in" type="s" name="traddr"/>
            <arg direction="in" type="s" name="trsvcid"/>
            <arg direction="in" type="s" name="host_traddr"/>
            <arg direction="in" type="s" name="host_iface"/>
            <arg direction="in" type="s" name="subsysnqn"/>
            <arg direction="out" type="s" name="info_json"/>
        </method>
    </interface>

    <interface name="%s">
        <method name="list_controllers">
            <arg direction="in" type="b" name="detailed"/>
            <arg direction="out" type="s" name="controller_list_json"/>
        </method>
        <method name="get_log_pages">
            <arg direction="in" type="s" name="transport"/>
            <arg direction="in" type="s" name="traddr"/>
            <arg direction="in" type="s" name="trsvcid"/>
            <arg direction="in" type="s" name="host_traddr"/>
            <arg direction="in" type="s" name="host_iface"/>
            <arg direction="in" type="s" name="subsysnqn"/>
            <arg direction="out" type="s" name="log_pages_json"/>
        </method>
        <method name="get_all_log_pages">
            <arg direction="in" type="b" name="detailed"/>
            <arg direction="out" type="s" name="log_pages_json"/>
        </method>
        <signal name="log_pages_changed">
          <arg direction="out" type="s" name="transport"/>
          <arg direction="out" type="s" name="traddr"/>
          <arg direction="out" type="s" name="trsvcid"/>
          <arg direction="out" type="s" name="host_traddr"/>
          <arg direction="out" type="s" name="host_iface"/>
          <arg direction="out" type="s" name="subsysnqn"/>
          <arg direction="out" type="s" name="device"/>
        </signal>
    </interface>
</node>
''' % (defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_NAME)

def parse_args(conf_file:str):
    parser = ArgumentParser(description=f'{defs.STAF_DESCRIPTION} ({defs.STAF_ACRONYM}). Must be root to run this program.')
    parser.add_argument('-f', '--conf-file', action='store', help='Configuration file (default: %(default)s)', default=conf_file, type=str, metavar='FILE')
    parser.add_argument('-s', '--syslog', action='store_true', help='Send messages to syslog instead of stdout. Use this when running %(prog)s as a daemon. (default: %(default)s)', default=False)
    parser.add_argument('--tron', action='store_true', help='Trace ON. (default: %(default)s)', default=False)
    parser.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)
    parser.add_argument('--idl', action='store', help='Print D-Bus IDL, then exit', type=str, metavar='FILE')
    return parser.parse_args()

ARGS = parse_args(defs.STAFD_CONFIG_FILE)

if ARGS.version:
    print(f'{defs.PROJECT_NAME} {defs.VERSION}')
    sys.exit(0)

if ARGS.idl:
    with open(ARGS.idl, 'w') as f:
        print(f'{DBUS_IDL}', file=f)
    sys.exit(0)


# There is a reason for having this import here and not at the top of the file.
# We want to allow running stafd with the --version and --idl options without
# having to import stas and avahi.
from staslib import stas, avahi # pylint: disable=wrong-import-position

# Before going any further, make sure the script is allowed to run.
stas.check_if_allowed_to_continue()


################################################################################
# Preliminary checks have passed. Let her rip!
# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order
import json
import dasbus.server.interface
import systemd.daemon
from gi.repository import GLib

LOG = stas.get_logger(ARGS.syslog, defs.STAFD_PROCNAME)
CNF = stas.get_configuration(ARGS.conf_file)
stas.trace_control(ARGS.tron or CNF.tron)

#*******************************************************************************
class Dc(stas.Controller):
    ''' @brief This object establishes a connection to one Discover Controller (DC).
               It retrieves the discovery log pages and caches them.
               It also monitors udev events associated with that DC and updates
               the cached discovery log pages accordingly.
    '''
    GET_LOG_PAGE_RETRY_RERIOD_SEC = 20

    def __init__(self, tid:stas.TransportId):
        super().__init__(tid, discovery_ctrl=True, register=stas.NVME_OPTIONS.register_supp)
        self._get_log_op = None
        self._log_pages  = list() # Log pages cache

    def _release_resources(self):
        LOG.debug('Dc._release_resources()            - %s | %s', self.id, self.device)
        super()._release_resources()
        self._log_pages  = list()
        if self._get_log_op:
            self._get_log_op.kill()
            self._get_log_op = None

    def _kill_ops(self):
        super()._kill_ops()
        if self._get_log_op:
            self._get_log_op.kill()
            self._get_log_op = None

    def info(self) -> dict:
        ''' @brief Get the controller info for this object
        '''
        info = super().info()
        if self._get_log_op:
            info['get log page operation'] = self._get_log_op.as_dict()
        return info

    def cancel(self):
        ''' @brief Used to cancel pending operations.
        '''
        super().cancel()
        if self._get_log_op:
            self._get_log_op.cancel()

    def disconnect(self, disconnected_cb):
        LOG.debug('Dc.disconnect()                    - %s | %s', self.id, self.device)
        self._kill_ops()
        if self._ctrl and self._ctrl.connected() and not CNF.persistent_connections:
            LOG.info('%s | %s - Disconnect initiated', self.id, self.device)
            op = stas.AsyncOperationWithRetry(self._on_disconnected_success, self._on_disconnected_fail, self._ctrl.disconnect)
            op.run_async(disconnected_cb)
        else:
            # Defer callback to the next main loop's idle period.
            GLib.idle_add(disconnected_cb, self.tid)

    def _on_disconnected_success(self, op_obj, data, disconnected_cb): # pylint: disable=unused-argument
        LOG.debug('Dc._on_disconnected_success()      - %s | %s', self.id, self.device)
        op_obj.kill()
        disconnected_cb(self.tid)

    def _on_disconnected_fail(self, op_obj, err, fail_cnt, disconnected_cb): # pylint: disable=unused-argument
        LOG.debug('Dc._on_disconnected_fail()         - %s | %s: %s', self.id, self.device, err)
        op_obj.kill()
        disconnected_cb(self.tid)

    def log_pages(self) -> list:
        ''' @brief Get the cached log pages for this object
        '''
        return self._log_pages

    def referrals(self) -> list:
        ''' @brief Return the list of referrals
        '''
        return [ page for page in self._log_pages if page['subtype'] == 'referral' ]

    def _on_udev_change(self, udev):
        super()._on_udev_change(udev)
        if self._get_log_op:
            self._get_log_op.run_async()

    def _on_udev_remove(self, udev):
        super()._on_udev_remove(udev)

        # Defer attempt to connect to the next main loop's idle period.
        GLib.idle_add(self._try_to_connect)

    def _find_existing_connection(self):
        return stas.UDEV.find_nvme_dc_device(self.tid)

    #--------------------------------------------------------------------------
    def _on_connect_success(self, op_obj, data):
        ''' @brief Function called when we successfully connect to the
                   Discovery Controller.
        '''
        super()._on_connect_success(op_obj, data)

        if self._alive():
            self._get_log_op = stas.AsyncOperationWithRetry(self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover)
            self._get_log_op.run_async()

    #--------------------------------------------------------------------------
    def _on_get_log_success(self, op_obj, data): # pylint: disable=unused-argument
        ''' @brief Function called when we successfully retrieve the log pages
                   from the Discovery Controller. See self._get_log_op object
                   for details.
        '''
        if self._alive():
            # Note that for historical reasons too long to explain, the CDC may
            # return invalid addresses ("0.0.0.0", "::", or ""). Those need to be
            # filtered out.
            referrals_before = self.referrals()
            self._log_pages = [ { k: str(v) for k,v in dictionary.items() } for dictionary in data if dictionary.get('traddr') not in ('0.0.0.0', '::', '') ] if data else list()
            LOG.info('%s | %s - Received discovery log pages (num records=%s).', self.id, self.device, len(self._log_pages))
            referrals_after = self.referrals()
            STAF.log_pages_changed(self, self.device)
            if referrals_after != referrals_before:
                LOG.debug('Dc._on_get_log_success()           - %s | %s Referrals before = %s', self.id, self.device, referrals_before)
                LOG.debug('Dc._on_get_log_success()           - %s | %s Referrals after  = %s', self.id, self.device, referrals_after)
                STAF.referrals_changed()
        else:
            LOG.debug('Dc._on_get_log_success()           - %s | %s Received event on dead object.', self.id, self.device)

    def _on_get_log_fail(self, op_obj, err, fail_cnt):
        ''' @brief Function called when we fail to retrieve the log pages
                   from the Discovery Controller. See self._get_log_op object
                   for details.
        '''
        if self._alive():
            LOG.debug('Dc._on_get_log_fail()              - %s | %s: %s. Retry in %s sec', self.id, self.device, err, Dc.GET_LOG_PAGE_RETRY_RERIOD_SEC)
            if fail_cnt == 1: # Throttle the logs. Only print the first time we fail to connect
                LOG.error('%s | %s - Failed to retrieve log pages. %s', self.id, self.device, err)
            op_obj.retry(Dc.GET_LOG_PAGE_RETRY_RERIOD_SEC)
        else:
            LOG.debug('Dc._on_get_log_fail()              - %s | %s Received event on dead object. %s', self.id, self.device, err)
            op_obj.kill()


#*******************************************************************************
class Staf(stas.Service):
    ''' STorage Appliance Finder (STAF)
    '''

    CONF_STABILITY_SOAK_TIME_SEC = 1.5

    class Dbus:
        ''' This is the DBus interface that external programs can use to
            communicate with stafd.
        '''
        __dbus_xml__ = DBUS_IDL

        @dasbus.server.interface.dbus_signal
        def log_pages_changed(self, transport:str, traddr:str, trsvcid:str, host_traddr:str, host_iface:str, subsysnqn:str, device:str):
            pass

        @property
        def tron(self):
            ''' @brief Get Trace ON property '''
            return stas.TRON

        @tron.setter
        def tron(self, value): # pylint: disable=no-self-use
            ''' @brief Set Trace ON property '''
            stas.trace_control(value)

        @property
        def log_level(self) -> str:
            ''' @brief Get Log Level property '''
            return stas.log_level()

        def process_info(self) -> str:
            ''' @brief Get status info (for debug)
                @return A string representation of a json object.
            '''
            info = {
                'tron': stas.TRON,
                'log-level': self.log_level,
            }
            info.update(STAF.info())
            return json.dumps(info)

        def controller_info(self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn) -> str: # pylint: disable=no-self-use,too-many-arguments
            controller = STAF.get_controller(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn)
            return json.dumps(controller.info()) if controller else '{}'

        def get_log_pages(self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn) -> str: # pylint: disable=no-self-use,too-many-arguments
            controller = STAF.get_controller(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn)
            return json.dumps(controller.log_pages()) if controller else '[]'

        def get_all_log_pages(self, detailed) -> str: # pylint: disable=no-self-use
            log_pages = list()
            for controller in STAF.get_controllers():
                log_pages.append({'discovery-controller': controller.details() if detailed else controller.controller_id_dict(),
                                  'log-pages': controller.log_pages()})
            return json.dumps(log_pages)

        def list_controllers(self, detailed) -> str: # pylint: disable=no-self-use
            ''' @brief Return the list of discovery controller IDs
            '''
            return json.dumps([ controller.details() if detailed else controller.controller_id_dict() for controller in STAF.get_controllers() ])


    #===========================================================================
    def __init__(self):
        super().__init__(self._reload_hdlr)

        # Check that the hostnqn and hostid are configured
        for file in ('/etc/nvme/hostnqn', '/etc/nvme/hostid'):
            if not os.path.exists(file):
                LOG.warning('Mising "/etc/nvme/hostnqn" and/or "/etc/nvme/hostid". %s will operate with reduced functionality.', defs.STAFD_PROCNAME)
                LOG.warning('Use stasadm to configure these files (see stasadm [hostnqn|hostid] -f /etc/nvme/[hostnqn|hostid])')
                break

        self._avahi = avahi.Avahi(LOG, self._sysbus, self._avahi_change)
        self._avahi.config_stypes(CNF.get_stypes())

        # We don't want to apply configuration changes to nvme-cli right away.
        # Often, multiple changes will occur in a short amount of time (sub-second).
        # We want to wait until there are no more changes before applying them
        # to the system. The following timer acts as a "soak period". Changes
        # will be applied by calling self._on_config_ctrls() at the end of
        # the soak period.
        self._cfg_soak_tmr = stas.GTimer(Staf.CONF_STABILITY_SOAK_TIME_SEC, self._on_config_ctrls)
        self._cfg_soak_tmr.start()

        # Create the D-Bus instance.
        self._config_dbus(Staf.Dbus(), defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)

    def info(self) -> dict:
        ''' @brief Get the status info for this object (used for debug)
        '''
        info = super().info()
        info['avahi'] = self._avahi.info()
        return info

    def _release_resources(self):
        LOG.debug('Staf._release_resources()')
        super()._release_resources()
        self._avahi.kill()
        self._avahi = None

    def _reload_hdlr(self):
        ''' @brief Reload configuration file. This is triggered by the SIGHUP
                   signal, which can be sent with "systemctl reload stafd".
        '''
        systemd.daemon.notify('RELOADING=1')
        CNF.reload()
        stas.trace_control(CNF.tron)
        self._avahi.config_stypes(CNF.get_stypes())
        self._cfg_soak_tmr.start()
        systemd.daemon.notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def log_pages_changed(self, controller, device):
        self._dbus_iface.log_pages_changed.emit(controller.tid.transport, controller.tid.traddr, controller.tid.trsvcid,
                                                controller.tid.host_traddr, controller.tid.host_iface, controller.tid.subsysnqn, device)

    def referrals_changed(self):
        LOG.debug('Staf.referrals_changed()')
        self._cfg_soak_tmr.start()

    def _referrals(self) -> list:
        return [ stas.cid_from_dlpe(dlpe, controller.tid.host_traddr, controller.tid.host_iface)
                 for controller in self.get_controllers() for dlpe in controller.referrals() ]

    def _config_ctrls_finish(self, configured_ctrl_list):
        ''' @brief Finish discovery controllers configuration after
                   hostnames (if any) have been resolved.
        '''
        configured_ctrl_list = [ ctrl_dict for ctrl_dict in configured_ctrl_list if 'traddr' in ctrl_dict
                                   and ctrl_dict.setdefault('subsysnqn', 'nqn.2014-08.org.nvmexpress.discovery') ]

        discovered_ctrl_list = self._avahi.get_controllers()
        referral_ctrl_list   = self._referrals()
        LOG.debug('Staf._config_ctrls_finish()        - configured_ctrl_list  = %s', configured_ctrl_list)
        LOG.debug('Staf._config_ctrls_finish()        - discovered_ctrl_list  = %s', discovered_ctrl_list)
        LOG.debug('Staf._config_ctrls_finish()        - referral_ctrl_list    = %s', referral_ctrl_list)

        controllers = stas.remove_blacklisted(configured_ctrl_list + discovered_ctrl_list + referral_ctrl_list)

        new_controller_ids = { stas.TransportId(controller) for controller in controllers }
        cur_controller_ids = set(self._controllers.keys())
        controllers_to_add = new_controller_ids - cur_controller_ids
        controllers_to_rm  = cur_controller_ids - new_controller_ids

        LOG.debug('Staf._config_ctrls_finish()        - controllers_to_add    = %s', list(controllers_to_add))
        LOG.debug('Staf._config_ctrls_finish()        - controllers_to_rm     = %s', list(controllers_to_rm))

        for tid in controllers_to_rm:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                controller.kill()

        for tid in controllers_to_add:
            self._controllers[tid] = Dc(tid)

    def _avahi_change(self):
        self._cfg_soak_tmr.start()

#*******************************************************************************
STAF = Staf()
STAF.run()

STAF = None
CNF  = None
LOG  = None
ARGS = None
