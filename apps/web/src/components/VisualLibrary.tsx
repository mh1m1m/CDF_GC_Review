import {
  Activity,
  BookOpen,
  FileCheck2,
  GitBranch,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { Dashboard } from "../intelligence";
import { GlassSurface, GlassPanel, GlassIconBadge } from "./Glass";
import {
  GlassMetricCard,
  ExecutiveGauge,
  EvidenceCoverageGauge,
  RiskIntensityGauge,
  GovernanceRadar,
  SegmentedComplianceWheel,
} from "./Instruments";
import {
  AuthorityCard,
  DepartmentResponsibilityCard,
  EvidenceProvenanceCard,
  ReleaseGateStatus,
  DecisionTimeline,
} from "./GovernanceCards";
import type {
  AuthorityCandidate,
  ResponsibilityCandidate,
} from "./GovernanceCards";
export default function VisualLibrary({
  data,
  references,
}: {
  data: Dashboard;
  references: {
    authorities: AuthorityCandidate[];
    units: ResponsibilityCandidate[];
  } | null;
}) {
  const metric = (id: string) => data.metrics.find((m) => m.id === id)!;
  const icons = [
    { Icon: ShieldCheck, title: "ضمان الأدلة" },
    { Icon: Workflow, title: "مسار النقاش" },
    { Icon: GitBranch, title: "سلسلة المصدر" },
    { Icon: BookOpen, title: "الصلاحيات" },
    { Icon: Sparkles, title: "مشورة MAT" },
    { Icon: FileCheck2, title: "المعايرة" },
    { Icon: Activity, title: "التنفيذ" },
    { Icon: LockKeyhole, title: "بوابة الإصدار" },
  ];
  return (
    <div className="visual-library">
      <GlassSurface className="library-intro">
        <small>SHARED VISUAL SPECIFICATION</small>
        <h2>مكتبة الذكاء البصري</h2>
        <p>
          مكونات عاملة وبيانات القضية الحالية، مع مصطلحات وألوان مشتركة
          للتقارير. المعالجة الزجاجية مقترح رقمي وليست اعتماداً للهوية.
        </p>
      </GlassSurface>
      <GlassPanel title="أيقونات ذات دلالة">
        <div className="icon-gallery">
          {icons.map(({ Icon, title }, i) => (
            <div key={title}>
              <GlassIconBadge
                tone={i % 3 === 0 ? "warm" : i % 3 === 1 ? "violet" : "cool"}
              >
                <Icon size={24} />
              </GlassIconBadge>
              <span>{title}</span>
            </div>
          ))}
        </div>
      </GlassPanel>
      <div className="gallery-grid">
        <GlassPanel title="تغطية الأدلة">
          <EvidenceCoverageGauge metric={metric("evidence_coverage")} />
        </GlassPanel>
        <GlassPanel title="مؤشر تنفيذي نصف دائري">
          <ExecutiveGauge metric={metric("objections_resolved")} semi />
        </GlassPanel>
        <GlassPanel title="حلقة التغطية المقسمة">
          <SegmentedComplianceWheel metric={metric("calibration")} />
        </GlassPanel>
        <GlassPanel title="الأهمية قيد المراجعة">
          <RiskIntensityGauge metric={metric("material_open")} />
        </GlassPanel>
        <GlassPanel title="رادار الحوكمة المقاس">
          <GovernanceRadar
            metrics={[
              metric("evidence_coverage"),
              metric("objections_resolved"),
              metric("calibration"),
              metric("human_alignment"),
            ]}
          />
        </GlassPanel>
        <GlassMetricCard metric={metric("human_alignment")} />
      </div>
      <div className="gallery-grid">
        <GlassPanel title="مصدر الملاحظة">
          {data.evidence[0] ? (
            <EvidenceProvenanceCard item={data.evidence[0]} />
          ) : (
            <p>لا يوجد دليل مسجل.</p>
          )}
        </GlassPanel>
        <GlassPanel title="حالة التصريح">
          <ReleaseGateStatus gate={data.release_gate} />
        </GlassPanel>
        <GlassPanel title="التسلسل الزمني">
          <DecisionTimeline events={data.timeline} />
        </GlassPanel>
        <GlassPanel title="نماذج صلاحيات ومسؤوليات افتراضية">
          {references?.authorities[0] && (
            <AuthorityCard item={references.authorities[0]} />
          )}{" "}
          {references?.units[0] && (
            <DepartmentResponsibilityCard item={references.units[0]} />
          )}
        </GlassPanel>
      </div>
    </div>
  );
}
