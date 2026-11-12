"""Start the built product locally with Gemini -> Groq (or no LLM); Ctrl+C stops it."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true", help="Use explicit glossary fallback only")
    parser.add_argument("--cloud", action="store_true",
                        help="Gemini, falling back to Groq, with keys from the environment (the default)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stop-after", type=float, help="Stop after this many seconds for a lifecycle smoke check")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a local port between 1024 and 65535")
    if args.stop_after is not None and not 0 < args.stop_after <= 3600:
        parser.error("Stop-after must be between zero and 3600 seconds")
    if not (ROOT / "apps/web/dist/index.html").is_file():
        parser.error("Build the interface first: npm --prefix apps/web run build")
    children = []
    env = dict(os.environ)
    try:
        if not args.no_llm:
            available = [name for name, key in (("gemini", "GEMINI_API_KEY"), ("groq", "GROQ_API_KEY")) if env.get(key)]
            if not available:
                parser.error("Set GEMINI_API_KEY and/or GROQ_API_KEY first (see .env.example)")
            env["LLM_PROVIDER"] = available[0]
            env["LLM_MODEL"] = "gemini-3.1-flash-lite" if available[0] == "gemini" else ""
            env["LLM_FALLBACK_PROVIDERS"] = ",".join(available[1:])
            print("Providers: " + " -> ".join(available), flush=True)
        else:
            env["LLM_PROVIDER"]="disabled"
        children.append(subprocess.Popen([sys.executable,"-m","uvicorn","meal_discovery.api:app","--host","127.0.0.1",
                                         "--port",str(args.port),"--no-access-log"],cwd=ROOT,env=env,
                                         creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)))
        deadline = time.monotonic() + 15
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{args.port}/health",timeout=1) as response:
                    if response.status == 200:break
            except OSError:
                if time.monotonic() > deadline or children[-1].poll() is not None:
                    raise RuntimeError("The API did not become ready; check the local port and configuration")
                time.sleep(.2)
        print(f"Mesa: http://127.0.0.1:{args.port} — Ctrl+C stops both services.",flush=True)
        stop_at = time.monotonic() + args.stop_after if args.stop_after is not None else None
        while children[-1].poll() is None and (stop_at is None or time.monotonic() < stop_at):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                if os.name == "nt":
                    # Windows venv launchers can create an interpreter child; stop the owned tree.
                    subprocess.run(["taskkill","/PID",str(child.pid),"/T","/F"],capture_output=True,check=False)
                else:
                    child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
