"""Set up pinned portable Windows Node and n8n locally, without global installs."""

import argparse
import os
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

from fetch_local_llm import download

if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    if os.name != "nt":
        raise SystemExit("Use Node 24 and n8n@2.46.6 directly on other platforms; this helper is Windows-only")
    root = Path(__file__).resolve().parents[1]
    tools = root / ".tools"
    filename = "node-v24.22.2-win-x64.zip"
    archive = tools / filename
    download("https://nodejs.org/dist/v24.22.2/" + filename, archive,
             {"bytes":37754834,"sha256":"ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2"})
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename or ":" in member.filename:
                raise ValueError("Unsafe Node archive path")
            if not path.parts or path.parts[0] != "node-v24.22.2-win-x64":
                raise ValueError("Unexpected Node archive root")
            destination = tools.joinpath(*path.parts)
            if member.is_dir():
                destination.mkdir(parents=True,exist_ok=True)
            else:
                content = zipped.read(member)
                if destination.exists():
                    if destination.read_bytes() != content:
                        raise ValueError("Existing portable Node file differs; preserve it and choose another directory")
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with destination.open("xb") as stream:stream.write(content)
    directory = tools / "node-v24.22.2-win-x64"
    env = {**os.environ,"PATH":str(directory)+os.pathsep+os.environ.get("PATH","")}
    subprocess.run([str(directory/"node.exe"),str(directory/"node_modules/npm/bin/npm-cli.js"),"install",
                    "--prefix",str(tools/"n8n"),"n8n@2.46.6","--no-fund"],env=env,cwd=root,check=True)
    print("Portable Node and n8n are ready. No instance was started.")
