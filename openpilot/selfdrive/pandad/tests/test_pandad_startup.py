import unittest
from unittest.mock import MagicMock, patch

from panda import Panda
from openpilot.selfdrive.pandad import pandad

SERIAL = "123456789012345678901234"
OTHER = "223456789012345678901234"


class TestPandaSelection(unittest.TestCase):
  def test_spi_preferred(self):
    with patch.object(Panda, "spi_list", return_value=[SERIAL]), patch.object(pandad, "usb_red_pandas") as usb:
      self.assertEqual(pandad.select_panda(), (SERIAL, "spi"))
      usb.assert_not_called()

  def test_usb_fallback_and_explicit_serial(self):
    with patch.object(Panda, "spi_list", return_value=[]), patch.object(pandad, "usb_red_pandas", return_value=[SERIAL]):
      self.assertEqual(pandad.select_panda(), (SERIAL, "usb"))
      self.assertIsNone(pandad.select_panda(OTHER))
    with patch.object(Panda, "spi_list", return_value=[OTHER]), patch.object(pandad, "usb_red_pandas", return_value=[SERIAL]):
      self.assertEqual(pandad.select_panda(SERIAL), (SERIAL, "usb"))

  def test_ambiguous_or_missing_usb(self):
    with patch.object(Panda, "spi_list", return_value=[]), patch.object(pandad, "usb_red_pandas", return_value=[SERIAL, OTHER]):
      with self.assertRaisesRegex(RuntimeError, "PANDA_SERIAL"):
        pandad.select_panda()
      self.assertEqual(pandad.select_panda(OTHER), (OTHER, "usb"))
    with patch.object(Panda, "spi_list", return_value=[]), patch.object(pandad, "usb_red_pandas", return_value=[]):
      self.assertIsNone(pandad.select_panda())

  def test_spi_probe_failure_falls_back(self):
    with patch.object(Panda, "spi_list", side_effect=RuntimeError("old protocol")), \
         patch.object(pandad, "usb_red_pandas", return_value=[SERIAL]):
      self.assertEqual(pandad.select_panda(), (SERIAL, "usb"))

  def test_usb_probe_is_read_only_and_closes_handles(self):
    context, handle = MagicMock(), MagicMock()
    with patch.object(Panda, "usb_list", return_value=[SERIAL]), \
         patch.object(Panda, "usb_connect", return_value=(context, handle, SERIAL, False)) as connect:
      for hardware, expected in [(Panda.HW_TYPE_RED_PANDA, [SERIAL]), (Panda.HW_TYPE_TRES, [])]:
        handle.controlRead.return_value = hardware
        self.assertEqual(pandad.usb_red_pandas(), expected)
      handle.controlRead.side_effect = RuntimeError("unplugged")
      self.assertEqual(pandad.usb_red_pandas(), [])
    connect.assert_called_with(SERIAL, claim=False, no_error=True)
    self.assertEqual(handle.close.call_count, 3)
    self.assertEqual(context.close.call_count, 3)
    handle.controlWrite.assert_not_called()

  def test_transport_connections_never_fall_back(self):
    self.assertEqual(pandad.SpiPanda.usb_connect(SERIAL), (None, None, None, False))
    self.assertEqual(pandad.UsbPanda.spi_connect(SERIAL), (None, None, None, False))


class TestUsbFirmware(unittest.TestCase):
  def setUp(self):
    self.panda = MagicMock()
    self.panda.bootstub = False
    self.panda.get_type.return_value = Panda.HW_TYPE_RED_PANDA
    self.panda.up_to_date.return_value = True
    self.panda.health_version = Panda.HEALTH_PACKET_VERSION
    self.panda.can_version = Panda.CAN_PACKET_VERSION
    self.connection = patch.object(pandad, "UsbPanda")
    self.constructor = self.connection.start()
    self.addCleanup(self.connection.stop)
    self.constructor.return_value.__enter__.return_value = self.panda

  def test_matching_firmware_keeps_heartbeat_checks(self):
    pandad.prepare_usb_panda(SERIAL)
    self.constructor.assert_called_once_with(SERIAL, cli=False, disable_checks=False)
    self.panda.flash.assert_not_called()
    self.panda.set_safety_mode.assert_called_once_with(pandad.CarParams.SafetyModel.noOutput)
    self.panda.send_heartbeat.assert_called_once_with(engaged=False)

  def test_outdated_firmware_updates_and_verifies(self):
    self.panda.up_to_date.side_effect = [False, True]
    pandad.prepare_usb_panda(SERIAL)
    self.panda.flash.assert_called_once_with()

  def test_bootstub_updates(self):
    self.panda.bootstub = True
    self.panda.flash.side_effect = lambda: setattr(self.panda, "bootstub", False)
    pandad.prepare_usb_panda(SERIAL)
    self.panda.flash.assert_called_once_with()

  def test_failed_firmware_verification(self):
    self.panda.up_to_date.return_value = False
    with self.assertRaisesRegex(RuntimeError, "verification failed"):
      pandad.prepare_usb_panda(SERIAL)
    self.panda.send_heartbeat.assert_not_called()

  def test_wrong_hardware_never_flashed(self):
    self.panda.get_type.return_value = Panda.HW_TYPE_TRES
    with self.assertRaisesRegex(RuntimeError, "requires a Red Panda"):
      pandad.prepare_usb_panda(SERIAL)
    self.panda.flash.assert_not_called()

  def test_packet_mismatch(self):
    for field in ("health_version", "can_version"):
      previous = getattr(self.panda, field)
      setattr(self.panda, field, 0)
      with self.assertRaisesRegex(RuntimeError, "packet versions"):
        pandad.prepare_usb_panda(SERIAL)
      setattr(self.panda, field, previous)


class StopAfterWaits:
  def __init__(self, waits=2):
    self.remaining = waits

  def is_set(self):
    return self.remaining == 0

  def set(self):
    self.remaining = 0

  def wait(self, timeout):
    assert timeout == 1
    self.remaining -= 1


class TestPandaStartup(unittest.TestCase):
  def test_usb_reconnect_pins_selection_and_avoids_internal_recovery(self):
    with patch.object(pandad.threading, "Event", return_value=StopAfterWaits()), \
         patch.object(pandad.signal, "signal"), patch.dict(pandad.os.environ, {"PANDA_SERIAL": SERIAL}), \
         patch.object(pandad, "COMMA_HARDWARE", False), \
         patch.object(pandad, "select_panda", return_value=(SERIAL, "usb")) as select, \
         patch.object(pandad, "prepare_usb_panda") as prepare, patch.object(pandad, "HARDWARE") as hardware, \
         patch.object(pandad.subprocess, "Popen") as process:
      pandad.main()
    select.assert_called_once_with(SERIAL)
    self.assertEqual(prepare.call_count, 2)
    self.assertEqual(process.call_count, 2)
    self.assertEqual(process.call_args.args[0], ["./pandad", SERIAL, "--transport=usb"])
    hardware.reset_internal_panda.assert_not_called()
    hardware.recover_internal_panda.assert_not_called()

  def test_missing_panda_waits_without_flashing(self):
    event = StopAfterWaits()
    with patch.object(pandad.threading, "Event", return_value=event), patch.object(pandad.signal, "signal"), \
         patch.object(pandad, "COMMA_HARDWARE", False), patch.object(pandad, "select_panda", return_value=None), \
         patch.object(pandad, "HARDWARE") as hardware, patch.object(pandad.subprocess, "Popen") as process:
      pandad.main()
    self.assertTrue(event.is_set())
    process.assert_not_called()
    hardware.recover_internal_panda.assert_not_called()

  def test_firmware_failure_never_starts_daemon(self):
    with patch.object(pandad.threading, "Event", return_value=StopAfterWaits()), patch.object(pandad.signal, "signal"), \
         patch.object(pandad, "select_panda", return_value=(SERIAL, "usb")), \
         patch.object(pandad, "prepare_usb_panda", side_effect=RuntimeError("verification failed")), \
         patch.object(pandad, "HARDWARE") as hardware, patch.object(pandad.subprocess, "Popen") as process:
      pandad.main()
    process.assert_not_called()
    hardware.recover_internal_panda.assert_not_called()


if __name__ == "__main__":
  unittest.main()
