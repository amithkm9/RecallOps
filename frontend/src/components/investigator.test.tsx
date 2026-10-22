import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import {
  ClaimCard,
  ResolutionForm,
  EvidenceSimulation,
  type DeliveryClaim,
} from "./investigator";
import type { Detail, Inventory } from "../api";
const stock: Inventory = {
  id: "stock-1",
  sku: "SALMON-24",
  product_name: "Salmon",
  gtin: "3760099533007",
  lot: null,
  quantity: 24,
  supplier: "Demo",
  expires_on: "2024-12-20",
  status: "available",
  store_id: "store-1",
};
const claim: DeliveryClaim = {
  id: "claim-1",
  document_id: "document-1",
  delivery_id: "D-104",
  sku: stock.sku,
  gtin: stock.gtin,
  lot: "24326020",
  quantity: 24,
  expires_on: stock.expires_on,
  reference: "D-104",
  locator: "row 2",
  excerpt: "D-104, SALMON-24, 24326020, 24",
  status: "unconfirmed",
  inventory_lot_id: null,
  candidate_inventory_lot_ids: [stock.id],
  validation_evidence_id: null,
};
function wrap(node: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("investigator evidence controls", () => {
  it("requires stock selection, a reason and explicit confirmation before accepting a candidate", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: "Association recorded" }),
    });
    vi.stubGlobal("fetch", fetch);
    wrap(
      <ClaimCard
        incidentId="case-1"
        claim={claim}
        inventory={[stock]}
        documentName="delivery.csv"
      />,
    );
    const accept = screen.getByRole("button", {
      name: "Confirm association & reassess",
    });
    expect(accept).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Stock described by this record"), {
      target: { value: stock.id },
    });
    fireEvent.change(
      screen.getByLabelText("Reason for this evidence decision"),
      {
        target: {
          value: "Checked shipment D-104 against the physical stock labels.",
        },
      },
    );
    expect(accept).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(accept);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/incidents/case-1/investigator/claims/claim-1/validate",
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      inventory_lot_id: stock.id,
      reason: "Checked shipment D-104 against the physical stock labels.",
      accept: true,
    });
    await screen.findByText("Association recorded");
  });
  it("does not allow accepting a claim with no eligible stock association", () => {
    wrap(
      <ClaimCard
        incidentId="case-1"
        claim={{ ...claim, candidate_inventory_lot_ids: [] }}
        inventory={[stock]}
        documentName="unrelated.csv"
      />,
    );
    expect(screen.getByText(/No matching stock candidate/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm association & reassess" }),
    ).toBeDisabled();
  });
  it("includes validation dependencies in a frozen simulation and removes dependent claims with their source", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        run_id: "run-1",
        recall_version_id: "version-1",
        default_evidence_ids: ["source", "validation", "claim"],
        evidence: [
          {
            id: "source",
            kind: "delivery_document",
            label: "Original delivery",
            required_ids: [],
          },
          {
            id: "validation",
            kind: "claim_validation",
            label: "Operator confirmation",
            required_ids: [],
          },
          {
            id: "claim",
            kind: "delivery_claim",
            label: "Confirmed batch",
            required_ids: ["source", "validation"],
          },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetch);
    const detail = {
      incident: { id: "case-1" },
      runs: [
        {
          id: "run-1",
          status: "completed",
          created_at: "2026-10-22T10:00:00Z",
        },
      ],
    } as Detail;
    wrap(<EvidenceSimulation detail={detail} />);
    const confirmed = await screen.findByRole("checkbox", {
      name: /Confirmed batch/,
    });
    fireEvent.click(confirmed);
    expect(
      screen.getByRole("checkbox", { name: /Original delivery/ }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /Operator confirmation/ }),
    ).toBeChecked();
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Original delivery/ }),
    );
    expect(confirmed).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /Operator confirmation/ }),
    ).toBeChecked();
    const form = screen
      .getByRole("button", { name: "Run isolated comparison" })
      .closest("form")!;
    expect(
      within(form).getByText(/snapshot come from the selected run/),
    ).toBeInTheDocument();
  });
  it("allows an attributed revision of accepted evidence against its original stock", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: "Revision recorded" }),
    });
    vi.stubGlobal("fetch", fetch);
    wrap(
      <ClaimCard
        incidentId="case-1"
        claim={{
          ...claim,
          status: "accepted",
          inventory_lot_id: stock.id,
          validation_evidence_id: "validation-1",
          validation_reason: "Original source check",
        }}
        inventory={[stock]}
        documentName="delivery.csv"
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Revise evidence decision" }),
    );
    expect(
      screen.getByLabelText("Stock described by this record"),
    ).toBeDisabled();
    fireEvent.change(
      screen.getByLabelText("Reason for this evidence decision"),
      {
        target: {
          value:
            "The receiving reference was associated with the wrong shipment.",
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Reject claim" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({
      inventory_lot_id: stock.id,
      accept: false,
    });
  });
  it("blocks a resolution drafted against a superseded investigation", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const overview = {
      review_status: "open",
      resolutions: [],
      documents: [],
      claims: [],
      inventory: [],
      questions: [],
      limitations: [],
      retrieval_hints: [],
    } as React.ComponentProps<typeof ResolutionForm>["overview"];
    const detail = {
      incident: { id: "case-1" },
      runs: [{ id: "run-1" }],
      evidence: [{ id: "evidence-1", label: "Checked source" }],
    } as Detail;
    const view = (value: Detail) => (
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ResolutionForm detail={value} overview={overview} />
        </MemoryRouter>
      </QueryClientProvider>
    );
    const rendered = render(view(detail));
    fireEvent.change(screen.getByLabelText("Reviewed finding and reason"), {
      target: {
        value: "Reviewed the batch against the checked source record.",
      },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Checked source" }));
    expect(
      screen.getByRole("button", { name: "Record review resolution" }),
    ).toBeEnabled();
    rendered.rerender(
      view({
        ...detail,
        runs: [...detail.runs, { id: "run-2" } as Detail["runs"][number]],
      }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A newer investigation completed",
    );
    expect(
      screen.getByRole("button", { name: "Record review resolution" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Start review of latest investigation",
      }),
    );
    expect(screen.getByLabelText("Reviewed finding and reason")).toHaveValue(
      "",
    );
  });
});
