import React, { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowUpLeft,
  BookOpen,
  ChevronLeft,
  Download,
  FileCheck2,
  GitBranch,
  LayoutDashboard,
  LockKeyhole,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { EChartsCoreOption } from "echarts/core";
import type { Dashboard } from "./intelligence";
import { roleNames, sourceNames } from "./intelligence";
import tokens from "../../../shared/visual-tokens.json";
import "./style.css";
import { GlassMetricCard as MetricCard } from "./components/Instruments";
const Chart = lazy(() => import("./ExecutiveChart"));
const Graph = lazy(() => import("./IntelligenceGraph"));
const AuthorityExplorer = lazy(() => import("./components/AuthorityExplorer"));
const ObjectionTree = lazy(() => import("./ObjectionTree"));
const ExecutionWorkspace = lazy(
  () => import("./components/ExecutionWorkspace"),
);
const VisualLibrary = lazy(() => import("./components/VisualLibrary"));
const Calibration = lazy(() => import("./CalibrationApp"));
type Case = { case_id: string; stats: Record<string, number | boolean> };
type References = {
  synthetic: boolean;
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
  sources: Array<{
    id: string;
    url: string;
    version: string;
    approval_status: string;
  }>;
  authorities: Array<{
    id: string;
    source_id: string;
    title: string;
    category: string;
    page: number;
    roles: Record<string, string>;
    qualifiers: Record<string, string>;
    threshold: string;
  }>;
  units: Array<{
    id: string;
    source_id: string;
    name: string;
    sector: string;
    page: number;
    tasks: string[];
  }>;
};
const views = [
  ["overview", "نظرة تنفيذية", LayoutDashboard],
  ["debate", "مسرح النقاش", Workflow],
  ["evidence", "سلسلة الأدلة", GitBranch],
  ["references", "المراجع والصلاحيات", BookOpen],
  ["mat", "استوديو MAT", Sparkles],
  ["calibration", "معايرة الملاحظات", FileCheck2],
  ["gallery", "المكتبة البصرية", ShieldCheck],
  ["execution", "التنفيذ والملفات", Activity],
] as const;
const categoryNames: Record<string, string> = {
  AML: "غسل الأموال",
  DELEGATED_AUTHORITY: "الصلاحيات المفوضة",
  CONTROL_FAILURE: "فاعلية الضوابط",
  AUDIT_RIGHTS: "حقوق المراجعة",
  DATA_PROTECTION: "حماية البيانات",
};
const fmt = (n: number) => new Intl.NumberFormat("ar-SA").format(n);
function App() {
  const [token, setToken] = useState(""),
    [cases, setCases] = useState<Case[]>([]),
    [data, setData] = useState<Dashboard | null>(null),
    [view, setView] = useState("overview"),
    [selected, setSelected] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [references, setReferences] = useState<References | null>(null),
    [observationFilter, setObservationFilter] = useState(""),
    [playback, setPlayback] = useState(2000),
    [tree, setTree] = useState(false);
  async function api<T>(path: string): Promise<T> {
    const r = await fetch(path, {
      headers: { Authorization: "Bearer " + token },
    });
    if (!r.ok) throw Error(`${r.status}: ${await r.text()}`);
    return r.json() as Promise<T>;
  }
  async function connect() {
    setBusy(true);
    setError("");
    try {
      setCases(await api<Case[]>("/api/cases"));
      setData(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function openCase(id: string) {
    setBusy(true);
    setError("");
    setSelected("");
    try {
      setData(
        await api<Dashboard>(
          "/api/cases/" + encodeURIComponent(id) + "/intelligence",
        ),
      );
      setView("overview");
      setObservationFilter("");
      setPlayback(2000);
      setTree(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function changeView(next: string) {
    setView(next);
    setSelected("");
    if ((next === "references" || next === "gallery") && !references) {
      try {
        setReferences(await api<References>("/api/reference-candidates"));
      } catch (e) {
        setError(String(e));
      }
    }
  }
  async function download(kind: string) {
    if (!data) return;
    setError("");
    try {
      const r = await fetch(
        `/api/cases/${encodeURIComponent(data.case_id)}/intelligence/export/${kind}`,
        { headers: { Authorization: "Bearer " + token } },
      );
      if (!r.ok) throw Error(`تعذر إعداد نسخة العمل (${r.status})`);
      const href = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = href;
      a.download = `INTERNAL_DRAFT__executive.${kind}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    document.title = "CDF | مركز الذكاء الحوكمي";
    for (const key of [
      "ink",
      "blue",
      "violet",
      "gold",
      "mint",
      "salmon",
    ] as const)
      document.documentElement.style.setProperty("--" + key, tokens[key]);
  }, []);
  const riskOption = useMemo<EChartsCoreOption>(
    () => ({
      grid: { left: 115, right: 14, top: 12, bottom: 35 },
      tooltip: { renderMode: "richText" },
      xAxis: {
        type: "category",
        data: ["قيد المعايرة", "قرار مقدم"],
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontFamily: "Tahoma", color: "#455564" },
      },
      yAxis: {
        type: "category",
        data:
          data?.heatmap.map((h) => categoryNames[h.category] || h.category) ||
          [],
        axisLabel: {
          show: true,
          fontFamily: "Tahoma",
          fontSize: 9,
          width: 105,
          overflow: "truncate",
          color: "#455564",
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      visualMap: {
        show: false,
        min: 0,
        max: Math.max(
          1,
          ...(data?.heatmap.flatMap((h) => [h.pending, h.submitted]) || [1]),
        ),
        inRange: { color: ["#eff3f6", "#f4c2ac", "#c86644"] },
      },
      series: [
        {
          type: "heatmap",
          data:
            data?.heatmap.flatMap((h, i) => [
              [0, i, h.pending],
              [1, i, h.submitted],
            ]) || [],
          label: { show: true, color: "#263c4a" },
          itemStyle: { borderColor: "#fff", borderWidth: 7, borderRadius: 8 },
        },
      ],
    }),
    [data?.heatmap],
  );
  const distribution = useMemo<EChartsCoreOption>(() => {
    const family = (
      d:
        | Dashboard["calibration_analytics"]["original_distribution"]
        | undefined,
    ) =>
      d
        ? [
            d.question_count,
            d.recommendation_count,
            d.mixed_count,
            Math.max(
              0,
              d.denominator -
                d.question_count -
                d.recommendation_count -
                d.mixed_count,
            ),
          ]
        : [];
    return {
      grid: { left: 12, right: 12, top: 14, bottom: 28, containLabel: true },
      tooltip: { renderMode: "richText" },
      xAxis: {
        type: "category",
        data: ["أسئلة", "توصيات", "مختلط", "غير مصنف"],
        axisLabel: { fontFamily: "Tahoma", color: "#455564" },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        splitLine: { lineStyle: { color: "#e8edf0" } },
      },
      series: [
        {
          name: "الأصل",
          type: "bar",
          barMaxWidth: 18,
          data: family(data?.calibration_analytics.original_distribution),
          itemStyle: { color: "#a5b0e3", borderRadius: [5, 5, 0, 0] },
        },
        {
          name: "المعاد",
          type: "bar",
          barMaxWidth: 18,
          data: family(data?.calibration_analytics.reviewed_distribution),
          itemStyle: { color: "#447f7b", borderRadius: [5, 5, 0, 0] },
        },
      ],
    };
  }, [data?.calibration_analytics]);
  const debateData = useMemo(
    () =>
      data
        ? {
            ...data,
            invocations: data.invocations
              .slice(0, playback)
              .filter(
                (i) =>
                  !observationFilter ||
                  !i.observation_id ||
                  i.observation_id === observationFilter,
              ),
            objections: data.objections.filter(
              (o) =>
                !observationFilter || o.observation_id === observationFilter,
            ),
          }
        : null,
    [data, observationFilter, playback],
  );
  const selectedEvidence = data?.evidence.find((e) => e.id === selected);
  return (
    <div className="app-shell" dir="rtl">
      <a href="#main-content" className="skip-link">
        تجاوز إلى المحتوى
      </a>
      <aside className="rail" aria-label="التنقل الرئيسي">
        <div className="rail-symbol" aria-hidden="true">
          <ScanLine size={25} />
        </div>
        {views.map(([key, title, Icon]) => (
          <button
            key={key}
            disabled={!data}
            onClick={() => void changeView(key)}
            className={view === key ? "rail-active" : ""}
            aria-label={title}
            aria-current={view === key ? "page" : undefined}
            title={title}
          >
            <Icon size={21} />
          </button>
        ))}
        <span className="rail-bottom" aria-hidden="true">
          V7.12
        </span>
      </aside>
      <div className="app-body">
        <header className="masthead">
          <img
            src="/cdf-wordmark-on-dark.jpg"
            alt="الصندوق الثقافي — Cultural Development Fund"
          />
          <div className="masthead-center">
            <span>GOVERNANCE INTELLIGENCE</span>
            <small>منظومة المراجعة والامتثال</small>
          </div>
          <span className="environment-pill">
            <span />
            SYNTHETIC LOCAL DEVELOPMENT ONLY
          </span>
        </header>
        <main id="main-content" dir="rtl" tabIndex={-1}>
          <div className="workspace-heading">
            <div>
              <div className="eyebrow">GCO / INTELLIGENCE WORKSPACE</div>
              <h1>
                مركز الذكاء الحوكمي<span className="heading-dot">.</span>
              </h1>
            </div>
            <div className="heading-state">
              <LockKeyhole size={16} />
              <span>مساحة تجريبية · غير مصرح بالإصدار</span>
            </div>
          </div>
          <section
            className="connection glass"
            aria-label="الاتصال ببيئة التجربة"
          >
            <label>
              رمز جلسة التطوير المحلي
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="رمز الجلسة المؤقت"
                autoComplete="off"
              />
            </label>
            <button
              className="button dark"
              onClick={() => void connect()}
              disabled={busy}
            >
              الاتصال وعرض القضايا <ArrowUpLeft size={16} />
            </button>
            {data && (
              <div className="case-breadcrumb">
                <FileCheck2 size={16} />
                <bdi>{data.case_id}</bdi>
              </div>
            )}
          </section>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {busy && (
            <p role="status" className="loading-state">
              جارٍ قراءة السجلات…
            </p>
          )}
          {!data ? (
            <section className="glass welcome">
              <div className="welcome-symbol">
                <Workflow size={40} />
              </div>
              <div className="eyebrow">EVIDENCE BEFORE DECISIONS</div>
              <h2>وضوحٌ يصنع القرار.</h2>
              <p>
                مسار واحد يربط الملاحظة بالدليل، ويمر بالتحدي المستقل، ويترك
                القرار المهني للمراجع.
              </p>
              <div className="case-list">
                {cases.length ? (
                  cases.map((c) => (
                    <article key={c.case_id} className="case-card">
                      <div>
                        <small>قضية تجريبية</small>
                        <h3>
                          <bdi>{c.case_id}</bdi>
                        </h3>
                        <p>
                          {String(c.stats.observation_count)} ملاحظات ·{" "}
                          {String(c.stats.submitted_observations)} قرارات معايرة
                        </p>
                      </div>
                      <button
                        className="button dark"
                        onClick={() => void openCase(c.case_id)}
                      >
                        فتح القضية <ChevronLeft size={17} />
                      </button>
                    </article>
                  ))
                ) : (
                  <p>اتصل لعرض القضايا المصرح بها.</p>
                )}
              </div>
            </section>
          ) : (
            <>
              <div className="view-bar">
                <nav aria-label="أقسام القضية">
                  {views.map(([key, title]) => (
                    <button
                      key={key}
                      className={view === key ? "tab-active" : ""}
                      onClick={() => void changeView(key)}
                    >
                      {title}
                    </button>
                  ))}
                </nav>
                <button
                  className="button ghost"
                  aria-label="تحديث القراءة"
                  onClick={() => void openCase(data.case_id)}
                >
                  <RefreshCw size={16} />
                </button>
                <details className="export-menu">
                  <summary>
                    <Download size={15} />
                    نسخة عمل
                  </summary>
                  <div>
                    {["docx", "xlsx", "pdf"].map((kind) => (
                      <button key={kind} onClick={() => void download(kind)}>
                        {kind === "docx"
                          ? "Word"
                          : kind === "xlsx"
                            ? "Excel"
                            : "PDF"}{" "}
                        · مسودة
                      </button>
                    ))}
                  </div>
                </details>
              </div>
              <div className="mode-notice">
                البيئة العامة · قضايا ومراجع افتراضية · الوضع المؤسسي غير مُفعّل
              </div>
              {(view === "overview" || view === "mat") && (
                <>
                  <section className="hero glass">
                    <div className="hero-copy">
                      <div className="eyebrow">
                        <span className="tiny-dot" /> EXECUTIVE REVIEW ·
                        SNAPSHOT
                      </div>
                      <h2>
                        {view === "mat" ? (
                          <>
                            من قرارٍ موثّق،
                            <br />
                            <em>إلى منهجٍ أدق.</em>
                          </>
                        ) : (
                          <>
                            كل قرارٍ أقوى،
                            <br />
                            <em>حين يُرى دليله.</em>
                          </>
                        )}
                      </h2>
                      <p>
                        قراءة مترابطة للأدلة، والاعتراضات، وقرارات المعايرة.
                        مؤشرات تصف السجل المتاح؛ لا تمنح صلاحية اعتماد.
                      </p>
                      <div className="hero-footer">
                        <span>
                          <Activity size={15} />{" "}
                          {data.run_id ? "تشغيل مسجل" : "لم يسجل تشغيل"}
                        </span>
                        <bdi>
                          {data.captured_at
                            ? new Date(data.captured_at).toLocaleString("ar-SA")
                            : "لا توجد لقطة تشغيل"}
                        </bdi>
                      </div>
                    </div>
                    <div className="hero-orbit">
                      <div className="orbit-word">MAT</div>
                      <div className="orbit-core">
                        <ShieldCheck size={35} />
                        <strong>{fmt(data.actual_live_inference_count)}</strong>
                        <span>اتصال مزود فعلي مسجل</span>
                      </div>
                      <div className="orbit-chip top">
                        <GitBranch size={15} />
                        {fmt(data.objections.length)} اعتراض مسجل
                      </div>
                      <div className="orbit-chip bottom">
                        <FileCheck2 size={15} />
                        {fmt(data.observation_count)} ملاحظات
                      </div>
                      <span className="orbit-caption">
                        {data.trace_integrity
                          ? "سلسلة محلية متسقة · ليست تصديقاً خارجياً"
                          : "سلسلة التشغيل غير متحققة"}
                      </span>
                    </div>
                  </section>
                  <div className="section-title">
                    <div>
                      <small>مقاييس قابلة للتتبع</small>
                      <h2>
                        {view === "mat"
                          ? "المعايرة وتطور القرار"
                          : "من السجل إلى الصورة الكاملة"}
                      </h2>
                    </div>
                    <span className="subtle-pill">
                      بيانات تجريبية · لا توجد درجات ثقة مُختلقة
                    </span>
                  </div>
                  <section className="metrics-grid" aria-label="مؤشرات الحوكمة">
                    {(view === "mat"
                      ? ["calibration", "mat_reversal", "human_alignment"]
                      : [
                          "evidence_coverage",
                          "objections_resolved",
                          "calibration",
                        ]
                    ).map((id, i) => {
                      const m = data.metrics.find((m) => m.id === id);
                      return m ? (
                        <MetricCard key={id} metric={m} semi={i === 1} />
                      ) : null;
                    })}
                  </section>
                  <section className="insight-grid">
                    <article className="glass chart-panel">
                      <div className="panel-heading">
                        <div className="icon-glass warm">
                          <ScanLine size={19} />
                        </div>
                        <div>
                          <small>MATERIALITY MONITOR</small>
                          <h2>الأهمية تحت المراجعة</h2>
                        </div>
                        <strong className="count-pill">
                          {fmt(data.unresolved_material.length)} مفتوحة
                        </strong>
                      </div>
                      <p>
                        عدد الملاحظات حسب التصنيف وحالة المعايرة، وليس تقديراً
                        لاحتمال الخطر.
                      </p>
                      <Suspense
                        fallback={<div className="chart-placeholder" />}
                      >
                        <Chart
                          option={riskOption}
                          label="خريطة أعداد الملاحظات المادية حسب حالة المعايرة"
                          height={220}
                        />
                      </Suspense>
                      <details>
                        <summary>البيانات وسلسلة الحساب</summary>
                        <table>
                          <thead>
                            <tr>
                              <th>التصنيف</th>
                              <th>قيد المعايرة</th>
                              <th>قرار مقدم</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.heatmap.map((h) => (
                              <tr key={h.category}>
                                <td>
                                  <bdi>{h.category}</bdi>
                                </td>
                                <td>{h.pending}</td>
                                <td>{h.submitted}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    </article>
                    <article className="glass chart-panel">
                      <div className="panel-heading">
                        <div className="icon-glass cool">
                          <Sparkles size={19} />
                        </div>
                        <div>
                          <small>CALIBRATION INTELLIGENCE</small>
                          <h2>تطور صياغة الملاحظات</h2>
                        </div>
                      </div>
                      <p>
                        الأصل <span className="legend-dot violet" /> مقابل
                        النسخة المعادة <span className="legend-dot green" />؛
                        النصوص الفارغة مستبعدة.
                      </p>
                      <Suspense
                        fallback={<div className="chart-placeholder" />}
                      >
                        <Chart
                          option={distribution}
                          label="توزيع الأسئلة والتوصيات في الأصل والنسخة المعادة"
                          height={220}
                        />
                      </Suspense>
                      <details>
                        <summary>عرض أعداد التصنيف</summary>
                        <pre>
                          {JSON.stringify(data.calibration_analytics, null, 2)}
                        </pre>
                      </details>
                    </article>
                  </section>
                  <section className="bottom-grid">
                    <article className="glass gate-card">
                      <div className="panel-heading">
                        <div className="icon-glass">
                          <LockKeyhole size={20} />
                        </div>
                        <div>
                          <small>RELEASE AUTHORIZATION</small>
                          <h2>بوابة الإصدار</h2>
                        </div>
                        <span className="blocked-chip">
                          {data.release_gate.authorized
                            ? "يتطلب إعادة التحقق"
                            : "الإصدار محجوب"}
                        </span>
                      </div>
                      <p>
                        آخر تحقق مسجل؛ التصريح الفعلي يتطلب إعادة التحقق عند
                        الإصدار. لا تعوض المؤشرات أي شرط إلزامي.
                      </p>
                      <ul>
                        {data.release_gate.reasons.slice(0, 4).map((reason) => (
                          <li key={reason}>
                            <span className="status-square" />
                            <bdi>{reason.split(":")[0]}</bdi>
                          </li>
                        ))}
                      </ul>
                      <button
                        className="text-button"
                        onClick={() => void changeView("debate")}
                      >
                        استعرض مسار القرار <ArrowUpLeft size={16} />
                      </button>
                    </article>
                    <article className="glass timeline-panel">
                      <div className="panel-heading">
                        <div>
                          <small>DECISION JOURNAL</small>
                          <h2>أثر كل خطوة</h2>
                        </div>
                      </div>
                      <ol className="decision-timeline">
                        {data.timeline
                          .slice(-4)
                          .reverse()
                          .map((e) => (
                            <li key={e.id}>
                              <span className="timeline-marker" />
                              <div>
                                <strong>
                                  {e.kind === "CASE_IMPORTED"
                                    ? "استيراد القضية"
                                    : e.kind === "EXECUTION_CAPTURED"
                                      ? "توثيق تشغيل المراجعة"
                                      : e.kind === "OBSERVATION_CALIBRATION"
                                        ? "تسجيل قرار معايرة"
                                        : e.kind}
                                </strong>
                                <small>
                                  {new Date(e.at).toLocaleString("ar-SA")} ·{" "}
                                  <bdi>{e.observation_id || "القضية"}</bdi>
                                </small>
                              </div>
                            </li>
                          ))}
                      </ol>
                    </article>
                  </section>
                </>
              )}
              {(view === "debate" || view === "evidence") && (
                <section className="glass theater">
                  <div className="panel-heading">
                    <div>
                      <small>
                        {view === "debate"
                          ? "MULTI-AGENT DEBATE THEATER"
                          : "EVIDENCE LINEAGE"}
                      </small>
                      <h2>
                        {view === "debate"
                          ? "الحجة، ثم اختبارها."
                          : "من النص إلى الملاحظة."}
                      </h2>
                    </div>
                    <span className="subtle-pill">
                      لقطة سجلات · لا يوجد بث مصطنع
                    </span>
                  </div>
                  <p>
                    {view === "debate"
                      ? "الروابط تعكس ترتيب التنفيذ المسجل. MAT مستشار؛ القرار المستقل لا يستبدل الاعتماد البشري."
                      : "كل رابط ظاهر موجود في سجل ربط الأدلة. وقوع النص في المصدر لا يثبت اعتماد المصدر أو سريانه."}
                  </p>
                  {view === "debate" && (
                    <div className="history-controls">
                      <label>
                        الملاحظة
                        <select
                          aria-label="الملاحظة"
                          value={observationFilter}
                          onChange={(e) => setObservationFilter(e.target.value)}
                        >
                          <option value="">كل الملاحظات</option>
                          {data.observations.map((o) => (
                            <option key={o.observation_id}>
                              {o.observation_id}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        قراءة زمنية لسجل محفوظ
                        <input
                          type="range"
                          disabled={tree}
                          min={1}
                          max={Math.max(1, data.invocations.length)}
                          value={Math.min(playback, data.invocations.length)}
                          onChange={(e) => setPlayback(Number(e.target.value))}
                        />
                      </label>
                      <span>
                        {tree
                          ? "الاعتراضات المسجلة كاملة"
                          : `${Math.min(playback, data.invocations.length)} من ${data.invocations.length} تنفيذ`}
                      </span>
                      <button onClick={() => setTree(!tree)}>
                        {tree ? "عرض المراحل" : "شجرة الاعتراضات"}
                      </button>
                    </div>
                  )}
                  <Suspense fallback={<div className="chart-placeholder" />}>
                    {view === "debate" && tree && debateData ? (
                      <ObjectionTree data={debateData} onSelect={setSelected} />
                    ) : (
                      <Graph
                        data={
                          view === "debate" && debateData ? debateData : data
                        }
                        kind={view === "debate" ? "debate" : "evidence"}
                        onSelect={setSelected}
                      />
                    )}
                  </Suspense>
                  <div className="graph-alternatives">
                    {view === "debate"
                      ? data.stages.map((stage) => (
                          <button
                            key={stage}
                            className={selected === stage ? "selected" : ""}
                            onClick={() => setSelected(stage)}
                          >
                            {roleNames[stage] || stage}{" "}
                            <small>
                              (
                              {
                                (debateData || data).invocations.filter(
                                  (i) => i.stage === stage,
                                ).length
                              }
                              )
                            </small>
                          </button>
                        ))
                      : data.evidence.map((e) => (
                          <button key={e.id} onClick={() => setSelected(e.id)}>
                            <bdi>{e.id}</bdi>
                          </button>
                        ))}
                  </div>
                  {view === "debate" && (
                    <div className="execution-details" aria-live="polite">
                      <h3>
                        {selected
                          ? roleNames[selected] || selected
                          : "اختر مرحلة لاستعراض المصدر والحالة"}
                      </h3>
                      {(debateData || data).invocations
                        .filter((i) => i.stage === selected)
                        .map((i) => (
                          <article className="execution-row" key={i.id}>
                            <strong>
                              {i.observation_id || "القضية"} · {i.status}
                            </strong>
                            <span>{sourceNames[i.source] || i.source}</span>
                            <small>
                              <bdi>{i.id}</bdi> ·{" "}
                              {i.latency_ms === null
                                ? "زمن غير مسجل"
                                : i.latency_ms + " ms"}
                            </small>
                            <div>
                              {i.evidence_refs.map((ref) => (
                                <button
                                  className="evidence-chip"
                                  key={ref}
                                  onClick={() => {
                                    setView("evidence");
                                    setSelected(ref);
                                  }}
                                >
                                  {ref}
                                </button>
                              ))}
                            </div>
                          </article>
                        ))}
                    </div>
                  )}
                  {selectedEvidence && (
                    <article className="evidence-detail" aria-live="polite">
                      <h3>
                        <bdi>{selectedEvidence.id}</bdi>
                      </h3>
                      <p>{selectedEvidence.excerpt}</p>
                      <dl>
                        <dt>المصدر والموضع</dt>
                        <dd>
                          {selectedEvidence.file} ·{" "}
                          {selectedEvidence.page_or_paragraph}
                        </dd>
                        <dt>اعتماد المصدر</dt>
                        <dd>{selectedEvidence.approval_status}</dd>
                        <dt>قابلية التطبيق</dt>
                        <dd>{selectedEvidence.applicability}</dd>
                      </dl>
                    </article>
                  )}
                  {view === "debate" &&
                    (debateData || data).objections.map((o) => (
                      <details className="objection-card" key={o.id}>
                        <summary>
                          <bdi>{o.observation_id}</bdi> · {o.productive_cycles}{" "}
                          دورات منتجة · <bdi>{o.disposition}</bdi>
                        </summary>
                        <ol>
                          {o.turns.map((turn, i) => (
                            <li key={i}>
                              <strong>
                                {turn.actor} · {turn.cycle}
                              </strong>
                              <p>{turn.claim}</p>
                              <div>
                                {turn.evidence_refs.map((ref) => (
                                  <button
                                    key={ref}
                                    className="evidence-chip"
                                    onClick={() => {
                                      setView("evidence");
                                      setSelected(ref);
                                    }}
                                  >
                                    {ref}
                                  </button>
                                ))}
                              </div>
                            </li>
                          ))}
                        </ol>
                        {o.advisory_turns.map((t, i) => (
                          <div key={i} className="advisory-turn">
                            <strong>{t.stage} · رأي استشاري</strong>
                            <p>{t.claim}</p>
                          </div>
                        ))}
                        <p>خلاصة المحكّم: {o.rationale}</p>
                      </details>
                    ))}
                </section>
              )}
              {view === "references" && (
                <Suspense fallback={<p>جارٍ تحميل المراجع…</p>}>
                  <AuthorityExplorer data={references} />
                </Suspense>
              )}
              {view === "execution" && (
                <Suspense fallback={<p>جارٍ قراءة السجل…</p>}>
                  <ExecutionWorkspace
                    caseId={data.case_id}
                    token={token}
                    onPublished={() =>
                      void api<Dashboard>(
                        "/api/cases/" +
                          encodeURIComponent(data.case_id) +
                          "/intelligence",
                      ).then(setData)
                    }
                  />
                </Suspense>
              )}
              {view === "gallery" && (
                <Suspense fallback={<p>جارٍ تحميل المكتبة…</p>}>
                  <VisualLibrary data={data} references={references} />
                </Suspense>
              )}
              {view === "calibration" && (
                <Suspense fallback={<p>جارٍ تحميل المعايرة…</p>}>
                  <Calibration
                    key={data.case_id}
                    initialToken={token}
                    caseId={data.case_id}
                  />
                </Suspense>
              )}
              <section className="provenance-strip" aria-label="مصادر التنفيذ">
                <span>
                  <span className="tiny-dot" /> مصدر التنفيذ
                </span>
                {Object.entries(data.execution_sources).map(
                  ([source, count]) => (
                    <span key={source}>
                      {sourceNames[source] || source}: <b>{fmt(count)}</b>
                    </span>
                  ),
                )}
                <span>الاعتماد المؤسسي: NOT_AUTHORIZED</span>
              </section>
            </>
          )}
          <footer className="app-footer">
            <span>CDF · GOVERNANCE INTELLIGENCE / V7.12</span>
            <span>
              الهوية الرقمية امتداد إبداعي قيد الاعتماد · MAT استشاري فقط
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
