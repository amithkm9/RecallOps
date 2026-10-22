import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { Badge, Empty, IncidentTable } from "./common";
import { Button } from "./ui/button";

describe("operator interface", () => {
  it("labels uncertain decisions clearly", () => {
    render(<Badge value="review" />);
    expect(screen.getByText("review")).toBeInTheDocument();
  });
  it("offers an honest empty state", () => {
    render(<Empty title="No decisions yet" />);
    expect(screen.getByText("No decisions yet")).toBeInTheDocument();
  });
  it("links persisted incidents to the detail workspace", () => {
    render(
      <BrowserRouter>
        <IncidentTable
          items={[
            {
              id: "case-1",
              status: "review",
              product_name: "Salmon",
              reference: "2024-12-0201",
              store_name: "Fictional store",
              affected_quantity: 0,
              updated_at: "2024-12-27T15:00:00Z",
              published_at: "2024-12-27T15:00:00Z",
              mode: "replay",
              recall_id: "recall-1",
            },
          ]}
        />
      </BrowserRouter>,
    );
    expect(screen.getByRole("link", { name: "Salmon" })).toHaveAttribute(
      "href",
      "/incidents/case-1",
    );
  });
  it("disables pending actions", () => {
    let calls = 0;
    render(
      <Button disabled onClick={() => calls++}>
        Inject evidence
      </Button>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(calls).toBe(0);
  });
});
