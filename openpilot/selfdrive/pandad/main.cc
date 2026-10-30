#include <cassert>

#include "selfdrive/pandad/pandad.h"
#include "common/swaglog.h"
#include "common/util.h"
#include "common/hardware/hw.h"

int main(int argc, char *argv[]) {
  LOGW("starting pandad");

  if (!Hardware::PC()) {
    int err;
    err = util::set_realtime_priority(54);
    assert(err == 0);
    err = util::set_core_affinity({3});
    assert(err == 0);
  }

  std::string serial;
  PandaTransport transport = PandaTransport::AUTO;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--transport=auto") transport = PandaTransport::AUTO;
    else if (arg == "--transport=spi") transport = PandaTransport::SPI;
    else if (arg == "--transport=usb") transport = PandaTransport::USB;
    else if (arg.rfind("--", 0) == 0 || !serial.empty()) {
      LOGE("usage: pandad [serial] [--transport=auto|spi|usb]");
      return 1;
    } else serial = arg;
  }
  pandad_main_thread(serial, transport);
  return 0;
}
