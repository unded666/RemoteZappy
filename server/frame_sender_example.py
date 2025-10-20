"""
server/frame_sender_example.py

Example program that connects to ws://localhost:8080/framepipe and sends periodic JPEG
frames (generated from numpy) to demonstrate the frame-push API. Run this on the same
Linux host as the bridge.

Usage:
    source .venv/bin/activate
    python server/frame_sender_example.py --url ws://127.0.0.1:8080/framepipe --fps 15

This script depends on Pillow (PIL). The PoC requirements file includes it.
"""

import argparse
import asyncio
import io
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import aiohttp


async def run(url: str, fps: int, width: int, height: int):
    session_timeout = aiohttp.ClientTimeout(total=None)
    async with aiohttp.ClientSession(timeout=session_timeout) as session:
        async with session.ws_connect(url) as ws:
            print(f"Connected to {url}")
            frame_interval = 1.0 / fps

            # try to load a default font; fallback to basic drawing
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

            start = time.time()
            frame_idx = 0
            while True:
                t = time.time() - start
                # generate a moving color gradient with text overlay
                x = np.linspace(0, 255, width, dtype=np.uint8)
                img = np.zeros((height, width, 3), dtype=np.uint8)
                img[:, :, 0] = (x + int(t * 30)) % 256
                img[:, :, 1] = np.roll(x, int(t * 10))
                img[:, :, 2] = np.roll(x, int(-t * 20))

                pil = Image.fromarray(img, 'RGB')
                draw = ImageDraw.Draw(pil)
                text = f"frame {frame_idx} t={t:.2f}s"
                draw.text((8, 8), text, fill=(255, 255, 255), font=font)

                bio = io.BytesIO()
                pil.save(bio, format='JPEG', quality=75)
                bio.seek(0)
                jpeg_bytes = bio.read()

                await ws.send_bytes(jpeg_bytes)

                frame_idx += 1
                await asyncio.sleep(frame_interval)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8080/framepipe")
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    asyncio.run(run(args.url, args.fps, args.width, args.height))


if __name__ == "__main__":
    main()

