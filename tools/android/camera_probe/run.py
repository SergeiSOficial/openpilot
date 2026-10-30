"""Run explicitly selected camera tests on the connected target via trusted adb.

Only adb is executed on the host. No compiler, native helper, FFI or JIT is used.
"""
from pathlib import Path
import argparse
import atexit
import json
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "tools/android/.cache/camera-private"
PACKAGE = "com.samsung.android.openpilotprobe"
SAMSUNG = "first-entrance=true;samsungcamera=true;shootingmode=3;recording-fps=30;sw-vdis=false;video-beautyface=false;"
SECOND = "first-entrance=false;samsungcamera=true;factorytest=false;shootingmode=3;recording-fps=30;sw-vdis=false;video-beautyface=false;vtmode=0;operation_mode=none;ssm_shot_mode=0;recording_dr_mode=sdr;sw-super_vdis=false;stream_type=0;"
CASES = {
    "baseline-main": dict(logical="0", layout="single"),
    "logical23-single": dict(logical="23", layout="single"),
    "logical23-private": dict(logical="23", format="private"),
    "logical23-logicalplus": dict(logical="23", layout="logicalplus"),
    "samsung23-single": dict(logical="23", layout="single", vendor=SAMSUNG),
    "samsung23-physical": dict(logical="23", vendor=SAMSUNG),
    "samsung20-physical": dict(logical="20", vendor=SAMSUNG),
    "samsung23-private": dict(logical="23", format="private", vendor=SAMSUNG),
    "samsung23-logicalplus": dict(logical="23", layout="logicalplus", vendor=SAMSUNG),
    "samsung23-shooting3": dict(logical="23", vendor=SAMSUNG, shooting=3),
    "samsung23-shooting10": dict(logical="23", vendor=SAMSUNG, shooting=10),
    "samsung23-shooting32": dict(logical="23", vendor=SAMSUNG, shooting=32),
    "allowlisted23-shooting3": dict(logical="23", vendor=SAMSUNG, shooting=3),
    "allowlisted20-shooting3": dict(logical="20", vendor=SAMSUNG, shooting=3),
    "allowlisted23-options": dict(logical="23", vendor=SAMSUNG, shooting=3, usecase0=65536, usecase1=65536),
    "allowlisted20-options": dict(logical="20", vendor=SAMSUNG, shooting=3, usecase0=65536, usecase1=65536),
    "stock20-single": dict(logical="20", layout="single", format="private", vendor=SECOND, twophase=True, jpeg=True, usecase0=65536, width=1920, height=1080),
    "stock20-dual": dict(logical="20", layout="logicalplus", format="mixed", vendor=SECOND, twophase=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080),
    "stock23-dual": dict(logical="23", layout="logicalplus", format="mixed", vendor=SECOND, twophase=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080),
    "galaxyraw20-single": dict(logical="20", layout="single", format="private", vendor=SECOND, twophase=True, jpeg=True, usecase0=65536, width=1920, height=1080),
    "galaxyraw20-dual": dict(logical="20", layout="logicalplus", format="mixed", vendor=SECOND, twophase=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080),
    "preview20-single": dict(logical="20", layout="single", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, width=1920, height=1080),
    "preview20-physical": dict(logical="20", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080),
    "preview23-physical": dict(logical="23", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080),
    "preview20-vendor": dict(logical="20", layout="vendor", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080),
    "preview20-vendor32": dict(logical="20", layout="vendor", vendor=SECOND.replace("shootingmode=3;", "shootingmode=32;"), twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080, shooting=32),
    "preview20-sustained": dict(logical="20", layout="vendor", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080, seconds=30),
    "preview20-lenscheck": dict(logical="20", layout="vendor", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080, seconds=180),
    "preview20-720p": dict(logical="20", layout="vendor", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1280, height=720, seconds=10),
    "preview20-video": dict(logical="20", layout="vendor", vendor=SECOND, twophase=True, preview=True, jpeg=True, usecase0=65536, usecase1=16842752, width=1920, height=1080, seconds=10, shooting=3),
}


def stop_log(process, log_file):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    if not log_file.closed:
        log_file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--package", default=PACKAGE)
    parser.add_argument("names", nargs="+", choices=CASES)
    args = parser.parse_args()
    package = args.package
    OUT.mkdir(parents=True, exist_ok=True)

    def adb(*command, check=True):
        return subprocess.run(["adb", "-s", args.serial, *command], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=25, check=check)

    model = adb("shell", "getprop ro.product.model").stdout.strip()
    if model != "SM-F926B":
        raise RuntimeError(f"Expected selected Fold3, got {model}")
    for name in args.names:
        config = dict(width=640, height=480, fps=30, seconds=4)
        config.update(CASES[name])
        adb("shell", shlex.join(["am", "force-stop", package]))
        # Hidden IDs are lazily populated on this vendor provider. Preserve the
        # preflight dump rather than counting startup unknown-ID failures as a
        # negative stream-configuration result.
        dump = adb("shell", "dumpsys media.camera").stdout
        (OUT / f"{name}-preflight.txt").write_text(dump, encoding="utf-8")
        log_file = (OUT / f"{name}-live-logcat.txt").open("w", encoding="utf-8")
        log_process = subprocess.Popen(["adb", "-s", args.serial, "logcat", "-v", "threadtime", "-T", "1"],
                                       stdout=log_file, stderr=subprocess.STDOUT)
        atexit.register(stop_log, log_process, log_file)
        cmd = ["am", "start", "-W", "-n", f"{package}/ai.comma.cameraprobe.Probe"]
        for key, value in config.items():
            flag = "--ez" if isinstance(value, bool) else "--ei" if isinstance(value, int) else "--es"
            cmd += [flag, key, str(value).lower() if isinstance(value, bool) else str(value)]
        launch = adb("shell", shlex.join(cmd)).stdout
        deadline = time.monotonic() + config["seconds"] + 20
        result = ""
        while time.monotonic() < deadline:
            result = adb("shell", shlex.join(["run-as", package, "cat", "files/result.txt"]), check=False).stdout
            if "\nDONE\n" in result or "DONE_INSPECT" in result:
                break
            time.sleep(0.5)
        (OUT / f"{name}.txt").write_text(result, encoding="utf-8")
        (OUT / f"{name}.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        (OUT / f"{name}-launch.txt").write_text(launch, encoding="utf-8")
        logcat = adb("logcat", "-d", "-t", "2200").stdout
        (OUT / f"{name}-logcat.txt").write_text(logcat, encoding="utf-8")
        stop_log(log_process, log_file)
        highlights = [line for line in result.splitlines() if line.startswith(("END=", "RESULT ", "PAIR ", "VENDOR_EXCEPTION", "METADATA", "PHYSICAL_RESULT", "VENDOR_PARAMETERS_SENT", "SESSION_SUPPORTED="))]
        print(name + ": " + " | ".join(highlights), flush=True)
        if "\nDONE\n" not in result:
            raise RuntimeError(f"Probe did not finish: {name}")
        if "Broken pipe" in result:
            time.sleep(10)
    adb("shell", shlex.join(["am", "force-stop", package]))


if __name__ == "__main__":
    main()
