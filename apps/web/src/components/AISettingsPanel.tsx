// AI settings (admins only): which service reviews documents, its model, and its key.
// A key typed here goes to the server once and is never shown again: the page only learns where a key comes from
// (saved here, the server's environment, or none) and its last four characters.
import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, PlugZap, Settings, Trash2, XCircle } from "lucide-react";

type KeyState = { source: "saved" | "environment" | "none"; hint: string | null; saved_at: string | null };
type Provider = {
  id: string;
  label: string;
  model: string;
  default_model: string;
  models: string[];
  console: string;
  note: string | null;
  key: KeyState;
  active: boolean;
};
type State = {
  active: string | null;
  active_source: "settings" | "environment" | "none";
  key_storage: "vault" | "memory";
  provider_api_enabled: boolean;
  data_authorized: boolean;
  providers: Provider[];
};
type TestResult = { ok: boolean; model: string | null; error: string | null; latency_ms: number };

const ERRORS: Record<string, string> = {
  CALIBRATION_ADMIN: "إعدادات الذكاء الاصطناعي متاحة لمسؤول المنظومة فقط.",
  INVALID_API_KEY_FORMAT: "صيغة المفتاح غير صحيحة: الصق المفتاح كما هو دون مسافات داخلية.",
  INVALID_MODEL_NAME: "اسم النموذج غير صالح.",
  UNKNOWN_AI_PROVIDER: "خدمة غير معروفة.",
  SIGN_IN_REQUIRED: "سجّل الدخول أولاً.",
};
const TEST_ERRORS: Record<string, string> = {
  AUTHENTICATION: "رفضت الخدمة المفتاح. تحقق من نسخه كاملاً.",
  PERMISSION: "المفتاح لا يملك صلاحية هذا النموذج.",
  NOT_FOUND: "اسم النموذج غير متاح لهذا الحساب.",
  RATE_LIMIT: "تجاوزت حد الطلبات مؤقتاً؛ أعد المحاولة بعد قليل.",
  CREDIT_BALANCE_TOO_LOW: "رصيد الحساب لا يكفي.",
  BILLING: "رفضت الخدمة الطلب لسبب يتعلق بالفوترة أو الخطة.",
  CREDENTIAL_UNAVAILABLE: "لا يوجد مفتاح لهذه الخدمة بعد.",
  EXECUTION_POLICY_BLOCKED: "استدعاء خدمات الذكاء الاصطناعي غير مفعّل على الخادم (CDF_ENABLE_PROVIDER_API).",
  TIMEOUT: "انتهت مهلة الاتصال؛ أعد المحاولة.",
  CONNECTION: "تعذر الوصول إلى الخدمة.",
  UNEXPECTED_REPLY: "ردّت الخدمة بصيغة غير متوقعة.",
};

function explain(code: string, table: Record<string, string>) {
  const hit = Object.entries(table).find(([k]) => code.includes(k));
  return hit ? hit[1] : code;
}

export default function AISettingsPanel({ token }: { token: string }) {
  const [state, setState] = useState<State | null>(null),
    [error, setError] = useState(""),
    [forbidden, setForbidden] = useState(false),
    [busy, setBusy] = useState(""),
    [keys, setKeys] = useState<Record<string, string>>({}),
    [models, setModels] = useState<Record<string, string>>({}),
    [tests, setTests] = useState<Record<string, TestResult>>({}),
    [notice, setNotice] = useState("");

  async function request(path: string, init: RequestInit = {}) {
    const r = await fetch(path, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: "Bearer " + token, "Content-Type": "application/json" },
    });
    if (!r.ok) {
      let detail = String(r.status);
      try {
        const body = await r.json();
        detail = typeof body.detail === "string" ? body.detail : detail;
      } catch {
        /* not JSON */
      }
      if (r.status === 403) setForbidden(true);
      throw Error(explain(detail, ERRORS));
    }
    return r.json();
  }

  async function load() {
    try {
      const s: State = await request("/api/ai/settings");
      setState(s);
      setModels(Object.fromEntries(s.providers.map((p) => [p.id, p.model])));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    if (token) void load();
  }, [token]);

  async function act(label: string, run: () => Promise<State | void>, done?: string) {
    setBusy(label);
    setNotice("");
    try {
      const s = await run();
      if (s) {
        setState(s);
        setModels(Object.fromEntries(s.providers.map((p) => [p.id, p.model])));
      }
      if (done) setNotice(done);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (forbidden) return null; // reviewers without the admin role do not see this section
  return (
    <section className="glass ai-settings" id="ai-settings" aria-labelledby="ai-settings-title">
      <div className="eyebrow">
        <Settings size={14} /> AI SETTINGS
      </div>
      <h2 id="ai-settings-title">إعدادات الذكاء الاصطناعي</h2>
      <p className="documents-note">
        اختر الخدمة التي تراجع المستندات، والنموذج، وأضف مفتاح الخدمة. يُحفظ المفتاح مشفّراً على الخادم ولا يُعرض مرة
        أخرى؛ تظهر هنا آخر أربعة أحرف منه فقط.
        {state?.key_storage === "memory" && " (بيئة التطوير المحلية: المفاتيح تبقى حتى إعادة تشغيل الخادم فقط.)"}
      </p>
      {state && !state.provider_api_enabled && (
        <p className="documents-warning">استدعاء خدمات الذكاء الاصطناعي غير مفعّل على الخادم (CDF_ENABLE_PROVIDER_API).</p>
      )}
      {state && !state.data_authorized && (
        <p className="documents-warning">
          لم يُسجَّل إذن إرسال المستندات إلى خدمات الذكاء الاصطناعي (CDF_AI_DATA_AUTHORIZATION)؛ ستُرفض المراجعات.
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="ai-notice" role="status">
          {notice}
        </p>
      )}
      {!state && !error && <p className="loading-state">جارٍ قراءة الإعدادات…</p>}
      <div className="ai-providers">
        {state?.providers.map((p) => {
          const test = tests[p.id];
          return (
            <article key={p.id} className={"ai-provider" + (p.active ? " ai-provider-active" : "")}>
              <div className="ai-provider-head">
                <h3>{p.label}</h3>
                {p.active ? (
                  <span className="ai-badge">
                    {state.active_source === "settings" ? "المستخدمة في المراجعة" : "المستخدمة (من إعدادات الخادم)"}
                  </span>
                ) : (
                  <button
                    className="button ghost"
                    disabled={Boolean(busy)}
                    onClick={() =>
                      void act(
                        "choose-" + p.id,
                        () =>
                          request("/api/ai/active", {
                            method: "PUT",
                            body: JSON.stringify({ provider: p.id, model: models[p.id] || p.model }),
                          }),
                        `أصبحت ${p.label} الخدمة المستخدمة في المراجعة.`,
                      )
                    }
                  >
                    استخدامها في المراجعة
                  </button>
                )}
              </div>
              {p.note === "PROCESSED_IN_CHINA" && (
                <p className="ai-note">تعالج DeepSeek الطلبات على خوادم في الصين.</p>
              )}
              <label className="ai-field">
                النموذج
                <span className="ai-row">
                  <input
                    dir="ltr"
                    list={"models-" + p.id}
                    value={models[p.id] ?? p.model}
                    onChange={(e) => setModels({ ...models, [p.id]: e.target.value })}
                  />
                  <datalist id={"models-" + p.id}>
                    {p.models.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  <button
                    className="button ghost"
                    disabled={Boolean(busy) || (models[p.id] ?? p.model) === p.model}
                    onClick={() =>
                      void act(
                        "model-" + p.id,
                        () =>
                          request(`/api/ai/providers/${p.id}/model`, {
                            method: "PUT",
                            body: JSON.stringify({ model: models[p.id] }),
                          }),
                        "حُفظ اسم النموذج.",
                      )
                    }
                  >
                    حفظ
                  </button>
                </span>
              </label>
              <p className="ai-key-state">
                <KeyRound size={14} />{" "}
                {p.key.source === "saved"
                  ? `مفتاح محفوظ ${p.key.hint ?? ""}`
                  : p.key.source === "environment"
                    ? "مفتاح من إعدادات الخادم (Vercel)"
                    : "لا يوجد مفتاح"}
              </p>
              <label className="ai-field">
                {p.key.source === "none" ? "أضف المفتاح" : "استبدال المفتاح"}
                <span className="ai-row">
                  <input
                    dir="ltr"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={p.console.replace("https://", "")}
                    value={keys[p.id] ?? ""}
                    onChange={(e) => setKeys({ ...keys, [p.id]: e.target.value })}
                  />
                  <button
                    className="button dark"
                    disabled={Boolean(busy) || !(keys[p.id] ?? "").trim()}
                    onClick={() =>
                      void act(
                        "key-" + p.id,
                        async () => {
                          const s = await request(`/api/ai/providers/${p.id}/key`, {
                            method: "PUT",
                            body: JSON.stringify({ key: keys[p.id] }),
                          });
                          setKeys({ ...keys, [p.id]: "" });
                          return s;
                        },
                        "حُفظ المفتاح.",
                      )
                    }
                  >
                    حفظ المفتاح
                  </button>
                </span>
              </label>
              <div className="ai-actions">
                <button
                  className="button ghost"
                  disabled={Boolean(busy) || p.key.source === "none"}
                  onClick={() =>
                    void act("test-" + p.id, async () => {
                      const result: TestResult = await request(`/api/ai/providers/${p.id}/test`, { method: "POST" });
                      setTests((t) => ({ ...t, [p.id]: result }));
                    })
                  }
                >
                  <PlugZap size={15} /> {busy === "test-" + p.id ? "جارٍ الاختبار…" : "اختبار الاتصال"}
                </button>
                {p.key.source === "saved" && (
                  <button
                    className="button ghost"
                    disabled={Boolean(busy)}
                    onClick={() =>
                      void act(
                        "clear-" + p.id,
                        () => request(`/api/ai/providers/${p.id}/key`, { method: "DELETE" }),
                        "حُذف المفتاح المحفوظ.",
                      )
                    }
                  >
                    <Trash2 size={15} /> حذف المفتاح
                  </button>
                )}
              </div>
              {test && (
                <p className={"ai-test " + (test.ok ? "ai-test-ok" : "ai-test-failed")} role="status">
                  {test.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}{" "}
                  {test.ok
                    ? `يعمل · ${test.model ?? ""} · ${(test.latency_ms / 1000).toFixed(1)} ث`
                    : explain(test.error ?? "", TEST_ERRORS)}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
