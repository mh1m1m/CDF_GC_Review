import { useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
type Graph = {
  nodes: Array<{ id: string; label: string; kind: string }>;
  edges: Array<{
    source: string;
    target: string;
    relation: string;
    page: number;
    approval_status: string;
  }>;
};
export default function ReferenceGraph({ graph }: { graph: Graph }) {
  const [query, setQuery] = useState(""),
    [selected, setSelected] = useState("");
  const { nodes, edges } = useMemo(() => {
    const results = graph.nodes
      .filter((n) => n.label.includes(query))
      .slice(0, 25);
    const ids = new Set(results.map((n) => n.id));
    const related = graph.edges
      .filter((e) => ids.has(e.target) || ids.has(e.source))
      .slice(0, 45);
    related.forEach((e) => {
      ids.add(e.source);
      ids.add(e.target);
    });
    const chosen = graph.nodes.filter((n) => ids.has(n.id)).slice(0, 65);
    const shown = new Set(chosen.map((n) => n.id));
    const nodes: Node[] = chosen.map((n, i) => ({
      id: n.id,
      position: { x: (i % 4) * 250, y: Math.floor(i / 4) * 100 },
      sourcePosition: Position.Left,
      targetPosition: Position.Right,
      data: {
        label: (
          <div>
            {n.label}
            <small className="graph-evidence-label">{n.kind}</small>
          </div>
        ),
      },
    }));
    const edges: Edge[] = related
      .filter((e) => shown.has(e.source) && shown.has(e.target))
      .map((e, i) => ({
        id: "reference-" + i,
        source: e.source,
        target: e.target,
        label: e.relation,
        type: "smoothstep",
      }));
    return { nodes, edges };
  }, [graph, query]);
  return (
    <div>
      <label>
        تصفية الخريطة المصدرية
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="اسم الجهة أو الوظيفة"
        />
      </label>
      <p>
        عرض محدود إلى ٦٥ عقدة؛ العلاقات موثقة كمحتوى مستخرج، وليست إقراراً بصحة
        التفويض أو سريانه.
      </p>
      <div className="graph-canvas" dir="ltr">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodeClick={(_, n) => setSelected(n.id)}
          nodesConnectable={false}
          nodesDraggable={false}
          fitView
          minZoom={0.1}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {selected && (
        <ul>
          {graph.edges
            .filter((e) => e.source === selected || e.target === selected)
            .map((e, i) => (
              <li key={i}>
                {e.relation} · ص. {e.page} · {e.approval_status}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
