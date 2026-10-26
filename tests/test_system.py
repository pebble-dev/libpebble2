from __future__ import absolute_import

from libpebble2.protocol.system import Reset


def test_reset_commands():
    assert Reset(command=Reset.Command.Reset).serialise() == b'\x00'
    assert Reset(command=Reset.Command.DumpCore).serialise() == b'\x01'
    assert Reset(command=Reset.Command.FactoryReset).serialise() == b'\xfe'
    assert Reset(command=Reset.Command.PRF).serialise() == b'\xff'
