import { describe, expect, it } from "vitest";
import { parseInvestigationDataset } from "./investigator-evaluation";
describe("external investigation labels", () => {
  it("requires declared source and label author before evaluating external cases", () => {
    expect(() =>
      parseInvestigationDataset(
        JSON.stringify({
          cases: [{ name: "Missing batch", expected: "review" }],
        }),
      ),
    ).toThrow("source and labeler");
  });
  it("preserves a held-out declaration without certifying independence", () => {
    const value = {
      source: "Independent exercise",
      labeler: "Reviewer one",
      independent_review_declared: true,
      cases: [{ name: "Missing batch", expected: "review", split: "held_out" }],
    };
    expect(parseInvestigationDataset(JSON.stringify(value))).toEqual(value);
  });
  it("rejects oversized case counts and invalid expected decisions", () => {
    const base = {
      source: "Source",
      labeler: "Author",
      independent_review_declared: false,
    };
    expect(() =>
      parseInvestigationDataset(
        JSON.stringify({
          ...base,
          cases: Array(101).fill({ name: "Case", expected: "review" }),
        }),
      ),
    ).toThrow("1 and 100");
    expect(() =>
      parseInvestigationDataset(
        JSON.stringify({
          ...base,
          cases: [{ name: "Case", expected: "safe" }],
        }),
      ),
    ).toThrow("expected verdict");
  });
});
