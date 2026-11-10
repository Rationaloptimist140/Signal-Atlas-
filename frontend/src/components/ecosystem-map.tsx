"use client";

import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { CATEGORY_COLORS, cn, formatCompact } from "@/lib/utils";

export type GraphNode = { id: string; type: "repository" | "technology" | "company" | "developer" | "dependency"; label: string; ref_id?: number; stars?: number; category?: string | null };
export type GraphEdge = { source: string; target: string; type: string };

const KIND_STYLE: Record<GraphNode["type"], { ring: string; dot: string; name: string }> = {
  repository: { ring: "border-primary/50 bg-card", dot: "#8B5CF6", name: "Repository" },
  technology: { ring: "border-accent/50 bg-accent-soft", dot: "#22D3EE", name: "Technology" },
  company: { ring: "border-success/40 bg-success-soft", dot: "#10B981", name: "Organisation" },
  developer: { ring: "border-warning/40 bg-warning-soft", dot: "#F59E0B", name: "Developer" },
  dependency: { ring: "border-line-strong bg-surface", dot: "#94A3B8", name: "Dependency" },
};

type AtlasData = { kind: GraphNode["type"]; label: string; stars?: number; category?: string | null };

function AtlasNode({ data }: NodeProps<Node<AtlasData>>) {
  const style = KIND_STYLE[data.kind];
  return (
    <div className={cn("max-w-[170px] rounded-lg border px-2.5 py-1.5 text-[12px] leading-tight text-ink shadow-card", style.ring)} title={`${style.name}: ${data.label}`}>
      <Handle type="target" position={Position.Top} className="!h-1 !w-1 !border-0 !bg-transparent" />
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: data.kind === "repository" ? CATEGORY_COLORS[data.category ?? ""] ?? style.dot : style.dot }} />
        <span className="truncate font-medium">{data.label}</span>
      </div>
      {data.kind === "repository" && data.stars !== undefined && <div className="num mt-0.5 pl-3 text-[10px] text-ink-faint">★ {formatCompact(data.stars)}</div>}
      <Handle type="source" position={Position.Bottom} className="!h-1 !w-1 !border-0 !bg-transparent" />
    </div>
  );
}

const nodeTypes = { atlas: AtlasNode };

/** Deterministic concentric layout: technologies at the centre, repositories around them, everything else on the rim. */
export function layoutGraph(nodes: GraphNode[]): Record<string, { x: number; y: number }> {
  const rings: Record<string, GraphNode[]> = { technology: [], repository: [], outer: [] };
  for (const node of nodes) (rings[node.type] ?? rings.outer).push(node);
  rings.repository.sort((a, b) => (a.category ?? "").localeCompare(b.category ?? "") || a.label.localeCompare(b.label));
  rings.outer.sort((a, b) => a.type.localeCompare(b.type) || a.label.localeCompare(b.label));
  const positions: Record<string, { x: number; y: number }> = {};
  const place = (items: GraphNode[], radiusX: number, radiusY: number, offset: number) => {
    items.forEach((node, index) => {
      const angle = offset + (2 * Math.PI * index) / Math.max(items.length, 1);
      positions[node.id] = { x: Math.round(Math.cos(angle) * radiusX), y: Math.round(Math.sin(angle) * radiusY) };
    });
  };
  place(rings.technology, 210, 120, 0);
  place(rings.repository, 470, 270, 0.2);
  place(rings.outer, 720, 410, 0.1);
  return positions;
}

const EDGE_COLORS: Record<string, string> = {
  uses_technology: "rgba(34,211,238,0.35)", maintains: "rgba(16,185,129,0.4)", contributes: "rgba(245,158,11,0.4)", depends_on: "rgba(148,163,184,0.3)", fork: "rgba(139,92,246,0.6)",
};

export function EcosystemMap({ nodes, edges, height = 520 }: { nodes: GraphNode[]; edges: GraphEdge[]; height?: number }) {
  const router = useRouter();
  const { flowNodes, flowEdges } = useMemo(() => {
    const positions = layoutGraph(nodes);
    return {
      flowNodes: nodes.map<Node<AtlasData>>((n) => ({ id: n.id, type: "atlas", position: positions[n.id], data: { kind: n.type, label: n.label, stars: n.stars, category: n.category } })),
      flowEdges: edges.map<Edge>((e, i) => ({ id: `e${i}`, source: e.source, target: e.target, style: { stroke: EDGE_COLORS[e.type] ?? "rgba(148,163,184,0.3)", strokeWidth: 1 }, animated: e.type === "fork" })),
    };
  }, [nodes, edges]);
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);

  return (
    <div style={{ height }} className="relative">
      <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView minZoom={0.2} maxZoom={2} nodesConnectable={false} proOptions={{ hideAttribution: true }}
        onNodeClick={(_event, node) => {
          const source = byId[node.id];
          if (source?.type === "repository" && source.ref_id) router.push(`/repositories/${source.ref_id}`);
          if (source?.type === "developer" && source.ref_id) router.push(`/developers/${source.ref_id}`);
        }}>
        <Background gap={28} size={1} color="rgba(148,163,184,0.12)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      <ul className="pointer-events-none absolute left-4 top-4 flex flex-wrap gap-x-3 gap-y-1 rounded-lg border border-line bg-bg/80 px-3 py-2 text-2xs text-ink-muted backdrop-blur">
        {(Object.keys(KIND_STYLE) as GraphNode["type"][]).map((kind) => (
          <li key={kind} className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: KIND_STYLE[kind].dot }} />{KIND_STYLE[kind].name}</li>
        ))}
      </ul>
    </div>
  );
}
