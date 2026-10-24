import { useEffect, useRef } from "react";
import { init, use } from "echarts/core";
import { GaugeChart, HeatmapChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
use([
  GaugeChart,
  HeatmapChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
  AriaComponent,
  SVGRenderer,
]);
export default function ExecutiveChart({
  option,
  label,
  height = 210,
}: {
  option: EChartsCoreOption;
  label: string;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = init(ref.current, undefined, { renderer: "svg" });
    chart.setOption({
      ...option,
      animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
      aria: { enabled: true },
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option]);
  return (
    <div
      ref={ref}
      className="executive-chart"
      role="img"
      aria-label={label}
      style={{ height, direction: "ltr" }}
    />
  );
}
