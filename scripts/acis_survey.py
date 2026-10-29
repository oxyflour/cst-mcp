"""Classify what SpaACIS.dll actually exposes, and find its ACIS release."""
from __future__ import print_function

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out")
DLL = r"C:\Programs\CST Studio Suite 2022\ACIS\NT_VC15_64_DLL\code\bin\SpaACIS.dll"


def classify():
    exports = open(os.path.join(OUT, "SpaACIS.dll.exports.txt")).read().split()
    print("named exports:", len(exports))
    groups = {
        "BODY": [], "ENTITY": [], "SPAposition": [], "law": [], "surface": [],
        "curve": [], "solid": [], "face": [], "edge": [], "mesh": [],
        "ATTRIB": [], "PART": [], "journal": [], "version": [],
    }
    for e in exports:
        for key in groups:
            if key.lower() in e.lower():
                groups[key].append(e)
                break
    for key, hits in groups.items():
        print("%-12s %5d   e.g. %s" % (key, len(hits), hits[0][:100] if hits else "-"))


def find_acis_banner():
    with open(DLL, "rb") as fh:
        data = fh.read()
    print("\nfile size: %.1f MB" % (len(data) / 1048576.0))
    for needle in (b"ACIS", b"apollo", b"api_start_modeller", b"ACIS_VERSION"):
        idxs = []
        start = 0
        while True:
            i = data.find(needle, start)
            if i < 0:
                break
            idxs.append(i)
            start = i + 1
            if len(idxs) >= 400:
                break
        print("%-20s occurrences (first 400): %d" % (needle.decode(), len(idxs)))

    # version-shaped strings near ACIS banners
    text = data.decode("latin-1")
    pats = [
        r"ACIS[ \t]*[0-9]{4}[^\x00]{0,40}",
        r"[0-9]{4}\s*[0-9]\.[0-9]\.[0-9][^\x00]{0,30}",
        r"Spatial[^\x00]{0,60}",
    ]
    for p in pats:
        hits = sorted(set(re.findall(p, text)))[:20]
        print("\n/%s/ -> %d" % (p, len(hits)))
        for h in hits:
            print("   ", repr(h[:90]))


if __name__ == "__main__":
    classify()
    find_acis_banner()
    sys.exit(0)
