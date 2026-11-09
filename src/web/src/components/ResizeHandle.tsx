// Side panels the user resizes by their edge, or with the keyboard (UX-021).
import { type KeyboardEvent, type PointerEvent, useCallback, useRef, useState } from "react";

const STEP = 16;

export interface PanelWidth {
  width: number;
  min: number;
  max: number;
  change: (width: number) => void;
  reset: () => void;
}

/** A panel's width, kept on the device; what was kept is ignored when it is out of bounds. */
export function usePanelWidth(key: string, initial: number, min: number, max: number): PanelWidth {
  const read = () => {
    try {
      const kept = Number(localStorage.getItem(key));
      return kept >= min && kept <= max ? kept : initial;
    } catch {
      return initial;
    }
  };
  const [width, setWidth] = useState(read);
  const change = useCallback(
    (next: number) => {
      const bounded = Math.round(Math.min(max, Math.max(min, next)));
      setWidth(bounded);
      try {
        localStorage.setItem(key, String(bounded));
      } catch {
        // Kept for this page only.
      }
    },
    [key, min, max],
  );
  const reset = useCallback(() => {
    setWidth(initial);
    try {
      localStorage.removeItem(key);
    } catch {
      // Nothing was kept.
    }
  }, [key, initial]);
  return { width, min, max, change, reset };
}

/**
 * The edge of a panel: dragged, or moved with the arrow keys, it resizes the panel; a double click
 * brings back its default width. `side` is where the edge is on the panel.
 */
export function ResizeHandle({ label, side, panel, className = "" }: { label: string; side: "left" | "right"; panel: PanelWidth; className?: string }) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  // Moving the edge away from the panel widens it.
  const direction = side === "right" ? 1 : -1;

  function down(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, width: panel.width };
  }

  function move(event: PointerEvent<HTMLDivElement>) {
    if (drag.current === null) return;
    panel.change(drag.current.width + direction * (event.clientX - drag.current.x));
  }

  function up(event: PointerEvent<HTMLDivElement>) {
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function key(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = { ArrowLeft: -STEP * direction, ArrowRight: STEP * direction };
    if (event.key in moves) panel.change(panel.width + (moves[event.key] ?? 0));
    else if (event.key === "Home") panel.change(panel.min);
    else if (event.key === "End") panel.change(panel.max);
    else return;
    event.preventDefault();
  }

  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={panel.width}
      aria-valuemin={panel.min}
      aria-valuemax={panel.max}
      tabIndex={0}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onKeyDown={key}
      onDoubleClick={panel.reset}
      className={`absolute inset-y-0 z-10 w-2 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-0.5 after:-translate-x-1/2 after:transition-colors hover:after:bg-accent focus-visible:after:bg-accent ${side === "right" ? "-right-1" : "-left-1"} ${className}`}
    />
  );
}
