# CDF visual system

The existing visual implementation was extracted into reusable components without replacing the application. Shared colors remain in shared/visual-tokens.json; terminology, metric definitions, unknown handling and cross-format semantics are in shared/rendering-specification.json.

| Components | Actual implementation/use |
|---|---|
| GlassSurface, GlassPanel, GlassIconBadge | Reusable translucent surfaces, semantic icon treatments and gallery panels |
| GlassMetricCard, ExecutiveGauge | Existing production dashboard cards/gauges extracted and reused |
| EvidenceCoverageGauge, RiskIntensityGauge | Source-coverage and unresolved-materiality instruments; materiality is explicitly not probability/severity |
| SegmentedComplianceWheel | Native ECharts gauge graduation; segments are visual divisions, not invented approval thresholds |
| GovernanceRadar | Independent known ratios; missing measures are excluded, never imputed as zero; no aggregate governance score |
| AgentDebateNode | Existing recorded role/source node content |
| AuthorityCard, DepartmentResponsibilityCard | Source-linked roles, responsibilities and unknown conditions |
| EvidenceProvenanceCard, ReleaseGateStatus, DecisionTimeline | Recorded evidence, hard-gate restrictions and case events |

The running component library, semantic icon gallery and gauge gallery use the selected case's backend measures. ECharts uses SVG with LTR coordinate geometry inside Arabic RTL content. Text alternatives expose values, definitions, numerator/denominator, source record IDs, limitations and unknown states. Reduced motion, high contrast, keyboard skip navigation, visible focus and mobile layout are retained. Graphs support accessible button/detail alternatives.

The liquid-glass treatment is a creative digital proposal. Automated contrast checks and engineering visual inspection do not establish institutional design approval or complete WCAG/manual screen-reader certification. Native Word/Excel semantics take priority over pretending static artwork updates dynamically.
