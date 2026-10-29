"""Recover the ACIS `outcome` return ABI from a CST call site.

MSVC x64 returns a non-trivial class by value through a hidden pointer in RCX.
A trivially-copyable 8-byte struct comes back in RAX. Which one applies to
`outcome` decides every prototype we hand-declare without ACIS headers.
"""
from __future__ import print_function

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86 import X86_OP_MEM, X86_OP_IMM, X86_REG_RIP

PATH = r"C:\Programs\CST Studio Suite 2022\AMD64\SatMifInterface_AMD64.dll"
WANTED = [
    "?api_save_version@@YA?AVoutcome@@HH@Z",
    "?api_get_save_version@@YA?AVoutcome@@AEAH0@Z",
    "?api_save_entity_list@@YA?AVoutcome@@PEAU_iobuf@@HAEBVENTITY_LIST@@PEAVAcisOptions@@@Z",
    "?api_make_wire@@YA?AVoutcome@@PEAVBODY@@HQEAVSPAposition@@AEAPEAV2@PEAVAcisOptions@@@Z",
]


def main():
    pe = pefile.PE(PATH)
    base = pe.OPTIONAL_HEADER.ImageBase

    slot_addrs = {}
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        if entry.dll.lower() != b"spaacis.dll":
            continue
        for imp in entry.imports:
            nm = (imp.name or b"").decode(errors="replace")
            if nm in WANTED:
                slot_addrs[imp.address] = nm  # IAT slot VA

    text = next(s for s in pe.sections if b".text" in s.Name)
    data = text.get_data()
    tva = base + text.VirtualAddress
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True

    def mem_target(insn, op):
        if op.mem.base == X86_REG_RIP:
            return insn.address + insn.size + op.mem.disp
        return None

    thunks = {}
    calls = []
    for insn in md.disasm(data, tva):
        if not insn.operands:
            continue
        op = insn.operands[0]
        if insn.mnemonic == "jmp" and op.type == X86_OP_MEM:
            t = mem_target(insn, op)
            if t in slot_addrs:
                thunks[insn.address] = slot_addrs[t]
        elif insn.mnemonic == "call":
            if op.type == X86_OP_IMM:
                calls.append((insn, op.imm))
            elif op.type == X86_OP_MEM:
                t = mem_target(insn, op)
                if t in slot_addrs:
                    calls.append((insn, insn.address))

    print("iat slots: %d  thunks: %d  calls: %d" % (len(slot_addrs), len(thunks), len(calls)))
    shown = 0
    for insn, tgt in calls:
        name = thunks.get(tgt)
        if not name:
            continue
        start = insn.address - 0x30
        print("\n=== call to %s" % name[:70])
        print("    site 0x%X  thunk 0x%X" % (insn.address, tgt))
        for i in md.disasm(data[start - tva:start - tva + 0x40], start):
            mark = "   <<< CALL" if i.address == insn.address else ""
            print("    %012X  %-22s %s %s%s" % (i.address, i.bytes.hex(), i.mnemonic, i.op_str, mark))
        shown += 1
        if shown >= 3:
            break
    if not shown:
        print("no thunked calls; sample:", list(thunks.items())[:4])
    pe.close()


if __name__ == "__main__":
    main()
