import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import AxeBuilder from "@axe-core/playwright";

test("CLI-created case, MCP changes and persisted artifacts are visible in real React", async ({
  page,
}) => {
  test.skip(
    !process.env.CDF_UNIFIED_CASE_ID,
    "Dedicated unified harness supplies the shared case and evidence directory",
  );
  const caseId = process.env.CDF_UNIFIED_CASE_ID!;
  const output = process.env.CDF_UNIFIED_REPORT_DIR!;
  const expected = JSON.parse(
    fs.readFileSync(path.join(output, "expected-interface.json"), "utf8"),
  );
  // Coverage comes from the CLI's own metrics: it depends on how many decisions the scenario recorded.
  const calibration = expected.metrics.find((m: { id: string }) => m.id === "calibration");
  const arabic = (n: number) => n.toLocaleString("ar-EG");
  const calibrationCoverage = `${arabic(calibration.numerator)} من ${arabic(calibration.denominator)}`;
  await page.goto("/");
  await page
    .getByLabel("رمز جلسة التطوير المحلي", { exact: true })
    .fill(process.env.CDF_CALIBRATION_DEV_TOKEN!);
  await page.getByRole("button", { name: "الاتصال وعرض القضايا" }).click();
  await page
    .locator(".case-card")
    .filter({ hasText: caseId })
    .getByRole("button", { name: "فتح القضية" })
    .click();
  await expect(page.locator(".metrics-grid")).toBeVisible();
  const nav = (name: string) =>
    page
      .getByRole("navigation", { name: "أقسام القضية" })
      .getByRole("button", { name, exact: true });
  await nav("التنفيذ والملفات").click();
  const workspace = page.locator(".execution-workspace");
  await expect(workspace).toHaveAttribute("data-case-id", caseId);
  await expect(workspace).toHaveAttribute("data-run-id", expected.run_id);
  await workspace.locator(".consistency-proof summary").click();
  const value = async (name: string) =>
    (await workspace.locator(`[data-field="${name}"]`).innerText()).trim();
  const rendered = {
    case_id: await value("case-id"),
    run_id: await value("run-id"),
    observation_ids: (await value("observation-ids")).split(", "),
    agent_status: await workspace
      .locator("[data-stage]")
      .evaluateAll((nodes) =>
        nodes.map((node) => ({
          stage: (node as HTMLElement).dataset.stage,
          status: (node as HTMLElement).dataset.status,
          source: (node as HTMLElement).dataset.source,
        })),
      ),
    evidence_references: (await value("evidence-refs")).split(", "),
    calibration_version: await value("calibration-version"),
    release_gate: JSON.parse(
      (await workspace
        .locator('[data-field="release-gate"]')
        .getAttribute("data-gate"))!,
    ),
    metrics: await workspace.locator("[data-metric-id]").evaluateAll((nodes) =>
      nodes.map((node) => {
        const d = (node as HTMLElement).dataset;
        return {
          id: d.metricId,
          numerator: JSON.parse(d.numerator!),
          denominator: JSON.parse(d.denominator!),
        };
      }),
    ),
    artifact_ids: await workspace
      .locator("[data-artifact-id]")
      .evaluateAll((nodes) =>
        nodes.map((n) => (n as HTMLElement).dataset.artifactId),
      ),
  };
  expect(rendered).toEqual(expected);
  const issues = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(issues.violations).toEqual([]);
  fs.writeFileSync(
    path.join(output, "react-interface.json"),
    JSON.stringify(rendered, null, 2),
  );
  await page.screenshot({
    path: path.join(output, "screenshots", "unified-execution-desktop.png"),
    fullPage: true,
  });
  if (rendered.artifact_ids.length) {
    const download = page.waitForEvent("download");
    await workspace
      .locator("[data-artifact-id]")
      .first()
      .getByRole("button")
      .click();
    const file = await download;
    const downloaded = await file.path();
    expect(downloaded).toBeTruthy();
    const firstId = rendered.artifact_ids[0];
    // Compare actual browser-downloaded bytes with the independently recorded CLI metadata.
    const cli = JSON.parse(
      fs.readFileSync(path.join(output, "expected-artifacts.json"), "utf8"),
    );
    const metadata = Object.values(cli).find(
      (m: any) => m.artifact_id === firstId,
    ) as { sha256: string };
    expect(
      crypto
        .createHash("sha256")
        .update(fs.readFileSync(downloaded!))
        .digest("hex"),
    ).toBe(metadata.sha256);
  }
  await nav("مسرح النقاش").click();
  await expect(page.locator(".graph-canvas .react-flow__node")).toHaveCount(9);
  await expect(page.locator(".objection-card").first()).toBeVisible();
  await page.locator(".objection-card").first().locator("summary").click();
  await page.screenshot({
    path: path.join(output, "screenshots", "unified-debate.png"),
    fullPage: true,
  });
  await nav("المراجع والصلاحيات").click();
  await expect(page.locator(".authority-card").first()).toBeVisible();
  await expect(page.locator(".reference-panel")).toContainText(
    "مراجع افتراضية",
  );
  await page.screenshot({
    path: path.join(output, "screenshots", "unified-references.png"),
    fullPage: true,
  });
  await nav("استوديو MAT").click();
  await expect(
    page.locator(".metric-card").filter({ hasText: "تغطية المعايرة" }),
  ).toContainText(calibrationCoverage);
  await page.screenshot({
    path: path.join(output, "screenshots", "unified-mat.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await nav("التنفيذ والملفات").click();
  await expect(workspace).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(output, "screenshots", "unified-execution-iphone.png"),
    fullPage: true,
  });
});
