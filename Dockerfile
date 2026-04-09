FROM python:3.13
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1
# Install App
RUN mkdir /workspace
ADD . /workspace
WORKDIR /workspace
RUN uv sync
