"""runs the agent's signal code away from the host scripts.

an import on the host would let the code read the holdout and forward prices from disk, and the truncation test
can't see that. in production LAB_SANDBOX is a throwaway-container command with no network and no data mounts
(the server setup); the code and the prices go in on stdin, so no host path is ever opened for the agent.
LAB_SANDBOX=local runs a plain subprocess (tests only).
"""
import json
import os
import pickle
import shlex
import subprocess
import sys
import traceback
from pathlib import Path

import pandas as pd

from harness.checks import Refused

HERE = Path(__file__).resolve().parent


def run(code, prices, grid, train=None, log=None, name="strategy", timeout=900):
    """the truncation test on train (skipped if None), then the weights of every grid point on prices.
    returns ((params, day) of a truncation failure or None, [weights per grid point]).
    Refused: the strategy itself failed. RuntimeError: the sandbox failed, not the strategy.
    a crash's text goes only to `log` (host only): the code could print the prices it was given."""
    template = os.environ.get("LAB_SANDBOX")
    if not template:
        raise RuntimeError("LAB_SANDBOX is not set: never run the agent's code on the host")
    if template == "local":
        cmd = [sys.executable, "-m", "harness.sandbox"]
    else:  # e.g. docker run --rm -i --network none --read-only -v {harness}:/w/harness:ro -w /w lab python -m harness.sandbox
        cmd = shlex.split(template.format(harness=HERE))
    job = pickle.dumps({"code": code, "prices": prices, "grid": grid, "train": train})
    try:
        out = subprocess.run(cmd, input=job, capture_output=True, timeout=timeout, cwd=HERE.parent)
    except subprocess.TimeoutExpired:
        raise Refused(f"the signal code ran longer than {timeout} s") from None
    if log and out.stderr:
        with open(log, "a") as f:
            f.write(f"--- {name}\n{out.stderr.decode(errors='replace')[-2000:]}\n")
    if out.returncode:
        raise RuntimeError(f"the sandbox failed (exit {out.returncode}), see {log}")
    try:
        answer = json.loads(out.stdout)
    except ValueError:
        raise Refused("the signal code broke the sandbox answer") from None
    if answer.get("crashed"):
        raise Refused("the signal code crashed on the lab's data; run your smoke test on data/train/")
    weights = [pd.DataFrame(w, index=prices.index, columns=prices.columns, dtype=float) for w in answer["weights"]]
    failure = answer["truncation"] and (answer["truncation"][0], pd.Timestamp(answer["truncation"][1]))
    return failure, weights


def main():
    """inside the sandbox: run the strategy, answer on stdout as JSON (never pickle: the host must not unpickle it)."""
    from harness.checks import grid_points, truncation_failure

    job = pickle.load(sys.stdin.buffer)

    def signal(prices, **params):  # a fresh module per call: a cache can't carry later prices back
        module = {"__name__": "strategy"}
        exec(code, module)
        return module["signal"](prices, **params)

    out, sys.stdout = sys.stdout, sys.stderr  # the strategy's prints must not break the answer
    prices, grid, train = job["prices"], job["grid"], job["train"]
    try:
        code = compile(job["code"], "strategy.py", "exec")
        failure = None if train is None else truncation_failure(signal, train, grid)
        weights = [signal(prices.copy(), **p).reindex(index=prices.index, columns=prices.columns).to_numpy(float).tolist()
                   for p in grid_points(grid)]
    except BaseException:  # the strategy failed (sys.exit too); a non-zero exit means the sandbox itself failed
        traceback.print_exc()
        out.write(json.dumps({"crashed": True}))
        return
    out.write(json.dumps({"truncation": failure and [failure[0], str(failure[1])], "weights": weights}))


if __name__ == "__main__":
    main()
