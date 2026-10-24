import { test, expect } from "@playwright/test";

test("synthetic calibration persists after browser restart and denies unsubstantiated material withdrawal", async ({
  page,
}) => {
  const token = process.env.CDF_CALIBRATION_DEV_TOKEN;
  if (!token) throw new Error("synthetic local test token not configured");
  await page.goto("/");
  await expect(
    page.getByText("SYNTHETIC LOCAL DEVELOPMENT ONLY"),
  ).toBeVisible();
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "الاتصال وعرض القضايا" }).click();
  await page
    .locator(".case-card")
    .filter({ hasText: "SYN-MAT-DEMO-001" })
    .getByRole("button", { name: "فتح القضية" })
    .click();
  await page
    .getByRole("navigation", { name: "أقسام القضية" })
    .getByRole("button", { name: "معايرة الملاحظات" })
    .click();
  await expect(page.getByText("SYN-001", { exact: false })).toBeVisible();
  await page
    .getByPlaceholder("ما الدليل أو السبب وراء هذا القرار؟")
    .fill("Synthetic reason validated in browser.");
  await page.getByRole("button", { name: "إرسال قرار المعايرة" }).click();
  await expect(page.getByRole("status")).toContainText("حُفظ القرار");
  await page.reload();
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "الاتصال وعرض القضايا" }).click();
  await page
    .locator(".case-card")
    .filter({ hasText: "SYN-MAT-DEMO-001" })
    .getByRole("button", { name: "فتح القضية" })
    .click();
  await page
    .getByRole("navigation", { name: "أقسام القضية" })
    .getByRole("button", { name: "معايرة الملاحظات" })
    .click();
  await expect(page.getByText("آخر إجراء:", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "التالي" }).click();
  await expect(page.getByText("SYN-002", { exact: false })).toBeVisible();
  await page.getByLabel("الإجراء").selectOption("WITHDRAW");
  await page
    .getByPlaceholder("ما الدليل أو السبب وراء هذا القرار؟")
    .fill("Synthetic rationale, missing verification evidence.");
  await page.getByRole("button", { name: "إرسال قرار المعايرة" }).click();
  await expect(page.getByRole("alert")).toContainText("MATERIAL_WITHDRAWAL");
});

test("Arabic RTL calibration remains usable at mobile viewport width", async ({
  page,
}) => {
  const token = process.env.CDF_CALIBRATION_DEV_TOKEN;
  if (!token) throw new Error("synthetic token missing");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("main")).toHaveAttribute("dir", "rtl");
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "الاتصال وعرض القضايا" }).click();
  await page
    .locator(".case-card")
    .filter({ hasText: "SYN-MAT-DEMO-001" })
    .getByRole("button", { name: "فتح القضية" })
    .click();
  await page
    .getByRole("navigation", { name: "أقسام القضية" })
    .getByRole("button", { name: "معايرة الملاحظات" })
    .click();
  await expect(
    page.getByRole("button", { name: "إرسال قرار المعايرة" }),
  ).toBeVisible();
  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 2,
  );
  expect(horizontalOverflow).toBe(false);
});
