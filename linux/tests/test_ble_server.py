# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from musegadget import ble_framing


@pytest.mark.parametrize("during_startup", [True, False])
def test_stop_closes_ble_server(monkeypatch, during_startup):
    def stub(name):
        module = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    dbus = stub("dbus")
    dbus.exceptions = stub("dbus.exceptions")
    dbus.service = stub("dbus.service")
    dbus.service.Object = object
    dbus.service.method = dbus.service.signal = lambda *args, **kwargs: lambda fn: fn
    dbus.mainloop = stub("dbus.mainloop")
    dbus.mainloop.glib = stub("dbus.mainloop.glib")
    dbus.mainloop.glib.DBusGMainLoop = Mock()
    dbus.Boolean = bool
    dbus.String = str
    adapter = Mock()
    dbus.Interface = Mock(return_value=adapter)

    gi = stub("gi")
    gi.repository = stub("gi.repository")
    pending = []
    loop = Mock()
    gi.repository.GLib = SimpleNamespace(
        MainLoop=lambda: loop, idle_add=pending.append,
        unix_signal_add=Mock(), PRIORITY_DEFAULT=0,
    )

    # Load the production server with local substitutes for its system modules.
    path = Path(ble_framing.__file__).with_name("ble_server.py")
    spec = importlib.util.spec_from_file_location("ble_server_under_test", path)
    ble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ble)
    monkeypatch.setattr(ble, "_find_adapter", lambda bus: "/adapter")
    monkeypatch.setattr(ble, "Application", lambda *args: SimpleNamespace(services=[]))
    monkeypatch.setattr(ble, "Service", lambda *args: SimpleNamespace(characteristics=[]))
    monkeypatch.setattr(ble, "Characteristic", Mock())
    monkeypatch.setattr(ble, "Advertisement", Mock())
    server = ble.BleServer("MuseGadget", on_write=Mock(), on_disconnect=Mock())

    def open_bus():
        if during_startup:
            server.stop()
        return Mock()

    def run_loop():
        if not during_startup:
            server.stop()
        for callback in pending:
            callback()

    dbus.SystemBus = open_bus
    loop.run.side_effect = run_loop
    server.run()

    if during_startup:
        loop.run.assert_not_called()
    else:
        loop.quit.assert_called_once()
    adapter.UnregisterAdvertisement.assert_called_once_with(ble.ADV_PATH)
    adapter.UnregisterApplication.assert_called_once_with(ble.APP_PATH)
