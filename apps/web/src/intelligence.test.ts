import { describe, it, expect } from "vitest";
import { displayValue, sourceNames } from "./intelligence";
describe("executive evidence presentation", () => {
  it("distinguishes missing measurements from measured zero", () => {
    expect(displayValue(null)).toBe("غير مقاس");
    expect(displayValue(0)).not.toBe("غير مقاس");
  });
  it("keeps mock and provider sources visibly distinct", () => {
    expect(sourceNames.MOCK_SCRIPT).not.toBe(sourceNames.PROVIDER_API);
    expect(sourceNames.DETERMINISTIC_RULES).not.toBe(sourceNames.PROVIDER_API);
  });
});
