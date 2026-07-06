import os
import sys
import time

sys.path.insert(0, ".")
from capture_test import find_window_for_process, capture_window, PROCESS_NAME

OUT_DIR = sys.argv[3] if len(sys.argv) > 3 else "sequence"
DURATION_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
INTERVAL_SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 0.75


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        os.remove(os.path.join(OUT_DIR, f))

    hwnd = find_window_for_process(PROCESS_NAME)
    if not hwnd:
        print("Game window not found.")
        return

    print(f"Capturing for {DURATION_SECONDS}s every {INTERVAL_SECONDS}s. Navigate the menu now!")
    start = time.time()
    i = 0
    while time.time() - start < DURATION_SECONDS:
        img, _ = capture_window(hwnd)
        path = os.path.join(OUT_DIR, f"frame_{i:03d}.png")
        img.save(path)
        print(f"  saved {path} at t={time.time()-start:.1f}s")
        i += 1
        time.sleep(INTERVAL_SECONDS)
    print("Done.")


if __name__ == "__main__":
    main()
