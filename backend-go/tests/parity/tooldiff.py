#!/usr/bin/env python3
"""Invoke the same AI tool on the Python and Go backends of a run and diff the output.

usage: tooldiff.py <run> <tool_name> '<json args>' [--show]

Python: imports the run's backend copy (data = $PARITY_RUNS/<run>/py/data) and calls the
tool handler. Go: runs `octo -tool` against $PARITY_RUNS/<run>/go/data. Both talk to their
own mock GitHub API. NOTE: write tools mutate each side's data + mock state.
"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.environ.get("PARITY_RUNS", "/tmp/octofinance-parity")
sys.path.insert(0, HERE)
from parity import diff  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
run, tool, args = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "{}"
show = "--show" in sys.argv
root = os.path.join(RUNS, run)
py_port, go_port, py_mock, go_mock = open(os.path.join(root, "ports")).read().split()

PY = r'''
import asyncio, json, sys
from app.services.pat_manager import pat_manager
from app.services.api_manager import api_manager
from app.services.data_collector import data_collector
from app.services.copilot_engine import copilot_engine
from copilot.tools import ToolInvocation
async def main():
    pat_manager.load()
    await api_manager.rebuild()
    data_collector.set_api_manager(api_manager)
    copilot_engine.set_api_manager(api_manager)
    tools = copilot_engine._build_tools_for_session(None)
    t = next((t for t in tools if t.name == sys.argv[1]), None)
    if t is None:
        print(json.dumps({"__unknown_tool__": sys.argv[1]})); return
    res = await t.handler(ToolInvocation(tool_name=sys.argv[1], arguments=json.loads(sys.argv[2])))
    if res.result_type != "success":
        print(json.dumps({"result_type": res.result_type, "text": res.text_result_for_llm, "error": res.error}))
    else:
        print(res.text_result_for_llm)
asyncio.run(main())
'''
env = dict(os.environ, OCTOFINANCE_GITHUB_API_BASE=f"http://127.0.0.1:{py_mock}")
py = subprocess.run([f"{REPO}/.venv/bin/python", "-c", PY, tool, args], cwd=os.path.join(root, "py/backend"),
                    env=env, capture_output=True, text=True, timeout=900)
genv = dict(os.environ, OCTOFINANCE_GITHUB_API_BASE=f"http://127.0.0.1:{go_mock}",
            OCTOFINANCE_DATA_DIR=os.path.join(root, "go/data"))
go = subprocess.run([os.path.join(root, "go/octo"), "-tool", tool, "-args", args], cwd=os.path.join(root, "go"),
                    env=genv, capture_output=True, text=True, timeout=900)

def last_json(out):
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None

a, b = last_json(py.stdout), last_json(go.stdout)
if a is None or b is None:
    print(f"FAIL {tool}: could not parse output")
    print("py stdout:", py.stdout[-1500:], "\npy stderr:", py.stderr[-1500:])
    print("go stdout:", go.stdout[-1500:], "\ngo stderr:", go.stderr[-1500:])
    sys.exit(1)
problems = diff(a, b)
print(("OK   " if not problems else "DIFF ") + f"{tool} {args}")
for p in problems:
    print("     " + p)
if show:
    print("  py:", json.dumps(a)[:3000]); print("  go:", json.dumps(b)[:3000])
sys.exit(1 if problems else 0)
