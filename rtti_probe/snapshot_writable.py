"""
Snapshot every writable region of mk_legacy_kollection.exe's memory to a
single file (region table + concatenated bytes), for later diffing
against a second snapshot to find a value that changed between two known
game states (e.g. character-select cursor moved from A to B).
"""
import ctypes
import pickle
import sys
from ctypes import wintypes

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
TH32CS_SNAPPROCESS = 0x00000002
WRITABLE_PROTECT_FLAGS = {0x04, 0x08, 0x20, 0x40}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
    ]


def find_pid(process_name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    if not kernel32.Process32First(snap, ctypes.byref(entry)):
        return None
    while True:
        if entry.szExeFile.decode(errors="replace").lower() == process_name.lower():
            kernel32.CloseHandle(snap)
            return entry.th32ProcessID
        if not kernel32.Process32Next(snap, ctypes.byref(entry)):
            kernel32.CloseHandle(snap)
            return None


def main():
    out_path = sys.argv[1]
    pid = find_pid("mk_legacy_kollection.exe")
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)

    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    regions = []
    total = 0
    while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize
        if mbi.State == MEM_COMMIT and mbi.Protect in WRITABLE_PROTECT_FLAGS and not (mbi.Protect & PAGE_GUARD) and size > 0:
            data = bytearray()
            off = 0
            while off < size:
                n = min(size - off, 8 << 20)
                buf = (ctypes.c_ubyte * n)()
                read_n = ctypes.c_size_t(0)
                ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base + off), buf, n, ctypes.byref(read_n))
                data += bytes(buf) if ok else bytes(n)
                off += n
            regions.append((base, bytes(data)))
            total += len(data)
        address = (mbi.BaseAddress or 0) + max(size, 1)
        if address > (1 << 48):
            break
    kernel32.CloseHandle(handle)

    with open(out_path, "wb") as f:
        pickle.dump(regions, f, protocol=4)
    print(f"Snapshot: {len(regions)} regions, {total/1e6:.1f} MB -> {out_path}")


if __name__ == "__main__":
    main()
