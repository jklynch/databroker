from __future__ import print_function
import sys
import logging
import unittest
import threading
import random
import time
import copy

from contextlib import contextmanager

import numpy as np
from numpy.testing import assert_array_equal

import epics

from ophyd.signal import (Signal, EpicsSignal, EpicsSignalRO)
from ophyd.utils import (ReadOnlyError, TimeoutError)

logger = logging.getLogger(__name__)


class FakeEpicsPV(object):
    _connect_delay = (0.05, 0.1)
    _update_rate = 0.1
    fake_values = (0.1, 0.2, 0.3)
    _pv_idx = 0

    def __init__(self, pvname, form=None,
                 callback=None, connection_callback=None,
                 auto_monitor=True,
                 **kwargs):

        self._pvname = pvname
        self._callback = callback
        self._connection_callback = connection_callback
        self._form = form
        self._auto_monitor = auto_monitor
        self._value = self.fake_values[0]
        self._connected = False

        FakeEpicsPV._pv_idx += 1
        self._idx = FakeEpicsPV._pv_idx

        self._update = True

        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._update_loop)
        self._thread.setDaemon(True)
        self._thread.start()

        # callbacks mechanism copied from pyepics
        self.callbacks = {}

        if callback:
            self.add_callback(callback)

    def get_ctrlvars(self):
        pass

    @property
    def connected(self):
        return self._connected

    def wait_for_connection(self, timeout=None):
        if self._pvname in ('does_not_connect', ):
            return False

        while not self._connected:
            time.sleep(0.05)

        return True

    def _update_loop(self):
        time.sleep(random.uniform(*self._connect_delay))
        if self._connection_callback is not None:
            self._connection_callback(pvname=self._pvname, conn=True, pv=self)

        if self._pvname in ('does_not_connect', ):
            return

        self._connected = True
        last_value = None

        while True:
            with self._lock:
                if self._update:
                    self._value = random.choice(self.fake_values)

                if self._value != last_value:
                    sys.stdout.flush()
                    self.run_callbacks()
                    last_value = self._value

                time.sleep(self._update_rate)

            time.sleep(0.01)

    @property
    def lower_ctrl_limit(self):
        return min(self.fake_values)

    @property
    def upper_ctrl_limit(self):
        return max(self.fake_values)

    def run_callbacks(self):
        for index in sorted(list(self.callbacks.keys())):
            self.run_callback(index)

    def run_callback(self, index):
        fcn, kwargs = self.callbacks[index]
        kwd = dict(pvname=self._pvname,
                   count=1,
                   nelm=1,
                   type=None,
                   typefull=None,
                   ftype=None,
                   access='rw',
                   chid=self._idx,
                   read_access=True,
                   write_access=True,
                   value=self.value,
                   )

        kwd.update(kwargs)
        kwd['cb_info'] = (index, self)
        if hasattr(fcn, '__call__'):
            fcn(**kwd)

    def add_callback(self, callback=None, index=None, run_now=False,
                     with_ctrlvars=True, **kw):
        if hasattr(callback, '__call__'):
            if index is None:
                index = 1
                if len(self.callbacks) > 0:
                    index = 1 + max(self.callbacks.keys())
            self.callbacks[index] = (callback, kw)

        if run_now:
            if self.connected:
                self.run_callback(index)
        return index

    def remove_callback(self, index=None):
        if index in self.callbacks:
            self.callbacks.pop(index)

    def clear_callbacks(self):
        self.callbacks = {}

    @property
    def precision(self):
        return 0

    @property
    def timestamp(self):
        return time.time()

    @property
    def pvname(self):
        return self._pvname

    @property
    def value(self):
        return self._value

    def __repr__(self):
        return '<FakePV %s value=%s>' % (self._pvname, self.value)

    def get(self, as_string=False, use_numpy=False,
            use_monitor=False):
        if as_string:
            if isinstance(self.value, list):
                return list(self.value)
            else:
                return str(self.value)
        elif use_numpy:
            return np.array(self.value)
        else:
            return self.value

    def put(self, value, wait=False, timeout=30.0,
            use_complete=False, callback=None, callback_data=None):

        with self._lock:
            self._update = False
            self._value = value


class FakeEpicsWaveform(FakeEpicsPV):
    strings = ['abcd', 'efgh', 'ijkl']
    fake_values = [[ord(c) for c in s] + [0]
                   for s in strings]


def setUpModule():
    epics._PV = epics.PV
    epics.PV = FakeEpicsPV


def tearDownModule():
    logger.debug('Cleaning up')
    epics.PV = epics._PV


class FakePVTests(unittest.TestCase):
    def test_fakepv(self):
        pvname = 'fakepv_nowaythisexists' * 10

        info = dict(called=False)

        def conn(**kwargs):
            info['conn'] = True
            info['conn_kw'] = kwargs

        def value_cb(**kwargs):
            info['value'] = True
            info['value_kw'] = kwargs

        pv = epics.PV(pvname, callback=value_cb, connection_callback=conn,
                      )

        if not pv.wait_for_connection():
            raise ValueError('should return True on connection')

        self.assertEquals(pv.pvname, pvname)

        pv._update_rate = 0.5
        time.sleep(0.2)

        self.assertTrue(info['conn'])
        self.assertTrue(info['value'])
        self.assertEquals(info['value_kw']['value'], pv.value)


class SignalTests(unittest.TestCase):
    def test_signal_separate(self):
        self.signal_t(True)

    def test_signal_unified(self):
        self.signal_t(False)

    def signal_t(self, separate):
        start_t = time.time()
        setpoint_t = start_t + 1

        name = 'test'
        value, setpoint = 10.0, 20.0
        signal = Signal(name=name,
                        value=value, setpoint=setpoint,
                        timestamp=start_t, setpoint_ts=setpoint_t,
                        separate_readback=separate)

        signal.wait_for_connection()

        self.assertTrue(signal.connected)
        self.assertEquals(signal.name, name)
        self.assertEquals(signal.value, value)
        self.assertEquals(signal.get(), value)
        self.assertEquals(signal.setpoint, setpoint)
        self.assertEquals(signal.get_setpoint(), setpoint)
        self.assertEquals(signal.timestamp, start_t)
        self.assertEquals(signal.setpoint_ts, setpoint_t)

        info = dict(called=False)

        def _sub_test(**kwargs):
            info['called'] = True
            info['kw'] = kwargs

        signal.subscribe(_sub_test, run=False)
        self.assertTrue(not info['called'])

        signal.value = value
        signal.clear_sub(_sub_test)

        signal.subscribe(_sub_test, run=False)
        signal.clear_sub(_sub_test, event_type=signal.SUB_VALUE)

        if separate:
            # separate setpoint will not trigger a readback/value callback
            self.assertTrue(not info['called'])
        else:
            kw = info['kw']
            self.assertIn('value', kw)
            self.assertIn('timestamp', kw)
            self.assertIn('old_value', kw)

            self.assertEquals(kw['value'], value)
            self.assertEquals(kw['old_value'], value)
            self.assertEquals(kw['timestamp'], signal.timestamp)

        # setpoint callback
        info = dict(called=False)
        signal.subscribe(_sub_test, event_type=Signal.SUB_SETPOINT,
                         run=False)
        self.assertTrue(not info['called'])
        signal.value = value + 1
        self.assertTrue(info['called'])

        signal.clear_sub(_sub_test)
        kw = info['kw']

        self.assertIn('value', kw)
        self.assertIn('timestamp', kw)
        self.assertIn('old_value', kw)

        self.assertEquals(kw['value'], value + 1)
        self.assertEquals(kw['old_value'], value)
        self.assertEquals(kw['timestamp'], signal.setpoint_ts)

        signal.read()
        eval(repr(signal))
        signal.report

    def test_signal_copy(self):
        start_t = time.time()
        setpoint_t = start_t + 1

        name = 'test'
        value, setpoint = 10.0, 20.0
        signal = Signal(name=name,
                        value=value, setpoint=setpoint,
                        timestamp=start_t, setpoint_ts=setpoint_t,
                        separate_readback=True)

        sig_copy = copy.copy(signal)

        self.assertEquals(signal.name, sig_copy.name)
        self.assertEquals(signal.value, sig_copy.value)
        self.assertEquals(signal.get(), sig_copy.get())
        self.assertEquals(signal.setpoint, sig_copy.setpoint)
        self.assertEquals(signal.get_setpoint(), sig_copy.get_setpoint())
        self.assertEquals(signal.timestamp, sig_copy.timestamp)
        self.assertEquals(signal.setpoint_ts, sig_copy.setpoint_ts)


class EpicsSignalTests(unittest.TestCase):
    def test_epicssignal_readonly(self):
        epics.PV = FakeEpicsPV

        signal = EpicsSignal('readpv', rw=False)
        signal.wait_for_connection()

        signal.value

        @contextmanager
        def readonly_block():
            try:
                yield
            except ReadOnlyError:
                pass
            else:
                raise ValueError('Should be readonly')

        with readonly_block():
            signal.value = 10

        with readonly_block():
            signal.setpoint_ts

        with readonly_block():
            signal.setpoint

        with readonly_block():
            signal.check_value(0)

        signal.precision
        signal.timestamp
        signal.report
        signal.read()

        with readonly_block():
            signal.limits

        self.assertEquals(signal.setpoint_pvname, None)

        eval(repr(signal))
        time.sleep(0.2)

    def test_epicssignal_readwrite_limits(self):
        epics.PV = FakeEpicsPV

        signal = EpicsSignal('readpv', write_pv='readpv',
                             limits=True)

        signal.wait_for_connection()
        signal.check_value((signal.low_limit + signal.high_limit) / 2)

        try:
            signal.check_value(None)
        except ValueError:
            pass
        else:
            raise ValueError('value=None')

        try:
            signal.check_value(signal.low_limit - 1)
        except ValueError:
            pass
        else:
            raise ValueError('lower limit %s' % (signal.limits, ))

        try:
            signal.check_value(signal.high_limit + 1)
        except ValueError:
            pass
        else:
            raise ValueError('upper limit')

    def test_epicssignal_readwrite(self):
        epics.PV = FakeEpicsPV

        signal = EpicsSignal('readpv', write_pv='writepv')
        signal.wait_for_connection()

        self.assertEquals(signal.setpoint_pvname, 'writepv')
        self.assertEquals(signal.pvname, 'readpv')
        signal.value

        signal._update_rate = 2
        time.sleep(0.2)

        value = 10
        signal.value = value
        signal.setpoint = value
        self.assertEquals(signal.setpoint, value)
        signal.setpoint_ts

        signal.limits
        signal.precision
        signal.timestamp
        signal.report
        signal.read()

        eval(repr(signal))
        time.sleep(0.2)

    def test_epicssignal_waveform(self):
        epics.PV = FakeEpicsWaveform

        def update_cb(value=None, **kwargs):
            self.assertIn(value, FakeEpicsWaveform.strings)

        signal = EpicsSignal('readpv', string=True)
        signal.wait_for_connection()

        signal.subscribe(update_cb)
        self.assertIn(signal.value, FakeEpicsWaveform.strings)

    def test_no_connection(self):
        epics.PV = FakeEpicsPV
        # special case in FakeEpicsPV that returns false in wait_for_connection
        sig = EpicsSignal('does_not_connect')
        self.assertRaises(TimeoutError, sig.wait_for_connection)

        sig = EpicsSignal('connects', write_pv='does_not_connect')
        self.assertRaises(TimeoutError, sig.wait_for_connection)

    def test_setpoint(self):
        epics.PV = FakeEpicsPV
        # special case in FakeEpicsPV that returns false in wait_for_connection
        sig = EpicsSignal('connects')
        sig.wait_for_connection()

        sig.get_setpoint()
        sig.get_setpoint(as_string=True)

    def test_epicssignalro(self):
        self.assertRaises(ValueError, EpicsSignalRO, 'test',
                          write_pv='nope_sorry')


from . import main
is_main = (__name__ == '__main__')
main(is_main)