# USB Red Panda on Linux

This branch restores the normal openpilot CAN receive/transmit path through one
USB Red Panda. Startup prefers a responding SPI Panda; otherwise it selects one
USB Red Panda. Vehicle identification, safety configuration, control readiness,
and firmware heartbeat checks still apply.

## Setup and startup

Use Ubuntu 24.04 with Python 3.12 and the repository's normal development setup
(`tools/op.sh setup`). The core dependencies include vendored libusb. Build the
daemon and the matching firmware before connecting:

```sh
source .venv/bin/activate
scons -j4 openpilot/selfdrive/pandad/pandad panda/board/obj/panda_h7.bin.signed
```

Configure Linux USB access using the udev instructions in `panda/README.md`.
Connect the Red Panda with a USB data cable and verify that the user running
openpilot can access it. A WSL development environment needs USB passthrough to
access physical hardware; a successful software build does not establish this.

The normal openpilot manager starts the Python wrapper automatically. To run
only the Panda service, without another instance of openpilot running:

```sh
python -m openpilot.selfdrive.pandad.pandad
```

To select a particular board, including when several Red Pandas are connected:

```sh
PANDA_SERIAL=YOUR_24_CHARACTER_SERIAL python -m openpilot.selfdrive.pandad.pandad
```

Set `PANDA_SERIAL` in the manager's environment when running the full stack.
An explicit serial takes precedence over automatic SPI selection. The wrapper
pins the chosen serial and transport until it exits, including across unplug
and reconnect. It will not switch to another board during recovery. Missing or
ambiguous devices produce diagnostics and a one-second retry interval.

Startup updates only the selected Red Panda's application when its firmware is
outdated or it is in bootstub. It verifies the firmware signature and packet
versions, sets no-output safety, and enables heartbeat checks before launching
the daemon. A Red Panda stuck in DFU, with a broken bootloader, or failing
verification requires manual recovery. USB startup never invokes internal
Panda GPIO reset or bootloader recovery.

For development, the native executable also accepts an optional serial and
`--transport=auto|spi|usb`. For example:

```sh
cd openpilot/selfdrive/pandad
./pandad YOUR_24_CHARACTER_SERIAL --transport=usb
```

The native executable requires matching firmware already installed. Use the
Python wrapper for normal startup and firmware updates.

## Software checks

```sh
scons -j4 openpilot/common/libparams_c.so \
  openpilot/selfdrive/pandad/tests/test_pandad_canprotocol \
  openpilot/selfdrive/pandad/tests/test_pandad_usb
python -m unittest openpilot.selfdrive.pandad.tests.test_pandad_startup
openpilot/selfdrive/pandad/tests/test_pandad_canprotocol
openpilot/selfdrive/pandad/tests/test_pandad_usb
```

The USB native test supplies fake libusb devices and transfer results. Its
deliberately injected errors can appear in the log even when the test succeeds.
These checks cover selection, application update and verification, timeout and
partial-transfer behavior, disconnects, and cleanup. They do not exercise a
physical USB link or vehicle.

## Hardware acceptance

Use an isolated, correctly powered Red Panda and an external CAN peer, with the
vehicle disconnected. Record the checkout, Panda serial, firmware signature,
packet versions, bus rates, frame counts, timestamps, and reported errors.

1. Verify cold startup, ignition reporting, and `redPanda` health publication.
   Test matching firmware and the application update from outdated firmware or
   bootstub. Confirm that an unselected board is unaffected.
2. Verify receive, transmit, and returned/rejected frame reporting on each bus
   against the external peer. Exercise classic CAN and CAN FD where applicable,
   idle periods, sustained traffic, and frame fragmentation. Compare sent and
   received counts and measure latency and missed 100 Hz receive-loop deadlines.
3. Verify no-output startup, diagnostic-to-vehicle safety transitions, and
   firmware rejection of prohibited commands. Stop host heartbeats and confirm
   the firmware's existing timeout removes control permission.
4. Unplug USB during traffic and stop the daemon during idle traffic. Verify
   bounded exit, loss of control permission, and reconnect to the same serial
   with fresh safety initialization. Confirm that commands are not replayed and
   another board is not selected automatically.

Physical USB/CAN acceptance and vehicle qualification remain pending until
measured. This restoration does not provide the Linux PC's cameras, sensors,
model runtime, or vehicle compatibility validation.
