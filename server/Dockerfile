FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Install system deps needed by aiortc / av / ffmpeg and minimal libs for headless pygame
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        xvfb \
        git \
        libsdl2-2.0-0 \
        libdbus-1-3 \
        libasound2 \
        libx11-6 \
        libxext6 \
        libxrender1 \
        fonts-dejavu-core \
        libavcodec-dev libavformat-dev libavdevice-dev libavutil-dev libavfilter-dev libavresample-dev \
        pkg-config \
        libssl-dev \
        libsrtp2-dev \
        libopus-dev \
        libv4l-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only what's needed for the PoC
COPY requirements.txt /app/
COPY server /app/server
COPY web /app/web
COPY main.py /app/main.py
COPY magic.py /app/magic.py
COPY *.json /app/
COPY icons /app/icons
COPY gesture_control /app/gesture_control

RUN python -m pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the start script and make it executable
COPY server/start-all.sh /app/server/start-all.sh
RUN chmod +x /app/server/start-all.sh

EXPOSE 8080

# Run the wrapper script which starts both the game (headless) and the bridge
CMD ["/app/server/start-all.sh"]
