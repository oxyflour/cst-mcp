"""Dump exports/imports of the ACIS-related DLLs shipped with CST 2022."""
from __future__ import print_function

import os
import sys
import pefile

ROOT = r"C:\Programs\CST Studio Suite 2022"
TARGETS = [
    os.path.join(ROOT, "ACIS", "NT_VC15_64_DLL", "code", "bin", "SpaACIS.dll"),
    os.path.join(ROOT, "AMD64", "AcisInterface_AMD64.dll"),
    os.path.join(ROOT, "AMD64", "AcisTools_AMD64.dll"),
    os.path.join(ROOT, "AMD64", "MeshConvertersAcis_AMD64.dll"),
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")


def file_version(path):
    try:
        pe = pefile.PE(path, fast_load=True)
        for fi in pe.FileInfo or []:
            for entry in fi:
                if getattr(entry, "Key", b"") == b"StringFileInfo":
                    for st in entry.StringTable:
                        d = {k.decode(errors="replace"): v.decode(errors="replace") for k, v in st.entries.items()}
                        return d
    except Exception as exc:
        return {"error": str(exc)}
    return {}


def main():
    os.makedirs(OUT, exist_ok=True)
    for path in TARGETS:
        name = os.path.basename(path)
        print("=" * 70)
        print(name, "%.2f MB" % (os.path.getsize(path) / 1048576.0))
        ver = file_version(path)
        for k in ("CompanyName", "FileDescription", "FileVersion", "ProductVersion", "LegalCopyright"):
            if k in ver:
                print("  %-16s %s" % (k + ":", ver[k]))

        pe = pefile.PE(path)
        print("  machine          %s" % hex(pe.FILE_HEADER.Machine))
        print("  timestamp        %s" % pe.FILE_HEADER.TimeDateStamp)

        imports = sorted({e.dll.decode(errors="replace") for e in (pe.DIRECTORY_ENTRY_IMPORT or [])})
        print("  imports (%d): %s" % (len(imports), ", ".join(imports[:12])))

        exports = []
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for sym in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                if sym.name:
                    exports.append(sym.name.decode(errors="replace"))
        print("  exports          %d (named)" % len(exports))

        with open(os.path.join(OUT, name + ".exports.txt"), "w") as fh:
            fh.write("\n".join(exports))

        api = [e for e in exports if e.startswith("api_")]
        print("  api_*            %d" % len(api))
        if api:
            print("  sample           %s" % ", ".join(api[:8]))
        non_api = [e for e in exports if not e.startswith("api_")]
        print("  non api_*        %d" % len(non_api))
        for e in non_api[:25]:
            print("      ", e[:110])
        if len(non_api) > 25:
            print("       ... (%d more, see out/%s.exports.txt)" % (len(non_api) - 25, name))
        pe.close()


if __name__ == "__main__":
    sys.exit(main())
