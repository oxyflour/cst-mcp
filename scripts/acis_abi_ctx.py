"""Print machine code around ACIS api_* call sites to recover the `outcome` ABI."""
from __future__ import print_function

import struct

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

PATH = r"C:\Programs\CST Studio Suite 2022\AMD64\AcisTools_AMD64.dll"
MAX_SITES = 3


def main():
    pe = pefile.PE(PATH)
    base = pe.OPTIONAL_HEADER.ImageBase

    api_slots = {}
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        if entry.dll.lower() != b"spaacis.dll":
            continue
        for imp in entry.imports:
            name = (imp.name or b"").decode(errors="replace")
            if name.startswith("?api_"):
                api_slots[imp.address] = name

    text = next(s for s in pe.sections if b".text" in s.Name)
    data = text.get_data()
    tva = base + text.VirtualAddress

    sites = []
    for k in range(len(data) - 6):
        if data[k] == 0xFF and data[k + 1] == 0x15:
            disp = struct.unpack_from("<i", data, k + 2)[0]
            target = tva + k + 6 + disp
            if target in api_slots:
                sites.append((tva + k, api_slots[target]))

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    seen = set()
    shown = 0
    for addr, name in sites:
        if name in seen:
            continue
        seen.add(name)
        start = addr - 0x38
        print("\n=== %s" % name[:78])
        for insn in md.disasm(data[start - tva:start - tva + 0x50], start):
            mark = "   <<< CALL api" if insn.address == addr else ""
            print("   %012X  %-26s %-8s %s%s" % (
                insn.address, insn.bytes.hex(), insn.mnemonic, insn.op_str, mark))
        shown += 1
        if shown >= MAX_SITES:
            break
    pe.close()


if __name__ == "__main__":
    main()
