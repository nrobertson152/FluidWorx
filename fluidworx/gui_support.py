"""Drawing facts that need no window, so they can be tested without one."""
from __future__ import annotations


def cylinder_motion(geometry):
    """(moving primitive indexes, retracted piston dx, extended dx) for a drawn cylinder, or None if unusual.

    OpenSchematix cylinders share a body from x=-30 to x=20 with a piston (a thick line, or a thin rectangle in
    ANSI symbols) and a rod along y=0."""
    piston_x, moving = None, []
    for i, p in enumerate(geometry.prims):
        if p["k"] == "line" and p.get("w") == "thick" and len(p["pts"]) == 2 and p["pts"][0][0] == p["pts"][1][0]:
            piston_x = p["pts"][0][0]
            moving.append(i)
        elif p["k"] == "poly" and len(p["pts"]) == 4:
            xs = [q[0] for q in p["pts"]]
            ys = [q[1] for q in p["pts"]]
            if max(xs) - min(xs) == 4 and max(ys) - min(ys) == 20:
                piston_x = min(xs)
                moving.append(i)
    if piston_x is None or len(moving) != 1:
        return None
    for i, p in enumerate(geometry.prims):
        if i in moving:
            continue
        if p["k"] == "line":
            xs = [q[0] for q in p["pts"]]
            # the rod along y=0, or any line that leaves the body (a large rod's outline, a rear rod)
            if all(abs(q[1]) < 1e-6 for q in p["pts"]) or max(xs) > 20 or min(xs) < -30:
                moving.append(i)
        elif p["k"] == "poly" and i > 0:
            ys = [q[1] for q in p["pts"]]
            if max(ys) <= 5 and min(ys) >= -5:      # a cushion boss rides on the piston
                moving.append(i)
    if len(moving) < 2:
        return None
    return moving, -28.0 - piston_x, 14.0 - piston_x
