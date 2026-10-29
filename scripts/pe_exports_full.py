"""Read the full export name table of a PE without pefile's 8192-name cap."""
from __future__ import print_function

import struct
import sys

PATH = r"C:\Programs\CST Studio Suite 2022\ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll"


def main():
    data = open(PATH, "rb").read()
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)
    exp_rva, exp_size = struct.unpack_from("<II", data, dd)
    print("export dir rva=0x%X size=%d" % (exp_rva, exp_size))

    sec = opt + struct.unpack_from("<H", data, e_lfanew + 20)[0]
    sections = []
    for i in range(nsec):
        off = sec + i * 40
        vsize, va, rsize, rptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((va, vsize, rptr, rsize))

    def rva2off(rva):
        for va, vsize, rptr, rsize in sections:
            if va <= rva < va + max(vsize, rsize):
                return rptr + (rva - va)
        return None

    e = rva2off(exp_rva)
    (chars, ts, maj, minr, name_rva, base, nfunc, nnames,
     addr_funcs, addr_names, addr_ords) = struct.unpack_from("<IIHHIIIIIII", data, e)

    print("NumberOfFunctions", nfunc, "NumberOfNames", nnames, "base", base)
    names_off = rva2off(addr_names)
    print("names table offset 0x%X, bytes %d" % (names_off, nnames * 4))

    names = []
    for i in range(nnames):
        nrva = struct.unpack_from("<I", data, names_off + i * 4)[0]
        o = rva2off(nrva)
        if o is None:
            continue
        end = data.index(b"\x00", o)
        names.append(data[o:end].decode("latin-1"))

    print("parsed", len(names))
    api = [n for n in names if n.startswith("api_")]
    print("api_*", len(api))
    for n in api[:15]:
        print("   ", n)
    print("plain (no ?)", sum(1 for n in names if not n.startswith("?")))
    print("last 5:", names[-5:])

    with open("out/SpaACIS.full.exports.txt", "w") as fh:
        fh.write("\n".join(names))


if __name__ == "__main__":
    sys.exit(main())
