#!/usr/bin/env python3
"""daemon.py <pidfile> <logfile> <cwd> -- cmd args...  (env passes through)"""
import os, sys
pidfile, logfile, cwd = sys.argv[1:4]
cmd = sys.argv[sys.argv.index("--") + 1:]
if os.fork():
    os._exit(0)
os.setsid()
pid = os.fork()
if pid:
    open(pidfile, "w").write(str(pid))
    os._exit(0)
os.chdir(cwd)
fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(fd, 1); os.dup2(fd, 2)
nul = os.open(os.devnull, os.O_RDONLY); os.dup2(nul, 0)
os.execvp(cmd[0], cmd)
