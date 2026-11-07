import { useEffect, useState } from "react";
import { MessageSquare, Play, RefreshCw, ShieldCheck } from "lucide-react";
import "../copilot.css";
type Step = {
  tool: string;
  status: string;
  job_id?: string;
  job_status?: string;
  current_job?: { status: string };
};
type Workflow = {
  workflow_id: string;
  case_id: string;
  status: string;
  version: number;
  pending_human: boolean;
  executor: string;
  steps: Step[];
};
type Review = {
  observation: {
    observation_id: string;
    original_text: string;
    material_categories: string[];
  };
  version: string;
};
const labels: Record<string, string> = {
  cdf_check_delegated_authority: "فحص الصلاحيات",
  cdf_get_department_responsibilities: "فحص المسؤوليات",
  cdf_review_document: "المراجعة الحوكمية",
  cdf_run_multi_agent_debate: "النقاش والمراجعة المستقلة",
  HUMAN_CHECKPOINT: "قرار المراجع البشري",
  cdf_generate_word_report: "تقرير Word",
  cdf_generate_excel_dashboard: "لوحة Excel",
  cdf_generate_pdf_report: "نسخة PDF",
};
const statuses: Record<string, string> = {
  PLANNED: "خطة محفوظة",
  WAITING_FOR_JOB: "بانتظار العمل الجاري",
  WAITING_FOR_HUMAN: "بانتظار قرار بشري",
  COMPLETED_DRAFT: "اكتملت مسودات العمل",
  FAILED: "تعذر التنفيذ",
  CANCELLED: "أُلغي",
  READY: "خطة جاهزة",
  BLOCKED: "طلب محجوب",
  UNSUPPORTED: "طلب غير مدعوم",
  HUMAN_INPUT_REQUIRED: "يتطلب قراراً بشرياً منظماً",
};
export default function GovernanceCopilot({
  caseId,
  token,
}: {
  caseId: string;
  token: string;
}) {
  const [text, setText] = useState("راجع الاتفاق وأعد تقرير Word وExcel"),
    [executor, setExecutor] = useState("deterministic"),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const [workflow, setWorkflow] = useState<Workflow | null>(null),
    [plan, setPlan] = useState<{
      status: string;
      steps: Step[];
      reason?: string;
    } | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]),
    [evidenceHash, setEvidenceHash] = useState(""),
    [index, setIndex] = useState(0),
    [action, setAction] = useState("ACCEPT"),
    [rationale, setRationale] = useState(""),
    [wording, setWording] = useState("");
  const [knowledge, setKnowledge] = useState<any>(null),
    [health, setHealth] = useState<any>(null),
    [busy, setBusy] = useState(false);
  async function api(op: string, body: object = {}) {
    const response = await fetch("/api/copilot/" + op, {
      method: "POST",
      headers: {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ case_id: caseId, ...body }),
    });
    const data = await response.json();
    if (!response.ok)
      throw Error(
        typeof data.detail === "string" ? data.detail : "تعذر تنفيذ الطلب",
      );
    return data.data;
  }
  async function load() {
    const [r, w] = await Promise.all([api("decisions"), api("status")]);
    setReviews(r.records);
    setEvidenceHash(r.evidence_hash);
    if (w.workflows.length) setWorkflow(w.workflows[0]);
  }
  useEffect(() => {
    void load().catch((e) => setError(String(e)));
  }, [caseId, token]);
  async function run(op: string, body: object = {}) {
    setBusy(true);
    setError("");
    try {
      const d = await api(op, body);
      if (d.workflow_id) setWorkflow(d);
      if (op === "plan") setPlan(d);
      if (op === "knowledge") setKnowledge(d);
      if (op === "health") setHealth(d);
      setMessage(statuses[d.status] || "قُرئت السجلات من الخدمة المشتركة");
      return d;
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const current = reviews[index];
  async function decide() {
    if (!current) return;
    const d = await run("decision", {
      observation_id: current.observation.observation_id,
      action,
      rationale,
      final_wording: wording,
      expected_version: current.version,
      expected_evidence_hash: evidenceHash,
      idempotency_key: crypto.randomUUID(),
    });
    if (d) {
      setMessage("حُفظ القرار بإصدار جديد؛ لا يمثل تصريح إصدار مؤسسي");
      await load();
    }
  }
  return (
    <section className="glass copilot" data-case-id={caseId}>
      <div className="panel-heading">
        <div>
          <small>GOVERNED CONVERSATIONAL OPERATIONS</small>
          <h2>المساعد الحوكمي</h2>
        </div>
        <MessageSquare />
      </div>
      <p>
        طلبات عربية وإنجليزية ضمن عمليات محددة. يستند الجواب إلى السجلات؛ لا
        ينشئ موافقة أو يحل محل قرار المراجع.
      </p>
      <label>
        طلب المراجعة
        <textarea
          aria-label="طلب المراجعة"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={4000}
        />
      </label>
      <label>
        مصدر التشغيل
        <select
          aria-label="مصدر تشغيل المساعد"
          value={executor}
          onChange={(e) => setExecutor(e.target.value)}
        >
          <option value="deterministic">قواعد حتمية · دون نموذج AI</option>
          <option value="mock">محاكاة معلنة · دون استدلال حقيقي</option>
          <option value="codex-cli">Codex · يتطلب إعداداً وتصريحاً</option>
          <option value="openai">OpenAI API · يتطلب إعداداً وتصريحاً</option>
          <option value="anthropic">
            Anthropic API · يتطلب إعداداً وتصريحاً
          </option>
        </select>
      </label>
      <div className="copilot-actions">
        <button
          disabled={busy}
          onClick={() => void run("plan", { text, executor })}
        >
          عرض الخطة
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void run("start", {
              text,
              executor,
              idempotency_key: crypto.randomUUID(),
            })
          }
        >
          <Play size={15} />
          بدء سير العمل
        </button>
        <button
          disabled={busy}
          onClick={() => void run("knowledge", { domain: "all", query: "" })}
        >
          الأدلة والصلاحيات
        </button>
        <button
          disabled={busy}
          onClick={() => void load().catch((e) => setError(String(e)))}
        >
          <RefreshCw size={15} />
          استعادة الحالة
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {plan && (
        <article className="copilot-plan">
          <h3>{statuses[plan.status] || plan.status}</h3>
          {plan.reason && <p>{plan.reason}</p>}
          <ol>
            {plan.steps?.map((s, i) => (
              <li key={i}>{labels[s.tool] || s.tool}</li>
            ))}
          </ol>
        </article>
      )}
      {workflow && (
        <article
          className="copilot-workflow"
          data-workflow-id={workflow.workflow_id}
          data-workflow-status={workflow.status}
          data-workflow-version={workflow.version}
        >
          <h3>{statuses[workflow.status] || workflow.status}</h3>
          <p>
            <bdi>{workflow.workflow_id}</bdi>
          </p>
          <p>
            الإصدار {workflow.version} ·{" "}
            {workflow.executor === "mock"
              ? "محاكاة معلنة"
              : workflow.executor === "deterministic"
                ? "قواعد حتمية"
                : workflow.executor}
          </p>
          <ol>
            {workflow.steps.map((s, i) => (
              <li key={i}>
                {labels[s.tool] || s.tool}
                <small>
                  {s.current_job?.status || s.job_status || s.status}
                </small>
              </li>
            ))}
          </ol>
          <div className="copilot-actions">
            <button
              disabled={busy}
              onClick={() =>
                void run("resume", {
                  workflow_id: workflow.workflow_id,
                  expected_version: String(workflow.version),
                  idempotency_key: crypto.randomUUID(),
                })
              }
            >
              متابعة سير العمل
            </button>
            {workflow.pending_human && (
              <button
                disabled={busy || !rationale.trim()}
                onClick={() =>
                  void run("resume", {
                    workflow_id: workflow.workflow_id,
                    expected_version: String(workflow.version),
                    confirm_human: true,
                    rationale,
                    idempotency_key: crypto.randomUUID(),
                  })
                }
              >
                تأكيد متابعة المسودات بعد القرار المسجل
              </button>
            )}
            <button
              disabled={
                busy ||
                workflow.status === "CANCELLED" ||
                workflow.status === "COMPLETED_DRAFT"
              }
              onClick={() =>
                void run("cancel", {
                  workflow_id: workflow.workflow_id,
                  expected_version: String(workflow.version),
                  idempotency_key: crypto.randomUUID(),
                })
              }
            >
              إلغاء سير العمل
            </button>
          </div>
        </article>
      )}
      {current && (
        <article
          className="copilot-review"
          data-human-version={current.version}
        >
          <h3>قرار المراجع</h3>
          <label>
            الملاحظة
            <select
              aria-label="ملاحظة القرار"
              value={index}
              onChange={(e) => setIndex(Number(e.target.value))}
            >
              {reviews.map((r, i) => (
                <option key={r.observation.observation_id} value={i}>
                  {r.observation.observation_id}
                </option>
              ))}
            </select>
          </label>
          <blockquote>{current.observation.original_text}</blockquote>
          <p>المادية: {current.observation.material_categories.join("، ")}</p>
          <label>
            الإجراء
            <select
              aria-label="إجراء القرار"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="ACCEPT">الإبقاء على الملاحظة</option>
              <option value="REVISE">تعديل الصياغة</option>
              <option value="MORE_EVIDENCE">إعادة لاستكمال الدليل</option>
              <option value="ESCALATE">تصعيد</option>
              <option value="DISSENT">تسجيل رأي مخالف</option>
              <option value="DEFER">تأجيل</option>
              <option value="REJECT">طلب سحب · يتطلب أدلة وضوابط إضافية</option>
            </select>
          </label>
          <label>
            المبرر
            <textarea
              aria-label="مبرر القرار"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              maxLength={4000}
            />
          </label>
          {action === "REVISE" && (
            <label>
              الصياغة المقترحة
              <textarea
                aria-label="الصياغة المقترحة"
                value={wording}
                onChange={(e) => setWording(e.target.value)}
                maxLength={8000}
              />
            </label>
          )}
          <button
            disabled={busy || !rationale.trim()}
            onClick={() => void decide()}
          >
            حفظ القرار البشري
          </button>
          <p>
            يحفظ الأصل وهوية الجلسة وإصدار القرار. لا يمثل توقيعاً مؤسسياً أو
            موافقة على الإصدار.
          </p>
        </article>
      )}
      {knowledge && (
        <article className="copilot-knowledge">
          <h3>إسناد مرجعي قابل للتتبع</h3>
          <p>مراجع افتراضية غير ملزمة؛ الاعتماد والسريان غير متحققين.</p>
          {knowledge.records?.map((k: any, i: number) => (
            <details key={i}>
              <summary>{k.record.business_activity || k.record.name}</summary>
              <p>
                {JSON.stringify(
                  k.record.responsibilities ||
                    k.record.approver ||
                    k.record.preparer,
                )}
              </p>
              <p>
                <bdi>
                  {k.citation.source_id} · {k.citation.version}
                </bdi>{" "}
                · ص. {k.citation.page}
              </p>
              <p>{k.limitation}</p>
            </details>
          ))}
        </article>
      )}
      <details className="copilot-health">
        <summary>الصحة التشغيلية للمسؤول</summary>
        <button onClick={() => void run("health")}>
          قراءة المقاييس التشغيلية
        </button>
        {health && (
          <>
            <p>
              <ShieldCheck size={16} /> التفعيل المؤسسي معطل · مقاييس من السجل
            </p>
            <dl>
              <dt>حالة قاعدة البيانات</dt>
              <dd>{health.database_integrity ? "سليمة" : "تحتاج فحصاً"}</dd>
              <dt>الأعمال</dt>
              <dd>{JSON.stringify(health.job_counts)}</dd>
              <dt>الاستدلال الحقيقي عبر API</dt>
              <dd>{health.provider_api_inference_count}</dd>
            </dl>
          </>
        )}
      </details>
    </section>
  );
}
