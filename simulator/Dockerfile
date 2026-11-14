FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SIM_STATE_PATH=/data/simulation.sqlite3

WORKDIR /app
RUN useradd --create-home --uid 10001 simulator \
    && mkdir /data \
    && chown simulator:simulator /data
COPY --chown=simulator:simulator space_sim/ /app/space_sim/
COPY --chown=simulator:simulator schemas/ /app/schemas/
USER simulator

CMD ["python", "-m", "space_sim.container"]
