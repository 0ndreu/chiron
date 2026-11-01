# one image for both sandboxes: the agent's commands (Hermes docker backend) and the lab's strategy runs (LAB_SANDBOX).
# pandas, numpy and scipy match research/uv.lock: the prices go in pickled, and another pandas may fail to unpickle them.
# no duckdb: the registry belongs to the scripts. no requests: the network is off in both sandboxes.
FROM python:3.12.13-slim-trixie@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
RUN pip install --no-cache-dir --disable-pip-version-check \
    pandas==3.1.0 numpy==2.5.4 scipy==1.18.1 statsmodels==0.15.0
ENV PYTHONDONTWRITEBYTECODE=1
