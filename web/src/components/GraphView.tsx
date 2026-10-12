import clsx from "clsx";
import cytoscape, { type Core, type ElementDefinition, type EventObject, type LayoutOptions } from "cytoscape";
import fcose from "cytoscape-fcose";
import { Maximize2, Minimize2, Scan } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { colorFor, LABEL_ORDER, LABEL_SIZES } from "../lib/colors";
import type { Graph, GraphNode } from "../types";
import { useDocDrawer } from "./DocumentDrawer";

cytoscape.use(fcose);

const FONT = "Inter Variable, ui-sans-serif, system-ui, sans-serif";
const STYLE: cytoscape.StylesheetJson = [
  {
    selector: "node",
    style: {
      "background-color": "data(color)",
      width: "data(size)",
      height: "data(size)",
      label: "data(caption)",
      "font-family": FONT,
      "font-size": 10,
      "font-weight": 500,
      color: "#334155",
      "text-valign": "bottom",
      "text-margin-y": 5,
      "text-wrap": "wrap",
      "text-max-width": "130px",
      "text-outline-color": "#ffffff",
      "text-outline-width": 2.5,
      "border-width": 2,
      "border-color": "#ffffff",
      "overlay-opacity": 0,
    },
  },
  { selector: "node.hl", style: { "border-color": "#0f1b2d", "border-width": 3, color: "#0f172a", "font-weight": 700 } },
  {
    selector: "edge",
    style: {
      width: 1.2,
      "line-color": "#cbd2dc",
      "target-arrow-color": "#cbd2dc",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.7,
      "curve-style": "bezier",
      "font-family": FONT,
      "font-size": 8.5,
      color: "#64748b",
      "text-rotation": "autorotate",
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.9,
      "text-background-padding": "1.5px",
      "overlay-opacity": 0,
    },
  },
  { selector: "edge.inferred", style: { "line-style": "dashed", "line-dash-pattern": [5, 4] } },
  { selector: "edge.labels", style: { label: "data(type)" } },
  { selector: "edge.active", style: { "line-color": "#64748b", "target-arrow-color": "#64748b", width: 1.8, label: "data(type)", color: "#334155" } },
  { selector: ".faded", style: { opacity: 0.12 } },
];

function layout(fixed: boolean): LayoutOptions {
  if (fixed) return { name: "preset", fit: true, padding: 30 };
  return {
    name: "fcose", quality: "proof", randomize: true, animate: false, fit: true, padding: 40,
    nodeDimensionsIncludeLabels: true, idealEdgeLength: () => 95, nodeRepulsion: () => 9000,
    edgeElasticity: () => 0.45, gravity: 0.3, numIter: 2500, packComponents: true,
  } as LayoutOptions;
}

function toElements(graph: Graph, highlight: Set<string>): ElementDefinition[] {
  const ids = new Set(graph.nodes.map((n) => n.id));
  return [
    ...graph.nodes.map((n) => ({
      group: "nodes" as const,
      data: { id: n.id, label: n.label, caption: n.caption, color: colorFor(n.label), size: LABEL_SIZES[n.label] ?? 20, ref: n },
      position: n.position ? { ...n.position } : undefined,
      classes: highlight.has(n.id) ? "hl" : "",
    })),
    ...graph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        group: "edges" as const,
        data: { id: `e:${e.id}`, source: e.source, target: e.target, type: e.type },
        classes: e.inferred ? "inferred" : "",
      })),
  ];
}

interface Hover {
  x: number;
  y: number;
  node: GraphNode;
}

export function GraphView({ graph, height = 560, highlightIds = [], legend = true }: {
  graph: Graph;
  height?: number;
  highlightIds?: string[];
  legend?: boolean;
}) {
  const { open: openDoc } = useDocDrawer();
  const wrapRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const fixed = graph.nodes.length > 0 && graph.nodes.every((n) => n.position);
  const highlightKey = highlightIds.join("\u0000");
  const highlight = useMemo(() => new Set(highlightKey ? highlightKey.split("\u0000") : []), [highlightKey]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const n of graph.nodes) c[n.label] = (c[n.label] ?? 0) + 1;
    return Object.entries(c).sort((a, b) => LABEL_ORDER.indexOf(a[0]) - LABEL_ORDER.indexOf(b[0]));
  }, [graph]);

  useEffect(() => {
    if (!boxRef.current) return;
    const cy = cytoscape({ container: boxRef.current, style: STYLE, minZoom: 0.2, maxZoom: 3, boxSelectionEnabled: false, autounselectify: true });
    cyRef.current = cy;
    cy.on("mouseover", "node", (e: EventObject) => {
      const n = e.target;
      cy.elements().not(n.closedNeighborhood()).addClass("faded");
      n.connectedEdges().addClass("active");
      const p = n.renderedPosition();
      setHover({ x: p.x, y: p.y - n.renderedHeight() / 2, node: n.data("ref") });
    });
    const clear = () => {
      cy.elements().removeClass("faded");
      cy.edges().removeClass("active");
      setHover(null);
    };
    cy.on("mouseout", "node", clear);
    cy.on("pan zoom drag", () => setHover(null));
    const box = boxRef.current;
    box.addEventListener("mouseleave", clear);       // pointer left the canvas while over a node
    return () => {
      box.removeEventListener("mouseleave", clear);
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const tap = (e: EventObject) => {
      const n: GraphNode = e.target.data("ref");
      if (n.label === "Document" && typeof n.properties.id === "string") openDoc(n.properties.id);
    };
    cy.on("tap", "node", tap);
    return () => {
      cy.off("tap", "node", tap);
    };
  }, [openDoc]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add(toElements(graph, highlight));
    cy.edges().toggleClass("labels", graph.nodes.length <= 50);
    cy.layout(layout(fixed)).run();
  }, [graph, highlight, fixed]);

  useEffect(() => {
    const onChange = () => {
      setFullscreen(document.fullscreenElement === wrapRef.current);
      setTimeout(() => {
        cyRef.current?.resize();
        cyRef.current?.fit(undefined, 40);
      }, 60);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const name = (n: GraphNode) => String(n.properties.name ?? n.properties.title ?? n.caption);
  const isDoc = (n: GraphNode) => n.label === "Document" && typeof n.properties.id === "string";

  return (
    <div ref={wrapRef} className={clsx("relative flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white", fullscreen && "rounded-none")}>
      {legend && counts.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-100 px-4 py-2.5 text-[12px] text-slate-600">
          {counts.map(([label, n]) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: colorFor(label) }} />
              {label}
              <span className="text-slate-400 tabular-nums">{n}</span>
            </span>
          ))}
          {graph.edges.some((e) => e.inferred) && (
            <span className="inline-flex items-center gap-1.5 text-slate-400">
              <svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#94a3b8" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
              inferred
            </span>
          )}
        </div>
      )}
      <div className="relative" style={{ height: fullscreen ? undefined : height, flex: fullscreen ? 1 : undefined }}>
        <div ref={boxRef} style={{ position: "absolute", inset: 0 }} />
        {graph.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-[13px] text-slate-400">Nothing to show.</div>
        )}
        <div className="absolute top-2.5 right-2.5 flex gap-1">
          <button type="button" title="Fit to view" aria-label="Fit to view" onClick={() => cyRef.current?.fit(undefined, 40)} className="rounded-md bg-white/90 p-1.5 text-slate-400 shadow-sm ring-1 ring-slate-200 hover:text-slate-700">
            <Scan className="size-4" />
          </button>
          <button
            type="button"
            title={fullscreen ? "Exit full screen" : "Full screen"}
            aria-label={fullscreen ? "Exit full screen" : "Full screen"}
            onClick={() => (document.fullscreenElement ? void document.exitFullscreen() : void wrapRef.current?.requestFullscreen())}
            className="rounded-md bg-white/90 p-1.5 text-slate-400 shadow-sm ring-1 ring-slate-200 hover:text-slate-700"
          >
            {fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </button>
        </div>
        {hover && (
          <div
            className="pointer-events-none absolute z-10 max-w-[280px] -translate-x-1/2 -translate-y-full rounded-lg bg-ink-900 px-3 py-2 text-[12px] leading-snug text-white shadow-lg"
            style={{ left: hover.x, top: hover.y - 8 }}
          >
            <div className="text-[10.5px] font-semibold tracking-wide text-slate-400 uppercase">{hover.node.labels.join(" · ")}</div>
            <div className="font-medium">{name(hover.node)}</div>
            {isDoc(hover.node) && <div className="mt-0.5 text-[11px] text-brand-200">Click to open the document</div>}
          </div>
        )}
      </div>
    </div>
  );
}
