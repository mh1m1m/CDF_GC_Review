export type Metric = {
  id: string;
  title: string;
  definition: string;
  source_records: string[];
  evidence_status: string;
  synthetic: boolean;
  numerator: number | null;
  denominator: number | null;
  value: number | null;
  unit: string;
  lineage: string[];
  limitation: string;
  status: string;
  calculated_at: string;
  threshold_source: null;
};
export type Invocation = {
  id: string;
  role: string;
  stage: string;
  status: string;
  mode: string;
  source: string;
  observation_id: string | null;
  challenge_id: string | null;
  context_id: string | null;
  timestamp: string | null;
  latency_ms: number | null;
  evidence_refs: string[];
};
export type Evidence = {
  id: string;
  kind: string;
  file: string;
  page_or_paragraph: string;
  excerpt: string;
  approval_status: string;
  applicability: string;
};
export type Observation = {
  observation_id: string;
  original_text: string;
  reviewed_text: string | null;
  observed_change: string;
  material_categories: string[];
  calibration: { decision: string; status: string } | null;
};
export type Dashboard = {
  case_id: string;
  synthetic: boolean;
  run_id: string | null;
  captured_at: string | null;
  evidence_hash: string;
  metrics: Metric[];
  observation_count: number;
  unresolved_material: string[];
  invocations: Invocation[];
  trace_integrity: boolean;
  actual_live_inference_count: number;
  execution_sources: Record<string, number>;
  objections: Array<{
    id: string;
    observation_id: string;
    productive_cycles: number;
    turns: Array<{
      actor: string;
      claim: string;
      evidence_refs: string[];
      cycle: number;
    }>;
    advisory_turns: Array<{
      stage: string;
      claim: string;
      decision: string;
      advisory_only: boolean;
    }>;
    disposition: string;
    rationale: string;
    resolved: boolean;
  }>;
  stages: string[];
  heatmap: Array<{
    category: string;
    pending: number;
    submitted: number;
    lineage: string[];
  }>;
  observations: Observation[];
  evidence: Evidence[];
  evidence_links: Array<{ observation_id: string; evidence_id: string }>;
  timeline: Array<{
    id: string;
    kind: string;
    at: string;
    observation_id: string | null;
  }>;
  release_gate: {
    authorized: boolean;
    current_authority: false;
    reasons: string[];
  };
  calibration_analytics: {
    original_distribution: {
      by_class: Record<string, number>;
      question_count: number;
      recommendation_count: number;
      mixed_count: number;
      denominator: number;
    };
    reviewed_distribution: {
      by_class: Record<string, number>;
      question_count: number;
      recommendation_count: number;
      mixed_count: number;
      denominator: number;
    };
  };
};
export const roleNames: Record<string, string> = {
  DRAFTING: "صياغة GCO",
  "MAT-01": "MAT · المشورة الأولى",
  BLACK_TEAM: "الفريق الأسود",
  "MAT-02": "MAT · الاستجواب",
  RED_ADVOCATE: "المدافع المستقل",
  "MAT-03": "MAT · إعادة التقييم",
  ADJUDICATOR: "المحكّم المستقل",
  FINAL_REVIEWER: "المراجع النهائي",
  EDITORIAL: "التحرير المهني",
};
export const sourceNames: Record<string, string> = {
  MOCK_SCRIPT: "استجابة مبرمجة",
  DETERMINISTIC_RULES: "قواعد حتمية",
  PROVIDER_API: "اتصال مزود مسجل",
  CACHED_REPLAY: "إعادة تشغيل محفوظة",
  FAILED: "تنفيذ غير مكتمل",
  UNVERIFIED: "مصدر غير متحقق",
  SIMULATED_LIVE: "محاكاة اتصال",
};
export function displayValue(value: number | null) {
  return value === null
    ? "غير مقاس"
    : `${new Intl.NumberFormat("ar-SA", { maximumFractionDigits: 1 }).format(value)}٪`;
}
