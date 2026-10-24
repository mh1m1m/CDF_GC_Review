import type { Dashboard, Invocation, Evidence } from "../intelligence";
import { roleNames, sourceNames } from "../intelligence";
export type AuthorityCandidate = {
  id: string;
  title: string;
  page: number;
  source_id?: string;
  roles: Record<string, string>;
  qualifiers: Record<string, string>;
  threshold: string;
};
export type ResponsibilityCandidate = {
  id: string;
  name: string;
  sector: string;
  page: number;
  tasks: string[];
  internal_contacts?: string[];
  external_contacts?: string[];
};
export function AgentDebateNode({
  stage,
  invocations,
}: {
  stage: string;
  invocations: Invocation[];
}) {
  return (
    <div className="agent-node">
      <span className="node-eyebrow">{stage}</span>
      <strong>{roleNames[stage] || stage}</strong>
      <span>
        {invocations.length ? `${invocations.length} سجل تنفيذ` : "لم يُشغّل"}
      </span>
      <small>
        {invocations.length
          ? [
              ...new Set(
                invocations.map((i) => sourceNames[i.source] || i.source),
              ),
            ].join(" · ")
          : "NOT_RUN"}
      </small>
    </div>
  );
}
export function AuthorityCard({ item }: { item: AuthorityCandidate }) {
  return (
    <details className="authority-card">
      <summary>
        <bdi>{item.id}</bdi> · {item.title}
        <small>ص. {item.page} · مصدر مرشح؛ السريان غير متحقق</small>
      </summary>
      <dl>
        {Object.entries(item.roles).map(([body, role]) => (
          <div key={body}>
            <dt>{body}</dt>
            <dd>
              {role}
              {item.qualifiers[body] ? " · " + item.qualifiers[body] : ""}
            </dd>
          </div>
        ))}
      </dl>
      <p>الحدود والشروط: {item.threshold} — لا تعيينات مفترضة.</p>
    </details>
  );
}
export function DepartmentResponsibilityCard({
  item,
}: {
  item: ResponsibilityCandidate;
}) {
  return (
    <details className="responsibility-card">
      <summary>
        {item.name}
        <small>
          {item.sector} · ص. {item.page} · مسؤوليات موثقة في المصدر فقط
        </small>
      </summary>
      <ul>
        {item.tasks.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
      <p>جهات الاتصال لا تثبت علاقة تبعية.</p>
      {item.internal_contacts?.length ? (
        <p>واجهات داخلية: {item.internal_contacts.join("، ")}</p>
      ) : null}
    </details>
  );
}
export function EvidenceProvenanceCard({ item }: { item: Evidence }) {
  return (
    <article className="evidence-provenance-card">
      <strong>{item.id}</strong>
      <p>{item.excerpt}</p>
      <dl>
        <dt>نوع المصدر</dt>
        <dd>{item.kind}</dd>
        <dt>الموضع</dt>
        <dd>{item.page_or_paragraph}</dd>
        <dt>حالة الاعتماد</dt>
        <dd>{item.approval_status}</dd>
        <dt>قابلية التطبيق</dt>
        <dd>{item.applicability}</dd>
      </dl>
    </article>
  );
}
export function ReleaseGateStatus({
  gate,
}: {
  gate: Dashboard["release_gate"];
}) {
  return (
    <div className="release-gate-status">
      <strong className="blocked-chip">الإصدار محجوب</strong>
      <p>فحص مسجل؛ يلزم التحقق عند الإصدار. لا يعوضه متوسط مقاييس إيجابي.</p>
      <ul>
        {gate.reasons.map((r) => (
          <li key={r}>
            <bdi>{r}</bdi>
          </li>
        ))}
      </ul>
    </div>
  );
}
export function DecisionTimeline({
  events,
}: {
  events: Dashboard["timeline"];
}) {
  return (
    <ol className="decision-timeline">
      {events.map((e) => (
        <li key={e.id}>
          <strong>{e.kind}</strong>
          <small>
            <bdi>{e.at}</bdi>
          </small>
          {e.observation_id && <span>{e.observation_id}</span>}
        </li>
      ))}
    </ol>
  );
}
