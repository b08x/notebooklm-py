import { useEffect, useMemo, useRef, useState } from "react";
import { useMap } from "@/lib/queries";
import type { MapPoint } from "@/lib/types";
import { fmt, shortId } from "@/lib/utils";
import { actions, useApp } from "@/state/store";

const PALETTE = ["#a78bfa", "#7dd3fc", "#86efac", "#fcd34d", "#f0abfc", "#5eead4", "#fca5a5", "#93c5fd", "#fdba74", "#c4b5fd"];

function colorFor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

/** 2D projection of chunk embeddings; color by topic (or document); click opens the chunk. */
export function MapView() {
  const filters = useApp((s) => s.filters);
  const detailId = useApp((s) => s.detailId);
  const q = useMap(filters);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const [hover, setHover] = useState<{ p: MapPoint; x: number; y: number } | null>(null);
  const points = useMemo(() => q.data?.points ?? [], [q.data]);
  const colorBy = q.data?.color_by ?? "document";

  const scale = useMemo(() => {
    if (!points.length) return null;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const p of points) {
      x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y);
    }
    const pad = 24;
    const sx = (size.w - 2 * pad) / (x1 - x0 || 1);
    const sy = (size.h - 2 * pad) / (y1 - y0 || 1);
    return { tx: (x: number) => pad + (x - x0) * sx, ty: (y: number) => size.h - pad - (y - y0) * sy };
  }, [points, size]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width, h: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = canvas.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx || !scale) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size.w * dpr;
    c.height = size.h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    ctx.globalAlpha = 0.8;
    for (const p of points) {
      ctx.fillStyle = colorFor(colorBy === "topic" ? (p.topic ?? "—") : p.document_id);
      ctx.beginPath();
      ctx.arc(scale.tx(p.x), scale.ty(p.y), 2.4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    const sel = points.find((p) => p.external_id === detailId);
    if (sel) {
      ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--fg") || "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(scale.tx(sel.x), scale.ty(sel.y), 6, 0, Math.PI * 2);
      ctx.stroke();
    }
  }, [points, scale, size, colorBy, detailId]);

  const nearest = (mx: number, my: number): MapPoint | null => {
    if (!scale) return null;
    let best: MapPoint | null = null;
    let bestD = 64;
    for (const p of points) {
      const dx = scale.tx(p.x) - mx;
      const dy = scale.ty(p.y) - my;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5 text-[12px] text-muted">
        <span className="tabular">{q.isLoading ? "Projecting embeddings…" : `${fmt.format(points.length)} chunks`}</span>
        <span>colored by {colorBy}</span>
        <span className="ml-auto">hover to preview · click to open</span>
      </div>
      <div ref={wrap} className="relative min-h-0 min-w-0 flex-1 overflow-hidden" data-testid="map">
        <canvas
          ref={canvas}
          style={{ width: size.w, height: size.h, position: "absolute", inset: 0 }}
          aria-label={`Embedding map of ${points.length} chunks`}
          role="img"
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const p = nearest(e.clientX - r.left, e.clientY - r.top);
            setHover(p ? { p, x: e.clientX - r.left, y: e.clientY - r.top } : null);
          }}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const p = nearest(e.clientX - r.left, e.clientY - r.top);
            if (p) actions.open(p.external_id);
          }}
          className="cursor-crosshair"
        />
        {hover && (
          <div
            className="pointer-events-none absolute z-10 max-w-72 rounded-lg bg-surface p-2 text-[12px] shadow-pop ring-1 ring-line"
            style={{ left: Math.min(hover.x + 12, size.w - 290), top: hover.y + 12 }}
          >
            <div className="mb-1 font-mono text-[11px] text-muted">
              {hover.p.topic ?? `doc ${shortId(hover.p.document_id, 12)}`}
            </div>
            {hover.p.preview}
          </div>
        )}
      </div>
    </div>
  );
}
