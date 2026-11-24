"""
Live lines in a log (1.3.0, build 2026-11-19b): lines that are updated in
place, each with an elapsed-time clock, so a long step never looks frozen.

Background threads only change a line's text (set / done / remove, under a
lock); the lines are redrawn by a timer on the Tk thread, about once a
second, which also keeps the clocks moving during a long step that sends no
messages. Each line's text carries its own Tk tag, so lines can be inserted
around it (a child line under its parent) without disturbing it.

Build 2026-11-20b: a line given its final text with done() is retired once
drawn: its own tag is deleted and it leaves the list of lines, so the
redraw costs the same with 25,000 finished lines as with 25 (many Tk tags
slow a text widget down). A retired line is not changed again; a later
set() with its key starts a new line.
"""

import threading
import time


def fmt_elapsed(seconds):
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {(s % 3600) // 60:02d} min"


class LiveLines:
    def __init__(self, root, text, interval_ms=1000, on_tick=None):
        self.root = root
        self.text = text
        self.interval = interval_ms
        self.on_tick = on_tick          # called on the Tk thread each tick
        self.items = {}                 # key -> state
        self.lock = threading.Lock()
        self._after = None
        self._n = 0
        self.t0 = time.monotonic()

    # -- any thread ------------------------------------------------------
    def set(self, key, text, tag="dim", clock=True, parent=None,
            started=None):
        """Create or update a line. started: time.monotonic() value the
        clock counts from (default: when the line was created)."""
        with self.lock:
            it = self.items.get(key)
            if it is None:
                self._n += 1
                it = self.items[key] = {
                    "name": f"live{self._n}", "drawn": False,
                    "t0": started if started is not None
                    else time.monotonic(),
                    "parent": parent, "removed": False}
            elif started is not None:
                it["t0"] = started
            it.update(text=text, tag=tag, clock=clock, dirty=True,
                      final=False)

    def done(self, key, text, tag="success"):
        """Final text for a line; its clock stops (the time taken is
        whatever the caller puts in the text). The line is retired once
        drawn."""
        self.set(key, text, tag=tag, clock=False)
        with self.lock:
            it = self.items.get(key)
            if it is not None:
                it["final"] = True

    def remove(self, key):
        with self.lock:
            it = self.items.get(key)
            if it is not None:
                it["removed"] = True
                it["dirty"] = True

    def elapsed(self, key):
        with self.lock:
            it = self.items.get(key)
            return time.monotonic() - it["t0"] if it else 0.0

    # -- Tk thread -------------------------------------------------------
    def start(self):
        self.t0 = time.monotonic()
        self._redraw()
        self._schedule()

    def stop(self, wait=False):
        """Stop the timer and draw the final state on the Tk thread. With
        wait=True (only from another thread), return once it is drawn, so
        lines logged afterwards come below it."""
        import threading
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        drawn = threading.Event()

        def final():
            try:
                self._redraw()
                if self.on_tick:
                    self.on_tick()
            finally:
                drawn.set()
        try:
            self.root.after(0, final)
        except Exception:
            return
        if wait:
            drawn.wait(5)

    def _schedule(self):
        try:
            self._after = self.root.after(self.interval, self._tick)
        except Exception:
            self._after = None

    def _tick(self):
        self._redraw()
        if self.on_tick:
            try:
                self.on_tick()
            except Exception:
                pass
        self._schedule()

    def _redraw(self):
        with self.lock:
            snapshot = [(k, dict(v)) for k, v in self.items.items()]
            for _, v in self.items.items():
                v["dirty"] = False
            for k in [k for k, v in self.items.items() if v["removed"]]:
                del self.items[k]
        drawn_final = []
        now = time.monotonic()
        t = self.text
        try:
            t.config(state="normal")
            for key, it in snapshot:
                if not (it["dirty"] or it["clock"] or it["removed"]):
                    continue
                rng = t.tag_ranges(it["name"])
                if it["removed"]:
                    if rng:
                        t.delete(rng[0], rng[1])
                    continue
                line = it["text"]
                if it["clock"]:
                    line += f" · {fmt_elapsed(now - it['t0'])}"
                if it.get("final"):
                    drawn_final.append((key, it["name"]))
                if rng:
                    t.delete(rng[0], rng[1])
                    t.insert(rng[0], line + "\n", (it["tag"], it["name"]))
                else:
                    where = "end"
                    parent = it.get("parent")
                    if parent is not None:
                        pit = next((v for k, v in snapshot
                                    if k == parent), None)
                        prng = (t.tag_ranges(pit["name"]) if pit else ())
                        if prng:
                            # after the parent and its children so far
                            where = prng[1]
                            for k2, v2 in snapshot:
                                if v2.get("parent") == parent and k2 != key:
                                    r2 = t.tag_ranges(v2["name"])
                                    if r2 and t.compare(r2[1], ">", where):
                                        where = r2[1]
                    t.insert(where, line + "\n", (it["tag"], it["name"]))
            # Retire final lines drawn in this pass (after the whole pass,
            # so a child drawn in it could still find its parent), unless
            # changed meanwhile.
            with self.lock:
                for key, name in drawn_final:
                    cur = self.items.get(key)
                    if (cur is not None and cur["name"] == name
                            and cur.get("final") and not cur["dirty"]):
                        del self.items[key]
                        try:
                            t.tag_delete(name)
                        except Exception:
                            pass
            t.see("end")
            t.config(state="disabled")
        except Exception:
            pass
