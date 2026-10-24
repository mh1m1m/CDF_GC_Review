import { lazy, Suspense, useMemo } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type { Metric } from "../intelligence";
import { displayValue } from "../intelligence";
import tokens from "../../../../shared/visual-tokens.json";
const Chart = lazy(() => import("../ExecutiveChart"));
const fmt = (n: number) => new Intl.NumberFormat("ar-SA").format(n);
export function ExecutiveGauge({
  metric,
  semi = false,
}: {
  metric: Metric;
  semi?: boolean;
}) {
  const option = useMemo<EChartsCoreOption>(
    () => ({
      series: [
        {
          type: "gauge",
          startAngle: semi ? 180 : 90,
          endAngle: semi ? 0 : -270,
          min: 0,
          max: 100,
          radius: "92%",
          center: ["50%", semi ? "72%" : "50%"],
          axisLine: { lineStyle: { width: 12, color: [[1, "#e8edf0"]] } },
          progress: {
            show: metric.value !== null,
            width: 12,
            roundCap: true,
            itemStyle: {
              color:
                metric.id === "objections_resolved" ? "#4c7b78" : "#596cb0",
            },
          },
          pointer: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          detail: { show: false },
          title: { show: false },
          data: [{ value: metric.value ?? 0 }],
        },
      ],
    }),
    [metric.value, metric.id, semi],
  );
  return (
    <div className={"gauge " + (semi ? "gauge-semi" : "")}>
      <Suspense fallback={<div className="chart-placeholder" />}>
        <Chart
          option={option}
          label={`${metric.title}: ${displayValue(metric.value)}`}
          height={semi ? 165 : 152}
        />
      </Suspense>
      <div className="gauge-value" aria-hidden="true">
        <strong>{metric.value === null ? "—" : fmt(metric.value)}</strong>
        {metric.value !== null && <small>٪</small>}
      </div>
    </div>
  );
}
export function GlassMetricCard({
  metric,
  semi = false,
}: {
  metric: Metric;
  semi?: boolean;
}) {
  return (
    <article className="glass metric-card">
      <div className="eyebrow">
        MEASURED INTELLIGENCE <span className="tiny-dot" />
      </div>
      <ExecutiveGauge metric={metric} semi={semi} />
      <h3>{metric.title}</h3>
      <p className="metric-fraction">
        {metric.value === null
          ? "لا تتوفر عينة قابلة للقياس"
          : `${fmt(metric.numerator!)} من ${fmt(metric.denominator!)} سجل`}
      </p>
      <details>
        <summary>منهجية القياس</summary>
        <p>{metric.definition}</p>
        <p>{metric.limitation}</p>
        <p>
          السجلات المصدرية:{" "}
          <bdi>
            {metric.source_records.join(", ") || "لا توجد سجلات تحقق مستقلة"}
          </bdi>
        </p>
        <p>
          البسط: {metric.numerator ?? "غير متاح"} · المقام:{" "}
          {metric.denominator ?? "غير متاح"}
        </p>
        <p>
          المصدر:{" "}
          <bdi>{metric.lineage.join(" + ") || "لا توجد تسميات متحققة"}</bdi>
        </p>
        <p>لا توجد عتبات جودة معتمدة أو درجة ثقة مصطنعة.</p>
      </details>
    </article>
  );
}

export function EvidenceCoverageGauge({ metric }: { metric: Metric }) {
  return <ExecutiveGauge metric={metric} />;
}
export function RiskIntensityGauge({ metric }: { metric: Metric }) {
  return (
    <div>
      <ExecutiveGauge metric={metric} semi />
      <p>حجم الملاحظات المادية المفتوحة؛ ليس احتمال خطر أو درجة شدة.</p>
    </div>
  );
}
export function SegmentedComplianceWheel({ metric }: { metric: Metric }) {
  const option = useMemo<EChartsCoreOption>(
    () => ({
      series: [
        {
          type: "gauge",
          startAngle: 90,
          endAngle: -270,
          min: 0,
          max: 100,
          splitNumber: 10,
          pointer: { show: false },
          axisLine: { lineStyle: { width: 16, color: [[1, "#e8edf0"]] } },
          progress: {
            show: metric.value !== null,
            width: 16,
            itemStyle: { color: tokens.violet },
          },
          axisTick: { show: false },
          splitLine: {
            show: true,
            distance: -16,
            length: 16,
            lineStyle: { color: "#fff", width: 3 },
          },
          axisLabel: { show: false },
          detail: { show: false },
          title: { show: false },
          data: [{ value: metric.value ?? 0 }],
        },
      ],
    }),
    [metric],
  );
  return (
    <div className="instrument">
      <Suspense fallback={<p>جارٍ التحميل…</p>}>
        <Chart
          option={option}
          label={metric.title + ": " + displayValue(metric.value)}
          height={180}
        />
      </Suspense>
      <strong>{displayValue(metric.value)}</strong>
      <p>{metric.title} · تقسيم بصري فقط، بلا عتبات اعتماد مصطنعة.</p>
    </div>
  );
}
export function GovernanceRadar({ metrics }: { metrics: Metric[] }) {
  const known = metrics.filter((m) => m.value !== null);
  const option = useMemo<EChartsCoreOption>(
    () => ({
      radar: {
        indicator: known.map((m) => ({ name: m.title, max: 100 })),
        radius: "60%",
        axisName: {
          fontFamily: "Noto Sans Arabic",
          fontSize: 10,
          color: tokens.ink,
        },
        splitArea: { areaStyle: { color: ["#f0f5fa", "#ffffff"] } },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: known.map((m) => m.value),
              name: "مقاييس مستقلة",
              areaStyle: { color: tokens.violet, opacity: 0.25 },
              lineStyle: { color: tokens.violet },
              symbolSize: 5,
            },
          ],
        },
      ],
    }),
    [metrics],
  );
  return (
    <div>
      {known.length >= 3 ? (
        <Suspense fallback={<p>جارٍ التحميل…</p>}>
          <Chart
            option={option}
            label="رادار المقاييس المعروفة، دون تقييم تجميعي"
            height={275}
          />
        </Suspense>
      ) : (
        <p>عينة غير كافية للرادار؛ القيم المجهولة لا تتحول إلى صفر.</p>
      )}
      <p>محاور مستقلة، وليست درجة حوكمة كلية. المقاييس غير المقاسة مستبعدة.</p>
      <table>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.id}>
              <th>{m.title}</th>
              <td>{displayValue(m.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
