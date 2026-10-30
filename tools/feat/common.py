import sat, classify as C
def signed(m, f):
    s = 0
    for lp in m.loops(f):
        p = C.loop_points(m, lp)
        s += 0.5 * sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1] for i in range(len(p)))
    return s
