"""the server setup: the real strategy sandbox (skipped unless LAB_SANDBOX is a container command), the budget gates."""
import json
import os
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from harness import sandbox
from harness.checks import Refused

RESEARCH = sandbox.HERE.parent
REAL = os.environ.get("LAB_SANDBOX", "local") not in ("", "local")
real_only = pytest.mark.skipif(not REAL, reason="set LAB_SANDBOX to the server's container command")
_idx = pd.bdate_range("2011-01-03", "2011-12-30")
PRICES = pd.DataFrame(100.0 + np.arange(len(_idx))[:, None] * np.ones(3), index=_idx, columns=["SPY", "TLT", "GLD"])


@real_only
def test_the_real_sandbox_runs_a_strategy_with_the_hosts_pandas(tmp_path):
    code = ("import numpy, pandas, scipy, statsmodels\n"
            f"assert (pandas.__version__, numpy.__version__) == {(pd.__version__, np.__version__)!r}\n\n"
            "def signal(prices):\n    return prices * 0 + 1 / len(prices.columns)\n")
    _, weights = sandbox.run(code, PRICES, {}, log=tmp_path / "log")
    assert np.allclose(weights[0], 1 / 3)


@real_only
@pytest.mark.parametrize("attack", [
    f"open({str(RESEARCH / 'lab.yaml')!r}).read()",  # the host's research folder (data/ lives next to it)
    "__import__('socket').create_connection(('1.1.1.1', 53), timeout=5)",
])
def test_the_real_sandbox_sees_no_host_files_and_no_network(attack, tmp_path):
    code = f"def signal(prices):\n    {attack}\n    return prices * 0\n"
    with pytest.raises(Refused):
        sandbox.run(code, PRICES, {}, log=tmp_path / "log")


def test_without_lab_sandbox_the_agents_code_never_runs(monkeypatch, tmp_path):
    """a wrapper that forgot to export LAB_SANDBOX stops the run; it never falls back to the host."""
    monkeypatch.delenv("LAB_SANDBOX", raising=False)
    planted = tmp_path / "ran-on-the-host"
    code = f"def signal(prices):\n    open({str(planted)!r}, 'w').close()\n    return prices * 0\n"
    with pytest.raises(RuntimeError, match="LAB_SANDBOX is not set"):
        sandbox.run(code, PRICES, {})
    assert not planted.exists()


@pytest.mark.parametrize("track, fallback", [("lab", False), ("user", True)])
def test_a_broken_budget_check_skips_the_lab_runs_the_users_jobs_and_never_fails(tmp_path, track, fallback):
    def gate(check):  # the wrapper as Hermes runs it, with `check` as the project's python
        python = tmp_path / ".venv/bin/python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text(f"#!/bin/sh\n{check}\n")
        python.chmod(0o755)
        out = subprocess.run(["bash", RESEARCH.parent / f"deploy/scripts/budget-{track}.sh"], capture_output=True,
                             text=True, env={"PATH": os.environ["PATH"], "CHIRON_RESEARCH": str(tmp_path)})
        assert out.returncode == 0  # a failed script makes Hermes run the agent
        return json.loads(out.stdout)

    (tmp_path / "registry").mkdir()
    working = json.dumps({"wakeAgent": not fallback})
    assert gate(f"echo '{working}'") == {"wakeAgent": not fallback}  # a working check's answer passes as it is
    assert gate("echo boom >&2; exit 1") == {"wakeAgent": fallback}
    assert "boom" in (tmp_path / "registry/budget.log").read_text()
    shutil.rmtree(tmp_path / "registry")
    assert gate("exit 1") == {"wakeAgent": fallback}  # even when it can't log
