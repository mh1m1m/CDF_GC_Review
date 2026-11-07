import { lazy, Suspense, useMemo, useState } from "react";
import { ArrowUpLeft } from "lucide-react";
import { AuthorityCard, DepartmentResponsibilityCard } from "./GovernanceCards";
import type {
  AuthorityCandidate,
  ResponsibilityCandidate,
} from "./GovernanceCards";
const ReferenceGraph = lazy(() => import("../ReferenceGraph"));
type Catalog = {
  synthetic: boolean;
  sources: Array<{
    id: string;
    url: string;
    version: string;
    approval_status: string;
  }>;
  authorities: Array<
    AuthorityCandidate & { category: string; source_id: string }
  >;
  units: Array<ResponsibilityCandidate & { source_id: string }>;
  graph: {
    nodes: Array<{ id: string; label: string; kind: string }>;
    edges: Array<{
      source: string;
      target: string;
      relation: string;
      page: number;
      approval_status: string;
    }>;
  };
};
export default function AuthorityExplorer({ data }: { data: Catalog | null }) {
  const [query, setQuery] = useState(""),
    [role, setRole] = useState(""),
    [source, setSource] = useState(""),
    [open, setOpen] = useState(false),
    [kind, setKind] = useState("ALL");
  const graph = useMemo(() => {
    if (!data) return null;
    if (kind === "ALL") return data.graph;
    const ids = new Set(
      data.graph.nodes
        .filter(
          (n) =>
            n.kind ===
            (kind === "AUTHORITY" ? "AUTHORITY_CANDIDATE" : "UNIT_CANDIDATE"),
        )
        .map((n) => n.id),
    );
    const edges = data.graph.edges.filter((e) => ids.has(e.target));
    edges.forEach((e) => ids.add(e.source));
    return { nodes: data.graph.nodes.filter((n) => ids.has(n.id)), edges };
  }, [data, kind]);
  return (
    <section className="glass reference-panel">
      <div className="panel-heading">
        <div>
          <small>REFERENCE INTELLIGENCE</small>
          <h2>الصلاحية لا تُستنتج من وجود الوثيقة.</h2>
        </div>
      </div>
      <p>
        {data?.synthetic
          ? "مراجع افتراضية مستقلة عن الملفات المؤسسية. مرشحات استخراج تدريبية لا تمثل صلاحيات الصندوق."
          : "مراجع مؤسسية مقيدة؛ مرشحات استخراج لا تُعامل كتفويض نافذ دون التحقق من الاعتماد والسريان."}
      </p>
      <label>
        البحث في الصلاحيات والمسؤوليات
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="موضوع، جهة، أو مهمة"
        />
      </label>
      <div className="reference-filters">
        <label>
          دور الجهة
          <select aria-label="دور الجهة" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">كل الأدوار</option>
            {[
              "الإعداد",
              "المراجعة",
              "التوصية",
              "الاعتماد",
              "التنفيذ",
              "الإخطار",
              "الإبلاغ",
              "الإحاطة",
            ].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          المصدر الداعم
          <select aria-label="المصدر الداعم" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">كل المصادر</option>
            {data?.sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="source-cards">
        {data?.sources.map((s) => (
          <article key={s.id}>
            <strong>{s.id}</strong>
            <span className="blocked-chip">{s.approval_status}</span>
            <small>الإصدار: {s.version} · السريان الحالي غير متحقق</small>
            <a href={s.url} target="_blank" rel="noreferrer">
              {data.synthetic ? "مرجع افتراضي" : "المصدر المسجل"}
              <ArrowUpLeft size={13} />
            </a>
          </article>
        ))}
      </div>
      <details
        className="reference-graph"
        onToggle={(e) => setOpen(e.currentTarget.open)}
      >
        <summary>خريطة العلاقات المصدرية — مرشحات لا تفويضات نافذة</summary>
        <label>
          نوع الخريطة
          <select aria-label="نوع الخريطة" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="ALL">كل العلاقات المصدرية</option>
            <option value="AUTHORITY">خريطة الصلاحيات</option>
            <option value="RESPONSIBILITY">خريطة المسؤوليات</option>
          </select>
        </label>
        {graph && open && (
          <Suspense fallback={<p>جارٍ تحميل الخريطة…</p>}>
            <ReferenceGraph graph={graph} />
          </Suspense>
        )}
      </details>
      <h3>مستكشف الصلاحيات</h3>
      <div className="reference-results">
        {data?.authorities
          .filter(
            (a) =>
              (!source || a.source_id === source) &&
              (!role || Object.values(a.roles).includes(role)) &&
              [
                a.title,
                a.category,
                ...Object.keys(a.roles),
                ...Object.values(a.roles),
              ]
                .join(" ")
                .includes(query),
          )
          .slice(0, 30)
          .map((a) => (
            <AuthorityCard key={a.id} item={a} />
          ))}
      </div>
      <h3>خريطة المسؤوليات المقترحة</h3>
      <div className="unit-grid">
        {data?.units
          .filter(
            (u) =>
              (!source || u.source_id === source) &&
              [u.name, u.sector, ...u.tasks, ...(u.internal_contacts || [])]
                .join(" ")
                .includes(query),
          )
          .slice(0, 30)
          .map((u) => (
            <DepartmentResponsibilityCard key={u.id} item={u} />
          ))}
      </div>
      <p>
        المسؤولية التنظيمية لا تمنح صلاحية اعتماد، وجهة الاتصال لا تثبت خط
        تبعية. التعارضات تحتاج تسوية بشرية.
      </p>
    </section>
  );
}
