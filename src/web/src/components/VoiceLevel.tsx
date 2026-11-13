// That the microphone hears: bars that rise and fall with the loudness of the voice, newest on the right
// (UX-005, ADR-0088).
import { useEffect, useRef } from "react";

// How often a new bar comes in, in milliseconds, and how much a quiet voice is raised.
const BAR_MS = 60;
const GAIN = 5;

export function VoiceLevel({ stream, label, className = "" }: { stream: MediaStream; label: string; className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    const drawing = element?.getContext("2d");
    if (!element || !drawing) return;
    const audio = new AudioContext();
    const analyser = audio.createAnalyser();
    analyser.fftSize = 1024;
    audio.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    // Sized once, in device pixels: resizing a canvas clears it.
    element.width = Math.max(1, Math.round(element.clientWidth * devicePixelRatio));
    element.height = Math.max(1, Math.round(element.clientHeight * devicePixelRatio));
    const color = getComputedStyle(element).color;
    const bar = 4 * devicePixelRatio;
    const gap = 3 * devicePixelRatio;
    const levels: number[] = new Array<number>(Math.max(1, Math.floor(element.width / (bar + gap)))).fill(0);
    let level = 0;
    let frame = 0;
    let last = 0;
    const draw = (now: number) => {
      // The loudness now: the root mean square of the samples, smoothed so that the bars do not flicker.
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
      level = Math.max(Math.min(1, Math.sqrt(sum / samples.length) * GAIN), level * 0.85);
      if (now - last >= BAR_MS) {
        last = now;
        levels.shift();
        levels.push(level);
        drawing.clearRect(0, 0, element.width, element.height);
        drawing.fillStyle = color;
        levels.forEach((value, index) => {
          const height = Math.max(bar, value * element.height);
          drawing.beginPath();
          drawing.roundRect(index * (bar + gap), (element.height - height) / 2, bar, height, bar / 2);
          drawing.fill();
        });
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      void audio.close();
    };
  }, [stream]);

  return <canvas ref={canvas} role="img" aria-label={label} className={`h-12 ${className}`} />;
}
