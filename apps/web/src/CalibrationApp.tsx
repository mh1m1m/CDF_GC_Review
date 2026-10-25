import React, { useEffect, useState } from "react";

import "./style.css";
import { diffTokens } from "./diff";

type Observation = {
  observation_id: string;
  original_text?: string;
  reviewed_text?: string;
  observed_change?: string;
  material_categories?: string[];
  decision_head?: string | null;
  decision_state?: {
    decision_event_hash: string;
    decision: string;
    status: string;
    decided_by: string;
    heightened_review: boolean;
    reviewed_by: string | null;
  } | null;
};
type CaseData = {
  case_id: string;
  evidence_hash: string;
  source_hash: string;
  observations: Observation[];
  rule_eligible_events?: string[];
  profile_versions_known?: string[];
  statistics: Record<string, unknown>;
};
type EventData = {
  observation_id: string | null;
  event_type: string;
  payload_json: string;
  event_hash: string;
  created_at: string;
  actor: string;
};
type ProfileSummary = {
  profile_version: string;
  profile_sha256: string;
  active: boolean;
  created_by: string;
  created_at: string;
};
type CaseSummary = {
  case_id: string;
  evidence_hash: string;
  stats: Record<string, number | boolean>;
};
const choices = [
  ["KEEP_UNCHANGED", "إبقاء دون تعديل"],
  ["KEEP_WITH_REVISIONS", "إبقاء مع تعديل"],
  ["STRENGTHEN", "تعزيز"],
  ["SOFTEN", "تخفيف"],
  ["SHORTEN", "اختصار"],
  ["EXPAND", "توسيع"],
  ["CONVERT_TO_QUESTION", "تحويل إلى سؤال"],
  ["CONVERT_TO_RECOMMENDATION", "تحويل إلى توصية"],
  ["NARROW_SCOPE", "تضييق النطاق"],
  ["MERGE_WITH_ANOTHER", "دمج مع ملاحظة أخرى"],
  ["REQUEST_MORE_EVIDENCE", "طلب أدلة"],
  ["ESCALATE", "تصعيد"],
  ["WITHDRAW", "سحب"],
];
const grounds = [
  ["W01", "تعارض"],
  ["W02", "عدم الانطباق"],
  ["W03", "خارج اختصاص الحوكمة"],
  ["W04", "ضوابط كافية"],
  ["W05", "أدلة غير كافية"],
  ["W06", "تكرار"],
  ["W07", "توصية غير متناسبة"],
  ["W08", "صلاحية غير صحيحة"],
  ["W09", "تفاصيل تشغيلية"],
  ["W10", "أهمية محدودة"],
  ["W11", "سوء تفسير"],
  ["W12", "معالج في بند آخر"],
  ["W13", "بيانات قديمة"],
  ["W14", "معالجة غير فعالة"],
  ["W15", "سبب آخر"],
];
export default function CalibrationApp({
  initialToken,
  caseId,
}: {
  initialToken: string;
  caseId: string;
}) {
  const [token, setToken] = useState(initialToken);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [active, setActive] = useState<CaseData | null>(null);
  const [events, setEvents] = useState<EventData[]>([]);
  const [focus, setFocus] = useState(0);
  // No preselected decision and no preselected withdrawal ground: the reviewer chooses each time.
  const [choice, setChoice] = useState("");
  const [reason, setReason] = useState("");
  const [ground, setGround] = useState("");
  const [evidence, setEvidence] = useState("");
  const [reviewReason, setReviewReason] = useState("");
  const [ruleProfile, setRuleProfile] = useState("");
  const [view, setView] = useState("compare");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [ruleId, setRuleId] = useState("SYN-S01");
  const [ruleReason, setRuleReason] = useState("");
  const [ruleAction, setRuleAction] = useState("DEFER");
  const [analyticsData, setAnalyticsData] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [profileData, setProfileData] = useState<Record<
    string,
    unknown
  > | null>(null);
  // Form state belongs to one observation: reset it whenever the reviewer moves to another observation or case,
  // so a rationale, ground or evidence typed for one observation can never be submitted for the next.
  useEffect(() => {
    setChoice("");
    setReason("");
    setGround("");
    setEvidence("");
    setReviewReason("");
  }, [focus, active?.case_id]);
  async function api<T>(
    url: string,
    method = "GET",
    body?: object,
  ): Promise<T> {
    const resp = await fetch(url, {
      method,
      headers: {
        Authorization: "Bearer " + token,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!resp.ok) {
      let t = "";
      try {
        t = JSON.stringify(await resp.json());
      } catch {}
      throw Error(resp.status + " " + t);
    }
    return resp.json() as Promise<T>;
  }
  async function load() {
    setError("");
    try {
      setCases(await api<CaseSummary[]>("/api/cases"));
    } catch (e) {
      setError(String(e));
    }
  }
  async function openCase(id: string, selected = 0, display = "compare") {
    setError("");
    try {
      const [c, ev] = await Promise.all([
        api<CaseData>("/api/cases/" + encodeURIComponent(id)),
        api<EventData[]>("/api/cases/" + encodeURIComponent(id) + "/events"),
      ]);
      setActive(c);
      setEvents(ev);
      setFocus(selected);
      setView(display);
    } catch (e) {
      setError(String(e));
    }
  }
  async function loadProfiles() {
    if (!active) return;
    try {
      setProfiles(
        await api<ProfileSummary[]>(
          "/api/cases/" + encodeURIComponent(active.case_id) + "/profiles",
        ),
      );
    } catch (e) {
      setError(String(e));
    }
  }
  async function compileProfile() {
    if (!active) return;
    setError("");
    try {
      await api(
        "/api/cases/" +
          encodeURIComponent(active.case_id) +
          "/profiles/compile",
        "POST",
      );
      setSuccess("أُنشئت نسخة تجريبية غير معتمدة من ملف DNA");
      await loadProfiles();
    } catch (e) {
      setError(String(e));
    }
  }
  async function activateProfile(version: string) {
    if (!active) return;
    setError("");
    try {
      await api(
        "/api/cases/" +
          encodeURIComponent(active.case_id) +
          "/profiles/" +
          encodeURIComponent(version) +
          "/activate",
        "POST",
      );
      setSuccess("تم تفعيل النسخة التجريبية مع تسجيل الحدث");
      await loadProfiles();
    } catch (e) {
      setError(String(e));
    }
  }
  async function viewProfile(version: string) {
    if (!active) return;
    setError("");
    try {
      setProfileData(
        await api<Record<string, unknown>>(
          "/api/cases/" +
            encodeURIComponent(active.case_id) +
            "/profiles/" +
            encodeURIComponent(version),
        ),
      );
      setView("writing");
    } catch (e) {
      setError(String(e));
    }
  }
  async function loadAnalytics() {
    if (!active) return;
    try {
      setAnalyticsData(
        await api<Record<string, unknown>>(
          "/api/cases/" + encodeURIComponent(active.case_id) + "/analytics",
        ),
      );
    } catch (e) {
      setError(String(e));
    }
  }
  async function save(status: "DRAFT" | "SUBMITTED") {
    if (!active) return;
    const obs = active.observations[focus];
    setError("");
    setSuccess("");
    try {
      await api(
        "/api/cases/" +
          encodeURIComponent(active.case_id) +
          "/observations/" +
          encodeURIComponent(obs.observation_id) +
          "/decisions",
        "POST",
        {
          decision: choice,
          rationale: reason,
          expected_evidence_hash: active.evidence_hash,
          expected_decision_head: obs.decision_head ?? null,
          status,
          reasons: choice === "WITHDRAW" && ground ? [ground] : [],
          evidence_refs: evidence.trim() ? [evidence.trim()] : [],
          material_categories: obs.material_categories || [],
        },
      );
      setSuccess(
        status === "SUBMITTED"
          ? "حُفظ القرار وأُضيف إلى سجل التدقيق"
          : "حُفظت المسودة",
      );
      await openCase(active.case_id, focus, "compare");
    } catch (e) {
      setError(String(e));
    }
  }
  async function reviewDecision(outcome: "APPROVED" | "RETURNED") {
    if (!active) return;
    const obs = active.observations[focus];
    if (!obs.decision_state) return;
    setError("");
    setSuccess("");
    try {
      await api(
        "/api/cases/" + encodeURIComponent(active.case_id) + "/decisions/review",
        "POST",
        {
          decision_event_hash: obs.decision_state.decision_event_hash,
          outcome,
          rationale: reviewReason,
        },
      );
      setSuccess(outcome === "APPROVED" ? "اعتمد مراجع ثانٍ القرار" : "أُعيد القرار للمراجعة");
      await openCase(active.case_id, focus, "compare");
    } catch (e) {
      setError(String(e));
    }
  }
  async function reviewRule() {
    if (!active) return;
    setError("");
    setSuccess("");
    // Only the latest decision of each observation counts as evidence; material withdrawals need a second review.
    const hashes = active.rule_eligible_events || [];
    const version = ruleProfile || active.profile_versions_known?.[0] || "";
    try {
      await api(
        "/api/cases/" +
          encodeURIComponent(active.case_id) +
          "/rules/" +
          encodeURIComponent(ruleId) +
          "/review",
        "POST",
        {
          action: ruleAction,
          rationale: ruleReason,
          observation_event_hashes: hashes,
          profile_version: version,
        },
      );
      setSuccess(
        "حُفظت مراجعة القاعدة، ولم تُنشأ صلاحية إصدار أو اعتماد مؤسسي",
      );
      await openCase(active.case_id, focus, "rules");
    } catch (e) {
      setError(String(e));
    }
  }
  const obs = active?.observations[focus];
  const comparison = obs
    ? diffTokens(obs.original_text || "", obs.reviewed_text || "")
    : null;
  const decisionEvents = events.filter(
    (e) => e.event_type === "OBSERVATION_CALIBRATION",
  );
  const latest = obs
    ? decisionEvents
        .filter((e) => e.observation_id === obs.observation_id)
        .at(-1)
    : null;
  useEffect(() => {
    document.title = "MAT | معايرة المنهجية المهنية";
  }, []);
  useEffect(() => {
    void openCase(caseId);
  }, [caseId]);
  return (
    <div className="calibration-workspace" dir="rtl">
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      {success && (
        <div role="status" className="success">
          {success}
        </div>
      )}
      <nav>
        {active && (
          <>
            <button onClick={() => setView("compare")}>مقارنة الملاحظات</button>
            <button
              onClick={() => {
                setView("analytics");
                void loadAnalytics();
              }}
            >
              المؤشرات
            </button>
            <button onClick={() => setView("rules")}>اعتماد قواعد DNA</button>
            <button onClick={() => setView("withdrawals")}>
              الملاحظات المستبعدة
            </button>
            <button
              onClick={() => {
                setView("profiles");
                void loadProfiles();
              }}
            >
              إصدارات DNA
            </button>
            <button onClick={() => setView("writing")}>الأسلوب المهني</button>
            <button onClick={() => setView("history")}>سجل القرارات</button>
          </>
        )}
      </nav>
      {!active ? (
        <section className="panel">
          <h2>القضايا المتاحة</h2>
          <p>
            لا تظهر إلا القضايا المصرح بها في بيئة التجربة. لم تُستورد ملفات
            الصندوق الحقيقية.
          </p>
          {cases.length === 0 ? (
            <p className="empty">لا توجد قضايا أو لم يتم الاتصال بالخادم.</p>
          ) : (
            cases.map((c) => (
              <article className="row" key={c.case_id}>
                <strong>{c.case_id}</strong>
                <span>
                  الملاحظات: {String(c.stats.observation_count)} • المعايرة:{" "}
                  {String(c.stats.submitted_observations)}
                </span>
                <button onClick={() => openCase(c.case_id)}>فتح القضية</button>
              </article>
            ))
          )}
        </section>
      ) : (
        <>
          <section className="stats">
            <div>
              <small>القضية</small>
              <strong>{active.case_id}</strong>
            </div>
            <div>
              <small>الملاحظات</small>
              <strong>{String(active.statistics.observation_count)}</strong>
            </div>
            <div>
              <small>المعاير منها</small>
              <strong>
                {String(active.statistics.submitted_observations)}
              </strong>
            </div>
            <div>
              <small>قيد المعايرة</small>
              <strong>{String(active.statistics.pending_observations)}</strong>
            </div>
            <div>
              <small>سلامة التدقيق</small>
              <strong>
                {active.statistics.audit_chain_valid ? "سليمة" : "تحقق مطلوب"}
              </strong>
            </div>
          </section>
          {view === "compare" && (
            <section className="panel">
              <div className="row">
                <h2>
                  الملاحظة {focus + 1} من {active.observations.length}
                </h2>
                <div>
                  <button
                    disabled={focus <= 0}
                    onClick={() => setFocus(focus - 1)}
                  >
                    السابق
                  </button>
                  <button
                    disabled={focus >= active.observations.length - 1}
                    onClick={() => setFocus(focus + 1)}
                  >
                    التالي
                  </button>
                </div>
              </div>
              {obs && (
                <>
                  <p className="tag">
                    {obs.observation_id} · {obs.observed_change || "غير مصنف"}
                  </p>
                  <div className="comparison">
                    <article>
                      <h3>الملاحظة الأصلية</h3>
                      <p>
                        {comparison?.old.map((x, i) => (
                          <span
                            key={i}
                            className={
                              x.op === "removed" ? "removed" : undefined
                            }
                          >
                            {x.text}
                          </span>
                        ))}
                      </p>
                    </article>
                    <article>
                      <h3>النص في النسخة المعادة</h3>
                      <p>
                        {obs.reviewed_text
                          ? comparison?.revised.map((x, i) => (
                              <span
                                key={i}
                                className={
                                  x.op === "added" ? "added" : undefined
                                }
                              >
                                {x.text}
                              </span>
                            ))
                          : "غير موجود في هذه النسخة — ليس دليلاً على سحب معتمد"}
                      </p>
                    </article>
                  </div>
                  <p className="notice">
                    تُميز الإضافات باللون الأخضر والمحذوفات باللون الأحمر؛
                    المقارنة لعرض التحرير فقط ولا تُثبت سبب الحذف.{" "}
                    {comparison?.bounded ? "(تم تقييد المقارنة لطول النص)" : ""}
                  </p>
                  {latest && (
                    <p className="tag">
                      آخر إجراء: {JSON.parse(latest.payload_json).decision} (
                      {obs.decision_state?.status || JSON.parse(latest.payload_json).status})
                    </p>
                  )}
                  {obs.decision_state &&
                    obs.decision_state.status !== "DRAFT" && (
                      <div className="form">
                        <h3>مراجعة ثانية للقرار</h3>
                        <p className="notice">
                          يعتمد القرار أو يعيده مراجع غير من سجّله.
                          {obs.decision_state.heightened_review
                            ? " سحب ملاحظة جوهرية لا يُستخدم دليلاً لقاعدة قبل اعتماده."
                            : ""}
                        </p>
                        <label>
                          مبرر المراجعة
                          <textarea
                            value={reviewReason}
                            onChange={(e) => setReviewReason(e.target.value)}
                          />
                        </label>
                        <div className="actions">
                          <button onClick={() => reviewDecision("RETURNED")}>
                            إعادة القرار
                          </button>
                          <button
                            className="primary"
                            onClick={() => reviewDecision("APPROVED")}
                          >
                            اعتماد القرار
                          </button>
                        </div>
                      </div>
                    )}
                  <div className="form">
                    <h3>تسجيل القرار المهني</h3>
                    <label>
                      الإجراء
                      <select
                        value={choice}
                        onChange={(e) => setChoice(e.target.value)}
                      >
                        <option value="">— اختر القرار —</option>
                        {choices.map((x) => (
                          <option value={x[0]} key={x[0]}>
                            {x[1]}
                          </option>
                        ))}
                      </select>
                    </label>
                    {choice === "WITHDRAW" && (
                      <label>
                        سبب السحب
                        <select
                          value={ground}
                          onChange={(e) => setGround(e.target.value)}
                        >
                          <option value="">— اختر السبب —</option>
                          {grounds.map((x) => (
                            <option value={x[0]} key={x[0]}>
                              {x[1]}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    <label>
                      المبرر المهني
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="ما الدليل أو السبب وراء هذا القرار؟"
                      />
                    </label>
                    <label>
                      مرجع الدليل / فجوة الإثبات
                      <input
                        value={evidence}
                        onChange={(e) => setEvidence(e.target.value)}
                        placeholder="مثال: EVIDENCE_GAP:verification-required"
                      />
                    </label>
                    {!!obs.material_categories?.length && (
                      <p className="alert">
                        تصنيف عالي الأهمية: {obs.material_categories.join("، ")}
                        . يتطلب السحب مبرراً ومرجعاً واضحاً.
                      </p>
                    )}
                    <div className="actions">
                      <button disabled={!choice} onClick={() => save("DRAFT")}>
                        حفظ مسودة
                      </button>
                      <button
                        className="primary"
                        disabled={!choice}
                        onClick={() => save("SUBMITTED")}
                      >
                        إرسال قرار المعايرة
                      </button>
                    </div>
                  </div>
                </>
              )}
            </section>
          )}
          {view === "analytics" && (
            <section className="panel">
              <h2>مؤشرات المعايرة</h2>
              <p>
                الأرقام أدناه مأخوذة من قاعدة البيانات، وليست أهدافاً ثابتة
                لأسلوب المراجع.
              </p>
              {Object.entries(active.statistics).map(([k, v]) => (
                <div className="row" key={k}>
                  <span>{k}</span>
                  <strong>{String(v)}</strong>
                </div>
              ))}
              <h3>توزيع الأسئلة والتوصيات — مستخرج من نصوص القضية</h3>
              {analyticsData ? (
                Object.entries(analyticsData).map(([k, v]) => (
                  <div className="row" key={k}>
                    <span>{k}</span>
                    <strong>
                      {typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </strong>
                  </div>
                ))
              ) : (
                <p className="notice">لم يتم تحميل بيانات التصنيف بعد.</p>
              )}
            </section>
          )}
          {view === "rules" && (
            <section className="panel">
              <h2>مراجعة قاعدة DNA منفصلة</h2>
              <p>
                اعتماد قرار على ملاحظة لا يعتمد تلقائياً قاعدة عامة. هذه واجهة
                مراجعة تجريبية، وليس اعتماداً مؤسسياً.
              </p>
              <label>
                معرف القاعدة
                <input
                  value={ruleId}
                  onChange={(e) => setRuleId(e.target.value)}
                />
              </label>
              <label>
                نسخة الملف المستهدفة
                <select
                  value={ruleProfile || active.profile_versions_known?.[0] || ""}
                  onChange={(e) => setRuleProfile(e.target.value)}
                >
                  {(active.profile_versions_known || []).map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                الإجراء
                <select
                  value={ruleAction}
                  onChange={(e) => setRuleAction(e.target.value)}
                >
                  {[
                    "DEFER",
                    "REQUEST_MORE_EVIDENCE",
                    "REJECT",
                    "APPROVE",
                    "APPROVE_WITH_CHANGES",
                  ].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label>
                المبرر
                <textarea
                  value={ruleReason}
                  onChange={(e) => setRuleReason(e.target.value)}
                />
              </label>
              <p className="notice">
                سيتم ربط المراجعة بجميع قرارات المعايرة المقدمة في القضية؛ يجب
                تحسين اختيار أدلة محددة قبل اعتماد بشري فعلي.
              </p>
              <button className="primary" onClick={reviewRule}>
                حفظ مراجعة القاعدة
              </button>
            </section>
          )}

          {view === "withdrawals" && (
            <section className="panel">
              <h2>ملاحظات غائبة أو مقترح سحبها</h2>
              <p className="notice">
                غياب التعليق من النسخة الثانية ليس قراراً بشرياً موثقاً بسحبه.
              </p>
              {active.observations.map((o, i) =>
                o.observed_change === "REMOVED_FROM_VERSION" ||
                o.material_categories?.length ? (
                  <article className="row" key={o.observation_id}>
                    <div>
                      <strong>{o.observation_id}</strong>
                      <p>{o.original_text || "بدون نص"}</p>
                      <small>{o.observed_change}</small>
                    </div>
                    <button
                      onClick={() => {
                        // Opens the observation only; absence is not a withdrawal, so nothing is preselected.
                        setFocus(i);
                        setView("compare");
                      }}
                    >
                      مراجعة سبب الغياب
                    </button>
                  </article>
                ) : null,
              )}
            </section>
          )}
          {view === "profiles" && (
            <section className="panel">
              <h2>نسخ ملف MAT DNA</h2>
              <p>
                جميع النسخ المعروضة هنا تركيبية وحالتها PROVISIONAL /
                NOT_APPROVED؛ لا تعادل اعتماداً مؤسسياً.
              </p>
              <button className="primary" onClick={compileProfile}>
                تجميع نسخة تجريبية من قرارات المعايرة
              </button>
              {profiles.map((p) => (
                <article className="row" key={p.profile_version}>
                  <div>
                    <strong>{p.profile_version}</strong>
                    <small>
                      {p.active ? " • النسخة التجريبية النشطة" : ""}
                    </small>
                    <p>بصمة النسخة: {p.profile_sha256.slice(0, 24)}...</p>
                  </div>
                  <div>
                    <button onClick={() => viewProfile(p.profile_version)}>
                      عرض ملف DNA
                    </button>
                    <button
                      disabled={p.active}
                      onClick={() => activateProfile(p.profile_version)}
                    >
                      تفعيل / رجوع لنسخة سابقة
                    </button>
                  </div>
                </article>
              ))}
              {!profiles.length && (
                <p className="empty">
                  لا توجد نسخ مجمعة حتى الآن. يتطلب التجميع قرار معايرة مقدم
                  ومراجعة قاعدة مؤيدة بأدلة.
                </p>
              )}
            </section>
          )}
          {view === "writing" && (
            <section className="panel">
              <h2>بصمة الأسلوب المهني</h2>
              <p>
                ملف توجيهي للمحاكاة المنضبطة، ولا يجوز اعتباره أسلوب المراجع
                المعتمد دون تحقق بشري.
              </p>
              {!profileData ? (
                <p className="empty">
                  افتح «إصدارات DNA» واختر «عرض ملف DNA» لعرض القواعد الفعلية
                  والتصنيفات.
                </p>
              ) : (
                <>
                  <h3>حالة ملف DNA</h3>
                  <p>
                    {String(profileData["profile_id"])} ·{" "}
                    {String(profileData["status"])} ·{" "}
                    {String(profileData["human_approval_status"])}
                  </p>
                  {[
                    "writing_patterns",
                    "question_patterns",
                    "recommendation_patterns",
                    "selection_rules",
                    "withdrawal_rules",
                  ].map((k) => (
                    <div key={k}>
                      <h3>{k}</h3>
                      {(Array.isArray(profileData[k])
                        ? (profileData[k] as Record<string, unknown>[])
                        : []
                      ).map((p, i) => (
                        <article className="row" key={i}>
                          <span>
                            {String(
                              p["text"] || p["condition"] || p["ground"] || "",
                            )}
                          </span>
                          <small>
                            {String(p["confidence"] || "غير مثبت")} ·{" "}
                            {String(p["classification"] || "")}
                          </small>
                        </article>
                      ))}
                    </div>
                  ))}
                </>
              )}
            </section>
          )}
          {view === "history" && (
            <section className="panel">
              <h2>سجل القرارات غير القابل للاستبدال المباشر</h2>
              {events.map((e, i) => (
                <article className="history" key={i}>
                  <strong>
                    {e.event_type} · {e.observation_id || "القضية"}
                  </strong>
                  <small>
                    {e.created_at} · {e.actor}
                  </small>
                  <pre>
                    {JSON.stringify(JSON.parse(e.payload_json), null, 2)}
                  </pre>
                </article>
              ))}
            </section>
          )}
        </>
      )}
      <footer>
        نموذج هندسي تجريبي • لا توجد هوية مؤسسية معتمدة أو صلاحيات إصدار رسمية •
        لا ترسل مستندات سرية
      </footer>
    </div>
  );
}
