"""
MSVC x64 RTTI locate-and-identify toolkit for mk_legacy_kollection.exe.

Phase 1 tooling (see PROGRESS.md / project memory): the launcher's own
Dear ImGui UI has no accessibility hook, but the classic titles run on
two real emulator cores with intact (unstripped-at-the-symbol-name-level)
C++ RTTI - the open-source `ares` in pancake_libretro_windows.dll for the
PS1 titles, and an in-house `Moo` core inside the main exe for
Genesis/Game Gear/arcade titles. This toolkit locates *live* instances of
any named class in the main exe by walking standard x64 MSVC RTTI
structures - no Ghidra/IDA, no code injection, read-only
(PROCESS_VM_READ only) throughout.

Technique, in order:
  1. Dump the module's image from live process memory (already correctly
     relocated/laid out, unlike reading the file from disk).
  2. find-class:  locate the mangled TypeDescriptor name string for a
     class (e.g. ".?AVDevGroup@Moo@@"), then the Complete Object Locator
     (COL) structures that reference it by RVA, then the vtable(s) that
     point back at those COLs (a QWORD pointer to the COL sits 8 bytes
     before the actual vtable).
  3. find-instances: given a vtable VA, scan writable/heap memory for
     QWORD values equal to it - each hit's address is a live instance
     (the vfptr field sits at offset 0 of any polymorphic C++ object).
  4. identify: the inverse of (2) - given an arbitrary object's address,
     read its vfptr and walk backwards to the class name. Useful for
     labeling pointers found *inside* an already-located object (see
     PROGRESS.md's DevGroup child-device findings).

Verified 2026-09-12 against a live arcade Mortal Kombat II session: found
the one live Moo::DevGroup instance, then identified its four child
device pointers as Moo_CPU_TMS34010, Moo_Glue_Midway_Blit_T,
Moo_CPU_ADSP2105, and Moo_Sub_DCS - the real, documented Midway T-Unit
board hardware, which cross-checks the technique against ground truth.

CLI:
    python rtti_probe.py find-class ".?AVDevGroup@Moo@@"
    python rtti_probe.py find-instances 0x7ff74ff44ba0
    python rtti_probe.py identify 0x23edaa48178 0x23edaa69a50 ...

Every address printed is only valid for the current process instance -
ASLR means the module base (and therefore every VA derived from it)
changes on each relaunch. Re-run find-class/find-instances each session;
only the technique and the mangled class-name strings are durable.
"""

import ctypes
import re
import struct
import sys
from ctypes import wintypes

PROCESS_NAME = "mk_legacy_kollection.exe"

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
WRITABLE_PROTECT_FLAGS = {0x04, 0x08, 0x20, 0x40}  # PAGE_READWRITE, PAGE_WRITECOPY, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def find_pid(process_name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1):
        return None
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.decode(errors="replace").lower() == process_name.lower():
                return entry.th32ProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)


def find_module(pid, module_name):
    """Returns (base, size) or (None, None)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap in (0, -1):
        return None, None
    try:
        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        if not kernel32.Module32First(snap, ctypes.byref(entry)):
            return None, None
        while True:
            if entry.szModule.decode(errors="replace").lower() == module_name.lower():
                return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value, entry.modBaseSize
            if not kernel32.Module32Next(snap, ctypes.byref(entry)):
                return None, None
    finally:
        kernel32.CloseHandle(snap)


def attach():
    """Returns (handle, module_base, module_size) for the live game process."""
    pid = find_pid(PROCESS_NAME)
    if pid is None:
        raise RuntimeError(f"{PROCESS_NAME} is not running")
    base, size = find_module(pid, PROCESS_NAME)
    if base is None:
        raise RuntimeError(f"could not find module {PROCESS_NAME} in PID {pid}")
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise RuntimeError(f"OpenProcess failed (err={ctypes.get_last_error()})")
    return handle, base, size


def read(handle, addr, size):
    buf = (ctypes.c_ubyte * size)()
    read_n = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(read_n))
    if not ok or read_n.value != size:
        return None
    return bytes(buf)


def dump_module_image(handle, base, size, chunk=1 << 20):
    """Best-effort: unmapped/guarded pages inside the image become zero-
    filled placeholders so offsets downstream stay correct."""
    out = bytearray()
    off = 0
    while off < size:
        n = min(chunk, size - off)
        data = read(handle, base + off, n)
        out += data if data is not None else bytes(n)
        off += n
    return bytes(out)


def demangle_guess(mangled: str) -> str:
    """Cheap best-effort MSVC name unscramble for the common '.?AV<name>@<ns>@@'
    pattern (single/multi-namespace class), not a general demangler."""
    m = re.match(r"^\.\?A[VU]((?:\w+@)+)@$", mangled)
    if not m:
        return mangled
    parts = [p for p in m.group(1).split("@") if p]
    return "::".join(reversed(parts))


def mangle_guess(class_path: str) -> bytes:
    """Inverse of demangle_guess: 'Moo::DevGroup' -> b'.?AVDevGroup@Moo@@\\x00'."""
    parts = class_path.split("::")
    return (".?AV" + "@".join(reversed(parts)) + "@@\x00").encode("ascii")


def find_vtables_for_class(image, module_base, mangled_name: bytes):
    """Returns a list of (col_rva, vtable_va) for every validated Complete
    Object Locator + vtable found for this TypeDescriptor name."""
    results = []
    start = 0
    while True:
        name_off = image.find(mangled_name, start)
        if name_off == -1:
            break
        start = name_off + 1
        td_offset = name_off - 16  # TypeDescriptor: {vfptr(8); spare(8); name[]}
        if td_offset < 0:
            continue
        target_rva = struct.pack("<I", td_offset)
        pos = 0
        while True:
            idx = image.find(target_rva, pos)
            if idx == -1:
                break
            pos = idx + 1
            col_start = idx - 12  # pTypeDescriptor sits at COL+0xC
            if not (0 <= col_start and col_start + 24 <= len(image)):
                continue
            sig, off_, cd_off, p_td, p_cd, p_self = struct.unpack_from("<IIIIII", image, col_start)
            if not (sig == 1 and p_td == td_offset and p_self == col_start):
                continue
            col_va = module_base + col_start
            target_qword = struct.pack("<Q", col_va)
            vpos = 0
            while True:
                vidx = image.find(target_qword, vpos)
                if vidx == -1:
                    break
                vpos = vidx + 1
                vtable_rva = vidx + 8
                results.append((col_start, module_base + vtable_rva))
    return results


def find_instances_of_vtable(handle, vtable_va, max_hits=50):
    target = struct.pack("<Q", vtable_va)
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    hits = []
    while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize
        if mbi.State == MEM_COMMIT and mbi.Protect in WRITABLE_PROTECT_FLAGS and not (mbi.Protect & PAGE_GUARD) and size > 0:
            off = 0
            while off < size and len(hits) < max_hits:
                chunk_size = min(size - off, 8 << 20)
                data = read(handle, base + off, chunk_size)
                if data:
                    pos = 0
                    while True:
                        idx = data.find(target, pos)
                        if idx == -1:
                            break
                        hits.append(base + off + idx)
                        pos = idx + 1
                        if len(hits) >= max_hits:
                            break
                off += chunk_size
        address = (mbi.BaseAddress or 0) + max(size, 1)
        if len(hits) >= max_hits or address > (1 << 48):
            break
    return hits


def identify_object(handle, module_base, module_size, obj_addr):
    """Returns (vtable_va_or_None, description_string)."""
    vfptr_bytes = read(handle, obj_addr, 8)
    if vfptr_bytes is None:
        return None, "unreadable"
    vtable_va = struct.unpack("<Q", vfptr_bytes)[0]
    if not (module_base <= vtable_va < module_base + module_size):
        return vtable_va, "vtable not in main module (not a polymorphic instance of this exe, or a bad pointer)"
    col_ptr_bytes = read(handle, vtable_va - 8, 8)
    if col_ptr_bytes is None:
        return vtable_va, "couldn't read COL pointer slot"
    col_va = struct.unpack("<Q", col_ptr_bytes)[0]
    if not (module_base <= col_va < module_base + module_size):
        return vtable_va, "COL pointer out of module range - probably not an RTTI vtable"
    col = read(handle, col_va, 24)
    if col is None:
        return vtable_va, "couldn't read COL"
    sig, off_, cd_off, p_td_rva, p_cd_rva, p_self_rva = struct.unpack("<IIIIII", col)
    if sig != 1:
        return vtable_va, f"COL signature mismatch ({sig}, expected 1)"
    name_bytes = read(handle, module_base + p_td_rva + 16, 128)
    if name_bytes is None:
        return vtable_va, "couldn't read TypeDescriptor name"
    name = name_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return vtable_va, demangle_guess(name)


def _cmd_find_class(args):
    mangled_name = args[0].encode("ascii") if args[0].startswith(".?A") else mangle_guess(args[0])
    handle, base, size = attach()
    print(f"Attached to {PROCESS_NAME} - base=0x{base:012x} size=0x{size:x}")
    image = dump_module_image(handle, base, size)
    results = find_vtables_for_class(image, base, mangled_name)
    if not results:
        print(f"No vtable found for {mangled_name!r}.")
        return 1
    for col_rva, vtable_va in results:
        print(f"  COL RVA=0x{col_rva:08x}  vtable VA=0x{vtable_va:012x}")
    return 0


def _cmd_find_instances(args):
    vtable_va = int(args[0], 0)
    max_hits = int(args[1]) if len(args) > 1 else 50
    handle, base, size = attach()
    hits = find_instances_of_vtable(handle, vtable_va, max_hits)
    print(f"Found {len(hits)} instance(s):")
    for h in hits:
        print(f"  0x{h:012x}")
    return 0


def _cmd_identify(args):
    handle, base, size = attach()
    for a in args:
        addr = int(a, 0)
        vtable_va, name = identify_object(handle, base, size, addr)
        vt_str = f"0x{vtable_va:012x}" if vtable_va else "?"
        print(f"0x{addr:012x}  vtable={vt_str}  class={name}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "find-class" and args:
        return _cmd_find_class(args)
    if cmd == "find-instances" and args:
        return _cmd_find_instances(args)
    if cmd == "identify" and args:
        return _cmd_identify(args)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
