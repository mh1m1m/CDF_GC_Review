import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Dashboard } from "./intelligence";
import { roleNames, sourceNames } from "./intelligence";
export default function IntelligenceGraph({
  data,
  kind,
  onSelect,
}: {
  data: Dashboard;
  kind: "debate" | "evidence";
  onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    if (kind === "debate") {
      const stages = [
        ...data.stages,
        ...(data.invocations.some((i) => i.stage === "EDITORIAL")
          ? ["EDITORIAL"]
          : []),
      ];
      stages.forEach((stage, index) => {
        const inv = data.invocations.filter((i) => i.stage === stage);
        nodes.push({
          id: stage,
          position: {
            x: (3 - (index % 4)) * 245,
            y: Math.floor(index / 4) * 160,
          },
          sourcePosition: Position.Left,
          targetPosition: Position.Right,
          data: {
            label: (
              <div className="agent-node">
                <span className="node-eyebrow">{stage}</span>
                <strong>{roleNames[stage] || stage}</strong>
                <span>
                  {inv.length ? `${inv.length} سجل تنفيذ` : "لم يُشغّل"}
                </span>
                <small>
                  {inv.length
                    ? [
                        ...new Set(
                          inv.map((i) => sourceNames[i.source] || i.source),
                        ),
                      ].join(" · ")
                    : "NOT_RUN"}
                </small>
              </div>
            ),
          },
          className: inv.some((i) => i.status !== "OK")
            ? "node-failed"
            : inv.length
              ? "node-complete"
              : "node-idle",
        });
      });
      const known = new Set(stages);
      const paths = new Set<string>();
      for (let i = 1; i < data.invocations.length; i++) {
        const a = data.invocations[i - 1].stage,
          b = data.invocations[i].stage;
        if (
          a !== b &&
          known.has(a) &&
          known.has(b) &&
          !paths.has(a + ">" + b)
        ) {
          paths.add(a + ">" + b);
          edges.push({
            id: a + ">" + b,
            source: a,
            target: b,
            type: "smoothstep",
            animated: false,
          });
        }
      }
    } else {
      data.observations.forEach((o, i) =>
        nodes.push({
          id: o.observation_id,
          position: { x: 600, y: i * 100 },
          data: { label: o.observation_id },
          sourcePosition: Position.Left,
        }),
      );
      data.evidence.slice(0, 40).forEach((e, i) =>
        nodes.push({
          id: e.id,
          position: { x: 80, y: i * 90 },
          data: {
            label: (
              <div>
                <strong>{e.id}</strong>
                <small className="graph-evidence-label">
                  {e.kind} · {e.approval_status}
                </small>
              </div>
            ),
          },
          targetPosition: Position.Right,
        }),
      );
      const ids = new Set(nodes.map((n) => n.id));
      data.evidence_links.forEach((link, i) => {
        if (ids.has(link.evidence_id) && ids.has(link.observation_id))
          edges.push({
            id: "e-" + i,
            source: link.observation_id,
            target: link.evidence_id,
          });
      });
    }
    return { nodes, edges };
  }, [data, kind]);
  return (
    <div
      className="graph-canvas"
      role="region"
      aria-label={
        kind === "debate"
          ? "الرسم التفاعلي لمسار النقاش"
          : "الرسم التفاعلي لسلسلة الأدلة"
      }
      dir="ltr"
    >
      <ReactFlow
        style={{ width: "100%", height: "100%" }}
        nodes={nodes}
        edges={edges}
        onNodeClick={(_, node) => onSelect(node.id)}
        fitView
        minZoom={0.2}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: false }}
      >
        <Background color="#d8dfe4" gap={22} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
