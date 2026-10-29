"""Disassemble CST's own call to api_save_entity_list to copy the exact args."""
import struct

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

PATH = r"C:\Programs\CST Studio Suite 2022\AMD64\SatMifInterface_AMD64.dll"
TARGET = "?api_save_entity_list@@"

pe = pefile.PE(PATH)
base = pe.OPTIONAL_HEADER.ImageBase

slot = None
for entry in pe.DIRECTORY_ENTRY_IMPORT:
    if entry.dll.lower() != b"spaacis.dll":
        continue
    for imp in entry.imports:
        name = (imp.name or b"").decode(errors="replace")
        if name.startswith(TARGET):
            slot = imp.address
            print("iat slot VA:", hex(slot))

text = next(s for s in pe.sections if b".text" in s.Name)
data = text.get_data()
tva = base + text.VirtualAddress
print("text rva", hex(text.VirtualAddress), "size", len(data), "tva", hex(tva))

sites = []
for k in range(len(data) - 6):
    if data[k] == 0xFF and data[k + 1] == 0x15:
        disp = struct.unpack_from("<i", data, k + 2)[0]
        if tva + k + 6 + disp == slot:
            sites.append(tva + k)
print("sites:", [hex(s) for s in sites])

md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True

for site in sites[:1]:
    start = site - 0x40
    off = start - tva
    print("disasm from", hex(start), "off", off)
    out = []
    for insn in md.disasm(data[off:off + 0x70], start):
        mark = "   <<< CALL" if insn.address == site else ""
        out.append("  %012X  %-22s %-9s %s%s" % (
            insn.address, insn.bytes.hex(), insn.mnemonic, insn.op_str, mark))
    print("\n".join(out))
pe.close()
