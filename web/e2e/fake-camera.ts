/**
 * Fake webcam input for the end-to-end tests.
 *
 * Chromium/Edge can replace the camera with a video file
 * (--use-file-for-fake-video-capture). qrVideo() turns a screenshot of the QR
 * printed on a badge into such a file (Y4M, a still frame repeated by the browser),
 * so the check-out page's camera scanner reads exactly what the badge shows.
 */
import fs from "node:fs";

import jsQR from "jsqr";
import { PNG } from "pngjs";

const WIDTH = 640;
const HEIGHT = 480;

/** Reads the QR in a PNG screenshot (independently of the app's own decoder). */
export function decodeQr(png: Buffer): string | null {
  const image = PNG.sync.read(png);
  return jsQR(new Uint8ClampedArray(image.data), image.width, image.height)?.data ?? null;
}

/** Writes a Y4M video showing the screenshot centred on white, scaled up for a comfortable read. */
export function writeQrVideo(png: Buffer, file: string): void {
  const image = PNG.sync.read(png);
  const scale = Math.max(1, Math.floor(Math.min(WIDTH * 0.7 / image.width, HEIGHT * 0.7 / image.height)));
  const left = Math.floor((WIDTH - image.width * scale) / 2);
  const top = Math.floor((HEIGHT - image.height * scale) / 2);

  const luma = (x: number, y: number): number => {
    const sx = Math.floor((x - left) / scale);
    const sy = Math.floor((y - top) / scale);
    if (sx < 0 || sy < 0 || sx >= image.width || sy >= image.height) return 235;          // white
    const i = (sy * image.width + sx) * 4;
    const [r, g, b] = [image.data[i], image.data[i + 1], image.data[i + 2]];
    return Math.round(16 + (65.481 * r + 128.553 * g + 24.966 * b) / 255);                 // BT.601
  };

  const y = Buffer.alloc(WIDTH * HEIGHT);
  for (let row = 0; row < HEIGHT; row++) {
    for (let col = 0; col < WIDTH; col++) y[row * WIDTH + col] = luma(col, row);
  }
  const chroma = Buffer.alloc((WIDTH / 2) * (HEIGHT / 2), 128);                              // grey: no colour
  const header = Buffer.from(`YUV4MPEG2 W${WIDTH} H${HEIGHT} F10:1 Ip A1:1 C420jpeg\n`);
  const frame = Buffer.concat([Buffer.from("FRAME\n"), y, chroma, chroma]);
  fs.writeFileSync(file, Buffer.concat([header, frame, frame]));
}
