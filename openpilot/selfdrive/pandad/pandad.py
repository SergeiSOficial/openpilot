#!/usr/bin/env python3
# simple pandad wrapper that updates the panda first
import os
import signal
import subprocess
import threading
import time

from panda import Panda, PandaDFU
from opendbc.car.structs import CarParams
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.hardware import HARDWARE, COMMA_HARDWARE
from openpilot.common.swaglog import cloudlog


class DaemonPanda(Panda):
  def reconnect(self):
    # Panda.connect(wait=True) waits indefinitely. Keep daemon setup recoverable.
    self.close()
    deadline = time.monotonic() + 15
    while True:
      try:
        self.connect(claim=True, wait=False)
        return
      except Exception:
        self.close()
        if time.monotonic() >= deadline:
          raise
        time.sleep(0.1)


class SpiPanda(DaemonPanda):
  @classmethod
  def usb_connect(cls, serial, claim=True, no_error=False):
    return None, None, None, False

  @classmethod
  def list(cls, usb_only=False):
    return [] if usb_only else cls.spi_list()


class UsbPanda(DaemonPanda):
  @classmethod
  def spi_connect(cls, serial):
    return None, None, None, False

  @classmethod
  def list(cls, usb_only=False):
    return cls.usb_list()


class SpiPandaDFU(PandaDFU):
  def __init__(self):
    self._context, self._handle = self.spi_connect(None)
    if self._handle is None:
      raise RuntimeError("Cannot open internal Panda DFU over SPI")
    self._mcu_type = self._handle.get_mcu_type()


def usb_red_pandas() -> list[str]:
  """Identify application and bootstub devices without changing their CAN configuration."""
  serials = []
  for serial in sorted(Panda.usb_list()):
    context, handle, _, _ = Panda.usb_connect(serial, claim=False, no_error=True)
    try:
      if handle is not None and handle.controlRead(Panda.REQUEST_IN, 0xc1, 0, 0, 1, timeout=100) == Panda.HW_TYPE_RED_PANDA:
        serials.append(serial)
    except Exception:
      cloudlog.exception("pandad.usb_probe_failed")
    finally:
      if handle is not None:
        handle.close()
      if context is not None:
        context.close()
  return serials


def select_panda(requested_serial: str | None = None) -> tuple[str, str] | None:
  try:
    spi_serials = Panda.spi_list()
  except Exception:
    cloudlog.exception("pandad.spi_probe_failed")
    spi_serials = []
  if spi_serials and (requested_serial is None or requested_serial in spi_serials):
    return requested_serial or spi_serials[0], "spi"

  usb_serials = usb_red_pandas()
  if requested_serial is not None:
    return (requested_serial, "usb") if requested_serial in usb_serials else None
  if len(usb_serials) > 1:
    raise RuntimeError(f"Multiple USB Red Pandas found: {usb_serials}. Set PANDA_SERIAL to select one.")
  return (usb_serials[0], "usb") if usb_serials else None


def prepare_usb_panda(serial: str) -> None:
  with UsbPanda(serial, cli=False, disable_checks=False) as p:
    if p.get_type() != Panda.HW_TYPE_RED_PANDA:
      raise RuntimeError("USB control requires a Red Panda")
    if p.bootstub or not p.up_to_date():
      cloudlog.warning(f"Updating Red Panda application firmware: {serial}")
      p.flash()
    if p.bootstub or p.get_type() != Panda.HW_TYPE_RED_PANDA or not p.up_to_date():
      raise RuntimeError("Red Panda firmware verification failed; manual recovery required")
    if p.health_version != Panda.HEALTH_PACKET_VERSION or p.can_version != Panda.CAN_PACKET_VERSION:
      raise RuntimeError("Red Panda packet versions do not match this checkout; manual recovery required")
    p.set_safety_mode(CarParams.SafetyModel.noOutput)
    p.send_heartbeat(engaged=False)


def panda_ready(serial: str | None = None) -> bool:
  """Is the panda up and running the firmware we ship?"""
  try:
    # a healthy panda answers on SPI within ~200ms of reset
    if not SpiPanda.wait_for_panda(serial, timeout=1):
      cloudlog.warning("no panda found")
      return False
    with SpiPanda(serial, cli=False, disable_checks=False) as p:
      if p.bootstub:
        cloudlog.warning(f"panda stuck in bootstub, version {p.get_version()}")
        return False
      if not p.up_to_date():
        cloudlog.warning(f"panda firmware out of date, version {p.get_version()}")
        return False
      return True
  except Exception:
    # e.g. SPI protocol mismatch with old firmware
    cloudlog.exception("pandad.panda_check_failed")
    return False


def flash_panda() -> None:
  """Reflash bootstub + app from the ST bootloader. Works from any state the panda can be in."""
  cloudlog.warning("flashing panda")
  HARDWARE.recover_internal_panda()
  deadline = time.monotonic() + 5
  while not PandaDFU.spi_list():
    if time.monotonic() >= deadline:
      raise RuntimeError("internal panda didn't enter DFU")
    time.sleep(0.1)
  with SpiPandaDFU() as dfu:
    dfu.recover()

  assert SpiPanda.wait_for_panda(None, timeout=5), "panda didn't boot into bootstub"
  with SpiPanda(cli=False, disable_checks=False) as p:
    p.flash()
  cloudlog.warning("done flashing panda")


def main() -> None:
  # signal pandad to close the relay and exit
  def signal_handler(signum, frame):
    cloudlog.info(f"Caught signal {signum}, exiting")
    do_exit.set()
    if process is not None:
      process.send_signal(signal.SIGINT)

  process = None
  do_exit = threading.Event()
  signal.signal(signal.SIGINT, signal_handler)
  signal.signal(signal.SIGTERM, signal_handler)

  requested_serial = os.environ.get("PANDA_SERIAL") or None
  selected = None

  count = 0
  while not do_exit.is_set():
    try:
      cloudlog.event("pandad.flash_and_connect", count=count)
      count += 1

      if selected is None:
        selected = select_panda(requested_serial)
        if selected is None and COMMA_HARDWARE and requested_serial is None:
          HARDWARE.reset_internal_panda()
          if not panda_ready():
            flash_panda()
          selected = select_panda()
        if selected is None:
          cloudlog.warning("No selected Panda available; check USB permissions, connection, or manual DFU recovery")
          do_exit.wait(1)
          continue

      serial, transport = selected
      cloudlog.info(f"Selected Panda {serial} over {transport}")
      if transport == "usb":
        prepare_usb_panda(serial)
      else:
        # Only the internal path may reset/recover the internal board.
        try:
          with SpiPanda(serial, cli=False, disable_checks=False) as p:
            if not p.bootstub and p.health()["heartbeat_lost"]:
              Params().put_bool("PandaHeartbeatLost", True, block=True)
        except Exception:
          cloudlog.exception("pandad.heartbeat_check_failed")
        if COMMA_HARDWARE:
          HARDWARE.reset_internal_panda()
        if not panda_ready(serial):
          if not COMMA_HARDWARE:
            raise RuntimeError("SPI Panda firmware is not ready")
          flash_panda()
          assert panda_ready(serial), "panda not ready after flashing"

      if do_exit.is_set():
        break

      # run real pandad
      os.environ['MANAGER_DAEMON'] = 'pandad'
      process = subprocess.Popen(["./pandad", serial, f"--transport={transport}"], cwd=os.path.join(BASEDIR, "openpilot/selfdrive/pandad"))
      process.wait()
      process = None
    except Exception:
      cloudlog.exception("pandad.uncaught_exception")
    do_exit.wait(1)


if __name__ == "__main__":
  main()
