import ctypes
import os
import time

dll_path = os.path.join(os.path.dirname(__file__), "nvda_controller_client", "x64", "nvdaControllerClient.dll")
clientLib = ctypes.windll.LoadLibrary(dll_path)

res = clientLib.nvdaController_testIfRunning()
if res != 0:
    print("NVDA does not appear to be running. Error:", ctypes.WinError(res))
else:
    print("NVDA is running - speaking test message...")
    clientLib.nvdaController_speakText("Accessibility test: if you can hear this, the NVDA controller client is working.")
    time.sleep(3)
    print("Done.")
