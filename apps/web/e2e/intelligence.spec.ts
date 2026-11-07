import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import path from "node:path";

test.describe.configure({ mode: "serial" });
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByLabel("رمز جلسة التطوير المحلي", { exact: true })
    .fill(process.env.CDF_CALIBRATION_DEV_TOKEN!);
  await page.getByRole("button", { name: "الاتصال وعرض القضايا" }).click();
  const result = page.waitForResponse(
    (r) =>
      r.url().endsWith("/SYN-COMMAND-001/intelligence") && r.status() === 200,
  );
  await page
    .locator(".case-card")
    .filter({ hasText: "SYN-COMMAND-001" })
    .getByRole("button", { name: "فتح القضية" })
    .click();
  const data = await (await result).json();
  await expect(page.locator(".metrics-grid")).toBeVisible();
  await expect(page.locator(".metrics-grid svg").first()).toBeVisible();
  await page.waitForTimeout(1200); // finish actual chart transition before captures
  return data;
}
const nav = (page: Page, name: string) =>
  page
    .getByRole("navigation", { name: "أقسام القضية" })
    .getByRole("button", { name, exact: true });

test("executive metrics match backend, source distinctions, keyboard and desktop evidence", async ({
  page,
}, info) => {
  await page.goto("/");
  await page.locator(".skip-link").waitFor({ state: "attached" });
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip-link")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main-content$/);
  const data = await open(page);
  expect(data.actual_live_inference_count).toBe(0);
  await expect(page.locator(".orbit-core strong")).toHaveText("٠");
  expect(
    data.metrics.find((m: { id: string }) => m.id === "human_alignment").value,
  ).toBeNull();
  const issues = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(issues.violations).toEqual([]);
  const mask = [
    page.locator(".hero-footer bdi"),
    page.locator(".decision-timeline small"),
    page.locator("input[type=password]"),
  ];
  await expect(page).toHaveScreenshot("executive-desktop.png", {
    fullPage: true,
    animations: "disabled",
    mask,
    maskColor: "#e7edf2",
    maxDiffPixelRatio: 0.025,
  });
  await page.screenshot({
    path: info.outputPath("command-center-desktop.png"),
    fullPage: true,
    mask,
    maskColor: "#e7edf2",
  });
  await nav(page, "مسرح النقاش").click();
  await expect(page.locator(".graph-canvas .react-flow__node")).toHaveCount(9);
  await page
    .locator(".graph-alternatives")
    .getByRole("button", { name: /الفريق الأسود/ })
    .click();
  await expect(page.locator(".execution-details")).toContainText(
    "استجابة مبرمجة",
  );
  await page.locator(".objection-card").first().locator("summary").click();
  await expect(page.locator(".objection-card").first()).toContainText(
    "دورات منتجة",
  );
  await page.screenshot({
    path: info.outputPath("debate-theater.png"),
    fullPage: true,
  });
  await nav(page, "سلسلة الأدلة").click();
  await page.locator(".graph-alternatives button").first().click();
  await expect(page.locator(".evidence-detail")).toContainText(
    "قابلية التطبيق",
  );
  await page.screenshot({
    path: info.outputPath("evidence-lineage.png"),
    fullPage: true,
  });
});

test("iPhone RTL, reduced motion, MAT unknown labels and reference explorer", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
  await expect(page.locator("main")).toHaveAttribute("id", "main-content");
  const mask = [
    page.locator(".hero-footer bdi"),
    page.locator(".decision-timeline small"),
    page.locator("input[type=password]"),
  ];
  await expect(page).toHaveScreenshot("executive-iphone.png", {
    fullPage: true,
    animations: "disabled",
    mask,
    maskColor: "#e7edf2",
    maxDiffPixelRatio: 0.025,
  });
  await page.screenshot({
    path: info.outputPath("command-center-iphone.png"),
    fullPage: true,
    mask,
    maskColor: "#e7edf2",
  });
  await nav(page, "استوديو MAT").click();
  await expect(
    page.locator(".metric-card").filter({ hasText: "التوافق مع المراجع" }),
  ).toContainText("لا تتوفر عينة قابلة للقياس");
  await nav(page, "المراجع والصلاحيات").click();
  await expect(page.locator(".reference-panel")).toContainText(
    "مرشحات استخراج",
  );
  await expect(page.locator(".source-cards article")).toHaveCount(3);
  await page.screenshot({
    path: info.outputPath("authority-explorer-iphone.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
});

test("draft downloads and recalibration refresh are grounded in persistent events", async ({
  page,
}) => {
  await open(page);
  await page.locator(".export-menu summary").click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Excel · مسودة" }).click();
  expect((await download).suggestedFilename()).toBe(
    "INTERNAL_DRAFT__executive.xlsx",
  );
  await nav(page, "معايرة الملاحظات").click();
  await page
    .getByPlaceholder("ما الدليل أو السبب وراء هذا القرار؟")
    .fill("Synthetic executive acceptance decision.");
  await page.getByRole("button", { name: "إرسال قرار المعايرة" }).click();
  await expect(page.getByRole("status")).toContainText("حُفظ القرار");
  await page
    .getByRole("button", { name: "تحديث القراءة", exact: true })
    .click();
  await expect(
    page.locator(".metric-card").filter({ hasText: "تغطية المعايرة" }),
  ).toContainText("١ من ٤ سجل");
  await expect(page.locator(".gate-card")).toContainText("الإصدار محجوب");
});
