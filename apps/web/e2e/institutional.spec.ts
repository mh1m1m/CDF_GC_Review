import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const nav = (page: Page, name: string) =>
  page
    .getByRole("navigation", { name: "أقسام القضية" })
    .getByRole("button", { name, exact: true });
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByLabel("رمز جلسة التطوير المحلي", { exact: true })
    .fill(process.env.CDF_CALIBRATION_DEV_TOKEN!);
  await page.getByRole("button", { name: "الاتصال وعرض القضايا" }).click();
  await page
    .locator(".case-card")
    .filter({ hasText: "SYN-COMMAND-001" })
    .getByRole("button", { name: "فتح القضية" })
    .click();
  await expect(page.locator(".metrics-grid")).toBeVisible();
}
const mask = (page: Page) => [
  page.locator("input[type=password]"),
  page.locator(".decision-timeline small"),
  page.locator(".hero-footer bdi"),
];
test("public authority and responsibility lookups stay fictional with actual source graphs", async ({
  page,
}, info) => {
  await open(page);
  await nav(page, "المراجع والصلاحيات").click();
  await expect(page.locator(".reference-panel")).toContainText(
    "مراجع افتراضية",
  );
  await expect(page.locator(".source-cards article")).toHaveCount(3);
  await page.getByLabel("دور الجهة", { exact: true }).selectOption("الاعتماد");
  await expect(page.locator(".authority-card")).toHaveCount(2);
  await page.locator(".authority-card").first().locator("summary").click();
  await page.screenshot({
    path: info.outputPath("authority-explorer-desktop.png"),
    fullPage: true,
    mask: mask(page),
    maskColor: "#e7edf2",
  });
  await page.getByLabel("دور الجهة", { exact: true }).selectOption("");
  await page.locator(".reference-graph>summary").click();
  await page
    .getByLabel("نوع الخريطة", { exact: true })
    .selectOption("RESPONSIBILITY");
  await expect(page.locator(".reference-graph .react-flow__node")).toHaveCount(
    4,
  );
  await page.locator(".responsibility-card").first().locator("summary").click();
  await page.screenshot({
    path: info.outputPath("responsibility-map-desktop.png"),
    fullPage: true,
    mask: mask(page),
    maskColor: "#e7edf2",
  });
});
test("live component and gauge gallery has unknown-data and accessibility alternatives", async ({
  page,
}, info) => {
  await open(page);
  await nav(page, "المكتبة البصرية").click();
  await expect(page.locator(".icon-gallery .icon-glass")).toHaveCount(8);
  await expect(
    page.locator(".visual-library .executive-chart").first().locator("svg"),
  ).toBeVisible();
  await page.waitForTimeout(600);
  const issues = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(issues.violations).toEqual([]);
  await page.screenshot({
    path: info.outputPath("liquid-glass-library.png"),
    fullPage: true,
    mask: mask(page),
    maskColor: "#e7edf2",
  });
  await page
    .locator(".icon-gallery")
    .screenshot({ path: info.outputPath("icon-gallery.png") });
  await page
    .locator(".gallery-grid")
    .first()
    .screenshot({ path: info.outputPath("gauge-gallery.png") });
  await nav(page, "استوديو MAT").click();
  await expect(
    page.locator(".metric-card").filter({ hasText: "التوافق مع المراجع" }),
  ).toContainText("لا تتوفر عينة");
  await page.screenshot({
    path: info.outputPath("mat-calibration-desktop.png"),
    fullPage: true,
    mask: mask(page),
    maskColor: "#e7edf2",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await nav(page, "المكتبة البصرية").click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("liquid-glass-iphone.png"),
    fullPage: true,
    mask: mask(page),
    maskColor: "#e7edf2",
  });
});
test("debate inspection supports observation filters and recorded timeline navigation without live animation", async ({
  page,
}, info) => {
  await open(page);
  await nav(page, "مسرح النقاش").click();
  await page.getByLabel("الملاحظة", { exact: true }).selectOption("SYN-001");
  const history = page.getByLabel("قراءة زمنية لسجل محفوظ", { exact: true });
  await history.focus();
  await page.keyboard.press("Home");
  await expect(history).toHaveValue("1");
  await expect(page.locator(".history-controls")).toContainText("1 من");
  await page
    .getByRole("button", { name: "شجرة الاعتراضات", exact: true })
    .click();
  await expect(history).toBeDisabled();
  await expect(
    page.locator(".objection-tree .react-flow__node").first(),
  ).toBeVisible();
  await expect(page.locator(".objection-card")).toHaveCount(1);
  await page.screenshot({
    path: info.outputPath("debate-objection-tree.png"),
    fullPage: true,
    mask: mask(page),
    maskColor: "#e7edf2",
  });
});
