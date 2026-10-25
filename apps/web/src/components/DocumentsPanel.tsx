// Uploaded Word/Excel/PDF documents (shown only when the API reports document_uploads = PUBLIC).
// "Review" queues the AI review run by the review worker; the other tools are the deterministic engine.
import { useEffect, useRef, useState } from "react";
import { Download, FileSpreadsheet, FileText, LayoutDashboard, Sparkles, Trash2, Upload } from "lucide-react";

type Summary = {
  package?: { safe: boolean; parts: number };
  review_workbook?: boolean;
  reason?: string;
  document?: string;
  rounds?: number[];
  observations?: number;
  paragraphs?: number;
  words?: number;
  comments?: number;
  review_comments?: number;
  tracked_changes?: number;
  pages?: number;
  text_layer?: boolean | null;
};
type Review = {
  review_id: string;
  document_id: string;
  status: "QUEUED" | "RUNNING" | "DONE" | "FAILED";
  stage: string;
  error: string | null;
  case_id: string | null;
  detail: {
    drafting_window?: string;
    observations?: number;
    proposals?: number;
    adopted?: number;
    outcome?: string;
    executor?: string;
    live_calls?: number;
    outputs?: Array<{ document_id: string; filename: string; kind: string }>;
  };
};
type Doc = {
  document_id: string;
  filename: string;
  kind: "docx" | "xlsx" | "pdf";
  size: number;
  created_at: string;
  derived_from: string | null;
  action: string | null;
  summary: Summary;
};
type Gate = { gate: string; name: string; status: string; actual: string };
type ActionResult = {
  action: string;
  result: Record<string, unknown> & { ok?: boolean; counts?: Record<string, number>; gates?: Gate[] };
  output: Doc | null;
};

const institutional = import.meta.env.VITE_SITE_IDENTITY === "CDF";
const ACTION_NAMES: Record<string, string> = {
  qa: "فحوص الجودة",
  word_report: "تقرير Word",
  excel_rebuild: "إعادة بناء Excel",
  comment: "إدراج ملاحظات المراجعة في المستند",
  compare: "مقارنة النسخة المعادة",
  review: "المراجعة",
};
const STAGES: Record<string, string> = {
  QUEUED: "في انتظار خدمة المعالجة",
  READING: "قراءة المستند",
  DRAFTING: "وكيل الصياغة يقترح الملاحظات",
  CHALLENGING: "الفريق الأسود والمحامي والمحكّم يراجعون الملاحظات",
  RECORDING_CASE: "تسجيل القضية ولوحة المتابعة",
  WRITING_OUTPUTS: "إعداد ملفات Word وPDF وExcel",
};
const REVIEW_ERRORS: Record<string, string> = {
  ProviderFailure: "تعذر الاتصال بنموذج الذكاء الاصطناعي. تحقق من إضافة مفتاح ANTHROPIC_API_KEY في إعدادات الخدمة.",
  WEBSITE_TIME_LIMIT: "المستند أطول من أن يُراجع داخل الموقع خلال خمس دقائق؛ المستندات الطويلة تحتاج خدمة المعالجة المنفصلة.",
  DataHandlingViolation: "لم يُفعَّل إذن إرسال المستندات إلى نموذج الذكاء الاصطناعي في خدمة المعالجة.",
  NO_TEXT_FOUND_SCANNED_PDF_NEEDS_OCR: "ملف PDF ممسوح ضوئياً بلا طبقة نص؛ ارفع ملفاً يحتوي نصاً قابلاً للنسخ.",
  NO_TEXT_FOUND: "لم يُعثر على نص في المستند.",
  DRAFTING_FAILED: "تعذر على وكيل الصياغة إكمال القراءة.",
  WORKER_STOPPED_DURING_REVIEW: "توقفت خدمة المعالجة أثناء المراجعة مرتين؛ أعد المحاولة.",
};
const ERRORS: Record<string, string> = {
  ONLY_DOCX_XLSX_OR_PDF_ACCEPTED: "يُقبل ملف Word (.docx) أو Excel (.xlsx) أو PDF فقط.",
  NOT_A_VALID_PDF_FILE: "الملف ليس PDF سليماً.",
  REVIEW_ALREADY_RUNNING: "توجد مراجعة قيد التنفيذ لهذا المستند.",
  REVIEW_TRACKER_USE_NEXT_ROUND_TOOLS: "هذا سجل مراجعة؛ استخدم أدوات السجل بدلاً من مراجعة جديدة.",
  GENERATED_FILES_ARE_NOT_REVIEWED: "هذا ملف ناتج عن مراجعة سابقة.",
  PDF_IS_REVIEWED_WITH_THE_REVIEW_BUTTON: "يُراجع ملف PDF بزر «مراجعة المستند».",
  FILE_TOO_LARGE_MAX_4_MB: "حجم الملف أكبر من 4 ميغابايت.",
  EMPTY_FILE: "الملف فارغ.",
  UNSAFE_FILE_REFUSED: "رُفض الملف في فحص السلامة (ماكرو، روابط خارجية، أو بنية غير سليمة).",
  REVIEW_WORKBOOK_REQUIRED: "هذه الأداة تحتاج سجل مراجعة Excel صادراً عن المنظومة.",
  WORD_DOCUMENT_AND_REVIEW_WORKBOOK_REQUIRED: "اختر مستند Word وسجل مراجعة Excel.",
  TWO_WORD_DOCUMENTS_REQUIRED: "المقارنة تحتاج مستندَي Word.",
  SECOND_DOCUMENT_REQUIRED: "اختر الملف الثاني أولاً.",
  SIGN_IN_REQUIRED: "سجّل الدخول أولاً.",
  HOSTED_REVIEWER_NOT_LISTED: "هذا الحساب غير مدرج ضمن المراجعين.",
};

const LABELS: Record<string, string> = {
  ok: "سليم",
  observations: "الملاحظات",
  word_matches_workbook: "Word مطابق للسجل",
  round: "الجولة",
  anchored: "ملاحظات أُدرجت",
  unanchored: "لم يُعثر على موضعها",
  new_comments: "تعليقات جديدة",
  replies_added: "ردود متابعة",
  roots_found: "تعليقات أصلية موجودة",
  roots_missing: "تعليقات أصلية مفقودة",
  skipped: "موجودة مسبقاً",
  parts_preserved: "أجزاء لم تُمس",
  parts_changed: "أجزاء عُدّلت",
  warnings: "تنبيهات",
  tracked_changes: "تغييرات متتبَّعة",
  tracked_insertions: "إضافات متتبَّعة",
  tracked_deletions: "حذوفات متتبَّعة",
  paragraph_changes: "فقرات تغيّرت",
  silent_edits: "تعديلات غير متتبَّعة",
  missing_gco_comments: "ملاحظات مراجعة حُذفت",
  altered_gco_comments: "ملاحظات مراجعة عُدّلت",
  anchor_issues: "مواضع تغيّرت",
  owner_comments: "تعليقات الجهة",
  clean: "لا تغييرات غير مبررة",
};
const HIDDEN = new Set(["gates", "counts", "detail", "unanchored_detail", "warnings_detail", "note", "summary", "workbook", "delivered", "returned"]);
const show = (v: unknown) => (typeof v === "boolean" ? (v ? "نعم" : "لا") : Array.isArray(v) ? String(v.length) : String(v));

function explain(raw: string): string {
  for (const [code, text] of Object.entries(ERRORS)) if (raw.includes(code)) return text;
  return raw;
}
const size = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} ك.ب` : `${(n / 1048576).toFixed(1)} م.ب`);

function describe(d: Doc): string {
  const s = d.summary;
  if (d.kind === "pdf")
    return s.text_layer === false
      ? `PDF · ${s.pages} صفحة · لا توجد طبقة نص (ممسوح ضوئياً)`
      : `PDF · ${s.pages} صفحة · ${s.paragraphs ?? "؟"} فقرة · ${s.words ?? "؟"} كلمة`;
  if (d.kind === "xlsx")
    return s.review_workbook
      ? `سجل مراجعة · ${s.observations} ملاحظة · الجولات ${(s.rounds ?? []).join("، ")}`
      : "ملف Excel (ليس سجل مراجعة من المنظومة)";
  return `${s.paragraphs} فقرة · ${s.words} كلمة · ${s.comments} تعليق (${s.review_comments} من المراجعة) · ${s.tracked_changes} تغيير متتبَّع`;
}

function reviewable(d: Doc): boolean {
  return !d.action && (d.kind !== "xlsx" || !d.summary.review_workbook) && d.summary.text_layer !== false;
}

export default function DocumentsPanel({ token, onOpenCase }: { token: string; onOpenCase?: (caseId: string) => void }) {
  const [docs, setDocs] = useState<Doc[]>([]),
    [file, setFile] = useState<File | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [result, setResult] = useState<ActionResult | null>(null),
    [partner, setPartner] = useState<Record<string, string>>({}),
    [inputKey, setInputKey] = useState(0),
    [reviews, setReviews] = useState<Record<string, Review>>({}),
    [workerOnline, setWorkerOnline] = useState(true),
    [runner, setRunner] = useState<"website" | "worker">("worker"),
    [department, setDepartment] = useState("");
  const poll = useRef<number | null>(null);

  async function request(path: string, init: RequestInit = {}) {
    const r = await fetch(path, { ...init, headers: { ...(init.headers ?? {}), Authorization: "Bearer " + token } });
    if (!r.ok) {
      let detail = String(r.status);
      try {
        detail = (await r.json()).detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw Error(explain(String(detail)));
    }
    return r;
  }
  async function refresh() {
    try {
      setDocs(await (await request("/api/documents")).json());
      const state = await (await request("/api/document-reviews")).json();
      setReviews(state.latest ?? {});
      setWorkerOnline(Boolean(state.worker_online));
      setRunner(state.runner === "website" ? "website" : "worker");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const active = Object.values(reviews).some((r) => r.status === "QUEUED" || r.status === "RUNNING");
  useEffect(() => {
    if (!token || !active) return;
    poll.current = window.setInterval(() => void refresh(), 5000);
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, active]);
  async function startReview(d: Doc) {
    setBusy(d.document_id + "review");
    setError("");
    try {
      const query = department.trim() ? "?department=" + encodeURIComponent(department.trim()) : "";
      const r: Review & { worker_online: boolean; runner?: string } = await (
        await request(`/api/documents/${d.document_id}/review${query}`, { method: "POST" })
      ).json();
      setReviews({ ...reviews, [d.document_id]: r });
      setWorkerOnline(r.worker_online);
      if (r.runner === "website" && !r.worker_online && r.status === "QUEUED") {
        // The site runs the review itself in this long request; progress is read by the polling meanwhile.
        void request(`/api/document-reviews/${r.review_id}/run`, { method: "POST" })
          .catch((e) => setError((e as Error).message))
          .finally(() => void refresh());
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    if (token) void refresh();
    else setDocs([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function upload() {
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      await request("/api/documents?filename=" + encodeURIComponent(file.name), {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      setFile(null);
      setInputKey((k) => k + 1);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function download(d: Doc) {
    setError("");
    try {
      const href = URL.createObjectURL(await (await request(`/api/documents/${d.document_id}/content`)).blob());
      const a = document.createElement("a");
      a.href = href;
      a.download = d.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function remove(d: Doc) {
    if (!window.confirm(`حذف «${d.filename}»؟`)) return;
    setError("");
    try {
      await request(`/api/documents/${d.document_id}`, { method: "DELETE" });
      if (result?.output?.document_id === d.document_id) setResult(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function run(d: Doc, action: string, other?: string) {
    setBusy(d.document_id + action);
    setError("");
    setResult(null);
    try {
      const query = other ? "?other=" + encodeURIComponent(other) : "";
      setResult(await (await request(`/api/documents/${d.document_id}/actions/${action}${query}`, { method: "POST" })).json());
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  const workbooks = docs.filter((d) => d.kind === "xlsx" && d.summary.review_workbook);
  const words = docs.filter((d) => d.kind === "docx");
  const byId = Object.fromEntries(docs.map((d) => [d.document_id, d]));

  const roots = docs.filter((d) => !d.derived_from || !byId[d.derived_from]);
  function renderCard(d: Doc) {
              const partners = d.kind === "docx" ? workbooks : d.summary.review_workbook ? words : [];
              const others = words.filter((w) => w.document_id !== d.document_id);
              return (
                <li key={d.document_id} className="document-card">
                  <div className="document-head">
                    {d.kind === "xlsx" ? <FileSpreadsheet size={20} /> : <FileText size={20} />}
                    <div>
                      <strong>
                        <bdi>{d.filename}</bdi>
                      </strong>
                      <small>
                        {size(d.size)} · {new Date(d.created_at).toLocaleString("ar-SA")}
                        {d.action && byId[d.derived_from ?? ""] && (
                          <>
                            {" "}
                            · ناتج «{ACTION_NAMES[d.action]}» من <bdi>{byId[d.derived_from ?? ""].filename}</bdi>
                          </>
                        )}
                      </small>
                      <p>{describe(d)}</p>
                    </div>
                  </div>
                  {reviews[d.document_id] && <ReviewStatus review={reviews[d.document_id]} onOpenCase={onOpenCase} />}
                  <div className="document-actions">
                    {reviewable(d) && (
                      <button
                        className="button dark"
                        disabled={!!busy || ["QUEUED", "RUNNING"].includes(reviews[d.document_id]?.status ?? "")}
                        onClick={() => void startReview(d)}
                      >
                        <Sparkles size={14} /> {reviews[d.document_id]?.status === "DONE" ? "مراجعة جديدة" : "مراجعة المستند"}
                      </button>
                    )}
                    <button className="button" onClick={() => void download(d)}>
                      <Download size={14} /> تنزيل
                    </button>
                    {d.kind === "xlsx" && d.summary.review_workbook &&
                      (["qa", "word_report", "excel_rebuild"] as const).map((a) => (
                        <button key={a} className="button" disabled={!!busy} onClick={() => void run(d, a)}>
                          {ACTION_NAMES[a]}
                        </button>
                      ))}
                    {d.kind !== "pdf" && partners.length > 0 && (
                      <span className="document-pair">
                        <select
                          aria-label={d.kind === "docx" ? "سجل المراجعة" : "مستند Word"}
                          value={partner[d.document_id + "comment"] ?? ""}
                          onChange={(e) => setPartner({ ...partner, [d.document_id + "comment"]: e.target.value })}
                        >
                          <option value="">{d.kind === "docx" ? "اختر سجل المراجعة…" : "اختر مستند Word…"}</option>
                          {partners.map((p) => (
                            <option key={p.document_id} value={p.document_id}>
                              {p.filename}
                            </option>
                          ))}
                        </select>
                        <button
                          className="button"
                          disabled={!!busy || !partner[d.document_id + "comment"]}
                          onClick={() => void run(d, "comment", partner[d.document_id + "comment"])}
                        >
                          {ACTION_NAMES.comment}
                        </button>
                      </span>
                    )}
                    {d.kind === "docx" && others.length > 0 && (
                      <span className="document-pair">
                        <select
                          aria-label="النسخة المعادة من الجهة"
                          value={partner[d.document_id + "compare"] ?? ""}
                          onChange={(e) => setPartner({ ...partner, [d.document_id + "compare"]: e.target.value })}
                        >
                          <option value="">اختر النسخة المعادة…</option>
                          {others.map((p) => (
                            <option key={p.document_id} value={p.document_id}>
                              {p.filename}
                            </option>
                          ))}
                        </select>
                        <button
                          className="button"
                          disabled={!!busy || !partner[d.document_id + "compare"]}
                          onClick={() => void run(d, "compare", partner[d.document_id + "compare"])}
                        >
                          {ACTION_NAMES.compare}
                        </button>
                      </span>
                    )}
                    <button className="button ghost" aria-label={`حذف ${d.filename}`} onClick={() => void remove(d)}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </li>
              );
  }

  return (
    <section className="glass documents" aria-labelledby="documents-title">
      <div className="eyebrow">{institutional ? "DOCUMENTS" : "DOCUMENTS · PUBLIC UPLOADS"}</div>
      <h2 id="documents-title">المستندات</h2>
      <p className="documents-note">
        {institutional ? "" : "كل ملف يُرفع هنا يُعامل كمادة عامة. "}
        «مراجعة المستند» ترسل نصه إلى نموذج الذكاء الاصطناعي ليمر بمسار المنهجية: صياغة الملاحظات ثم التحدي والتحكيم والتحرير.
        بقية الأدوات تعمل داخل المحرك دون نموذج. كل ناتج نسخة عمل (INTERNAL_DRAFT) إلى أن يُعتمد إصداره بقرار بشري.
      </p>
      {!token ? (
        <p>سجّل الدخول لرفع المستندات.</p>
      ) : (
        <>
          <div className="documents-upload">
            <label htmlFor="document-file">ملف Word أو PDF أو Excel (حتى 4 ميغابايت)</label>
            <input
              key={inputKey}
              id="document-file"
              type="file"
              accept=".docx,.xlsx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <button className="button dark" onClick={() => void upload()} disabled={!file || busy === "upload"}>
              <Upload size={15} /> {busy === "upload" ? "جارٍ الرفع والفحص…" : "رفع"}
            </button>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {busy && busy !== "upload" && (
            <p role="status" className="loading-state">
              جارٍ التشغيل…
            </p>
          )}
          {result && <ResultView result={result} onDownload={download} />}
          <label className="documents-department">
            الإدارة المالكة للمستند (اختياري، يوجّه صياغة الملاحظات)
            <input value={department} onChange={(e) => setDepartment(e.target.value)} maxLength={120} />
          </label>
          {runner === "worker" && !workerOnline && Object.values(reviews).some((r) => r.status === "QUEUED") && (
            <p className="documents-warning" role="status">
              خدمة المعالجة غير متصلة الآن؛ ستبدأ المراجعة تلقائياً عند تشغيلها.
            </p>
          )}
          <ul className="document-list">
            {docs.length === 0 && <li className="document-empty">لا توجد مستندات بعد.</li>}
            {roots.map((d) => {
              const children = docs.filter((c) => c.derived_from === d.document_id);
              return (
                <li key={d.document_id} className="document-group">
                  <ul className="document-group-list">{renderCard(d)}</ul>
                  {children.length > 0 && (
                    <details className="document-children" open={children.some((c) => c.action === "review")}>
                      <summary>الملفات الناتجة ({children.length})</summary>
                      <ul className="document-list">{children.map((c) => renderCard(c))}</ul>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function ReviewStatus({ review, onOpenCase }: { review: Review; onOpenCase?: (caseId: string) => void }) {
  const d = review.detail ?? {};
  if (review.status === "FAILED") {
    const code = review.error ?? "";
    const text = Object.entries(REVIEW_ERRORS).find(([k]) => code.includes(k))?.[1] ?? code;
    return (
      <p className="review-status review-failed" role="status">
        تعذرت المراجعة: {text}
      </p>
    );
  }
  if (review.status === "DONE") {
    if (d.outcome === "NO_OBSERVATIONS_ADOPTED")
      return (
        <p className="review-status" role="status">
          اكتملت المراجعة: لم يقترح وكيل الصياغة ملاحظات قابلة للاعتماد ({d.proposals ?? 0} مقترح).
        </p>
      );
    return (
      <div className="review-status review-done" role="status">
        <span>
          اكتملت المراجعة · {d.observations} ملاحظة من {d.proposals} مقترحاً · {d.outputs?.length ?? 0} ملفات ناتجة
          {d.executor === "mock" ? " · تشغيل تجريبي (MOCK)" : ""}
        </span>
        {review.case_id && onOpenCase && (
          <button className="button" onClick={() => onOpenCase(review.case_id!)}>
            <LayoutDashboard size={14} /> فتح لوحة المتابعة والمعايرة
          </button>
        )}
      </div>
    );
  }
  return (
    <p className="review-status review-running" role="status">
      <span className="review-spinner" aria-hidden="true" />
      {STAGES[review.stage] ?? review.stage}
      {review.stage === "DRAFTING" && d.drafting_window ? ` (الجزء ${d.drafting_window})` : ""}
      {review.stage === "CHALLENGING" && d.observations ? ` · ${d.observations} ملاحظة` : ""}
    </p>
  );
}

function ResultView({ result, onDownload }: { result: ActionResult; onDownload: (d: Doc) => void }) {
  const r = result.result;
  const rows: Array<[string, unknown]> = Object.entries(r).filter(([k, v]) => !HIDDEN.has(k) && (typeof v !== "object" || Array.isArray(v)));
  const summary = (r.summary ?? null) as Record<string, unknown> | null;
  return (
    <div className="document-result" role="status">
      <h3>
        {ACTION_NAMES[result.action]} · {r.ok ? "اكتمل" : "اكتمل مع ملاحظات"}
      </h3>
      {r.counts && (
        <p>
          {Object.entries(r.counts)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}
        </p>
      )}
      {typeof r.note === "string" && <p className="documents-note">{r.note}</p>}
      {rows.length > 0 && (
        <dl>
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{LABELS[k] ?? k}</dt>
              <dd>{show(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {summary && (
        <dl>
          {Object.entries(summary).map(([k, v]) => (
            <div key={k}>
              <dt>{LABELS[k] ?? k}</dt>
              <dd>{show(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {r.gates && (
        <details>
          <summary>تفاصيل الفحوص ({r.gates.length})</summary>
          <table>
            <thead>
              <tr>
                <th>الفحص</th>
                <th>الحالة</th>
                <th>النتيجة</th>
              </tr>
            </thead>
            <tbody>
              {r.gates.map((g) => (
                <tr key={g.gate}>
                  <td>
                    <bdi>{g.gate}</bdi> {g.name}
                  </td>
                  <td>{g.status}</td>
                  <td>
                    <bdi>{g.actual}</bdi>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {result.output && (
        <button className="button dark" onClick={() => onDownload(result.output!)}>
          <Download size={14} /> تنزيل <bdi>{result.output.filename}</bdi>
        </button>
      )}
    </div>
  );
}
