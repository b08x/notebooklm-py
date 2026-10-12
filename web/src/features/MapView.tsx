import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useFacets, useMap } from "@/lib/queries";
import type { MapPoint } from "@/lib/types";
import { cn, documentLabel, fmt } from "@/lib/utils";
import { actions, useApp } from "@/state/store";

const PALETTE = ["#a78bfa", "#7dd3fc", "#86efac", "#fcd34d", "#f0abfc", "#5eead4", "#fca5a5", "#93c5fd", "#fdba74", "#c4b5fd"];

function colorFor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

interface View {
  k: number;
  x: number;
  y: number;
}

const IDENT: View = { k: 1, x: 0, y: 0 };
const K_MIN = 0.5;
const K_MAX = 40;
const LEGEND_MAX = 12;

/** 2D projection of chunk embeddings; color by topic (or document); click opens the chunk. */
export function MapView() {
  const filters = useApp((s) => s.filters);
  const detailId = useApp((s) => s.detailId);
  const q = useMap(filters);
  const facets = useFacets(filters);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const lastDragMoved = useRef(false);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const [view, setView] = useState<View>(IDENT);
  const [iso, setIso] = useState<string | null>(null);
  const [hover, setHover] = useState<{ p: MapPoint; x: number; y: number } | null>(null);
  const points = useMemo(() => q.data?.points ?? [], [q.data]);
  const colorBy = q.data?.color_by ?? "document";
  const method = q.data?.method ?? "pca";

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

  const keyOf = (p: MapPoint): string => (colorBy === "topic" ? (p.topic ?? "—") : p.document_id);
  const sxOf = (p: MapPoint): number => (scale ? view.k * scale.tx(p.x) + view.x : 0);
  const syOf = (p: MapPoint): number => (scale ? view.k * scale.ty(p.y) + view.y : 0);

  const groups = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of points) {
      const key = keyOf(p);
      m.set(key, (m.get(key) ?? 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyOf depends on colorBy and points only
  }, [points, colorBy]);

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
    if (!c || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size.w * dpr;
    c.height = size.h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    if (!scale || points.length === 0) return;
    const r = 2.4 * Math.sqrt(view.k);
    for (const p of points) {
      ctx.globalAlpha = iso && keyOf(p) !== iso ? 0.08 : 0.8;
      ctx.fillStyle = colorFor(keyOf(p));
      ctx.beginPath();
      ctx.arc(sxOf(p), syOf(p), r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    const sel = points.find((p) => p.external_id === detailId);
    if (sel) {
      ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--fg") || "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(sxOf(sel), syOf(sel), r + 4, 0, Math.PI * 2);
      ctx.stroke();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- transform helpers close over scale/view/iso
  }, [points, scale, size, colorBy, detailId, view, iso]);

  const nearest = (mx: number, my: number): MapPoint | null => {
    if (!scale) return null;
    let best: MapPoint | null = null;
    let bestD = 64;
    for (const p of points) {
      const dx = sxOf(p) - mx;
      const dy = syOf(p) - my;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  };

  const zoomAt = (mx: number, my: number, deltaY: number): void => {
    setView((v) => {
      const k = Math.min(K_MAX, Math.max(K_MIN, v.k * Math.exp(-deltaY * 0.0015)));
      const scaleChange = k / v.k;
      return { k, x: mx - (mx - v.x) * scaleChange, y: my - (my - v.y) * scaleChange };
    });
  };

  const docTitles = facets.data?.labels?.document;
  const shown = groups.slice(0, LEGEND_MAX);
  const rest = groups.length - shown.length;
  const isDefault = view.k === 1 && view.x === 0 && view.y === 0 && !iso;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5 text-[12px] text-muted">
        <span className="tabular">{q.isLoading ? "Projecting embeddings…" : `${fmt.format(points.length)} chunks`}</span>
        <span className="truncate">
          {method.toUpperCase()} projection of chunk embeddings · 1 point = 1 chunk · color = {colorBy} · nearby points are semantically similar
        </span>
        <span className="ml-auto shrink-0">scroll to zoom · drag to pan · click a point to open</span>
        {!isDefault && (
          <Button variant="ghost" size="sm" onClick={() => { setView(IDENT); setIso(null); }} data-testid="map-reset">
            Reset view
          </Button>
        )}
      </div>
      <div
        ref={wrap}
        className="relative min-h-0 min-w-0 flex-1 overflow-hidden"
        data-testid="map"
        data-k={view.k.toFixed(2)}
        onWheel={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY);
        }}
      >
        <canvas
          ref={canvas}
          style={{ width: size.w, height: size.h, position: "absolute", inset: 0 }}
          aria-label={`Embedding map of ${points.length} chunks`}
          role="img"
          onPointerDown={(e) => {
            drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
            e.currentTarget.setPointerCapture?.(e.pointerId);
          }}
          onPointerMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const d = drag.current;
            if (d) {
              if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) > 3) d.moved = true;
              if (d.moved) setView((v) => ({ ...v, x: d.vx + (e.clientX - d.x), y: d.vy + (e.clientY - d.y) }));
              return;
            }
            const p = nearest(e.clientX - r.left, e.clientY - r.top);
            setHover(p ? { p, x: e.clientX - r.left, y: e.clientY - r.top } : null);
          }}
          onPointerUp={() => {
            lastDragMoved.current = drag.current?.moved ?? false;
            drag.current = null;
          }}
          onPointerLeave={() => setHover(null)}
          onClick={(e) => {
            if (lastDragMoved.current) {
              lastDragMoved.current = false;
              return;
            }
            const r = e.currentTarget.getBoundingClientRect();
            const p = nearest(e.clientX - r.left, e.clientY - r.top);
            if (p) actions.open(p.external_id);
          }}
          className={cn("touch-none", drag.current ? "cursor-grabbing" : "cursor-crosshair")}
        />
        {groups.length > 0 && (
          <div
            className="absolute top-2 right-2 z-10 max-h-64 overflow-auto rounded-xl bg-surface/90 p-1.5 text-[11.5px] shadow-pop ring-1 ring-line backdrop-blur"
            data-testid="map-legend"
          >
            {shown.map(([key, n]) => (
              <button
                key={key}
                type="button"
                aria-pressed={iso === key}
                data-testid={`legend-${key}`}
                onClick={() => setIso(iso === key ? null : key)}
                className={cn(
                  "flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 transition-[background-color,opacity] duration-150 hover:bg-surface-2/60",
                  iso && iso !== key && "opacity-40",
                  iso === key && "bg-surface-2 text-fg",
                )}
              >
                <i className="size-2 shrink-0 rounded-full" style={{ background: colorFor(key) }} />
                <span className="max-w-40 truncate" title={colorBy === "topic" ? key : documentLabel(key, docTitles)}>
                  {colorBy === "topic" ? key : documentLabel(key, docTitles)}
                </span>
                <span className="ml-auto pl-1.5 text-muted tabular">{n}</span>
              </button>
            ))}
            {rest > 0 && (
              <p className="px-1.5 py-0.5 text-muted" data-testid="map-legend-more">
                +{rest} more
              </p>
            )}
          </div>
        )}
        {hover && (
          <div
            className="pointer-events-none absolute z-10 max-w-72 rounded-lg bg-surface p-2 text-[12px] shadow-pop ring-1 ring-line"
            style={{ left: Math.min(hover.x + 12, size.w - 290), top: hover.y + 12 }}
            data-testid="map-tooltip"
          >
            <div className="mb-1 font-mono text-[11px] text-muted">
              {hover.p.topic ? `${hover.p.topic} · ` : ""}
              {documentLabel(hover.p.document_id, docTitles)}
            </div>
            {hover.p.preview}
          </div>
        )}
        {!q.isLoading && points.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6 text-[13px] text-muted" data-testid="map-empty">
            No chunks match these filters.
          </div>
        )}
      </div>
    </div>
  );
}
