import ctypes
from ctypes import wintypes
import win32gui
import win32process
import win32api
import win32con
import win32ui
from PIL import Image

PW_RENDERFULLCONTENT = 0x00000002
PROCESS_NAME = "mk_legacy_kollection.exe"


def find_window_for_process(process_name):
    target_hwnd = None

    def callback(hwnd, _):
        nonlocal target_hwnd
        if not win32gui.IsWindowVisible(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
            exe_name = win32process.GetModuleFileNameEx(handle, 0)
        except Exception:
            return True
        if exe_name.lower().endswith(process_name.lower()) and target_hwnd is None:
            # Prefer windows with a non-empty title and real size
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
                target_hwnd = hwnd
        return True  # always continue - returning False here triggers a spurious pywin32 exception

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass  # some pywin32 versions raise a bogus error even on clean completion
    return target_hwnd


def capture_window(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = right - left
    height = bottom - top

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()

    save_bitmap = win32ui.CreateBitmap()
    save_bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(save_bitmap)

    result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

    bmpinfo = save_bitmap.GetInfo()
    bmpstr = save_bitmap.GetBitmapBits(True)
    img = Image.frombuffer(
        "RGB",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr, "raw", "BGRX", 0, 1,
    )

    win32gui.DeleteObject(save_bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return img, result


if __name__ == "__main__":
    hwnd = find_window_for_process(PROCESS_NAME)
    if not hwnd:
        print(f"Could not find a window for process {PROCESS_NAME}")
    else:
        title = win32gui.GetWindowText(hwnd)
        print(f"Found window: hwnd={hwnd} title={title!r}")
        img, result = capture_window(hwnd)
        print(f"PrintWindow result: {result} (nonzero = success)")
        out_path = "capture_test_output.png"
        img.save(out_path)
        print(f"Saved capture to {out_path}, size={img.size}")
