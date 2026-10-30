"""Line-protocol client for the in-process ACIS agent (\\\\.\\pipe\\cst-acis-<pid>)."""
import os


class Agent:
    def __init__(self, pid, scratch):
        self.f = open("//./pipe/cst-acis-" + str(pid), "r+b", buffering=0)
        self.scratch = os.path.abspath(scratch).replace(os.sep, "/")
        os.makedirs(self.scratch, exist_ok=True)

    def cmd(self, line, check=True):
        self.f.write((line + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += self.f.read(4096)
        r = buf.decode().strip()
        if check and not r.startswith("OK"):
            raise RuntimeError(f"{line[:120]!r}: {r}")
        return r

    def ids(self, idx):
        """Index list argument: inline when short, else through a file."""
        s = " ".join(map(str, idx))
        if len(s) < 600:
            return s
        path = f"{self.scratch}/ids.txt"
        with open(path, "w") as f:
            f.write(s)
        return "@" + path

    def boxes(self, what):
        """Current faces/edges as [(index, (x0,y0,z0,x1,y1,z1))]."""
        path = f"{self.scratch}/dump_{what}.txt"
        self.cmd(f"dump {what} {path}")
        out = []
        for line in open(path):
            v = line.split()
            out.append((int(v[0]), tuple(float(x) for x in v[1:7])))
        return out


def box_dist(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


def match(targets, current, tol):
    """For each target box, the index of the current entity with the closest box
    (None when nothing is within tol)."""
    out = []
    for t in targets:
        best = min(current, key=lambda c: box_dist(c[1], t))
        out.append(best[0] if box_dist(best[1], t) <= tol else None)
    return out


def parse_bbox(reply):
    import re
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", reply.split("lo=")[1])]
    return tuple(v[:6])


class Guard:
    """Runs a modifying command and rolls it back when the body comes out
    implausible: grown past the original box, or volume changed by more than the
    region the operation can touch. ACIS reports success for some removals that
    leave spikes running far out of the part."""

    def __init__(self, ag, box_tol=0.01):
        self.ag = ag
        self.box0 = parse_bbox(ag.cmd("bbox"))
        self.box_tol = box_tol
        self.vol = self.volume()

    def volume(self):
        return float(self.ag.cmd("mass").split("volume=")[1])

    def run(self, cmd, dv_max):
        self.ag.cmd("snap")
        r = self.ag.cmd(cmd, check=False)
        if not r.startswith("OK"):
            return False, r
        box = parse_bbox(self.ag.cmd("bbox"))
        v = self.volume()
        grew = any(box[k] < self.box0[k] - self.box_tol for k in range(3)) or             any(box[k + 3] > self.box0[k + 3] + self.box_tol for k in range(3))
        if grew or abs(v - self.vol) > dv_max:
            self.ag.cmd("undo")
            return False, f"rejected: box {'grew' if grew else 'ok'}, dV={v - self.vol:.4g} (limit {dv_max:.4g})"
        self.vol = v
        return True, r
