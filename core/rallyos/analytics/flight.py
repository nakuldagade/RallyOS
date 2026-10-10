"""Launch speed of a shot from what the camera can measure: how far the shuttle went, how long it took, and how high the two
ends were. Training-free physics (§4.5), the config's drag law, no fitted parameters.

Why the plain "distance / time" number is wrong for a shuttle. A shuttle is slowed by air drag far more than a ball: with a
terminal velocity of 6.7 m/s the drag per metre is k = g / v_t^2 = 0.22 /m, so its speed falls by a factor e per 4.6 m. A
smash that leaves the racket at 300 km/h has dropped to about 100 km/h by the time it has crossed 5 m, and a flight of 10 m
that took 0.41 s (an average of 92 km/h) started at about 330 km/h. The average over the flight is therefore a small fraction
of the speed at the racket, and reporting it as the shot's speed (what the app did before) understates fast shots by a factor
of 2-4 and says nothing about how fast the shot was hit.

The model. The shuttle moves in a vertical plane through the two ends of the flight, with

    dv/dt = -g z^ - k |v| v ,        k = g / v_t^2

(gravity plus quadratic drag; the same `quadratic_drag` / `terminal_velocity_mps` the sport config already holds for the
shuttle search). For a launch speed v0 and angle theta the trajectory after a time T gives a displacement (dx, dz) that does
not depend on the starting height, so one table of displacements over a grid of (v0, theta) serves every shot. A shot gives
three measurements, the horizontal distance d, the flight time T and the height difference dz between the two ends, and two
unknowns (v0, theta): the answer is the cell of the table that reproduces (d, dz) at time T, refined with one Newton step and
checked by integrating that one trajectory.

What stays uncertain, and is reported. Distance (the players' feet are not the shuttle), timing (one video frame, or a few
milliseconds with sound) and the contact heights (from whether the wrist was above the head; the camera cannot measure the
height) all carry an error; the answer is solved again at every combination of those errors one standard deviation away, and
the spread is the band. Because drag makes the launch speed grow like exp(k d), a 10% error in distance is a 24% error in the
launch speed at d = 10 m: honest bands are wide, and the app says so. A (d, T, dz) that no launch can produce within the
speed limit of the sport (a 10 m flight in 0.15 s is faster than any smash ever recorded) is a measurement error and gets no
number, instead of the absurd one the old average produced.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

G = 9.81
DT = 0.004               # integration step of the table
KNOT = 0.02              # the table stores the displacement every KNOT seconds
T_MAX = 2.6              # longest flight the table covers (a high lift)
V_GRID = np.geomspace(2.0, 170.0, 190)               # m/s: 2.5 % steps
TH_GRID = np.radians(np.arange(-80.0, 85.01, 1.0))   # launch angle above the horizontal: down to up


@lru_cache(maxsize=4)
def _table(vt: float):
    """Displacement (x, z) after t = 0, KNOT, 2 KNOT ... for every (v0, theta): arrays of shape (knots, n_v, n_theta)."""
    k = G / (vt * vt)
    v0, th = np.meshgrid(V_GRID, TH_GRID, indexing="ij")
    x = np.zeros_like(v0)
    z = np.zeros_like(v0)
    vx, vz = v0 * np.cos(th), v0 * np.sin(th)

    def acc(vx, vz):
        s = np.hypot(vx, vz)
        return -k * s * vx, -G - k * s * vz

    per_knot = int(round(KNOT / DT))
    n_knots = int(T_MAX / KNOT) + 1
    X = np.empty((n_knots,) + v0.shape, np.float32)
    Z = np.empty_like(X)
    X[0], Z[0] = 0.0, 0.0
    for kn in range(1, n_knots):
        for _ in range(per_knot):                      # RK4
            a1x, a1z = acc(vx, vz)
            a2x, a2z = acc(vx + 0.5 * DT * a1x, vz + 0.5 * DT * a1z)
            a3x, a3z = acc(vx + 0.5 * DT * a2x, vz + 0.5 * DT * a2z)
            a4x, a4z = acc(vx + DT * a3x, vz + DT * a3z)
            nvx = vx + DT * (a1x + 2 * a2x + 2 * a3x + a4x) / 6.0
            nvz = vz + DT * (a1z + 2 * a2z + 2 * a3z + a4z) / 6.0
            x = x + DT * 0.5 * (vx + nvx)              # trapezoid on the RK4 velocity: second order, ample for this step size
            z = z + DT * 0.5 * (vz + nvz)
            vx, vz = nvx, nvz
        X[kn], Z[kn] = x, z
    return X, Z


def simulate(v0: float, theta: float, T: float, vt: float, steps: int = 240) -> tuple[float, float]:
    """Displacement (dx, dz) after T seconds of one flight: RK4 on the full model. Used to verify a solution."""
    k = G / (vt * vt)
    vx, vz, x, z = v0 * math.cos(theta), v0 * math.sin(theta), 0.0, 0.0
    h = T / steps

    def acc(ax, az):
        s = math.hypot(ax, az)
        return -k * s * ax, -G - k * s * az

    for _ in range(steps):
        a1x, a1z = acc(vx, vz)
        a2x, a2z = acc(vx + 0.5 * h * a1x, vz + 0.5 * h * a1z)
        a3x, a3z = acc(vx + 0.5 * h * a2x, vz + 0.5 * h * a2z)
        a4x, a4z = acc(vx + h * a3x, vz + h * a3z)
        nvx = vx + h * (a1x + 2 * a2x + 2 * a3x + a4x) / 6.0
        nvz = vz + h * (a1z + 2 * a2z + 2 * a3z + a4z) / 6.0
        x += h * 0.5 * (vx + nvx)
        z += h * 0.5 * (vz + nvz)
        vx, vz = nvx, nvz
    return x, z


def solve_launch(d: float, T: float, dz: float, vt: float, tol_m: float = 0.15) -> tuple[float, float] | None:
    """(launch speed m/s, launch angle rad) of the flight that covers horizontal distance d and height change dz in time T,
    or None when no launch within the table (2-170 m/s) does. When several launches fit, the slowest one."""
    if not (0.05 <= T <= T_MAX - KNOT and d > 0.0):
        return None
    X, Z = _table(round(vt, 3))
    f = T / KNOT
    i = int(f)
    w = f - i
    fx = (1 - w) * X[i] + w * X[i + 1]
    fz = (1 - w) * Z[i] + w * Z[i + 1]
    res = np.hypot(fx - d, fz - dz)
    best = float(res.min())
    if best > 1.0:                                      # nothing on the grid is within a metre: not a flight this shuttle can fly
        return None
    near = np.argwhere(res <= best + 0.15)
    iv, it = min(map(tuple, near), key=lambda ij: ij[0])      # the slowest of the cells that fit
    iv = min(max(iv, 1), len(V_GRID) - 2)
    it = min(max(it, 1), len(TH_GRID) - 2)
    # one Newton step on the table's own local slope
    dxdv = (fx[iv + 1, it] - fx[iv - 1, it]) / (V_GRID[iv + 1] - V_GRID[iv - 1])
    dzdv = (fz[iv + 1, it] - fz[iv - 1, it]) / (V_GRID[iv + 1] - V_GRID[iv - 1])
    dxdt = (fx[iv, it + 1] - fx[iv, it - 1]) / (TH_GRID[it + 1] - TH_GRID[it - 1])
    dzdt = (fz[iv, it + 1] - fz[iv, it - 1]) / (TH_GRID[it + 1] - TH_GRID[it - 1])
    det = dxdv * dzdt - dxdt * dzdv
    v, th = float(V_GRID[iv]), float(TH_GRID[it])
    if abs(det) > 1e-9:
        rx, rz = d - float(fx[iv, it]), dz - float(fz[iv, it])
        v += (rx * dzdt - rz * dxdt) / det
        th += (dxdv * rz - dzdv * rx) / det
    if not (V_GRID[0] <= v <= V_GRID[-1]):
        return None
    sx, sz = simulate(v, th, T, vt)                     # verify the one trajectory on the full model
    if math.hypot(sx - d, sz - dz) > tol_m:
        return None
    return v, th


def min_flight_time(d: float, vt: float, v_max: float) -> float:
    """The shortest time any launch up to v_max can take to cover d metres (a flat launch: v(x) = v0 exp(-k x))."""
    k = G / (vt * vt)
    return (math.exp(k * d) - 1.0) / (k * v_max)


def trajectory(v0: float, theta: float, T: float, vt: float, dt: float = 1.0 / 60.0) -> list[tuple[float, float, float]]:
    """(t, dx, dz) every `dt` seconds along one flight with the full model (RK4), ending exactly at T. For drawing a flight."""
    k = G / (vt * vt)
    vx, vz, x, z, t = v0 * math.cos(theta), v0 * math.sin(theta), 0.0, 0.0, 0.0
    out = [(0.0, 0.0, 0.0)]

    def acc(ax, az):
        s = math.hypot(ax, az)
        return -k * s * ax, -G - k * s * az

    n = max(1, int(round(T / dt)))
    h = T / n
    for i in range(1, n + 1):
        sub = 4                                            # a few RK4 steps per output step: a fast shot changes a lot in 1/60 s
        hh = h / sub
        for _ in range(sub):
            a1x, a1z = acc(vx, vz)
            a2x, a2z = acc(vx + 0.5 * hh * a1x, vz + 0.5 * hh * a1z)
            a3x, a3z = acc(vx + 0.5 * hh * a2x, vz + 0.5 * hh * a2z)
            a4x, a4z = acc(vx + hh * a3x, vz + hh * a3z)
            nvx = vx + hh * (a1x + 2 * a2x + 2 * a3x + a4x) / 6.0
            nvz = vz + hh * (a1z + 2 * a2z + 2 * a3z + a4z) / 6.0
            x += hh * 0.5 * (vx + nvx)
            z += hh * 0.5 * (vz + nvz)
            vx, vz = nvx, nvz
        out.append((round(i * h, 4), x, z))
    return out
