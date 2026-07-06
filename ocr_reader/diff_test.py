import ctypes
import sys
import time

import win32gui
import win32process
import win32api
import win32con
from PIL import Image, ImageChops

sys.path.insert(0, ".")
from capture_test import find_window_for_process, capture_window, PROCESS_NAME

KEYEVENTF_KEYUP = 0x0002
VK_MAP = {
    "down": 0x28, "up": 0x26, "left": 0x25, "right": 0x27,
    "enter": 0x0D, "escape": 0x1B, "tab": 0x09, "space": 0x20,
}


def send_key(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def main():
    key_name = sys.argv[1] if len(sys.argv) > 1 else "down"
    vk = VK_MAP[key_name]

    hwnd = find_window_for_process(PROCESS_NAME)
    if not hwnd:
        print("Game window not found.")
        return
    print(f"hwnd={hwnd}")

    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    before = capture_window(hwnd)[0]
    before.save("diff_before.png")

    send_key(vk)
    time.sleep(0.3)

    after = capture_window(hwnd)[0]
    after.save("diff_after.png")

    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    bbox = diff.getbbox()
    print("Diff bounding box (changed region):", bbox)
    diff.save("diff_raw.png")

    if bbox:
        # Amplify diff for visibility
        import numpy as np
        arr = np.array(diff)
        amplified = np.clip(arr.astype(int) * 5, 0, 255).astype("uint8")
        Image.fromarray(amplified).save("diff_amplified.png")
        print("Saved diff_before.png, diff_after.png, diff_amplified.png")


if __name__ == "__main__":
    main()
