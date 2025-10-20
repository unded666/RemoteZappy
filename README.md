Zappy-remote — PoC media bridge (server-hosted)

This repository contains a minimal proof-of-concept that demonstrates the core pieces needed to host the existing Tkinter-based gesture trainer and the Pygame game on a Linux server and expose them to a browser client via WebRTC.

What this PoC does

- Accepts a webcam stream from the browser (WebRTC) and optionally writes the incoming frames to a v4l2loopback device (so an unmodified gesture recognizer reading /dev/videoX can see them).
- Streams a synthetic "game" video back to the browser (placeholder for capturing the real game's window).
- Provides a tiny web client at / that captures your local webcam and connects via WebRTC.

Important: your development machine is Windows, so you'll need to host the PoC on a Linux machine (cloud VM or a Linux server). The code assumes a Linux host for v4l2loopback and ffmpeg.

Quick start (on a Linux host)

1) Install system packages (Ubuntu example):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg v4l2loopback-dkms
```

2) Create and activate a virtualenv, then install PoC Python deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-poc.txt
```

3) Create a v4l2loopback device (optional, if you want the gesture recognizer to read the browser webcam):

```bash
sudo modprobe v4l2loopback video_nr=2 card_label="webcam_from_browser" exclusive_caps=1
# this usually creates /dev/video2
```

4) Run the bridge server (replace /dev/video2 if you used a different device):

```bash
python server/bridge.py --v4l2 /dev/video2
```

5) Open a browser to http://<server-ip>:8080 and click Start. The page will ask for webcam access; grant it. You should see local and remote video.

Notes and next steps

- To integrate with the real game and the Tkinter-based gesture tool:
  - Run the gesture trainer and game on the same Linux host (or container) with DISPLAY set to a real X server or Xvfb.
  - Replace SyntheticGameTrack in `server/bridge.py` with a capture of the game's X window (mss, ffmpeg, or pygame surface). The PoC keeps that part separate intentionally.
  - The server already writes incoming webcam frames to a v4l2loopback device (if `--v4l2` is provided and ffmpeg is present). The gesture tool can open that device without modification.

- Production considerations: Use STUN/TURN, secure the signaling (HTTPS/WSS), add authentication, and run one game instance per player (containers or VMs).

Files added in this PoC

- server/bridge.py  — aiortc + aiohttp server implementing minimal signaling and media handling.
- web/index.html
- web/client.js
- README.md
- requirements-poc.txt

If you want, I can now:
- Replace the synthetic outgoing track with a real capture of your game's window (I'll need to know how you start the game on the Linux host), or
- Add a small local socket protocol so the game can push frames directly to the bridge (safer and lower-latency than window-capture).

## Docker and docker-compose (optional)

You can run the PoC bridge inside Docker which simplifies dependency setup on a remote Linux host.

Notes before using Docker

- The bridge expects to run on a Linux host for v4l2loopback support. If you want the bridge to write incoming webcam frames into a virtual camera device (so the unmodified Tkinter gesture trainer can open `/dev/videoN`), ensure the `v4l2loopback` kernel module is loaded on the host and map the device into the container.
- The provided `server/Dockerfile` is a minimal image that installs system deps (ffmpeg and libs) and the PoC Python requirements. It is intended for PoC usage only — for production you should harden the image and handle credentials, TLS, and TURN servers.

Quick docker-compose (recommended for testing)

1) Build and start the services (from the repo root):

```bash
docker compose build
docker compose up -d
```

2) Check logs (bridge):

```bash
docker compose logs -f bridge
```

3) Open a browser to http://<host-ip>:8080 and click Start.

Enable the example frame sender

The `docker-compose.yml` includes an optional `frame_sender` service that will connect to the bridge and push test frames. To start it alongside the bridge, uncomment or run:

```bash
docker compose up -d frame_sender
```

Mapping a host v4l2 device into the container

If you created a v4l2loopback device on the host (for example `/dev/video2`), map it into the container so the bridge's ffmpeg process can write to it. Example using `docker run`:

```bash
# create v4l2 device on host first
sudo modprobe v4l2loopback video_nr=2 card_label="webcam_from_browser" exclusive_caps=1
# run the bridge image mapping /dev/video2
docker run --rm -p 8080:8080 --device /dev/video2:/dev/video2 --name zappy-bridge zappy-remote-bridge
```

If you prefer docker-compose, add the device mapping under the `bridge` service in `docker-compose.yml` (the file includes a commented example).

Running the example frame sender against a containerized bridge

If you used docker-compose, the `frame_sender` service can be configured to connect to `ws://bridge:8080/framepipe` (it is in the provided compose file). Alternatively you can run the example sender on the host and point it at the container IP or `localhost` (if you published the bridge port):

```bash
# from host (bridge published on 8080)
python server/frame_sender_example.py --url ws://127.0.0.1:8080/framepipe --fps 15
```

Running the real game and gesture trainer

- Recommended: run the bridge, gesture trainer, and the game on the same Linux host (or in the same VM) so:
  - The gesture trainer can open the mapped v4l2 device (no code changes required), and
  - The game can push frames to `ws://127.0.0.1:8080/framepipe` (use the `FRAMEPIPE_URL` environment variable in `main.py`) so the bridge streams the actual game output to connected browsers.

Example: run game on the host with frame pushing enabled

```bash
export FRAMEPIPE_URL=ws://127.0.0.1:8080/framepipe
python main.py
```

Security and production notes

- Do not expose `/framepipe` to the public Internet unless you add authentication. The bridge defaults to refusing non-loopback connections to `/framepipe`.
- Use HTTPS/WSS for signaling and WebRTC in production. Configure a TURN server (coturn) for NAT traversal.
- Run a separate container per player/game instance for isolation and scaling, or use orchestration to spawn ephemeral containers when players connect.

Troubleshooting

- If the containerized bridge cannot write to the mapped `/dev/videoN`, confirm that the device node on the host exists and was passed into the container with `--device` and that the container has permission to write to it.
- If ffmpeg is missing or fails, check the bridge logs for the ffmpeg startup warning.

## CI: Build & publish Docker image (GitHub Actions -> GHCR)

A GitHub Actions workflow was added at `.github/workflows/docker-build.yml` that will build the Docker image from `server/Dockerfile` and push it to GitHub Container Registry (GHCR) as `ghcr.io/<OWNER>/zappy-remote-bridge:latest` on push to `main`/`master` or when run manually from the Actions tab.

How to trigger the build

- Push a commit to `main` (or `master`) or open the Actions tab in your repository and run the workflow manually using the `workflow_dispatch` button.

Verify the image in GHCR

- After the workflow completes, the image will be available at:

```
ghcr.io/<your-github-username-or-org>/zappy-remote-bridge:latest
```

Replace `<your-github-username-or-org>` with your repository owner.

Pull and run the image (Windows / cmd.exe)

1) (Optional) Authenticate to GHCR (if your image is private). Create a Personal Access Token (PAT) with the `read:packages` scope and run:

```cmd
docker login ghcr.io -u YOUR_GITHUB_USERNAME -p YOUR_PERSONAL_ACCESS_TOKEN
```

2) Pull and run the image:

```cmd
docker pull ghcr.io\YOUR_GITHUB_USERNAME\zappy-remote-bridge:latest
docker run --rm -p 8080:8080 --name zappy-bridge ghcr.io\YOUR_GITHUB_USERNAME\zappy-remote-bridge:latest
```

3) Open a browser to `http://localhost:8080` and click Start.

Pull and run on a Linux host (recommended for v4l2)

```bash
# Login if image is private
echo $CR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
# Pull
docker pull ghcr.io/YOUR_GITHUB_USERNAME/zappy-remote-bridge:latest
# Run (no v4l2)
docker run --rm -p 8080:8080 --name zappy-bridge ghcr.io/YOUR_GITHUB_USERNAME/zappy-remote-bridge:latest
```

Mapping a host v4l2 device (Linux-only)

If you created a `v4l2loopback` device on the Linux host (for the gesture trainer to read), map it into the container:

```bash
sudo modprobe v4l2loopback video_nr=2 card_label="webcam_from_browser" exclusive_caps=1
docker run --rm -p 8080:8080 --device /dev/video2:/dev/video2 --name zappy-bridge ghcr.io/YOUR_GITHUB_USERNAME/zappy-remote-bridge:latest
```

Notes and troubleshooting

- The workflow uses the built-in `GITHUB_TOKEN` so you don't need to configure secrets to push to GHCR for the same repo owner. If you want to push to a different registry (Docker Hub) I can add a workflow that uses secrets.
- If the image is published private, authenticate (`docker login ghcr.io`) before pulling.
- Building/pushing an image does not require the host to be Linux. Running features that interact with `/dev/video*` (v4l2) does require a Linux host with the `v4l2loopback` kernel module.

---
