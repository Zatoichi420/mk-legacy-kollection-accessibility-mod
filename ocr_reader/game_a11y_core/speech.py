"""
Speech output that picks a working voice on every utterance.

Added 2026-10 for the installable build. nvda_speaker.py (still here,
unchanged, used by the MKX reader) only ever spoke through NVDA: if NVDA
wasn't running within 60 seconds the reader beeped and quit, so a JAWS or
Narrator user - or an NVDA user whose NVDA started late - got nothing at
all. Speaker here instead checks, per utterance:

  1. NVDA, through the vendored NVDA Controller Client DLL, if NVDA is
     running right now.
  2. Otherwise the built-in Windows voice (SAPI, via pywin32's COM support).

Checking every time (nvdaController_testIfRunning is a cheap local RPC call)
means the reader follows NVDA being started, restarted or closed mid-session
without any special handling. If neither voice works, it beeps - rate-limited,
same as nvda_speaker.py - since a beep is the one signal that still reaches
the user when speech itself is what's broken.

Every utterance is also printed as "SPEAK: ..." so the log records what the
user heard, which is the only way to diagnose "it said the wrong thing"
after the fact. mode="none" does only that (used by tests and CI).
"""

import ctypes
import os

try:
    import winsound
except ImportError:  # non-Windows (only the tests' pure-logic parts run there)
    winsound = None

MODES = ("auto", "nvda", "sapi", "none")

# SpeechVoiceSpeakFlags
SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2


def _audible_alert():
    try:
        if winsound is not None:
            winsound.Beep(400, 300)
    except Exception:
        pass


class NvdaBackend:
    name = "NVDA"

    def __init__(self, dll_path):
        self.lib = None
        if not dll_path or not os.path.isfile(dll_path):
            print(f"NVDA controller DLL not found at {dll_path!r}; NVDA output disabled.")
            return
        try:
            lib = ctypes.windll.LoadLibrary(dll_path)
            lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            self.lib = lib
        except (OSError, AttributeError) as exc:
            print(f"Couldn't load the NVDA controller DLL ({exc!r}); NVDA output disabled.")

    def available(self):
        if self.lib is None:
            return False
        try:
            return self.lib.nvdaController_testIfRunning() == 0
        except Exception:
            return False

    def speak(self, text, interrupt):
        if interrupt:
            self.lib.nvdaController_cancelSpeech()
        return self.lib.nvdaController_speakText(text) == 0

    def wait_until_done(self, timeout_seconds):
        pass  # NVDA speaks from its own process; nothing to wait for here


class SapiBackend:
    name = "Windows voice"

    def __init__(self):
        self.voice = None
        try:
            import win32com.client
            self.voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as exc:
            print(f"Windows voice (SAPI) unavailable: {exc!r}")

    def available(self):
        return self.voice is not None

    def speak(self, text, interrupt):
        flags = SVSF_ASYNC | (SVSF_PURGE_BEFORE_SPEAK if interrupt else 0)
        self.voice.Speak(text, flags)
        return True

    def wait_until_done(self, timeout_seconds):
        # Async speech dies with the process - anything said right before
        # exiting ("Accessibility reader stopped.") has to be waited for.
        try:
            self.voice.WaitUntilDone(int(timeout_seconds * 1000))
        except Exception:
            pass


class Speaker:
    def __init__(self, nvda_dll_path, mode="auto", nvda_factory=NvdaBackend, sapi_factory=SapiBackend):
        if mode not in MODES:
            raise ValueError(f"speech mode must be one of {MODES}, not {mode!r}")
        self.mode = mode
        self._nvda = nvda_factory(nvda_dll_path) if mode in ("auto", "nvda") else None
        self._sapi_factory = sapi_factory if mode in ("auto", "sapi") else None
        self._sapi = None  # created on first need - most NVDA users never need it
        self.current = None
        self.consecutive_failures = 0

    def _sapi_backend(self):
        if self._sapi is None and self._sapi_factory is not None:
            self._sapi = self._sapi_factory()
        return self._sapi

    def _candidates(self):
        if self._nvda is not None:
            yield self._nvda
        if self._sapi_factory is not None:
            yield self._sapi_backend()

    def active_backend_name(self):
        """Which voice would be used right now, or None if none works.
        For the self-test report."""
        if self.mode == "none":
            return "none (log only)"
        for backend in self._candidates():
            if backend.available():
                return backend.name
        return None

    def speak(self, text, interrupt=True):
        """Returns True if some voice accepted the text. interrupt=False
        queues behind whatever is still being said (used for full-screen
        reads so a fast-following selection change can't chop them)."""
        print(f"SPEAK: {text}")
        if self.mode == "none":
            return True
        for backend in self._candidates():
            if not backend.available():
                continue
            try:
                ok = backend.speak(text, interrupt)
            except Exception as exc:
                print(f"{backend.name} speech failed: {exc!r}")
                ok = False
            if ok:
                if backend is not self.current:
                    print(f"Speech output is now: {backend.name}")
                    self.current = backend
                self.consecutive_failures = 0
                return True
        self.consecutive_failures += 1
        if self.current is not None:
            print("Speech output is now: none available")
            self.current = None
        if self.consecutive_failures in (1, 10) or self.consecutive_failures % 60 == 0:
            _audible_alert()
        return False

    def wait_until_done(self, timeout_seconds=10):
        if self.current is not None:
            self.current.wait_until_done(timeout_seconds)
