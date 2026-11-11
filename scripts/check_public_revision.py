"""Read-only deployment check before a deliberately requested public acceptance run."""
import json
from pathlib import Path
import re
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen


def check():
    config = json.loads(Path("configs/public-acceptance-request.json").read_text(encoding="utf-8"))
    expected = config["expected_deployment_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("An exact deployment commit is required")
    deadline = monotonic() + 240
    while True:
        try:
            with urlopen("https://mesa-meal-discovery.onrender.com/v1/system", timeout=45) as response:
                system = json.load(response)
            if system.get("deployment_commit") != expected:
                raise ValueError("Public deployment does not match requested revision")
            print(json.dumps({"verified_deployment_commit": expected, "model_calls": 0}))
            return
        except (URLError, TimeoutError, ValueError):
            if monotonic() >= deadline:
                raise
            sleep(5)


if __name__ == "__main__":
    check()
