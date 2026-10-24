import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Dashboard } from "./intelligence";
export default function ObjectionTree({
  data,
  onSelect,
}: {
  data: Dashboard;
  onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [],
      edges: Edge[] = [];
    data.objections.slice(0, 12).forEach((o, index) => {
      const base = index * 240;
      const root = "objection:" + o.id;
      nodes.push({
        id: root,
        position: { x: 850, y: base },
        sourcePosition: Position.Left,
        data: {
          label: (
            <div dir="rtl">
              <strong>{o.observation_id}</strong>
              <small>{o.id}</small>
              <p>اعتراض مسجل</p>
            </div>
          ),
        },
      });
      let previous = root;
      o.turns.slice(0, 12).forEach((t, i) => {
        const id = root + ":" + i;
        nodes.push({
          id,
          position: {
            x: 600 - (i % 3) * 245,
            y: base + 70 + Math.floor(i / 3) * 85,
          },
          targetPosition: Position.Right,
          sourcePosition: Position.Left,
          data: {
            label: (
              <div dir="rtl">
                <strong>
                  {t.actor} · {t.cycle}
                </strong>
                <p>{t.claim}</p>
                <small>{t.evidence_refs.length} مرجع</small>
              </div>
            ),
          },
        });
        edges.push({
          id: "link:" + id,
          source: previous,
          target: id,
          type: "smoothstep",
        });
        previous = id;
      });
      const final = root + ":disposition";
      nodes.push({
        id: final,
        position: { x: 110, y: base + 165 },
        data: {
          label: (
            <div dir="rtl">
              <strong>{o.disposition}</strong>
              <small>حسم مسجل؛ ليس اعتماداً بشرياً</small>
            </div>
          ),
        },
        targetPosition: Position.Right,
      });
      edges.push({
        id: final + ":edge",
        source: previous,
        target: final,
        type: "smoothstep",
      });
    });
    return { nodes, edges };
  }, [data]);
  return (
    <div className="graph-canvas objection-tree" dir="ltr">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        minZoom={0.15}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, n) => onSelect(n.id.split(":")[1] || n.id)}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
