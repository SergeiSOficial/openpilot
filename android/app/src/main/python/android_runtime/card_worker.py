"""Initialize the real vehicle interface from replay-generated CarParams before consuming timeline CAN."""
from opendbc.car.car_helpers import interfaces
from opendbc.car.structs import car
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process, Priority
from openpilot.selfdrive.car.card import Car


def main():
  raw = Params().get("CarParams", block=True)
  with car.CarParams.from_bytes(raw) as recorded:
    params = recorded.as_builder()
  interface = interfaces[params.carFingerprint](params)
  radar = interfaces[params.carFingerprint].RadarInterface(params)
  config_realtime_process(4, Priority.CTRL_HIGH)
  Car(CI=interface, RI=radar).card_thread()
