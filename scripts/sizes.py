"""Does the board survive — and stay readable at — small terminal sizes?

Walks every view at seven sizes from 200x40 down to 24x8 and fails on any
traceback. Curses is unforgiving about writes past the edge, and the usual
development window is wide enough to hide all of it.

    python3 scripts/sizes.py
"""
import pty, os, time, select, sys, json
import pathlib, tempfile, subprocess
REPO = str(pathlib.Path(__file__).resolve().parent.parent)

def run(lines, cols, keys, db):
    env = dict(os.environ, TERM="xterm-256color", LINES=str(lines),
               COLUMNS=str(cols), KIAREZ_SPACE_DB=db, SPACE_NO_FX="1")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe("python3", ["python3", "-c",
                   f"import sys;sys.path.insert(0,{REPO!r});"
                   "from space.app import run;run()"], env)
    os.set_blocking(fd, False); buf = b""
    def pump(t):
        nonlocal buf
        end = time.time() + t
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.03)
            if r:
                try: buf += os.read(fd, 65536)
                except OSError: return
    pump(1.0)
    for ch in keys:
        os.write(fd, ch.encode()); pump(0.10)
    os.write(fd, b"q"); pump(0.4)
    try:
        os.kill(pid, 9); os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    return buf.decode(errors="replace")

if len(sys.argv) > 1:
    db = sys.argv[1]
else:
    db = os.path.join(tempfile.mkdtemp(), "sizes.db")
    env = dict(os.environ, KIAREZ_SPACE_DB=db)
    subprocess.run([f"{REPO}/bin/space-cli", "node-add", "Work"],
                   capture_output=True, env=env)
    subprocess.run([f"{REPO}/bin/space-cli", "c", "a thought"],
                   capture_output=True, env=env)
bad = 0
for lines, cols in [(24, 80), (20, 60), (14, 44), (10, 34), (8, 24), (40, 200), (60, 100)]:
    out = run(lines, cols, "12345" + "c" + "x" + "\r" + "n\x1b" + "w" + "hi\r\r", db)
    if "Traceback" in out:
        bad += 1
        err = out[out.find("Traceback"):]
        line = [l for l in err.split("\n") if l.strip().startswith(("_curses", "curses.error", "ValueError", "IndexError", "TypeError", "AttributeError"))]
        print(f"FAIL  {lines}x{cols}: {(line or err.split(chr(10))[-4:])[0][:120]}")
    else:
        print(f"ok    {lines}x{cols}")
print("sizes with failures:", bad)
raise SystemExit(1 if bad else 0)
