"""
server/bridge.py

Minimal aiortc/aiohttp media bridge with a local frame-push WebSocket.
- POST /offer handles WebRTC SDP offers and returns answers.
- WS  /framepipe accepts binary JPEG frames from a local game process and enqueues them
  for streaming to connected browsers.

Run on a Linux host. For full integration, run your Tkinter gesture trainer and the game
on the same host so the trainer can read /dev/videoN (created by v4l2loopback) and the
game can push frames to /framepipe.
"""

import argparse
import asyncio
import io
import logging
import os
import subprocess
import time

from aiohttp import web, WSMsgType
import numpy as np
import av
from av import VideoFrame
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bridge")

ROOT = os.path.dirname(os.path.dirname(__file__))
WEB_ROOT = os.path.join(ROOT, "web")

# Small in-memory queue for frames pushed by the game process (VideoFrame objects)
FRAME_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=4)

pcs = set()


class SyntheticGameTrack(MediaStreamTrack):
    """Video track that uses frames from FRAME_QUEUE (pushed by the game) when available,
    otherwise falls back to a synthetic animated pattern.
    """

    kind = "video"

    def __init__(self, width=640, height=480, fps=20):
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self._start = time.time()

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # Try to get a pushed frame with a short timeout
        try:
            vf = await asyncio.wait_for(FRAME_QUEUE.get(), timeout=0.05)
            vf.pts = pts
            vf.time_base = time_base
            return vf
        except asyncio.TimeoutError:
            # No pushed frame — generate synthetic fallback
            t = time.time() - self._start
            img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            cv = (np.linspace(0, 255, self.width, dtype=np.uint8) + int(t * 50)) % 256
            img[:, :, 0] = cv
            img[:, :, 1] = np.roll(cv, int(t * 10))
            img[:, :, 2] = np.roll(cv, int(-t * 20))

            frame = VideoFrame.from_ndarray(img, format="rgb24")
            frame.pts = pts
            frame.time_base = time_base
            await asyncio.sleep(1 / self.fps)
            return frame


async def index(request):
    return web.FileResponse(os.path.join(WEB_ROOT, "index.html"))


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)
    logger.info("Created RTCPeerConnection %s", pc)

    v4l2_path = request.app.get("v4l2_path")

    @pc.on("track")
    def on_track(track):
        logger.info("Track %s received", track.kind)

        if track.kind == "video" and v4l2_path:
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                "640x480",
                "-r",
                "25",
                "-i",
                "-",
                "-f",
                "v4l2",
                v4l2_path,
            ]
            try:
                logger.info("Starting ffmpeg to write to %s", v4l2_path)
                ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

                async def relay_video():
                    try:
                        while True:
                            frame = await track.recv()
                            img = frame.to_ndarray(format="rgb24")
                            ffmpeg_proc.stdin.write(img.tobytes())
                    except Exception as exc:
                        logger.info("relay_video ended: %s", exc)
                        try:
                            ffmpeg_proc.stdin.close()
                        except Exception:
                            pass

                asyncio.ensure_future(relay_video())
            except FileNotFoundError:
                logger.warning("ffmpeg not found; cannot write to v4l2 device")

        @track.on("ended")
        def on_ended():
            logger.info("Track %s ended", track.kind)

    # Handle datachannels for input forwarding
    @pc.on("datachannel")
    def on_datachannel(channel):
        logger.info("DataChannel %s created", channel.label)

        @channel.on("message")
        def on_message(message):
            # Expect text messages (JSON); forward to local input server
            try:
                msg_bytes = None
                if isinstance(message, str):
                    msg_bytes = message.encode('utf-8')
                elif isinstance(message, bytes):
                    msg_bytes = message
                else:
                    logger.warning("Unknown datachannel message type: %s", type(message))
                    return

                async def _forward():
                    try:
                        reader, writer = await asyncio.open_connection('127.0.0.1', 5001)
                        writer.write(msg_bytes + b"\n")
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                    except Exception as exc:
                        logger.debug("Failed to forward input to local server: %s", exc)

                asyncio.ensure_future(_forward())
            except Exception as exc:
                logger.exception("Error handling datachannel message: %s", exc)

    # outgoing track is the game's frames
    game_track = SyntheticGameTrack(width=640, height=480, fps=20)
    pc.addTrack(game_track)

    # set remote description and answer
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})


async def framepipe(request):
    """WebSocket endpoint that accepts binary JPEG frames. Each binary message should
    contain exactly one JPEG image. Frames are decoded and enqueued for streaming.

    This endpoint should be bound to localhost (loopback) in deployment — do not expose
    it publicly unless you add authentication.
    """
    # Reject non-loopback connections by default, unless --allow-framepipe-remote is set
    if not request.app["framepipe_allow_remote"] and request.remote and request.remote[0] != "127.0.0.1":
        return web.HTTPForbidden(reason="Remote connections to /framepipe are not allowed")

    ws = web.WebSocketResponse(max_msg_size=64 * 1024 * 1024)
    await ws.prepare(request)
    logger.info("framepipe connected from %s", request.remote)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                jpeg = msg.data
                try:
                    # decode jpeg into frames using PyAV
                    container = av.open(io.BytesIO(jpeg), mode='r', format='jpeg')
                    for frame in container.decode(video=0):
                        img = frame.to_ndarray(format='rgb24')
                        vf = VideoFrame.from_ndarray(img, format='rgb24')
                        # enqueue, dropping oldest if full
                        try:
                            FRAME_QUEUE.put_nowait(vf)
                        except asyncio.QueueFull:
                            try:
                                _ = FRAME_QUEUE.get_nowait()
                            except Exception:
                                pass
                            try:
                                FRAME_QUEUE.put_nowait(vf)
                            except Exception:
                                pass
                        break
                    container.close()
                except Exception as exc:
                    logger.exception("failed to decode incoming JPEG frame: %s", exc)
            elif msg.type == WSMsgType.TEXT:
                logger.debug("framepipe text message: %s", msg.data)
            elif msg.type == WSMsgType.ERROR:
                logger.warning("framepipe connection closed with exception %s", ws.exception())
                break
    finally:
        await ws.close()
        logger.info("framepipe disconnected: %s", request.remote)

    return ws


async def on_shutdown(app):
    coros = [pc.close() for pc in list(pcs)]
    await asyncio.gather(*coros)


def ensure_web_root():
    if not os.path.exists(WEB_ROOT):
        raise RuntimeError(f"Web client files not found in {WEB_ROOT}. Create web/index.html and web/client.js")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--v4l2", default=None, help="Path to v4l2loopback device e.g. /dev/video2 (optional)")
    parser.add_argument("--allow-framepipe-remote", action="store_true", help="Allow non-loopback connections to /framepipe (unsafe)")
    args = parser.parse_args()

    ensure_web_root()

    app = web.Application()
    app["v4l2_path"] = args.v4l2
    app["framepipe_allow_remote"] = bool(args.allow_framepipe_remote)
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    app.router.add_get("/framepipe", framepipe)
    app.router.add_static("/static/", WEB_ROOT)

    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
