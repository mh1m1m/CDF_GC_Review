import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw, Workflow } from "lucide-react";
import type { Metric } from "../intelligence";
type Job = {
  job_id: string;
  kind: string;
  executor: string;
  status: string;
  run_id: string | null;
  error_code: string | null;
};
type Artifact = {
  artifact_id: string;
  kind: string;
  sha256: string;
  bytes: number;
  filename: string;
  state_hash: string;
  download_path: string;
};
type Snapshot = {
  case_id: string;
  source_imported: boolean;
  source_hash: string;
  run_id?: string;
  phase: string;
  observation_ids: string[];
  observation_count?: number;
  evidence_references?: string[];
  calibration_version?: string;
  release_gate?: { authorized: boolean; reasons: string[] };
  metrics?: Metric[];
  state_hash?: string;
  jobs: Job[];
  artifacts: Artifact[];
  agent_status?: Array<{ stage: string; status: string; source: string }>;
};
const statuses: Record<string, string> = {
  QUEUED: "في الانتظار",
  RUNNING: "قيد التنفيذ",
  WAITING_FOR_HUMAN: "بانتظار المراجع",
  COMPLETED: "اكتمل التنفيذ",
  FAILED: "تعذر التنفيذ",
  CANCELLED: "أُلغي",
  BLOCKED_AUTHORIZATION: "التصريح غير متاح",
};
export default function ExecutionWorkspace({
  caseId,
  token,
  onPublished,
}: {
  caseId: string;
  token: string;
  onPublished: () => void;
}) {
  const [data, setData] = useState<Snapshot | null>(null),
    [error, setError] = useState(""),
    [executor, setExecutor] = useState("deterministic");
  const refresh = useCallback(async () => {
    const r = await fetch(
      `/api/cases/${encodeURIComponent(caseId)}/execution`,
      { headers: { Authorization: "Bearer " + token } },
    );
    if (!r.ok) throw Error(`تعذر قراءة السجل (${r.status})`);
    setData(await r.json());
  }, [caseId, token]);
  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
  }, [refresh]);
  const active = data?.jobs.some(
    (j) => j.status === "QUEUED" || j.status === "RUNNING",
  );
  useEffect(() => {
    if (!active) return;
    const id = setInterval(
      () => void refresh().catch((e) => setError(String(e))),
      1000,
    );
    return () => clearInterval(id);
  }, [active, refresh]);
  async function submit(tool: string) {
    setError("");
    try {
      const r = await fetch("/api/operations/" + tool, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          case_id: caseId,
          executor,
          idempotency_key: crypto.randomUUID(),
          timeout: 180,
        }),
      });
      if (!r.ok) throw Error(`تعذر تسجيل العملية (${r.status})`);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }
  async function download(a: Artifact) {
    const r = await fetch(a.download_path, {
      headers: { Authorization: "Bearer " + token },
    });
    if (!r.ok) {
      setError(`تعذر استرجاع الملف (${r.status})`);
      return;
    }
    const href = URL.createObjectURL(await r.blob());
    const link = document.createElement("a");
    link.href = href;
    link.download = a.filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }
  if (!data) return <p role="status">{error || "جارٍ قراءة سجل التنفيذ…"}</p>;
  return (
    <section
      className="glass execution-workspace"
      data-case-id={data.case_id}
      data-run-id={data.run_id || ""}
    >
      <div className="panel-heading">
        <div>
          <small>SHARED CASE EXECUTION</small>
          <h2>التنفيذ والملفات</h2>
        </div>
        <Workflow />
      </div>
      <p>نفس سجل القضية عبر الواجهات. حالة التنفيذ لا تمنح موافقة مؤسسية.</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="history-controls">
        <label>
          مصدر التنفيذ
          <select
            aria-label="مصدر التنفيذ"
            value={executor}
            onChange={(e) => setExecutor(e.target.value)}
          >
            <option value="deterministic">قواعد حتمية</option>
            <option value="mock">محاكاة معلنة</option>
            <option value="codex-cli">Codex CLI · يتطلب تهيئة</option>
            <option value="claude-cli">Claude CLI · يتطلب تهيئة</option>
            <option value="openai">OpenAI API · يتطلب تصريحاً</option>
            <option value="anthropic">Anthropic API · يتطلب تصريحاً</option>
          </select>
        </label>
        <button
          disabled={!data.source_imported || active}
          onClick={() => void submit("cdf_review_document")}
        >
          تشغيل المراجعة
        </button>
        <button
          disabled={!data.source_imported || active}
          onClick={() => void submit("cdf_run_multi_agent_debate")}
        >
          تشغيل النقاش
        </button>
        <button
          onClick={() =>
            void refresh()
              .then(onPublished)
              .catch((e) => setError(String(e)))
          }
        >
          <RefreshCw size={16} />
          تحديث الحالة المشتركة
        </button>
      </div>
      {!data.source_imported && (
        <p>
          لا يوجد مستند تشغيل مستورد لهذه القضية؛ تظل مخرجات المراجعة السابقة
          متاحة.
        </p>
      )}
      <div className="stats">
        <div>
          القضية <strong data-field="case-id">{data.case_id}</strong>
        </div>
        <div>
          الملاحظات{" "}
          <strong data-field="observation-count">
            {data.observation_ids.length}
          </strong>
        </div>
        <div>
          الإصدار{" "}
          <strong
            data-field="release-gate"
            data-gate={JSON.stringify(data.release_gate)}
          >
            {data.release_gate?.authorized
              ? "AUTHORIZED_AT_RECORDED_RUN"
              : "NOT_AUTHORIZED"}
          </strong>
        </div>
      </div>
      <dl className="execution-identifiers">
        <dt>التشغيل المسجل</dt>
        <dd data-field="run-id">
          <bdi>{data.run_id || "NOT_RUN"}</bdi>
        </dd>
        <dt>نسخة قرار المعايرة</dt>
        <dd data-field="calibration-version">
          <bdi>{data.calibration_version || "NOT_RECORDED"}</bdi>
        </dd>
        <dt>معرفات الملاحظات</dt>
        <dd data-field="observation-ids">
          <bdi>{data.observation_ids.join(", ")}</bdi>
        </dd>
        <dt>مراجع الأدلة</dt>
        <dd data-field="evidence-refs">
          <bdi>{data.evidence_references?.join(", ") || ""}</bdi>
        </dd>
      </dl>
      <h3>سجل الأعمال</h3>
      <div className="execution-job-list">
        {data.jobs.map((j) => (
          <article key={j.job_id} data-job-id={j.job_id}>
            <strong>
              {j.kind} · {statuses[j.status] || j.status}
            </strong>
            <span>{j.executor}</span>
            <small>
              <bdi>{j.job_id}</bdi>
            </small>
            {j.error_code && <p>{j.error_code}</p>}
          </article>
        ))}
      </div>
      <h3>ملفات المراجعة المحفوظة</h3>
      <p>نسخ عمل قابلة للتحقق؛ لا يُسمح بإصدارها مؤسسياً.</p>
      <div className="execution-artifacts">
        {data.artifacts.map((a) => (
          <article key={a.artifact_id} data-artifact-id={a.artifact_id}>
            <strong>
              {a.kind.toUpperCase()} ·{" "}
              {a.state_hash === data.state_hash
                ? "مطابق للحالة الحالية"
                : "لقطة سابقة"}
            </strong>
            <small>
              <bdi>{a.artifact_id}</bdi> · {a.bytes} bytes
            </small>
            <button onClick={() => void download(a)}>
              <Download size={15} />
              استرجاع نسخة العمل
            </button>
          </article>
        ))}
      </div>
      <details className="consistency-proof">
        <summary>مقارنة المقاييس ومصادر التنفيذ</summary>
        <table>
          <thead>
            <tr>
              <th>المؤشر</th>
              <th>البسط</th>
              <th>المقام</th>
            </tr>
          </thead>
          <tbody>
            {data.metrics?.map((m) => (
              <tr
                key={m.id}
                data-metric-id={m.id}
                data-numerator={m.numerator ?? "null"}
                data-denominator={m.denominator ?? "null"}
              >
                <th>{m.title}</th>
                <td>{m.numerator ?? "غير مقاس"}</td>
                <td>{m.denominator ?? "غير مقاس"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ol>
          {data.agent_status?.map((a, i) => (
            <li
              key={i}
              data-stage={a.stage}
              data-status={a.status}
              data-source={a.source}
            >
              {a.stage} · {a.status} · {a.source}
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}
