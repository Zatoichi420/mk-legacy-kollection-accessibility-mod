import frida
import sys
import time

import sys as _sys
script_name = _sys.argv[1] if len(_sys.argv) > 1 else "find_gimgui.js"
ground_truth_frame = _sys.argv[2] if len(_sys.argv) > 2 else "10000"
with open(script_name, "r", encoding="utf-8") as f:
    source = "const GROUND_TRUTH_FRAME = " + ground_truth_frame + ";\n" + f.read()

session = frida.attach("mk_legacy_kollection.exe")

def on_message(message, data):
    if message["type"] == "send":
        print(message["payload"])
    elif message["type"] == "log":
        print(message["payload"])
    elif message["type"] == "error":
        print("ERROR:", message.get("stack", message))
    else:
        print("MSG:", message)

script = session.create_script(source)
script.on("message", on_message)
script.load()

time.sleep(45)
session.detach()
