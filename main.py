"""Aparejo (was Energia por Jogo): CPU/GPU frequency caps remembered per game.

Armada's power profiles (Armada Control > Power) are global. While a game that has its own entry here runs, its
caps are written over the profile's (scaling_max_freq per CPU policy, GPU devfreq max/min; group wheel can write
them). When the game exits, armada-powerd reloads and puts the active profile back.

Per game, `mode` picks what is automatic: "off" (fixed caps), "gpu" (GpuAuto), "cpu" (FpsAuto) or "both". The CPU
needs an FPS target (`fps_target`); the GPU uses one when set, to check that each step down keeps the frames.
"""
import asyncio
import collections
import json
import os
import re
import select
import struct
import subprocess
import threading
import time

import decky

CPUFREQ = "/sys/devices/system/cpu/cpufreq"
DEVFREQ = "/sys/class/devfreq"
TICK_S = 2.0
MISSING_TICKS = 3
MODES = ("off", "gpu", "cpu", "both")
SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "games.json")
_RX_APPID = re.compile(rb"AppId=(\d+)")
_RX_POLICY = re.compile(r"^policy(\d+)$")
_RX_ENGINE = re.compile(r"drm-engine-gpu:\s*(\d+)")
_RX_CLIENT = re.compile(r"drm-client-id:\s*(\d+)")


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def write(path, value):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(value))
        return True
    except OSError as exc:
        decky.logger.warning(f"write {path}={value}: {exc}")
        return False


def ints(text):
    out = []
    for item in text.split():
        try:
            out.append(int(item))
        except ValueError:
            pass
    return sorted(set(out))


def at_most(freqs, target):
    below = [f for f in freqs if f <= target]
    return below[-1] if below else freqs[0]


def nearest_index(freqs, value):
    best = 0
    for i, f in enumerate(freqs):
        if f <= value:
            best = i
    return best


def percentile(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * q))]


def cpu_policies():
    out = []
    try:
        names = os.listdir(CPUFREQ)
    except OSError:
        return out
    for name in names:
        m = _RX_POLICY.match(name)
        if not m:
            continue
        path = os.path.join(CPUFREQ, name)
        freqs = ints(read(os.path.join(path, "scaling_available_frequencies")))
        if not freqs:
            low, high = read(os.path.join(path, "cpuinfo_min_freq")), read(os.path.join(path, "cpuinfo_max_freq"))
            freqs = ints(f"{low} {high}")
        if not freqs:
            continue
        out.append({
            "id": int(m.group(1)),
            "path": path,
            "cpus": read(os.path.join(path, "related_cpus")),
            "freqs": freqs,
            "max": int(read(os.path.join(path, "scaling_max_freq"), "0") or 0),
        })
    out.sort(key=lambda p: p["id"])
    return out


def gpu_device():
    try:
        names = sorted(os.listdir(DEVFREQ))
    except OSError:
        return None
    for name in names:
        if "gpu" not in name and "kgsl" not in name:
            continue
        path = os.path.join(DEVFREQ, name)
        freqs = ints(read(os.path.join(path, "available_frequencies")))
        if freqs:
            return {
                "path": path,
                "freqs": freqs,
                "max": int(read(os.path.join(path, "max_freq"), "0") or 0),
                "min": int(read(os.path.join(path, "min_freq"), "0") or 0),
                "governor": read(os.path.join(path, "governor")),
            }
    return None


CPU_CHANGED = [0.0]  # monotonic time FpsAuto last wrote a CPU cap


def game_mode(cfg):
    """What is automatic for this game. Profiles saved before 0.1.7 have no `mode`: an FPS target meant CPU and
    GPU, `gpu_auto` meant the GPU."""
    if not isinstance(cfg, dict):
        return "off"
    mode = cfg.get("mode")
    if mode in MODES:
        return mode
    if fps_target(cfg):
        return "both"
    return "gpu" if cfg.get("gpu_auto") else "off"


def fps_target(cfg):
    value = cfg.get("fps_target") if isinstance(cfg, dict) else None
    return value if isinstance(value, int) and value > 0 else None


class ProcScan:
    """{appid: [reaper pids]}. Steam's reaper keeps "SteamLaunch AppId=<id>" in its command line for the game's
    whole life. A process that is not a reaper is read on two ticks (a fork can still exec into one) and then
    skipped until it exits, so a tick reads a handful of cmdlines instead of every process."""
    CHECKS = 2

    def __init__(self):
        self.others = {}

    def games(self):
        out = {}
        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return out
        others = {}
        for pid in pids:
            seen = self.others.get(pid, 0)
            if seen >= self.CHECKS:
                others[pid] = seen
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read(4096)
            except OSError:
                continue
            ids = [m for m in _RX_APPID.findall(cmd) if m != b"0"] if b"SteamLaunch" in cmd else []
            if ids:
                for m in ids:
                    out.setdefault(m.decode(), []).append(int(pid))
            else:
                others[pid] = seen + 1
        self.others = others
        return out


def descendants(pid):
    seen, stack = [], [pid]
    while stack:
        current = stack.pop()
        try:
            tids = os.listdir(f"/proc/{current}/task")
        except OSError:
            continue
        for tid in tids:
            try:
                with open(f"/proc/{current}/task/{tid}/children", encoding="utf-8") as f:
                    children = [int(c) for c in f.read().split()]
            except (OSError, ValueError):
                continue
            for child in children:
                if child not in seen:
                    seen.append(child)
                    stack.append(child)
    return seen


def drm_fds(pid):
    """[fd] of one process that are GPU clients (DRM fdinfo, readable for our own uid)."""
    out = []
    try:
        fds = os.listdir(f"/proc/{pid}/fdinfo")
    except OSError:
        return out
    for fd in fds:
        try:
            with open(f"/proc/{pid}/fdinfo/{fd}", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if _RX_ENGINE.search(text) and _RX_CLIENT.search(text):
            out.append(fd)
    return out


def gpu_clients(pid, fds):
    """{drm client id: busy ns} read from only the given fds."""
    out = {}
    for fd in fds:
        try:
            with open(f"/proc/{pid}/fdinfo/{fd}", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        m = _RX_ENGINE.search(text)
        c = _RX_CLIENT.search(text)
        if m and c:
            out[c.group(1)] = int(m.group(1))
    return out


def frame_stats(frames):
    """(fps, 97th percentile frame time ms)"""
    if not frames:
        return 0.0, 0.0
    return 1000.0 * len(frames) / sum(frames), percentile(frames, 0.97)


class FrameRef:
    """The game's frame pacing at full clocks, to judge every step down against. Measured on the first BASE_S of
    frames after start (CPU at its ceilings, GPU at its top), or taken from what an earlier session learned.

    `goal()` is the FPS the steps must keep: the target, or what the game does at full clocks when that is less
    (8 of the 20 games saved on 2026-11-18 had p97 54-120 ms at 30 FPS targets: they do not hold 30, and 0.1.6
    then never lowered anything). The game's own FPS is taken from the median frame, so a loading hitch during the
    measure does not lower the goal."""
    BASE_S = 10.0
    MIN_GOAL = 0.6  # never aim lower than this share of the target

    def __init__(self, probe, target, base_p97=None, base_fps=None):
        self.probe = probe
        self.target = target
        self.base = base_p97
        self.base_fps = base_fps
        self.t0 = time.monotonic()
        # Under gamescope's own frame limiter the app frame times it reports have lone spikes the screen does not
        # show (Yakuza 2026-11-18: no stutter seen, yet 3+ "slow frames" every few seconds pushed CPU and GPU to
        # their tops). Slow frames are only counted when that limiter is not the one holding the game.
        self.hitches = True

    def update(self):
        if self.base is not None:
            return
        now = time.monotonic()
        if now - self.t0 < self.BASE_S:
            return
        frames = self.probe.window(self.BASE_S - 2)
        if len(frames) < max(self.target * 4 * self.MIN_GOAL, 8):
            self.t0 = now  # no frames (paused, loading): try again
            return
        self.base = frame_stats(frames)[1]
        self.base_fps = min(float(self.target), 1000.0 / percentile(frames, 0.5))

    def goal(self):
        if self.base_fps and self.base_fps < self.target * 0.95:
            return max(self.base_fps, self.target * self.MIN_GOAL)
        return float(self.target)

    def limit(self):
        return self.base * 1.10 + 1

    def enough(self, frames, seconds):
        return len(frames) >= self.goal() * seconds * 0.5

    def stats(self, seconds):
        """(fps, p97, slow frames) of the last `seconds`, None without enough frames (loading, paused). A slow
        frame takes over 1.5x the goal's frame time: one hitch moves no percentile of a few seconds, but the
        player sees it (TLOU 2026-11-18: GPU at 607-734 MHz passed every p97 check with 160 ms hitches)."""
        frames = self.probe.window(seconds)
        if not self.enough(frames, seconds):
            return None
        return frame_stats(frames) + (self.slow(frames),)

    def slow(self, frames):
        if not self.hitches:
            return 0
        slow_ms = 1500.0 / self.goal()
        return sum(1 for ms in frames if ms > slow_ms)

    def ok(self, seconds, fps_frac=0.97):
        """True/False when the last `seconds` hold the goal and the pacing, None without enough frames."""
        s = self.stats(seconds)
        if self.base is None or s is None:
            return None
        return s[0] >= self.goal() * fps_frac and s[1] <= self.limit() and s[2] == 0

    def fps(self, seconds):
        s = self.stats(seconds)
        return None if s is None else s[0]


class GpuAuto:
    """Locks the GPU (min = max) at the lowest clock where its busiest 100 ms of the last HOLD_S stays under TARGET.

    Measured 2026-11-12: Yakuza Like a Dragon -1.2 W at 85 % average busy, same frame times. In TLOU the first
    version (cap only max, 3-sample average, a step down every 0.5 s) moved the clock ~2.5x/s and the governor
    still moved it under the cap; p99 frame time 40 -> 47-49 ms. A fixed 734 MHz there gave 46 ms, so most of
    that is the lower clock itself (TLOU runs CPU then GPU in series), and the rest the switching. Hence: lock
    (no governor jumps under us), decide on the peak not the average, go up at once, go down one step only after
    DOWN_S below.

    With an FPS target (`ref`), busy % alone is not trusted: games that run CPU -> GPU in series, or Vela's
    GPU -> NPU -> GPU chain (Sifu, 2026-11-12), miss frames at a lower clock even at 55-70 % busy. Every step down
    is then checked on the frames CHECK_S later and undone when they got worse; that clock becomes a floor for a
    while (longer each time it fails). `control=False` only measures (busy, work) for the CPU controller."""
    TARGET = 0.85
    GUARD = 0.95
    HOLD_S = 2.0
    DOWN_S = 3.0
    CHECK_S = 4.0
    FLOOR_S = 180.0
    FLOOR_MAX_S = 1200.0
    HITCHES = 3  # slow frames at one clock before its rate is judged
    HITCH_FRAMES = 300  # and frames seen at it (10 s at 30 FPS): Yakuza 2026-11-18 got a floor on 3 slow of 182
    CPU_QUIET_S = 6.0  # a CPU cap change this recent and the frames are not the GPU's to answer for
    JUMP_S = 0.5
    GUARD_WIN_S = 0.35
    EXT_S = 1.5
    HITCH_X = 3.0
    PERIOD_S = 0.1
    RULE = os.environ.get("EPJ_GPU_RULE", "avg")  # "peak": 0.1.6's rule also with an FPS target (bench A/B)

    def __init__(self, gpu_path, freqs, reapers, control=True):
        self.path = gpu_path
        self.freqs = freqs
        self.reapers = reapers
        self.control = control
        self.fds = {}
        self.clients = {}
        self.last_t = None
        self.hist = []
        self.idx = None
        self.low_since = None
        self.written = None
        self.ext_floor = 0
        self.fps_floor = 0  # raised by FpsAuto when the FPS needs a faster GPU than busy % asks for
        self.top = None
        self.busy = 0.0
        self.ref = None  # FrameRef: steps down are checked on the frames
        # FpsAuto is searching the CPU: the GPU may not go below this index meanwhile (it may go up, and back down
        # to it: in Sifu, 2026-11-18, a hitch sent it to 1050 MHz and a full freeze kept it there for the 2 min search)
        self.freeze_idx = None
        self.ext_seen = None  # (min_freq value, since): a raised min_freq not written by us
        self.rates = {}  # GPU index -> [frames, slow frames] seen while it held that clock
        self.rate_idx = None
        self.rate_held = False
        self.rate_t = 0.0
        self.jump_t = 0.0
        self.check = None  # (time, index before) of the last step down, until it is judged
        self.guard_idx = -1
        self.guard_until = 0.0
        self.guard_s = self.FLOOR_S
        self.changed = time.monotonic()
        self.works = collections.deque()  # (time, busy x MHz): how much GPU work the scene asks for
        self.buckets = []  # 10 s averages of that over the session
        self.bucket = []
        self.started = time.monotonic()
        self.refreshed = 0.0
        self.refresh_pids()

    @property
    def pids(self):
        return sorted(self.fds)

    def refresh_pids(self, force=True):
        # Game processes and their GPU fds rarely change after start: every tick early on, then every 10 s.
        now = time.monotonic()
        if not force and now - self.refreshed < (2 if now - self.started < 30 else 10):
            return
        self.refreshed = now
        fds = {}
        for reaper in self.reapers:
            for pid in descendants(reaper):
                found = drm_fds(pid)
                if found:
                    fds[pid] = found
        self.fds = fds

    def sample(self):
        clients = {}
        for pid, fds in self.fds.items():
            clients.update(gpu_clients(pid, fds))
        now = time.monotonic()
        busy = None
        if self.last_t is not None and now > self.last_t:
            spent = sum(ns - self.clients.get(cid, ns) for cid, ns in clients.items())
            busy = min(max(spent / ((now - self.last_t) * 1e9), 0.0), 1.0)
        self.clients, self.last_t = clients, now
        return busy, now

    def work(self, seconds):
        """Average GPU work (busy x MHz) of the last `seconds`, None before there is any."""
        now = time.monotonic()
        vals = [w for t, w in self.works if now - t <= seconds]
        return sum(vals) / len(vals) if vals else None

    def typical_work(self):
        """The work of a normal moment of this session (80th percentile of its 10 s averages)."""
        return percentile(self.buckets, 0.8) if len(self.buckets) >= 3 else None

    def lock(self, hz):
        cur_max = int(read(os.path.join(self.path, "max_freq"), "0") or 0)
        order = ("max_freq", "min_freq") if hz > cur_max else ("min_freq", "max_freq")
        for name in order:
            write(os.path.join(self.path, name), hz)
        self.written = hz
        self.changed = time.monotonic()

    def stable_for(self):
        return time.monotonic() - self.changed

    def hitch_floor(self, now):
        """Hitches counted per GPU clock while it holds still. The 4 s check after a step only sees a hitch that
        comes at once; Sifu (Vela, 2026-11-18) held 452 MHz with 6 slow frames a minute against 2 at 627. When the
        current clock hitches HITCH_X times more often than the clocks above it did, the next clock up becomes a
        floor for a while (-1 when nothing changes)."""
        # the frames of the last second belong to the clock held when it began: a hitch itself sends the clock up
        # (busy 100 %), so judging by the clock at the end of the second never counted one
        idx, held = self.rate_idx, self.rate_held
        self.rate_t, self.rate_idx = now, self.idx
        self.rate_held = self.idx == idx and now - self.changed >= 1.0
        frames = self.ref.probe.window(1.0)
        if idx is None or not held or len(frames) < self.ref.goal() * 0.5:
            return -1
        if now - CPU_CHANGED[0] < self.CPU_QUIET_S:
            return -1  # the CPU just moved (FpsAuto searching): its hitches are not this clock's
        st = self.rates.setdefault(idx, [0, 0])
        st[0] += len(frames)
        st[1] += self.ref.slow(frames)
        above = [self.rates[i] for i in self.rates if i > idx]
        n_up, slow_up = sum(s[0] for s in above), sum(s[1] for s in above)
        if st[1] < self.HITCHES or st[0] < self.HITCH_FRAMES or n_up < 600:
            return -1
        if st[1] / st[0] <= self.HITCH_X * (slow_up + 1) / (n_up + 300):
            return -1
        floor = idx + 1
        self.rates[idx] = [0, 0]
        self.guard_idx, self.guard_until = floor, now + self.guard_s
        self.guard_s = min(self.guard_s * 2, self.FLOOR_MAX_S)
        decky.logger.info(f"gpu auto: {self.freqs[idx] // 1000000} MHz hitches {st[1]}/{st[0]} frames vs "
                          f"{slow_up}/{n_up} above, floor {self.freqs[floor] // 1000000} MHz")
        return floor

    def worse(self, was):
        """Did the frames get worse than `was` ((fps, p97) before the step, or None)?"""
        now = self.ref.stats(self.CHECK_S)
        if now is None:
            return False  # loading, paused: nothing to judge
        if was is None:
            return self.ref.ok(self.CHECK_S) is False
        fps_floor = min(was[0], self.ref.goal()) * 0.97
        p97_limit = max(self.ref.limit(), was[1] * 1.10 + 1)
        if now[0] < fps_floor or now[1] > p97_limit:
            return True
        return "hitch" if now[2] > was[2] else False

    def step(self, ceiling_hz, floor_hz):
        if not self.fds:
            return  # the game's GPU processes are not found yet: busy would read 0 and drive the clock down
        busy, now = self.sample()
        if busy is None:
            return
        self.busy = busy
        cur = int(read(os.path.join(self.path, "cur_freq"), "0") or 0)
        self.works.append((now, busy * (cur or 0) / 1e6))
        while self.works and now - self.works[0][0] > 120:
            self.works.popleft()
        self.bucket.append(busy * (cur or 0) / 1e6)
        if now - self.started >= 10 * (len(self.buckets) + 1):
            if self.bucket:
                self.buckets.append(sum(self.bucket) / len(self.bucket))
                self.buckets = self.buckets[-360:]
            self.bucket = []
        self.hist = [(t, b) for t, b in self.hist if now - t <= self.HOLD_S] + [(now, busy)]
        if not self.control:
            return
        peak = max(b for _, b in self.hist)
        if self.ref is not None and self.RULE == "avg":
            # with the frames checking every step down, the average busy can lead: the peak of noisy 100 ms samples
            # kept Yakuza at ~1050 MHz where the average asked for ~830 (2026-11-13: -1.5 W instead of -2.2 W)
            peak = sum(b for _, b in self.hist) / len(self.hist)
        top = max(nearest_index(self.freqs, ceiling_hz), 0)
        self.top = top
        guard = self.guard_idx if now < self.guard_until else -1
        bottom = min(max(nearest_index(self.freqs, max(floor_hz or 0, self.ext_floor, self.fps_floor)), guard), top)
        if self.idx is None:
            self.idx = top
            self.lock(self.freqs[self.idx])
            return
        if self.check is not None and now - self.check[0] >= self.CHECK_S:
            _, before, was, again = self.check
            self.check = None
            verdict = self.worse(was) if self.ref is not None and before > self.idx else False
            if verdict and now - CPU_CHANGED[0] < self.CHECK_S + 2:
                verdict = False  # the CPU caps changed during the check: no telling which one lost the frames
            if verdict == "hitch" and not again:
                # one more slow frame than before the step: a lone hitch also happens at full clocks (Sifu 2026-11-18
                # pinned 1050 MHz for 9 min on one); judge another CHECK_S, with the same "before"
                self.check, verdict = (now, before, was, True), False
            if verdict:
                # the frames got worse after this step: undo it, and keep that clock as a floor for a while
                self.guard_idx, self.guard_until = before, now + self.guard_s
                self.guard_s = min(self.guard_s * 2, self.FLOOR_MAX_S)
                bottom = min(max(bottom, before), top)
                decky.logger.info(f"gpu auto: {self.freqs[self.idx] // 1000000} MHz lost frames, back to "
                                  f"{self.freqs[before] // 1000000} MHz for {self.guard_s / 2:.0f} s")
        if self.ref is not None and self.ref.base is not None and now - self.rate_t >= 1.0:
            bottom = min(max(bottom, self.hitch_floor(now)), top)
        # the clock we locked, not cur_freq: the msm driver boosts the GPU on a missed fence deadline (a hitch), and
        # cur_freq then reads up to 1100 MHz for a moment; need = 1100 x busy jumped the lock to the top (Sifu,
        # 2026-11-18: 342 -> 1100 MHz on each hitch, then 40 s to come back down)
        need = (self.written or cur or self.freqs[self.idx]) * peak / self.TARGET
        want = next((i for i, f in enumerate(self.freqs) if f >= need), len(self.freqs) - 1)
        recent = [b for t, b in self.hist if now - t <= self.GUARD_WIN_S]
        if sum(recent) / len(recent) > self.GUARD and now - self.jump_t >= self.JUMP_S:
            # +2 at most every JUMP_S: during a hitch every 100 ms sample reads 100 % and +2 each one took Sifu
            # from 342 to 1050 MHz in half a second. And on GUARD_WIN_S, not one sample: one noisy 100 ms over 95 %
            # moved Yakuza 832 -> 967 -> 900 -> 832 MHz every ~8 s (2026-11-18)
            want = max(want, self.idx + 2)
            self.jump_t = now
        want = max(min(want, top), bottom)
        if want > self.idx:
            self.low_since = None
            self.check = None
        elif want < self.idx:
            if self.low_since is None:
                self.low_since = now
            blocked = (self.freeze_idx is not None and self.idx - 1 < self.freeze_idx) or self.check is not None or (self.ref is not None and self.ref.base is None)
            if now - self.low_since < self.DOWN_S or blocked:
                want = self.idx
            else:
                want, self.low_since = self.idx - 1, now
                if self.ref is not None:
                    self.check = (now, self.idx, self.ref.stats(self.CHECK_S), False)
        else:
            self.low_since = None
        cur_max = int(read(os.path.join(self.path, "max_freq"), "0") or 0)
        cur_min = int(read(os.path.join(self.path, "min_freq"), "0") or 0)
        if cur_min != self.written and cur_min > self.freqs[want]:
            # someone else raised the floor (Vela's GPU floor): follow it instead of fighting it. min_freq also
            # reads the driver's fence-deadline boost for a moment, so only a value that stays EXT_S counts.
            if self.ext_seen is None or self.ext_seen[0] != cur_min:
                self.ext_seen = (cur_min, now)
            elif now - self.ext_seen[1] >= self.EXT_S:
                self.ext_floor = cur_min
                want = nearest_index(self.freqs, cur_min)
                self.low_since = None
                self.check = None
        else:
            self.ext_seen = None
        if want != self.idx or cur_max != self.freqs[want] or (cur_min != self.freqs[want] and self.ext_seen is None):
            if want >= self.idx + 3:
                decky.logger.info(f"gpu auto: jump {self.idx}->{want} busy {busy:.2f} level {peak:.2f} cur {cur} "
                                  f"min {cur_min} max {cur_max} written {self.written} bottom {bottom}")
            self.idx = want
            self.lock(self.freqs[want])


class FrameProbe:
    """App frame times from gamescope's messages to mangoapp, without taking them off the queue (the Steam
    overlay keeps working). Needs root. kprobes/eprobes on msgsnd are refused on Armada's kernel; the syscall
    tracepoint works. gamescope sends one message per display refresh (60/s) from two threads, and only one
    thread's buffer still holds the message when we read it, so the app frame time (u64 at msgp+16) is read from
    gamescope's memory right after each event, invalid reads are dropped and repeats are deduplicated."""
    TRACING = "/sys/kernel/tracing"
    INST = TRACING + "/instances/energia-por-jogo"
    EVENT = "syscalls/sys_enter_msgsnd"
    _RX = re.compile(r"-(\d+)\s+\[\d+\].*msgp: (0x[0-9a-f]+)")

    def __init__(self):
        self.lock = threading.Lock()
        self.frames = collections.deque()
        self.stop = False
        self.fd = None
        self.mems = {}
        self.close_event()
        os.mkdir(self.INST)
        try:
            self._w("buffer_percent", "0")  # wake on every event: read the message before gamescope reuses it
        except OSError:
            pass
        self._w(f"events/{self.EVENT}/filter", 'comm ~ "gamescope*"')
        self._w(f"events/{self.EVENT}/enable", "1")
        self.fd = os.open(self.INST + "/trace_pipe", os.O_RDONLY | os.O_NONBLOCK)
        threading.Thread(target=self.run, name="epj-frames", daemon=True).start()

    def _w(self, name, value):
        with open(os.path.join(self.INST, name), "w", encoding="utf-8") as f:
            f.write(value)

    def close_event(self):
        try:
            self._w(f"events/{self.EVENT}/enable", "0")
        except OSError:
            pass
        try:
            os.rmdir(self.INST)
        except OSError:
            pass

    def run(self):
        buf = b""
        fd = self.fd
        while not self.stop:
            try:
                ready, _, _ = select.select([fd], [], [], 0.5)
                if not ready:
                    continue
                buf += os.read(fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                break
            *lines, buf = buf.split(b"\n")
            for line in lines:
                m = self._RX.search(line.decode(errors="replace"))
                if not m:
                    continue
                tid = m.group(1)
                try:
                    f = self.mems.get(tid)
                    if f is None:
                        f = self.mems[tid] = open(f"/proc/{tid}/mem", "rb", buffering=0)
                    f.seek(int(m.group(2), 16) + 16)
                    ns = struct.unpack("<Q", f.read(8))[0]
                except (OSError, ValueError, struct.error):
                    old = self.mems.pop(tid, None)
                    if old:
                        old.close()
                    continue
                if 1000000 < ns < 1000000000:
                    with self.lock:
                        self.frames.append((time.monotonic(), ns / 1e6))
        for f in self.mems.values():
            f.close()

    def window(self, seconds):
        """Frame times (ms) of the last `seconds`, one per app frame."""
        now = time.monotonic()
        out, last = [], None
        with self.lock:
            while self.frames and now - self.frames[0][0] > 30:
                self.frames.popleft()
            for t, ms in self.frames:
                if now - t <= seconds and ms != last:
                    out.append(ms)
                last = ms
        return out

    def close(self):
        self.stop = True
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        self.close_event()


class FpsAuto:
    """FPS target for the CPU. Lowers the small cores, then the big ones (the game's main thread runs there), one
    step at a time while the FPS holds; a step that loses FPS while the GPU is not saturated is undone and becomes
    that cluster's floor. The floors found are saved per game and the next session starts from them.

    Order with GpuAuto: the GPU settles first (by busy %, each step checked on the frames), then the CPU search
    runs with the GPU kept from going below where it settled (so a lost frame is blamed on the right one), then
    both hold. A step judged bad only for one hitch (a slow frame, fps and p97 fine) is judged once more.

    Holding, the FPS is checked every second on the last HOLD_WIN_S: a slip raises a CPU step at once (0.1.6 waited
    for two failed 11 s windows, ~22 s of a slow game); a big drop (menu -> heavy scene) goes to the ceilings and,
    after a few seconds, searches again from two steps above the old floors instead of from the ceilings.

    Measured 2026-11-13, Yakuza Like a Dragon at 30 FPS, ceilings 2227/2246 MHz: found 960/1689 in ~2 min, last
    60 s 29.9 FPS, p97 37 -> 40 ms, ~12.6 -> ~9.4 W, 76-80 -> 67-72 C.

    Learned floors are only saved from a search run in a scene as heavy as the game usually is (GPU work at least
    MIN_WORK of the session's typical one) and, when an earlier session learned floors, at most one step below
    them per session: a retry in a pause menu (Lies of P, 2026-11-15) once saved 384/1017 MHz."""
    SETTLE_S = 3.0
    EVAL_S = 8.0
    GPU_FULL = 0.92
    GPU_WAIT_S = 8.0  # the GPU unchanged this long counts as settled
    GPU_WAIT_MAX_S = 60.0
    HOLD_WIN_S = 4.0
    SLIP = 0.94
    DROP = 0.85
    RAISE_GAP_S = 4.0
    RECOVER_S = 6.0
    MIN_WORK = 0.7
    RETRY_S = 300.0  # each retry costs a short dip when it finds nothing: rarely, and rarer each time
    RETRY_MAX_S = 1800.0
    RELAX_S = 90.0
    RETRY_FAIL_S = 120.0
    HITCH_WIN_S = 10.0
    HITCHES = 3  # slow frames in HITCH_WIN_S that count as a slip even when the average FPS holds

    def __init__(self, target, policies, ceilings, learned, on_learned, ref):
        self.target = target
        self.ref = ref
        self.ok_since = None
        self.retry_s = self.RETRY_S
        self.retry_from = None
        self.gpu_floor = 0
        self.pols = {p["id"]: p for p in policies}
        self.order = sorted(self.pols)  # small cores first, big ones last
        self.ceil = {pid: at_most(self.pols[pid]["freqs"], ceilings.get(pid, self.pols[pid]["freqs"][-1]))
                     for pid in self.pols}
        self.on_learned = on_learned
        self.cur = 0
        self.pending = None
        self.fps = 0.0
        self.raise_at = 0.0
        self.hold_t = time.monotonic()
        self.from_retry = False
        self.rejudged = False
        self.min_work = None  # lowest work ratio seen while judging the steps of this search
        self.t_state = time.monotonic()
        cpu = (learned or {}).get("cpu") or {}
        self.learned_idx = None
        if learned and learned.get("p97") and all(str(pid) in cpu for pid in self.pols):
            self.learned_idx = {pid: self.pols[pid]["freqs"].index(at_most(self.pols[pid]["freqs"],
                                                                            min(int(cpu[str(pid)]), self.ceil[pid])))
                                for pid in self.pols}
            self.idx = dict(self.learned_idx)
            self.state = "hold"
        else:
            self.idx = {pid: self.pols[pid]["freqs"].index(self.ceil[pid]) for pid in self.pols}
            self.state = "base"
        self.last_floor = dict(self.idx)
        self.write_all()

    def khz(self, pid):
        return self.pols[pid]["freqs"][self.idx[pid]]

    def write_all(self):
        CPU_CHANGED[0] = time.monotonic()
        for pid in self.pols:
            write(os.path.join(self.pols[pid]["path"], "scaling_max_freq"), self.khz(pid))

    def set(self, pid, i):
        CPU_CHANGED[0] = time.monotonic()
        self.idx[pid] = i
        write(os.path.join(self.pols[pid]["path"], "scaling_max_freq"), self.khz(pid))

    def caps(self):
        return {str(pid): self.khz(pid) for pid in self.pols}

    def learned_entry(self, cpu):
        entry = {"cpu": cpu, "p97": round(self.ref.base, 2)}
        if self.ref.base_fps:
            entry["fps"] = round(self.ref.base_fps, 1)
        return entry

    def to_ceilings(self):
        for pid in self.pols:
            self.idx[pid] = self.pols[pid]["freqs"].index(self.ceil[pid])
        self.write_all()

    def work_ratio(self, gpu_auto, seconds):
        if gpu_auto is None:
            return None
        typical, now = gpu_auto.typical_work(), gpu_auto.work(seconds)
        if not typical or now is None:
            return None
        return now / typical

    def learn(self, gpu_auto):
        found = {pid: self.idx[pid] for pid in self.pols}
        if self.min_work is not None and self.min_work < self.MIN_WORK:
            decky.logger.info(f"fps auto: floors {self.caps()} found in a light scene (work {self.min_work:.2f}), "
                              f"not saved")
            return
        if self.learned_idx is not None:
            # one step a session at most below what earlier sessions learned
            for pid in self.pols:
                if found[pid] < self.learned_idx[pid] - 1:
                    found[pid] = self.learned_idx[pid] - 1
        self.learned_idx = found
        out = {str(pid): self.pols[pid]["freqs"][found[pid]] for pid in self.pols}
        decky.logger.info(f"fps auto: floors {self.caps()} at {self.target} FPS, saved {out}")
        self.on_learned(self.learned_entry(out))

    def start_search(self, gpu_auto, from_idx=None):
        if from_idx is not None:
            for pid in self.pols:
                self.idx[pid] = from_idx[pid]
            self.write_all()
        self.state, self.cur, self.pending, self.min_work = "down", 0, None, None
        self.t_state = time.monotonic()
        if gpu_auto is not None:
            gpu_auto.freeze_idx = gpu_auto.idx if gpu_auto.idx is not None else 0

    def step(self, probe, gpu_auto):
        now = time.monotonic()
        self.fps = frame_stats(probe.window(1.0))[0]
        el = now - self.t_state
        if gpu_auto is not None:
            gpu_auto.fps_floor = self.gpu_floor
        gpu_up = (gpu_auto is not None and gpu_auto.control and gpu_auto.idx is not None
                  and gpu_auto.top is not None and gpu_auto.idx < gpu_auto.top)
        # "the GPU is short" only counts while it can still go up: at its ceiling (TLOU's 607 MHz, 2026-11-13) the
        # CPU is the only lever left, and waiting for the GPU left the game at 28.7-29 FPS
        gpu_full = gpu_up and bool(gpu_auto.hist) and max(b for _, b in gpu_auto.hist) >= self.GPU_FULL
        if self.state == "base":
            if self.ref.base is not None:
                self.state, self.t_state = "gpu", now
            return
        if self.state == "gpu":
            # let the GPU find its clock first (it moves every few seconds; a CPU step judged meanwhile would be
            # judged on a moving GPU)
            controlling = gpu_auto is not None and gpu_auto.control
            if not controlling or gpu_auto.stable_for() >= self.GPU_WAIT_S or el >= self.GPU_WAIT_MAX_S:
                self.start_search(gpu_auto)
            return
        if self.state == "recover":
            if el >= self.RECOVER_S:
                start = {pid: min(self.pols[pid]["freqs"].index(self.ceil[pid]), self.last_floor[pid] + 2)
                         for pid in self.pols}
                self.start_search(gpu_auto, start)
            return
        if self.state == "down":
            self.down(now, el, probe, gpu_auto, gpu_full)
            return
        self.hold(now, gpu_auto, gpu_up, gpu_full)

    def down(self, now, el, probe, gpu_auto, gpu_full):
        quick_fail = False
        if self.pending is not None and self.SETTLE_S + 2 <= el < self.SETTLE_S + self.EVAL_S:
            # a step that clearly fails is undone after 2 s, not after the full window: in TLOU (2026-11-13) a retry
            # at 748 MHz dropped to 22 FPS for the whole 8 s, which the player sees
            quick = probe.window(2.0)
            if len(quick) >= self.target * 0.5 and frame_stats(quick)[0] < self.ref.goal() * 0.95:
                quick_fail = True
        if el < self.SETTLE_S + self.EVAL_S and not quick_fail and self.pending is not None:
            return
        if self.pending is None and el < 1.0:
            return
        frames = probe.window(2.0 if quick_fail else self.EVAL_S)
        self.t_state = now
        if self.pending is not None:
            if not quick_fail and len(frames) < self.ref.goal() * self.EVAL_S * 0.5:
                return  # no game frames (loading screen, Steam menu): decide nothing
            fps, p97 = frame_stats(frames)
            slow = self.ref.slow(frames)
            # any hitch counts against the step: TLOU (2026-11-18) accepted big cores at 1017 MHz with "one per 8 s
            # allowed" and then hitched 12 times a minute (78 ms). A streaming hitch at the wrong moment only leaves
            # that cluster a step higher.
            pacing = not quick_fail and fps >= self.ref.goal() * 0.99 and p97 <= self.ref.limit()
            ok = pacing and slow == 0
            ratio = self.work_ratio(gpu_auto, self.EVAL_S)
            if ratio is not None:
                self.min_work = ratio if self.min_work is None else min(self.min_work, ratio)
            if not ok:
                if gpu_full:
                    return  # the GPU is short: GpuAuto raises it; judge this step again afterwards
                if pacing and slow == 1 and not self.rejudged:
                    # a lone hitch (TLOU streams while walking, ~1/min at full clocks; 2026-11-18 one right after
                    # loading ended both searches at the ceilings): judge the same step once more
                    self.rejudged = True
                    return
                self.rejudged = False
                self.set(self.pending, self.idx[self.pending] + 1)
                self.cur += 1
            self.pending = None
            self.rejudged = False
        while self.cur < len(self.order) and self.idx[self.order[self.cur]] == 0:
            self.cur += 1
        if self.cur >= len(self.order):
            self.state, self.hold_t = "hold", now
            self.from_retry = self.retry_from is not None
            if gpu_auto is not None:
                gpu_auto.freeze_idx = None
            self.last_floor = dict(self.idx)
            found = self.caps()
            if self.retry_from is not None:
                gained = found != self.retry_from
                self.retry_s = self.RETRY_S if gained else min(self.retry_s * 2, self.RETRY_MAX_S)
                self.retry_from = None
                if not gained:
                    return
            self.learn(gpu_auto)
            return
        pid = self.order[self.cur]
        self.set(pid, self.idx[pid] - 1)
        self.pending = pid

    def hold(self, now, gpu_auto, gpu_up, gpu_full):
        fps = self.ref.fps(self.HOLD_WIN_S)
        if fps is None:
            return  # loading, paused: nothing to judge
        hitches = self.ref.stats(self.HITCH_WIN_S)
        hitching = hitches is not None and hitches[2] >= self.HITCHES
        if (fps >= self.ref.goal() * self.SLIP and not hitching) or gpu_full:
            if fps >= self.ref.goal() * 0.99 and not gpu_full:
                # a search can stop high when a heavy moment passes during it: after a while of steady FPS, try
                # lower again from here (waiting longer each time that finds nothing). Only in a scene of normal
                # weight: floors found in a light one (pause menu) do not hold when the game goes on.
                ratio = self.work_ratio(gpu_auto, 30)
                if ratio is not None and ratio < 0.8:
                    self.ok_since = None  # light scene: the time to the retry counts from when the game is back
                    return
                self.ok_since = self.ok_since or now
                if now - self.ok_since >= self.retry_s and self.ref.ok(self.EVAL_S):
                    self.ok_since = None
                    self.retry_from = self.caps()
                    self.start_search(gpu_auto)
            return
        self.ok_since = None
        if now < self.raise_at:
            return
        # after a raise for hitches, wait until the hitches that caused it are out of the window
        self.raise_at = now + (self.HITCH_WIN_S if hitching and fps >= self.ref.goal() * self.SLIP else self.RAISE_GAP_S)
        if fps < self.ref.goal() * self.DROP:
            at_ceil = all(self.khz(pid) >= self.ceil[pid] for pid in self.pols)
            if not at_ceil:
                self.last_floor = dict(self.idx)
                self.to_ceilings()
                self.state, self.t_state, self.retry_from = "recover", now, None
                decky.logger.info(f"fps auto: {fps:.1f} FPS, ceilings for {self.RECOVER_S:.0f} s, then searching "
                                  f"again from {self.caps()}")
                return
        big, small = self.order[-1], self.order[0]
        for pid in (big, small) if self.idx[big] <= self.idx[small] + 2 else (small, big):
            if self.khz(pid) < self.ceil[pid]:
                self.set(pid, self.idx[pid] + 1)
                self.last_floor = dict(self.idx)
                self.learned_idx = dict(self.idx)
                if self.from_retry and now - self.hold_t < self.RETRY_FAIL_S:
                    # what the retry found does not hold: it gained nothing, wait longer for the next one
                    self.retry_s = min(max(self.retry_s, self.RETRY_S) * 2, self.RETRY_MAX_S)
                else:
                    # a raise is often for a heavy moment: look for the lower floors again sooner than a retry
                    self.retry_s = min(self.retry_s, self.RELAX_S)
                self.from_retry = False
                self.on_learned(self.learned_entry(self.caps()))
                return
        # CPU at its ceilings and still short with the GPU not "busy": games that run CPU then GPU in series (TLOU,
        # Vela's GPU -> NPU chain) lose frames at a lower GPU clock even at 55-70 % busy. Raise the GPU's floor.
        # Not for hitches alone: those happen at full clocks too, and each step down of the GPU is already checked
        # for them (TLOU 2026-11-18: streaming hitches at the CPU ceilings pinned the GPU at 967 MHz).
        if gpu_up and fps < self.ref.goal() * self.SLIP:
            self.gpu_floor = gpu_auto.freqs[gpu_auto.idx + 1]
            gpu_auto.fps_floor = self.gpu_floor
            decky.logger.info(f"fps auto: CPU at its ceilings, GPU floor -> {self.gpu_floor // 1000000} MHz")


def clean_env():
    env = dict(os.environ)
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    return env


def powerd_reload():
    try:
        subprocess.run(["/usr/bin/armada-power", "reload"], timeout=15, env=clean_env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        decky.logger.warning(f"armada-power reload failed: {exc}")
        return False


LIMITERS = ("gamescope", "mangohud", "off")
MANGOHUD_DIR = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "mangohud")
MANGOHUD_ENV = "MANGOHUD=1 MANGOHUD_CONFIGFILE="


def limiter_of(cfg):
    value = cfg.get("limiter") if isinstance(cfg, dict) else None
    return value if value in LIMITERS else "gamescope"


def mangohud_conf(appid):
    return os.path.join(MANGOHUD_DIR, f"{appid}.conf")


def mangohud_fps(cfg):
    """The MangoHud limit for a game: its target when MangoHud is the chosen lock, else 0 (no limit)."""
    if not isinstance(cfg, dict) or cfg.get("enabled") is False or game_mode(cfg) == "off":
        return 0
    return (fps_target(cfg) or 0) if limiter_of(cfg) == "mangohud" else 0


def write_mangohud_conf(appid, fps):
    """The MangoHud layer is loaded in every game that has a profile (MANGOHUD=1 in its launch options, added by
    the panel), draws nothing (Steam's overlay is mangoapp) and only limits the FPS. It re-reads this file when it
    changes, so the lock goes on, off or to a new value with the game running; 0 = no limit."""
    text = f"no_display\nfps_limit={int(fps)}\nfps_limit_method=early\n"
    path = mangohud_conf(appid)
    if read(path) == text.strip():
        return
    os.makedirs(MANGOHUD_DIR, exist_ok=True)
    os.chmod(MANGOHUD_DIR, 0o755)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o644)


class FpsLimiter:
    """Which FPS lock the running game has, for the panel and the MangoHud config file.

    gamescope: Steam's frame limit as the QAM Performance tab sets it on Armada (client settings
    gamescope_disable_framelimit off + gamescope_app_target_framerate), by the frontend because only Steam's JS
    reaches them. Writing the GAMESCOPE_FPS_LIMIT X property or the perf store's SetFPSLimit did nothing. mangohud: the MangoHud layer inside the game (the launch options get MANGOHUD=1 and
    this game's config file; the panel writes them), from the next launch; it re-reads its file live (TLOU
    2026-11-18: 29.9 and 39.8 FPS). Until the layer is seen in the game's memory, Steam's limit is used."""
    CHECK_LAYER_S = 10.0

    def __init__(self):
        self.kind = "off"
        self.layer = {}  # appid -> True once libMangoHud is in one of its processes
        self.layer_t = 0.0
        self.key = None
        self.since = 0.0
        self.fps = None
        self.last_appid = None

    def layer_loaded(self, appid, reapers):
        if self.layer.get(appid):
            return True
        now = time.monotonic()
        if now - self.layer_t < self.CHECK_LAYER_S:
            return False
        self.layer_t = now
        for reaper in reapers:
            for pid in descendants(reaper):
                try:
                    with open(f"/proc/{pid}/maps", "rb") as f:
                        if b"libMangoHud" in f.read():
                            self.layer[appid] = True
                            return True
                except OSError:
                    continue
        return False

    def update(self, appid, cfg, reapers):
        mode = game_mode(cfg)
        fps = fps_target(cfg) if mode != "off" else None
        kind = limiter_of(cfg) if appid and fps else "off"
        try:
            if appid:
                write_mangohud_conf(appid, mangohud_fps(cfg))
            if self.last_appid and self.last_appid != appid:
                write_mangohud_conf(self.last_appid, 0)  # profile turned off with the game running: lock off
        except OSError as exc:
            decky.logger.warning(f"mangohud config: {exc}")
        self.last_appid = appid
        if kind == "mangohud" and not self.layer_loaded(appid, reapers):
            kind = "mangohud-pending"
        if (appid, kind, fps) != self.key:
            self.key, self.since = (appid, kind, fps), time.monotonic()
        self.kind, self.fps = kind, fps
        if not appid:
            self.layer.clear()

    def holds(self, probe):
        """False when the game still runs over the limit 10 s after it was set (a native port under Steam's limit,
        a value Steam does not offer), None when that can't be told."""
        # not for gamescope: under its limiter the app frame times gamescope reports did not match (Yakuza at a 30
        # limit read 60-83 FPS while drawing 3 W less, 2026-11-18), so this check would cry wolf
        if self.kind != "mangohud" or probe is None or not self.fps:
            return None
        if time.monotonic() - self.since < 10:
            return None
        frames = probe.window(5.0)
        if len(frames) < self.fps * 2:
            return None
        return frame_stats(frames)[0] <= self.fps * 1.08

class Plugin:
    games = {}
    limiter = None
    active = None
    restore_at = None
    fresh = False
    missing = 0
    task = None
    auto = None
    auto_appid = None
    auto_key = None
    auto_ceiling = 0
    auto_floor = 0
    auto_task = None
    scan = None
    running = ()
    fps = None
    fps_appid = None
    fps_key = None
    fps_error = ""
    probe = None
    ref = None

    # ---- settings -------------------------------------------------------------------------------------------
    def load(self):
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                data = json.load(f)
            self.games = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.games = {}

    def store(self):
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        tmp = SETTINGS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.games, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, SETTINGS)

    # ---- applying -------------------------------------------------------------------------------------------
    def apply(self, cfg, first):
        mode = game_mode(cfg)
        # With the CPU automatic, FpsAuto owns the CPU caps (the saved ones are its ceilings).
        for policy in (cpu_policies() if self.fps is None else []):
            khz = (cfg.get("cpu") or {}).get(str(policy["id"]))
            if not isinstance(khz, int):
                continue
            want = at_most(policy["freqs"], khz)
            if policy["max"] != want:
                write(os.path.join(policy["path"], "scaling_max_freq"), want)
        gpu = gpu_device()
        # "userspace" = Steam's manual GPU clock; leave that alone.
        # With the GPU automatic, GpuAuto owns min and max (gpu_max/gpu_min are its ceiling and floor).
        if not gpu or gpu["governor"] == "userspace" or mode in ("gpu", "both"):
            return
        want_max = cfg.get("gpu_max")
        want_min = cfg.get("gpu_min")
        new_max = at_most(gpu["freqs"], want_max) if isinstance(want_max, int) else gpu["max"]
        if isinstance(want_min, int):
            new_min = at_most(gpu["freqs"], want_min)
            # After the first pass the min is only raised: another plugin (Vela's GPU floor) may lift it during
            # the game and must not be fought.
            if not first:
                new_min = max(new_min, gpu["min"])
        else:
            new_min = gpu["min"]
        new_min = min(new_min, new_max)
        if new_max == gpu["max"] and new_min == gpu["min"]:
            return
        if new_max < gpu["min"]:
            write(os.path.join(gpu["path"], "min_freq"), new_min)
            write(os.path.join(gpu["path"], "max_freq"), new_max)
        else:
            write(os.path.join(gpu["path"], "max_freq"), new_max)
            write(os.path.join(gpu["path"], "min_freq"), new_min)

    def update_controllers(self, target, reapers):
        """Starts/stops, for the running game, the frame probe, GpuAuto and FpsAuto as its mode asks."""
        cfg = self.games.get(target) if target else None
        mode = game_mode(cfg)
        fps = fps_target(cfg) if mode != "off" else None
        want_cpu = mode in ("cpu", "both") and fps is not None
        want_gpu = mode in ("gpu", "both")
        gpu = gpu_device()
        gpu_ok = bool(gpu) and gpu["governor"] != "userspace"
        # GpuAuto also runs (only measuring) for the CPU alone: the CPU search reads the GPU's busy and work
        want_gpu_obj = gpu_ok and (want_gpu or want_cpu)
        # restart everything when the game or what was saved for it changes (an edit in the panel)
        key = None
        if target and (want_gpu_obj or want_cpu or fps):
            key = (target, mode, fps, json.dumps(cfg.get("cpu") or {}, sort_keys=True), cfg.get("gpu_max"),
                   cfg.get("gpu_min"))
        if key == self.auto_key and not (key and want_gpu_obj and self.auto is None):
            if self.auto is not None:
                force = reapers != self.auto.reapers
                self.auto.reapers = reapers
                self.auto.refresh_pids(force)
            return
        had = self.auto is not None and self.auto.control or self.fps is not None
        self.auto_key = key
        self.auto = None
        self.fps = None
        self.ref = None
        if not fps and self.probe is not None:
            self.probe.close()
            self.probe = None
        if had and target:
            # back to fixed limits, or new limits: start from the profile again, then apply this game's limits
            powerd_reload()
            self.fresh = True
        if key is None:
            return
        if fps and self.probe is None:
            try:
                self.probe = FrameProbe()
                self.fps_error = ""
            except OSError as exc:
                self.fps_error = f"sem leitura de FPS ({exc})"
                decky.logger.error(f"frame probe: {exc!r}")
        learned = cfg.get("fps_learned") if (cfg.get("fps_learned") or {}).get("target") == fps else None
        if learned and not isinstance(learned.get("fps"), (int, float)):
            # learned by 0.1.6, without the FPS the game makes at full clocks: for a game that does not hold the
            # target (8 of the 20 saved ones) the goal would be the target, and the GPU pushed to its top. Measure
            # once again from the ceilings; the new entry has it.
            learned = None
        if fps and self.probe is not None:
            base = float(learned["p97"]) if want_cpu and learned and learned.get("p97") else None
            base_fps = learned.get("fps") if base and isinstance(learned.get("fps"), (int, float)) else None
            self.ref = FrameRef(self.probe, fps, base, base_fps)
        if want_gpu_obj:
            self.auto = GpuAuto(gpu["path"], gpu["freqs"], reapers, control=want_gpu)
            self.auto.ref = self.ref
            self.auto_appid = target
            self.auto_ceiling = cfg.get("gpu_max") if isinstance(cfg.get("gpu_max"), int) else gpu["freqs"][-1]
            self.auto_floor = cfg.get("gpu_min") if isinstance(cfg.get("gpu_min"), int) else 0
            decky.logger.info(f"GPU auto ({'control' if want_gpu else 'measure'}) on for {target}, "
                              f"{len(self.auto.pids)} GPU process(es)")
        if want_cpu and self.ref is not None:
            policies = cpu_policies()
            ceilings = {}
            for p in policies:
                khz = (cfg.get("cpu") or {}).get(str(p["id"]))
                ceilings[p["id"]] = khz if isinstance(khz, int) else p["freqs"][-1]

            def save_learned(found, appid=target, value=fps):
                game = self.games.get(appid)
                if isinstance(game, dict) and game.get("fps_target") == value:
                    game["fps_learned"] = {**found, "target": value}
                    try:
                        self.store()
                    except OSError as exc:
                        decky.logger.warning(f"save learned floors: {exc}")

            self.fps = FpsAuto(fps, policies, ceilings, learned if want_cpu else None, save_learned, self.ref)
            self.fps_appid = target
            decky.logger.info(f"FPS target {fps} ({mode}) on for {target}, ceilings {ceilings}, learned {learned}")

    async def auto_loop(self):
        fps_next = 0.0
        while True:
            auto, fps, ref, probe = self.auto, self.fps, self.ref, self.probe
            if (auto is not None or fps is not None) and self.active:
                if auto is not None:
                    try:
                        await asyncio.to_thread(auto.step, self.auto_ceiling, self.auto_floor)
                    except Exception as exc:
                        decky.logger.error(f"gpu auto: {exc!r}")
                if probe is not None and time.monotonic() >= fps_next:
                    fps_next = time.monotonic() + 1.0
                    try:
                        if ref is not None:
                            ref.update()
                        if fps is not None:
                            await asyncio.to_thread(fps.step, probe, auto)
                    except Exception as exc:
                        decky.logger.error(f"fps auto: {exc!r}")
                await asyncio.sleep(GpuAuto.PERIOD_S)
            else:
                await asyncio.sleep(0.5)

    def tick(self):
        games = self.scan.games()
        running = set(games)
        self.running = sorted(running)
        target = None
        for appid in sorted(running):
            cfg = self.games.get(appid)
            if isinstance(cfg, dict) and cfg.get("enabled", True):
                target = appid
                break
        self.update_controllers(target, games.get(target, []))
        self.limiter.update(target, self.games.get(target) if target else None, games.get(target, []))
        if self.ref is not None:
            self.ref.hitches = self.limiter.kind != "gamescope"
        if target:
            first = self.active != target or self.fresh
            self.fresh = False
            if self.active != target:
                decky.logger.info(f"game {target} running: applying {self.games[target]}")
            self.active = target
            self.missing = 0
            self.restore_at = None
            self.apply(self.games[target], first)
            return
        if self.active and self.active in running and not self.games.get(self.active, {}).get("enabled", False):
            self.missing = MISSING_TICKS  # turned off or removed while running: restore now
        if self.active:
            # Steam relaunches some games right after start (Sifu: a ~2 s gap); wait before restoring.
            self.missing += 1
            if self.missing < MISSING_TICKS:
                return
            self.missing = 0
            decky.logger.info(f"game {self.active} gone: restoring the Armada profile")
            self.active = None
            powerd_reload()
            # Again a little later: Vela's GPU floor restores its own saved min on its 10 s pass.
            self.restore_at = time.monotonic() + 12
        elif self.restore_at and time.monotonic() >= self.restore_at:
            self.restore_at = None
            powerd_reload()

    async def loop(self):
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception as exc:
                decky.logger.error(f"tick: {exc!r}")
            await asyncio.sleep(TICK_S)

    # ---- frontend calls -------------------------------------------------------------------------------------
    async def get_state(self):
        policies = await asyncio.to_thread(cpu_policies)
        gpu = await asyncio.to_thread(gpu_device)
        running = list(self.running)  # from the last tick (every 2 s)
        auto, fps, ref = self.auto, self.fps, self.ref
        return {
            "policies": [{k: p[k] for k in ("id", "cpus", "freqs", "max")} for p in policies],
            "gpu": None if not gpu else {k: gpu[k] for k in ("freqs", "max", "min", "governor")},
            "games": self.games,
            "running": running,
            "active": self.active,
            # Vela (upscale plugin) keeps a live file per game it is set up for
            "vela": [a for a in running if os.path.exists(f"/tmp/vela-live/{a}.ini")],
            "auto": None if auto is None or not auto.control else {
                "appid": self.auto_appid, "busy": round(auto.busy, 2),
                "mhz": (gpu["max"] // 1000000) if gpu else 0, "processes": len(auto.pids)},
            "fps": None if fps is None else {
                "appid": self.fps_appid, "target": fps.target, "fps": round(fps.fps, 1),
                "state": fps.state, "cpu": {k: v // 1000 for k, v in fps.caps().items()}},
            "live_fps": None if ref is None or fps is not None else {
                "appid": self.auto_appid, "target": ref.target, "fps": round(frame_stats(ref.probe.window(1.0))[0], 1)},
            "fps_error": self.fps_error,
            "limiter": {"appid": self.active, "kind": self.limiter.kind, "fps": self.limiter.fps, "holds": self.limiter.holds(self.probe)},
            "mangohud": {"env": MANGOHUD_ENV, "dir": MANGOHUD_DIR},
        }

    async def save_game(self, appid, cfg):
        appid = str(appid)
        if not appid.isdigit() or not isinstance(cfg, dict):
            raise ValueError("invalid game settings")
        clean = {"enabled": cfg.get("enabled", True) is not False, "cpu": {}}
        if isinstance(cfg.get("name"), str):
            clean["name"] = cfg["name"][:200]
        for key, khz in (cfg.get("cpu") or {}).items():
            if str(key).isdigit() and isinstance(khz, (int, float)):
                clean["cpu"][str(key)] = int(khz)
        for key in ("gpu_max", "gpu_min"):
            if isinstance(cfg.get(key), (int, float)):
                clean[key] = int(cfg[key])
        target = cfg.get("fps_target")
        if isinstance(target, (int, float)) and 10 <= int(target) <= 240:
            clean["fps_target"] = int(target)
        mode = game_mode(cfg)
        if mode in ("cpu", "both") and "fps_target" not in clean:
            clean["fps_target"] = 30  # the CPU has nothing to aim at without one
        clean["mode"] = mode
        if cfg.get("limiter") in LIMITERS:
            clean["limiter"] = cfg["limiter"]
        # the layer reads it when the game starts and live after: it must exist before the next launch
        try:
            await asyncio.to_thread(write_mangohud_conf, appid, mangohud_fps(clean))
        except OSError as exc:
            decky.logger.warning(f"mangohud config: {exc}")
        # learned floors are the backend's: keep the stored ones (the panel may hold an older copy)
        learned = (self.games.get(appid) or {}).get("fps_learned")
        if isinstance(learned, dict):
            clean["fps_learned"] = learned
        self.games[appid] = clean
        await asyncio.to_thread(self.store)
        self.fresh = True  # an edit is a fresh apply: the GPU min may go down too
        await asyncio.to_thread(self.tick)
        return await self.get_state()

    async def forget_learned(self, appid):
        game = self.games.get(str(appid))
        if isinstance(game, dict) and game.pop("fps_learned", None) is not None:
            await asyncio.to_thread(self.store)
            if self.active == str(appid):
                self.auto_key = None  # start this game's search over now
                await asyncio.to_thread(self.tick)
        return await self.get_state()

    async def remove_game(self, appid):
        self.games.pop(str(appid), None)
        await asyncio.to_thread(self.store)
        await asyncio.to_thread(self.tick)
        return await self.get_state()

    # ---- lifecycle ------------------------------------------------------------------------------------------
    async def _main(self):
        self.games, self.active, self.restore_at = {}, None, None
        self.load()
        self.auto, self.auto_appid, self.auto_key = None, None, None
        self.fps, self.ref = None, None
        self.scan, self.running = ProcScan(), ()
        self.limiter = FpsLimiter()
        for appid, cfg in self.games.items():
            if str(appid).isdigit():
                try:
                    write_mangohud_conf(appid, mangohud_fps(cfg))
                except OSError as exc:
                    decky.logger.warning(f"mangohud config: {exc}")
        self.task = asyncio.get_event_loop().create_task(self.loop())
        self.auto_task = asyncio.get_event_loop().create_task(self.auto_loop())
        decky.logger.info(f"Aparejo ready, {len(self.games)} game(s)")

    async def _unload(self):
        for task in (self.task, self.auto_task):
            if task:
                task.cancel()
        self.auto = None
        self.fps = None
        self.ref = None
        if self.probe is not None:
            self.probe.close()
            self.probe = None

        if self.active:
            # Don't wait for it: Decky kills a plugin that takes more than a few seconds to unload.
            try:
                subprocess.Popen(["/usr/bin/armada-power", "reload"], env=clean_env(), start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                decky.logger.warning(f"armada-power reload failed: {exc}")
            self.active = None
