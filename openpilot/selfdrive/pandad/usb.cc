#include "selfdrive/pandad/panda_comms.h"

#include <algorithm>
#include <array>
#include <stdexcept>

#include "common/swaglog.h"

namespace {
constexpr unsigned int USB_CONTROL_TIMEOUT = 100;
constexpr unsigned int USB_BULK_TIMEOUT = 5;
constexpr uint8_t RED_PANDA = 7;

bool is_panda(const libusb_device_descriptor &desc) {
  return (desc.idVendor == 0x3801 || desc.idVendor == 0xbbaa) && desc.idProduct == 0xddcc;
}

std::string read_serial(libusb_device_handle *handle, const libusb_device_descriptor &desc) {
  std::array<unsigned char, 25> serial{};
  int size = libusb_get_string_descriptor_ascii(handle, desc.iSerialNumber, serial.data(), serial.size());
  return size == 24 ? std::string(reinterpret_cast<char *>(serial.data()), size) : "";
}

bool is_red_panda(libusb_device_handle *handle) {
  uint8_t type = 0;
  return libusb_control_transfer(handle, 0xc0, 0xc1, 0, 0, &type, 1, USB_CONTROL_TIMEOUT) == 1 && type == RED_PANDA;
}
}  // namespace

PandaUsbHandle::PandaUsbHandle(std::string serial) {
  if (serial.empty()) {
    auto serials = list();
    if (serials.size() != 1) throw std::runtime_error("Specify the serial of one USB Red Panda");
    serial = serials[0];
  }
  if (libusb_init(&ctx) != 0) throw std::runtime_error("Cannot initialize libusb");

  libusb_device **devices = nullptr;
  try {
    ssize_t count = libusb_get_device_list(ctx, &devices);
    if (count < 0) throw std::runtime_error("Cannot enumerate USB devices");
    for (ssize_t i = 0; i < count; ++i) {
      libusb_device_descriptor desc{};
      if (libusb_get_device_descriptor(devices[i], &desc) != 0 || !is_panda(desc)) continue;
      libusb_device_handle *candidate = nullptr;
      if (libusb_open(devices[i], &candidate) != 0) continue;
      if (read_serial(candidate, desc) == serial && is_red_panda(candidate)) {
        dev_handle = candidate;
        hw_serial = serial;
        break;
      }
      libusb_close(candidate);
    }
    libusb_free_device_list(devices, 1);
    devices = nullptr;
    if (!dev_handle) throw std::runtime_error("Selected USB Red Panda is unavailable (check serial, firmware and permissions)");

    if (libusb_set_auto_detach_kernel_driver(dev_handle, 1) != 0 ||
        libusb_set_configuration(dev_handle, 1) != 0 || libusb_claim_interface(dev_handle, 0) != 0) {
      throw std::runtime_error("Cannot claim USB Red Panda interface");
    }
    claimed = true;
  } catch (...) {
    if (devices) libusb_free_device_list(devices, 1);
    cleanup();
    throw;
  }
}

PandaUsbHandle::~PandaUsbHandle() {
  cleanup();
}

void PandaUsbHandle::cleanup() {
  std::lock_guard lock(hw_lock);
  connected = false;
  if (dev_handle) {
    if (claimed) libusb_release_interface(dev_handle, 0);
    libusb_close(dev_handle);
    dev_handle = nullptr;
    claimed = false;
  }
  if (ctx) {
    libusb_exit(ctx);
    ctx = nullptr;
  }
}

std::vector<std::string> PandaUsbHandle::list() {
  libusb_context *context = nullptr;
  if (libusb_init(&context) != 0) return {};
  libusb_device **devices = nullptr;
  ssize_t count = libusb_get_device_list(context, &devices);
  std::vector<std::string> serials;
  for (ssize_t i = 0; i < count; ++i) {
    libusb_device_descriptor desc{};
    if (libusb_get_device_descriptor(devices[i], &desc) != 0 || !is_panda(desc)) continue;
    libusb_device_handle *handle = nullptr;
    if (libusb_open(devices[i], &handle) != 0) continue;
    auto serial = read_serial(handle, desc);
    if (!serial.empty() && is_red_panda(handle)) serials.push_back(serial);
    libusb_close(handle);
  }
  if (devices) libusb_free_device_list(devices, 1);
  libusb_exit(context);
  std::sort(serials.begin(), serials.end());
  serials.erase(std::unique(serials.begin(), serials.end()), serials.end());
  return serials;
}

int PandaUsbHandle::transfer_error(int err) {
  LOGE_100("USB Red Panda transfer failed: %d", err);
  comms_healthy = false;
  connected = false;
  return err;
}

int PandaUsbHandle::control_write(uint8_t request, uint16_t param1, uint16_t param2, unsigned int timeout) {
  std::lock_guard lock(hw_lock);
  if (!connected) return LIBUSB_ERROR_NO_DEVICE;
  int ret = libusb_control_transfer(dev_handle, 0x40, request, param1, param2, nullptr, 0, timeout ? timeout : USB_CONTROL_TIMEOUT);
  return ret == 0 ? ret : transfer_error(ret < 0 ? ret : LIBUSB_ERROR_IO);
}

int PandaUsbHandle::control_read(uint8_t request, uint16_t param1, uint16_t param2, unsigned char *data, uint16_t length, unsigned int timeout) {
  std::lock_guard lock(hw_lock);
  if (!connected) return LIBUSB_ERROR_NO_DEVICE;
  int ret = libusb_control_transfer(dev_handle, 0xc0, request, param1, param2, data, length, timeout ? timeout : USB_CONTROL_TIMEOUT);
  return ret >= 0 ? ret : transfer_error(ret);
}

int PandaUsbHandle::bulk_write(unsigned char endpoint, unsigned char *data, int length, unsigned int timeout) {
  std::lock_guard lock(hw_lock);
  if (!connected) return LIBUSB_ERROR_NO_DEVICE;
  int transferred = 0;
  int ret = libusb_bulk_transfer(dev_handle, endpoint, data, length, &transferred, timeout ? timeout : USB_BULK_TIMEOUT);
  // A partial packet cannot be retried without risking duplicated or corrupt CAN commands.
  if (ret != 0 || transferred != length) return transfer_error(ret < 0 ? ret : LIBUSB_ERROR_IO);
  return transferred;
}

int PandaUsbHandle::bulk_read(unsigned char endpoint, unsigned char *data, int length, unsigned int timeout) {
  std::lock_guard lock(hw_lock);
  if (!connected) return LIBUSB_ERROR_NO_DEVICE;
  int transferred = 0;
  int ret = libusb_bulk_transfer(dev_handle, endpoint, data, length, &transferred, timeout ? timeout : USB_BULK_TIMEOUT);
  // Timeout may include valid data; an idle bus is also normal.
  if (ret != 0 && ret != LIBUSB_ERROR_TIMEOUT) return transfer_error(ret);
  return transferred;
}
