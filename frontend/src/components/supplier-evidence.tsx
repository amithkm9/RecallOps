import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, CheckCheck } from "lucide-react";
import { post, type Detail } from "../api";
import { ErrorBox, Panel } from "./common";
import { Button } from "./ui/button";

export function SupplierEvidenceForm({ detail }: { detail: Detail }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [inventoryId, setInventoryId] = useState("");
  const [supplier, setSupplier] = useState("");
  const [lot, setLot] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [url, setUrl] = useState("");
  const [supersedes, setSupersedes] = useState("");
  const save = useMutation({
    mutationFn: () =>
      post<{ evidence_id: string; event_id: string; message: string }>(
        `/incidents/${detail.incident.id}/supplier-evidence`,
        {
          inventory_lot_id: inventoryId,
          supplier: supplier.trim(),
          lot: lot.trim(),
          reference: reference.trim(),
          notes: notes.trim(),
          source_url: url.trim() || null,
          supersedes_evidence_id: supersedes || null,
        },
      ),
    onSuccess: () => {
      void client.invalidateQueries();
      setOpen(false);
      setLot("");
      setReference("");
      setNotes("");
      setUrl("");
      setSupersedes("");
    },
  });
  const eligibleIds = new Set([
    ...detail.decisions.map((d) => d.inventory_lot_id),
    ...detail.inventory
      .filter((i) =>
        detail.targets.some(
          (t) => t.gtin.padStart(14, "0") === i.gtin.padStart(14, "0"),
        ),
      )
      .map((i) => i.id),
  ]);
  const inventory = detail.inventory.filter((i) => eligibleIds.has(i.id));
  const run = detail.runs.find((r) => r.event_id === save.data?.event_id);
  return (
    <Panel
      title="Bring new evidence into the investigation"
      caption="Record a supplier statement, keep its source, and reassess the affected stock."
      action={
        <Button
          variant="outline"
          disabled={!inventory.length || save.isPending}
          onClick={() => {
            setOpen(!open);
            save.reset();
          }}
        >
          <FilePlus2 size={15} />
          {open ? "Close form" : "Add supplier evidence"}
        </Button>
      }
    >
      {save.data && (
        <div className="evidence-success" role="status">
          <CheckCheck size={18} />
          <div>
            <strong>{save.data.message}</strong>
            <p>
              {run?.status === "completed"
                ? "Reassessment completed. Review the latest conclusions in Decision & response."
                : run?.status === "failed"
                  ? "The reassessment failed. The evidence is saved; use Investigate again to retry."
                  : "Waiting for the investigation worker. This view updates automatically."}
            </p>
          </div>
        </div>
      )}
      <ErrorBox error={save.error} />
      {open ? (
        <form
          className="evidence-form"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="evidence-form-grid">
            <label>
              Inventory lot
              <select
                required
                value={inventoryId}
                onChange={(e) => {
                  setInventoryId(e.target.value);
                  setSupersedes("");
                  setSupplier(
                    inventory.find((i) => i.id === e.target.value)?.supplier ||
                      "",
                  );
                }}
              >
                <option value="">
                  Choose the stock this statement concerns
                </option>
                {inventory.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.sku} · {i.lot || "Missing lot"} · {i.quantity} units
                  </option>
                ))}
              </select>
            </label>
            <label>
              Supplier name
              <input
                required
                minLength={2}
                maxLength={200}
                value={supplier}
                onChange={(e) => setSupplier(e.target.value)}
                placeholder="Supplier or manufacturer"
              />
            </label>
            <label>
              Supplier’s stated lot
              <input
                required
                maxLength={300}
                value={lot}
                onChange={(e) => setLot(e.target.value)}
                placeholder="Exact lot stated in the supplier record"
              />
            </label>
            <label>
              Document or message reference
              <input
                required
                minLength={3}
                maxLength={200}
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="Delivery note, email subject, or case reference"
              />
            </label>
            <label className="full-width">
              Correct a previous statement (optional)
              <select
                value={supersedes}
                onChange={(e) => setSupersedes(e.target.value)}
              >
                <option value="">Add independent evidence</option>
                {detail.evidence
                  .filter(
                    (e) =>
                      e.kind === "supplier" &&
                      e.payload.inventory_lot_id === inventoryId &&
                      e.payload.supplier === supplier,
                  )
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {String(e.payload.reference || e.label)} ·{" "}
                      {String(e.payload.lot)}
                    </option>
                  ))}
              </select>
              <small>
                The original remains in history. A correction never releases a
                hold automatically.
              </small>
            </label>
            <label className="full-width">
              Source URL (optional)
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
              />
              <small>
                The link is recorded as provenance; its contents are not fetched
                or verified.
              </small>
            </label>
            <label className="full-width">
              What does the supplier say?
              <textarea
                required
                minLength={10}
                maxLength={2000}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Describe the statement and why it changes or supports the current evidence."
              />
            </label>
          </div>
          <div className="evidence-form-footer">
            <p>
              {detail.incident.mode === "replay"
                ? "This is demo evidence for fictional stock. "
                : "This is an operator-submitted supplier statement. "}
              Existing holds remain in place. The warehouse lot is not
              overwritten.
            </p>
            <Button
              disabled={
                save.isPending ||
                !inventoryId ||
                supplier.trim().length < 2 ||
                !lot.trim() ||
                reference.trim().length < 3 ||
                notes.trim().length < 10
              }
              type="submit"
            >
              {save.isPending ? "Recording evidence…" : "Save & reassess"}
            </Button>
          </div>
        </form>
      ) : (
        !save.data && (
          <p className="evidence-intro">
            A delivery note or supplier correction can change the decision. Add
            it here to preserve the statement and trigger a new evidence check.
          </p>
        )
      )}
    </Panel>
  );
}
