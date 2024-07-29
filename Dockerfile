FROM python:3.12-slim

ARG APP_ENV=production

# Install necessary tools
RUN apt-get update && apt-get install -y \
    parted \
    e2fsprogs \
    wget \
    sudo \
    software-properties-common \
    libfuse2 \
    fdisk \
    udev

RUN apt-get update && apt-get install \
    git \
    -yq --no-install-suggests --no-install-recommends --allow-downgrades --allow-remove-essential --allow-change-held-packages \
  && apt-get clean

RUN pip install poetry

WORKDIR /app/node-bootstrapper
COPY . /app/node-bootstrapper
RUN rm -rf .venv

COPY poetry.lock pyproject.toml /app/k8s_utils/
RUN poetry config virtualenvs.create false --local \
    && if [ "$APP_ENV" = "production" ]; then poetry install --no-dev --no-interaction --no-ansi; else poetry install --no-interaction --no-ansi; fi

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT [ "/bin/bash" ]
