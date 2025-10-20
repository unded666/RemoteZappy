FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Install system deps needed by aiortc / av / ffmpeg
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libavcodec-dev libavformat-dev libavdevice-dev libavutil-dev libavfilter-dev libavresample-dev \
        pkg-config \
        libssl-dev \
        libsrtp2-dev \
        libopus-dev \
        libv4l-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only what's needed for the PoC
COPY requirements-poc.txt /app/
COPY server /app/server
COPY web /app/web
COPY main.py /app/main.py
COPY magic.py /app/magic.py
COPY *.json /app/
COPY icons /app/icons

RUN python -m pip install --upgrade pip
RUN pip install -r requirements-poc.txt

EXPOSE 8080

CMD ["python", "server/bridge.py", "--host", "0.0.0.0"]

