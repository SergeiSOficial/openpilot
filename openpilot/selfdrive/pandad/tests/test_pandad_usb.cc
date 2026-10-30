#include <algorithm>
#include <cstring>
#include <stdexcept>

#include "common/tests/native_test.h"
#include "selfdrive/pandad/panda.h"

namespace {
struct Device {
  uint16_t vendor = 0x3801;
  uint16_t product = 0xddcc;
  uint8_t type = 7;
  std::string serial = "123456789012345678901234";
  bool accessible = true;
};
std::vector<Device> devices;
std::vector<libusb_device *> device_list;
int opens, closes, contexts, releases, claims, transfers;
int bulk_result, bulk_count, control_result, claim_result, type_result;
unsigned int last_timeout;

Device &device(libusb_device_handle *handle) { return *reinterpret_cast<Device *>(handle); }

void reset() {
  devices = {Device{}};
  opens = closes = contexts = releases = claims = transfers = 0;
  bulk_result = bulk_count = control_result = claim_result = 0;
  type_result = 1;
  last_timeout = 0;
}
}  // namespace

// A fake libusb backend exercises the real USB transport without attached hardware.
extern "C" {
int libusb_init(libusb_context **ctx) {
  *ctx = reinterpret_cast<libusb_context *>(&contexts);
  ++contexts;
  return 0;
}
void libusb_exit(libusb_context *) { --contexts; }
ssize_t libusb_get_device_list(libusb_context *, libusb_device ***list) {
  device_list.clear();
  for (auto &dev : devices) device_list.push_back(reinterpret_cast<libusb_device *>(&dev));
  device_list.push_back(nullptr);
  *list = device_list.data();
  return devices.size();
}
void libusb_free_device_list(libusb_device **, int) {}
int libusb_get_device_descriptor(libusb_device *dev, libusb_device_descriptor *desc) {
  auto &d = *reinterpret_cast<Device *>(dev);
  desc->idVendor = d.vendor;
  desc->idProduct = d.product;
  desc->iSerialNumber = 3;
  return 0;
}
int libusb_open(libusb_device *dev, libusb_device_handle **handle) {
  if (!reinterpret_cast<Device *>(dev)->accessible) return LIBUSB_ERROR_ACCESS;
  *handle = reinterpret_cast<libusb_device_handle *>(dev);
  ++opens;
  return 0;
}
void libusb_close(libusb_device_handle *) { ++closes; }
int libusb_get_string_descriptor_ascii(libusb_device_handle *handle, uint8_t, unsigned char *data, int length) {
  auto &serial = device(handle).serial;
  int size = std::min(length, static_cast<int>(serial.size()));
  memcpy(data, serial.data(), size);
  return size;
}
int libusb_set_auto_detach_kernel_driver(libusb_device_handle *, int) { return 0; }
int libusb_get_configuration(libusb_device_handle *, int *configuration) { *configuration = 1; return 0; }
int libusb_set_configuration(libusb_device_handle *, int) { return 0; }
int libusb_claim_interface(libusb_device_handle *, int) { ++claims; return claim_result; }
int libusb_release_interface(libusb_device_handle *, int) { ++releases; return 0; }
int libusb_control_transfer(libusb_device_handle *handle, uint8_t, uint8_t request, uint16_t, uint16_t,
                            unsigned char *data, uint16_t length, unsigned int timeout) {
  CHECK(timeout != 0);
  last_timeout = timeout;
  if (request == 0xc1) { data[0] = device(handle).type; return type_result; }
  if (data) memset(data, 0, length);
  return control_result;
}
int libusb_bulk_transfer(libusb_device_handle *, unsigned char, unsigned char *, int, int *transferred, unsigned int timeout) {
  CHECK(timeout != 0);
  ++transfers;
  last_timeout = timeout;
  *transferred = bulk_count;
  return bulk_result;
}
}  // extern "C"

void test_usb() {
  reset();
  devices.push_back(Device{.type = 9, .serial = "223456789012345678901234"});
  devices.push_back(Device{.accessible = false});
  CHECK(PandaUsbHandle::list() == std::vector<std::string>{devices[0].serial});
  CHECK(opens == closes);
  CHECK(contexts == 0);

  reset();
  {
    PandaUsbHandle handle("");
    unsigned char data[64]{};
    CHECK(handle.connected);
    bulk_result = LIBUSB_ERROR_TIMEOUT;
    CHECK(handle.bulk_read(0x81, data, sizeof(data)) == 0);
    CHECK(last_timeout == 5);
    CHECK(handle.connected && handle.comms_healthy);
    bulk_count = 13;
    CHECK(handle.bulk_read(0x81, data, sizeof(data)) == 13);
    bulk_result = 0;
    bulk_count = sizeof(data);
    CHECK(handle.bulk_write(3, data, sizeof(data)) == sizeof(data));
    CHECK(handle.control_write(0xf3, 0, 0) == 0);
    CHECK(last_timeout == 100);
    bulk_count = 3;
    int before = transfers;
    CHECK(handle.bulk_write(3, data, sizeof(data)) < 0);
    CHECK(transfers == before + 1);  // no retry of a partially sent command
    CHECK(!handle.connected && !handle.comms_healthy);
    CHECK(handle.bulk_read(0x81, data, sizeof(data)) == LIBUSB_ERROR_NO_DEVICE);
    CHECK(transfers == before + 1);
    handle.cleanup();
    handle.cleanup();
  }
  CHECK(opens == closes && contexts == 0 && releases == 1);

  for (int error : {LIBUSB_ERROR_TIMEOUT, LIBUSB_ERROR_NO_DEVICE, LIBUSB_ERROR_PIPE, LIBUSB_ERROR_OVERFLOW}) {
    reset();
    {
      PandaUsbHandle handle(devices[0].serial);
      unsigned char data[64]{};
      bulk_result = error;
      if (error == LIBUSB_ERROR_TIMEOUT) {
        CHECK(handle.bulk_write(3, data, sizeof(data)) < 0);
      } else {
        CHECK(handle.bulk_read(0x81, data, sizeof(data)) == error);
      }
      CHECK(!handle.connected && !handle.comms_healthy);
      CHECK(transfers == 1);
    }
    CHECK(opens == closes && contexts == 0);
  }

  reset();
  {
    Panda panda(devices[0].serial, PandaTransport::USB);
    control_result = sizeof(health_t) - 1;
    CHECK(!panda.get_state().has_value());
    control_result = sizeof(health_t);
    CHECK(panda.get_state().has_value());
    control_result = sizeof(can_health_t) - 1;
    CHECK(!panda.get_can_state(0).has_value());
    control_result = sizeof(can_health_t);
    CHECK(panda.get_can_state(0).has_value());
  }
  CHECK(opens == closes && contexts == 0);

  reset();
  {
    PandaUsbHandle handle(devices[0].serial);
    control_result = LIBUSB_ERROR_TIMEOUT;
    CHECK(handle.control_write(0xf3, 0, 0) == LIBUSB_ERROR_TIMEOUT);
    CHECK(!handle.connected && !handle.comms_healthy);
  }
  CHECK(opens == closes && contexts == 0);

  reset();
  claim_result = LIBUSB_ERROR_BUSY;
  bool failed = false;
  try { PandaUsbHandle handle(devices[0].serial); } catch (const std::runtime_error &) { failed = true; }
  CHECK(failed && opens == closes && contexts == 0 && releases == 0);

  reset();
  devices.push_back(Device{.serial = "223456789012345678901234"});
  failed = false;
  try { PandaUsbHandle handle(""); } catch (const std::runtime_error &) { failed = true; }
  CHECK(failed && claims == 0 && opens == closes && contexts == 0);

  reset();
  type_result = 0;
  failed = false;
  try { PandaUsbHandle handle(devices[0].serial); } catch (const std::runtime_error &) { failed = true; }
  CHECK(failed && opens == closes && contexts == 0);
}

int main() { return run_native_test(test_usb); }
