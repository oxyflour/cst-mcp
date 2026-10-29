"""Decode MSVC-mangled ACIS api_* names into readable prototypes.

Handles the subset used by the ACIS C API: UDTs by value/pointer/reference,
scalars, bool, and the `0` "same as previous parameter" marker.
Output is meant for hand-writing C++ function pointer types, so pointer/ref
count and constness matter, exact cv placement does not.
"""
from __future__ import print_function

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORTS = os.path.join(HERE, "..", "out", "SpaACIS.full.exports.txt")

BUILTIN = {
    "X": "void", "D": "char", "C": "signed char", "E": "unsigned char",
    "F": "short", "G": "unsigned short", "H": "int", "I": "unsigned int",
    "J": "long", "K": "unsigned long", "_J": "__int64", "_K": "unsigned __int64",
    "M": "float", "N": "double", "O": "long double", "_N": "bool", "_W": "wchar_t",
}
MARKERS = "EAIF"


class Decoder(object):
    def __init__(self, s, i):
        self.s, self.i = s, i

    def peek(self, n=1):
        return self.s[self.i:self.i + n]

    def take(self, n=1):
        out = self.s[self.i:self.i + n]
        self.i += n
        return out

    def class_name(self):
        start = self.i
        while not self.s.startswith("@@", self.i) and self.i < len(self.s):
            self.i += 1
        name = self.s[start:self.i].split("@")[0]
        self.i += 2
        return name

    def type(self, is_return=False):
        const = False
        ptr = ref = 0
        if is_return and self.peek(2) in ("?A", "?B"):
            const = self.peek(2) == "?B"
            self.take(2)
        else:
            while True:
                c = self.peek()
                if c in "PQRS":
                    self.take()
                    while self.peek() in MARKERS:
                        self.take()
                    ptr += 1
                    if c in "QS":
                        const = True
                elif c in "AB":
                    self.take()
                    while self.peek() in MARKERS:
                        self.take()
                    if self.peek() == "B":
                        self.take()
                        const = True
                    elif self.peek() == "A":
                        self.take()
                    ref += 1
                else:
                    break

        c = self.peek()
        if c == "X":
            self.take()
            base = "void"
        elif self.peek(2) in ("_N", "_J", "_K", "_W"):
            code = self.take(2)
            base = BUILTIN[code]
        elif c == "W" and self.peek(2) == "W4":
            self.take(2)
            base = self.class_name()
        elif c in "VUT":
            self.take()
            base = self.class_name()
        elif c in BUILTIN:
            self.take()
            base = BUILTIN[c]
        else:
            base = "?" + self.take()

        return ("const " if const else "") + base + "*" * ptr + "&" * ref


def demangle(sym):
    if not sym.startswith("?"):
        return None
    body = sym[1:]
    idx = body.find("@@")
    if idx < 0:
        return None
    name = body[:idx]
    d = Decoder(body, idx + 2)
    if d.peek() == "Y":          # global function
        d.take()
    if d.peek() in "AGI":        # calling convention
        d.take()
    ret = d.type(is_return=True)
    params = []
    while d.i < len(d.s) - 1:
        if d.s.startswith("@Z", d.i):
            break
        if d.peek() == "@":
            d.take()
            continue
        if d.peek() == "0":
            d.take()
            if params:
                params.append(params[-1])
            continue
        try:
            params.append(d.type())
        except Exception:
            break
    return "%s __cdecl %s(%s)" % (ret, name, ", ".join(params))


def main():
    wanted = sys.argv[1:]
    lines = open(EXPORTS).read().splitlines()
    by_name = {}
    for l in lines:
        if l.startswith("?api_"):
            m = re.match(r"\?([A-Za-z0-9_]+)@@", l)
            if m:
                by_name.setdefault(m.group(1), []).append(l)
    for n in (wanted or sorted(by_name)):
        for sym in sorted(by_name.get(n, [])):
            print("%s\n    %s" % (sym, demangle(sym)))


if __name__ == "__main__":
    main()
