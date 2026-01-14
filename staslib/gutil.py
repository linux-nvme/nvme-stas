# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module provides utility functions (or classes) that simplify
the use of certain GLib/Gio/Gobject functions/resources.
'''

import logging
import socket
from gi.repository import Gio, GLib, GObject
from staslib import conf, iputil, trid


# ******************************************************************************
class GTimer:
    '''@brief Convenience class to wrap GLib timers'''

    def __init__(
        self, interval_sec: float = 0, user_cback=lambda: GLib.SOURCE_REMOVE, *user_data, priority=GLib.PRIORITY_DEFAULT
    ):  # pylint: disable=keyword-arg-before-vararg
        self._source = None
        self._interval_sec = float(interval_sec)
        self._user_cback = user_cback
        self._user_data = user_data
        self._priority = priority if priority is not None else GLib.PRIORITY_DEFAULT

    def _release_resources(self):
        self.stop()
        self._user_cback = None
        self._user_data = None

    def kill(self):
        '''@brief Used to release all resources associated with a timer.'''
        self._release_resources()

    def __str__(self):
        if self._source is not None:
            return f'{self._interval_sec}s [{self.time_remaining()}s]'

        return f'{self._interval_sec}s [off]'

    def _callback(self, *_):
        retval = self._user_cback(*self._user_data)
        if retval == GLib.SOURCE_REMOVE:
            self._source = None
        return retval

    def stop(self):
        '''@brief Stop timer'''
        if self._source is not None:
            self._source.destroy()
            self._source = None

    def start(self, new_interval_sec: float = -1.0):
        '''@brief Start (or restart) timer'''
        if new_interval_sec >= 0:
            self._interval_sec = float(new_interval_sec)

        if self._source is not None:
            self._source.set_ready_time(
                self._source.get_time() + (self._interval_sec * 1000000)
            )  # ready time is in micro-seconds (monotonic time)
        else:
            if self._interval_sec.is_integer():
                self._source = GLib.timeout_source_new_seconds(int(self._interval_sec))  # seconds resolution
            else:
                self._source = GLib.timeout_source_new(self._interval_sec * 1000.0)  # mili-seconds resolution

            self._source.set_priority(self._priority)
            self._source.set_callback(self._callback)
            self._source.attach()

    def clear(self):
        '''@brief Make timer expire now. The callback function
        will be invoked immediately by the main loop.
        '''
        if self._source is not None:
            self._source.set_ready_time(0)  # Expire now!

    def set_callback(self, user_cback, *user_data):
        '''@brief set the callback function to invoke when timer expires'''
        self._user_cback = user_cback
        self._user_data = user_data

    def set_timeout(self, new_interval_sec: float):
        '''@brief set the timer's duration'''
        if new_interval_sec >= 0:
            self._interval_sec = float(new_interval_sec)

    def get_timeout(self):
        '''@brief get the timer's duration'''
        return self._interval_sec

    def time_remaining(self) -> float:
        '''@brief Get how much time remains on a timer before it fires.'''
        if self._source is not None:
            delta_us = self._source.get_ready_time() - self._source.get_time()  # monotonic time in micro-seconds
            if delta_us > 0:
                return delta_us / 1000000.0

        return 0


# ******************************************************************************
class NameResolver:  # pylint: disable=too-few-public-methods
    '''@brief DNS resolver to convert host names to IP addresses.'''

    def __init__(self):
        self._resolver = Gio.Resolver.get_default()

    def resolve_ctrl_async(self, cancellable, controllers_in: list, callback):
        '''@brief The traddr fields may specify a hostname instead of an IP
        address. We need to resolve all the host names to addresses.
        Resolving hostnames may take a while as a DNS server may need
        to be contacted. For that reason, we're using async APIs with
        callbacks to resolve all the hostnames.

        The callback @callback will be called once all hostnames have
        been resolved.

        @param controllers_in: List of trid.TID
        '''
        pending_resolution_count = 0
        controllers_out = []
        service_conf = conf.SvcConf()

        def addr_resolved(resolver, result, controller):
            try:
                addresses = resolver.lookup_by_name_finish(result)  # List of Gio.InetAddress objects

            except GLib.GError as err:
                # We don't need to report "cancellation" errors.
                if err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    # pylint: disable=no-member
                    logging.debug('NameResolver.resolve_ctrl_async()  - %s %s', err.message, controller)
                else:
                    logging.error('%s', err.message)  # pylint: disable=no-member

                # if err.matches(Gio.resolver_error_quark(), Gio.ResolverError.TEMPORARY_FAILURE):
                # elif err.matches(Gio.resolver_error_quark(), Gio.ResolverError.NOT_FOUND):
                # elif err.matches(Gio.resolver_error_quark(), Gio.ResolverError.INTERNAL):

            else:
                traddr = None

                # If multiple addresses are returned (which is often the case),
                # prefer IPv4 addresses over IPv6.
                if 4 in service_conf.ip_family:
                    for address in addresses:
                        # There may be multiple IPv4 addresses. Pick 1st one.
                        if address.get_family() == Gio.SocketFamily.IPV4:
                            traddr = address.to_string()
                            break

                if traddr is None and 6 in service_conf.ip_family:
                    for address in addresses:
                        # There may be multiple IPv6 addresses. Pick 1st one.
                        if address.get_family() == Gio.SocketFamily.IPV6:
                            traddr = address.to_string()
                            break

                if traddr is not None:
                    logging.debug(
                        'NameResolver.resolve_ctrl_async()  - resolved \'%s\' -> %s', controller.traddr, traddr
                    )
                    cid = controller.as_dict()
                    cid['traddr'] = traddr
                    nonlocal controllers_out
                    controllers_out.append(trid.TID(cid))

            # Invoke callback after all hostnames have been resolved
            nonlocal pending_resolution_count
            pending_resolution_count -= 1
            if pending_resolution_count == 0:
                callback(controllers_out)

        for controller in controllers_in:
            if controller.transport in ('tcp', 'rdma'):
                hostname_or_addr = controller.traddr
                if not hostname_or_addr:
                    logging.error('Invalid traddr: %s', controller)
                else:
                    # Try to convert to an ipaddress object. If this
                    # succeeds, then we don't need to call the resolver.
                    ip = iputil.get_ipaddress_obj(hostname_or_addr)
                    if ip is None:
                        logging.debug('NameResolver.resolve_ctrl_async()  - resolving \'%s\'', hostname_or_addr)
                        pending_resolution_count += 1
                        self._resolver.lookup_by_name_async(hostname_or_addr, cancellable, addr_resolved, controller)
                    elif ip.version in service_conf.ip_family:
                        controllers_out.append(controller)
                    else:
                        logging.warning(
                            'Excluding configured IP address %s based on "ip-family" setting', hostname_or_addr
                        )
            else:
                controllers_out.append(controller)

        if pending_resolution_count == 0:  # No names are pending asynchronous resolution
            callback(controllers_out)


# ******************************************************************************
class _TaskRunner(GObject.Object):
    '''@brief This class allows running methods asynchronously in a thread.'''

    def __init__(self, user_function, *user_args):
        '''@param user_function: function to run inside a thread
        @param user_args: arguments passed to @user_function
        '''
        super().__init__()
        self._user_function = user_function
        self._user_args = user_args

    def communicate(self, cancellable, cb_function, *cb_args):
        '''@param cancellable: A Gio.Cancellable object that can be used to
                            cancel an in-flight async command.
        @param cb_function: User callback function to call when the async
                            command has completed.  The callback function
                            will be passed these arguments:

                                (runner, result, *cb_args)

                            Where:
                                runner: This _TaskRunner object instance
                                result: A GObject.Object instance that contains the result
                                cb_args: The cb_args arguments passed to communicate()

        @param cb_args: User arguments to pass to @cb_function
        '''

        def in_thread_exec(task, self, task_data, cancellable):  # pylint: disable=unused-argument
            if task.return_error_if_cancelled():
                return  # Bail out if task has been cancelled

            try:
                value = GObject.Object()
                value.result = self._user_function(*self._user_args)
                task.return_value(value)
            except Exception as ex:  # pylint: disable=broad-except
                task.return_error(GLib.Error(message=str(ex), domain=type(ex).__name__))

        task = Gio.Task.new(self, cancellable, cb_function, *cb_args)
        task.set_return_on_cancel(False)
        task.run_in_thread(in_thread_exec)
        return task

    def communicate_finish(self, result):
        '''@brief Use this function in your callback (see @cb_function) to
         extract data from the result object.

        @return On success (True, data, None),
        On failure (False, None, err: GLib.Error)
        '''
        try:
            success, value = result.propagate_value()
            return success, value.result, None
        except GLib.Error as err:
            return False, None, err


# ******************************************************************************
class AsyncTask:  # pylint: disable=too-many-instance-attributes
    '''Object used to manage an asynchronous GLib operation. The operation
    can be cancelled or retried.
    '''

    def __init__(self, on_success_callback, on_failure_callback, operation, *op_args):
        '''@param on_success_callback: Callback method invoked when @operation completes successfully
        @param on_failure_callback: Callback method invoked when @operation fails
        @param operation: Operation (i.e. a function) to execute asynchronously
        @param op_args: Arguments passed to operation
        '''
        self._cancellable = Gio.Cancellable()
        self._operation = operation
        self._op_args = op_args
        self._success_cb = on_success_callback
        self._fail_cb = on_failure_callback
        self._retry_tmr = None
        self._errmsg = None
        self._task = None
        self._fail_cnt = 0

    def _release_resources(self):
        if self._alive():
            self._cancellable.cancel()

        if self._retry_tmr is not None:
            self._retry_tmr.kill()

        self._operation = None
        self._op_args = None
        self._success_cb = None
        self._fail_cb = None
        self._retry_tmr = None
        self._errmsg = None
        self._task = None
        self._fail_cnt = None
        self._cancellable = None

    def __str__(self):
        return str(self.as_dict())

    def as_dict(self):
        '''Return object members as a dictionary'''
        info = {
            'fail count': self._fail_cnt,
            'completed': self._task.get_completed() if self._task else None,
            'alive': self._alive(),
        }

        if self._retry_tmr:
            info['retry timer'] = str(self._retry_tmr)

        if self._errmsg:
            info['error'] = self._errmsg

        return info

    def _alive(self):
        return self._cancellable and not self._cancellable.is_cancelled()

    def completed(self):
        '''@brief Returns True if the task has completed, False otherwise.'''
        return self._task is not None and self._task.get_completed()

    def cancel(self):
        '''@brief cancel async operation'''
        if self._alive():
            self._cancellable.cancel()

    def kill(self):
        '''@brief kill and clean up this object'''
        self._release_resources()

    def run_async(self, *args):
        '''@brief
        Method used to initiate an asynchronous operation with the
        Controller. When the operation completes (or fails) the
        callback method @_on_operation_complete() will be invoked.
        '''
        runner = _TaskRunner(self._operation, *self._op_args)
        self._task = runner.communicate(self._cancellable, self._on_operation_complete, *args)

    def retry(self, interval_sec, *args):
        '''@brief Tell this object that the async operation is to be retried
        in @interval_sec seconds.

        '''
        if self._retry_tmr is None:
            self._retry_tmr = GTimer()
        self._retry_tmr.set_callback(self._on_retry_timeout, *args)
        self._retry_tmr.start(interval_sec)

    def _on_retry_timeout(self, *args):
        '''@brief
        When an operation fails, the application has the option to
        retry at a later time by calling the retry() method. The
        retry() method starts a timer at the end of which the operation
        will be executed again. This is the method that is called when
        the timer expires.
        '''
        if self._alive():
            self.run_async(*args)
        return GLib.SOURCE_REMOVE

    def _on_operation_complete(self, runner, result, *args):
        '''@brief
        This callback method is invoked when the operation with the
        Controller has completed (be it successful or not).
        '''
        # The operation might have been cancelled.
        # Only proceed if it hasn't been cancelled.
        if self._operation is None or not self._alive():
            return

        success, data, err = runner.communicate_finish(result)

        if success:
            self._errmsg = None
            self._fail_cnt = 0
            self._success_cb(self, data, *args)
        else:
            self._errmsg = str(err)
            self._fail_cnt += 1
            self._fail_cb(self, err, self._fail_cnt, *args)


# ******************************************************************************
class Deferred:
    '''Implement a deferred function call. A deferred is a function that gets
    added to the main loop to be executed during the next idle slot.'''

    def __init__(self, func, *user_data):
        self._source = None
        self._func = func
        self._user_data = user_data

    def schedule(self):
        '''Schedule the function to be called by the main loop. If the
        function  is already scheduled, then do nothing'''
        if not self.is_scheduled():
            srce_id = GLib.idle_add(self._func, *self._user_data)
            self._source = GLib.main_context_default().find_source_by_id(srce_id)

    def is_scheduled(self):
        '''Check if deferred is currently scheduled to run'''
        return self._source and not self._source.is_destroyed()

    def cancel(self):
        '''Remove deferred from main loop'''
        if self.is_scheduled():
            self._source.destroy()
        self._source = None


# ******************************************************************************
class TcpChecker:  # pylint: disable=too-many-instance-attributes
    '''@brief Verify that a TCP connection can be established with an endpoint'''

    def __init__(
        self, traddr, trsvcid, host_iface, verbose, user_cback, *user_data
    ):  # pylint: disable=too-many-arguments
        self._user_cback = user_cback
        self._host_iface = host_iface
        self._user_data = user_data
        self._trsvcid = trsvcid
        self._traddr = iputil.get_ipaddress_obj(traddr, ipv4_mapped_convert=True)
        self._cancellable = None
        self._gio_sock = None
        self._native_sock = None
        self._verbose = verbose

    def connect(self):
        '''Attempt to connect'''
        self.close()

        # Gio has limited setsockopt() capabilities. To set SO_BINDTODEVICE
        # we need to use a generic socket.socket() and then convert to a
        # Gio.Socket() object to perform async connect operation within
        # the GLib context.
        family = socket.AF_INET if self._traddr.version == 4 else socket.AF_INET6
        self._native_sock = socket.socket(family, socket.SOCK_STREAM | socket.SOCK_NONBLOCK, socket.IPPROTO_TCP)
        if self._host_iface and isinstance(self._host_iface, str):
            self._native_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self._host_iface.encode('utf-8'))

        # Convert socket.socket() to a Gio.Socket() object
        try:
            self._gio_sock = Gio.Socket.new_from_fd(self._native_sock.fileno())  # returns None on error
        except GLib.Error as err:
            logging.error('Cannot create socket: %s', err.message)  # pylint: disable=no-member
            self._gio_sock = None

        if self._gio_sock is None:
            self._native_sock.close()
            raise RuntimeError(f'Unable to connect to {self._traddr}, {self._trsvcid}, {self._host_iface}')

        g_addr = Gio.InetSocketAddress.new_from_string(self._traddr.compressed, int(self._trsvcid))

        self._cancellable = Gio.Cancellable()

        g_sockconn = self._gio_sock.connection_factory_create_connection()
        g_sockconn.connect_async(g_addr, self._cancellable, self._connect_async_cback)

    def close(self):
        '''Terminate/Cancel current connection attempt and free resources'''
        if self._cancellable is not None:
            self._cancellable.cancel()
            self._cancellable = None

        if self._gio_sock is not None:
            try:
                self._gio_sock.close()
            except GLib.Error as err:
                logging.debug('TcpChecker.close() gio_sock.close  - %s', err.message)  # pylint: disable=no-member

            self._gio_sock = None

        if self._native_sock is not None:
            try:
                # This is expected to fail because the socket
                # is already closed by self._gio_sock.close() above.
                # This code is just for completeness.
                self._native_sock.close()
            except OSError:
                pass

            self._native_sock = None

    def _connect_async_cback(self, source_object, result):
        '''
        @param source_object: The Gio.SocketConnection object used to
        invoke the connect_async() API.
        '''
        try:
            connected = source_object.connect_finish(result)
        except GLib.Error as err:
            connected = False
            # We don't need to report "cancellation" errors.
            if err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                logging.debug('TcpChecker._connect_async_cback()  - %s', err.message)  # pylint: disable=no-member
            else:
                if self._verbose:
                    logging.info(
                        'Unable to verify TCP connectivity  - (%-10s %-14s %s): %s',
                        self._host_iface + ',',
                        self._traddr.compressed + ',',
                        self._trsvcid,
                        err.message,  # pylint: disable=no-member
                    )

        self.close()

        if self._user_cback is not None:
            self._user_cback(connected, *self._user_data)
