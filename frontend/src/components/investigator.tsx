import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCheck,
  Download,
  FileSearch,
  Play,
  Upload,
} from "lucide-react";
import {
  api,
  post,
  token,
  useApi,
  when,
  type Detail,
  type Inventory,
  type Settings,
} from "../api";
import { Badge, Empty, ErrorBox, Json, Loading, Panel } from "./common";
import { Button } from "./ui/button";

export interface DeliveryClaim {
  id: string;
  document_id: string;
  delivery_id: string;
  sku: string;
  gtin: string;
  lot: string | null;
  quantity: number | null;
  expires_on: string | null;
  reference: string;
  locator: string;
  excerpt: string;
  status: "unconfirmed" | "accepted" | "rejected";
  inventory_lot_id: string | null;
  candidate_inventory_lot_ids: string[];
  validation_evidence_id: string | null;
  validation_reason?: string | null;
  validated_by?: string | null;
}
interface InvestigatorOverview {
  documents: {
    id: string;
    filename: string;
    media_type: string;
    sha256: string;
    bytes: number;
    text_status: string;
    created_at: string;
    claim_count: number;
    errors?: { row: number | null; message: string }[];
  }[];
  claims: DeliveryClaim[];
  inventory: Inventory[];
  questions: {
    id: string;
    inventory_lot_id: string;
    question: string;
    claim_ids: string[];
  }[];
  resolutions: {
    id: string;
    reason: string;
    evidence_ids: string[];
    actor: string;
    created_at: string;
  }[];
  investigator?: {
    mode?: string;
    stop_reason?: string;
    steps?: {
      tool: string;
      inventory_lot_id: string;
      reason: string;
      status: string;
      result_count: number;
      new_evidence_ids: string[];
    }[];
    metrics?: {
      tool_calls: number;
      elapsed_ms: number;
      max_calls: number;
      max_seconds: number;
    };
  };
  review_status: string;
  reassessment_pending?: boolean;
  limitations: string[];
  retrieval_hints: Record<string, unknown>[];
}
interface ImportResult {
  document_id: string;
  event_id: string | null;
  duplicate: boolean;
  claims_count: number;
  errors: { row: number | null; message: string }[];
  text_status: string;
  message: string;
}
const endpoint = (id: string) => `/incidents/${id}/investigator`;

async function download(path: string, name: string) {
  const response = await fetch(`/api${path}`, {
    headers: token() ? { Authorization: `Bearer ${token()}` } : {},
  });
  if (!response.ok)
    throw new Error(
      "The source could not be downloaded. Check your operator access and try again.",
    );
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function InvestigatorPanel({ detail }: { detail: Detail }) {
  const [params] = useSearchParams();
  const unresolvedIncident = params.get("unresolved");
  const base = endpoint(detail.incident.id);
  const { data, error } = useApi<InvestigatorOverview>(base);
  const sourceSettings = useApi<Settings>("/settings");
  const client = useQueryClient();
  const run = useMutation({
    mutationFn: () => post(`/incidents/${detail.incident.id}/investigate`),
    onSuccess: () => void client.invalidateQueries(),
  });
  const latest = detail.runs.at(-1);
  const current = detail.decisions.filter(
    (d) => (d as typeof d & { run_id: string }).run_id === latest?.id,
  );
  const [sourceError, setSourceError] = useState<Error | null>(null);
  const sourceDownload = async (id: string, filename: string) => {
    setSourceError(null);
    try {
      await download(`${base}/documents/${id}`, filename);
    } catch (e) {
      setSourceError(e instanceof Error ? e : new Error("Download failed"));
    }
  };
  return (
    <div className="investigator-workspace">
      {unresolvedIncident && (
        <div className="mode-notice">
          <strong>Fictional delivery scenario</strong>
          <span>
            In this recorded scenario, the receiving reference is D-104. D-105
            describes a different shipment. Confirm the source association
            before changing the decision.
          </span>
          <Link
            to={`/incidents/${encodeURIComponent(unresolvedIncident)}?section=investigator`}
          >
            Inspect the unresolved case <ArrowRight size={14} />
          </Link>
        </div>
      )}
      <Panel
        title="Investigate the missing evidence"
        caption="Find the affected stock, resolve the unknowns, and keep a traceable next action."
        action={
          <Button
            disabled={run.isPending || latest?.status === "running"}
            onClick={() => run.mutate()}
          >
            <Play size={15} />
            {run.isPending ? "Queueing…" : "Run investigator"}
          </Button>
        }
      >
        <ErrorBox error={error || run.error} />
        {data?.reassessment_pending && (
          <p className="mode-notice" role="status">
            Evidence changes are awaiting a completed reassessment. The recorded
            conclusion may be superseded; resolve the review after processing
            finishes.
          </p>
        )}
        <div className="investigator-source-status">
          <a href={detail.recall.source_url} target="_blank" rel="noreferrer">
            Official recall {detail.incident.reference}
          </a>
          <span>
            Version {detail.recall.official_version} · Published{" "}
            {when(detail.recall.published_at)} · Stored{" "}
            {when(detail.recall.ingested_at)}
          </span>
          <strong>
            {detail.incident.mode === "replay"
              ? "Archived recall · fictional business evidence"
              : `Last successful live refresh: ${when(sourceSettings.data?.last_successful_sync)}`}
          </strong>
          {detail.incident.mode === "live" &&
            sourceSettings.data?.last_sync_error && (
              <p role="status">
                Latest source refresh failed:{" "}
                {sourceSettings.data.last_sync_error}. The recorded conclusions
                may not reflect newer notices.
              </p>
            )}
          {detail.incident.mode === "live" && sourceSettings.data?.coverage && (
            <p>{sourceSettings.data.coverage}</p>
          )}
          {detail.incident.mode === "live" && sourceSettings.error && (
            <p>
              Current source freshness is unavailable. Check Data & settings
              before relying on refresh coverage.
            </p>
          )}
          {detail.recall.clock_warnings?.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
        <div className="investigator-summary">
          <div>
            <span className="eyebrow">CURRENT CONCLUSION</span>
            <h3>{detail.incident.status.replaceAll("_", " ")}</h3>
            <p>
              {detail.incident.affected_quantity} units on internal hold ·{" "}
              {data?.questions.length ?? "…"} open information gaps
            </p>
          </div>
          <div>
            <span className="eyebrow">EXECUTION</span>
            <p role="status">
              {latest
                ? `${latest.status.replaceAll("_", " ")} · ${latest.active_node.replaceAll("_", " ")}`
                : "Waiting for the first investigation"}
            </p>
            <small>
              {latest
                ? `${latest.llm_mode} · ${when(latest.created_at)}`
                : "New evidence will trigger reassessment."}
            </small>
          </div>
        </div>
        {run.isSuccess && (
          <p className="evidence-intro" role="status">
            Investigation queued. Recorded progress updates automatically.
          </p>
        )}
        <div className="investigator-conclusions">
          {current.map((d) => (
            <article key={d.id}>
              <Badge value={d.verdict} />
              <strong>
                {d.quantity} units · {d.lot || "Batch unknown"}
              </strong>
              <p>{d.explanation}</p>
            </article>
          ))}
        </div>
        {!!data?.investigator?.steps?.length && (
          <div className="investigator-progress">
            <h3>Evidence search</h3>
            <p>
              {data.investigator.mode?.replaceAll("_", " ")} ·{" "}
              {data.investigator.stop_reason?.replaceAll("_", " ")}
            </p>
            <ol>
              {data.investigator.steps.map((step, index) => (
                <li key={index}>
                  <div>
                    <strong>{step.tool.replaceAll("_", " ")}</strong>
                    <Badge value={step.status} />
                  </div>
                  <p>{step.reason}</p>
                  <small>
                    {data.inventory.find(
                      (item) => item.id === step.inventory_lot_id,
                    )?.sku || "Stock investigation"}{" "}
                    · {step.result_count} records retrieved ·{" "}
                    {step.new_evidence_ids.length} new sources
                  </small>
                </li>
              ))}
            </ol>
            {data.investigator.metrics && (
              <small>
                {data.investigator.metrics.tool_calls} retrieval calls /{" "}
                {data.investigator.metrics.max_calls} limit ·{" "}
                {data.investigator.metrics.elapsed_ms.toFixed(1)} ms recorded
              </small>
            )}
          </div>
        )}
        {latest && (
          <details className="investigator-trace">
            <summary>
              What the investigator actually did · {latest.steps.length}{" "}
              recorded steps
            </summary>
            <ol>
              {latest.steps.map((step, i) => (
                <li key={i}>
                  <strong>{step.tool.replaceAll("_", " ")}</strong>
                  <small>
                    {when(step.timestamp)} · {step.latency_ms.toFixed(1)} ms
                  </small>
                  <details>
                    <summary>Recorded input and result</summary>
                    <Json value={{ input: step.input, output: step.output }} />
                  </details>
                </li>
              ))}
            </ol>
          </details>
        )}
      </Panel>
      {!data && !error && <Loading />}
      {data && (
        <>
          <Panel
            title="Information gaps"
            caption="Answer only what the available records can establish."
          >
            {data.questions.length ? (
              <div className="investigator-questions">
                {data.questions.map((question) => (
                  <article key={question.id}>
                    <FileSearch size={20} />
                    <div>
                      <h3>{question.question}</h3>
                      <p>
                        {data.inventory.find(
                          (item) => item.id === question.inventory_lot_id,
                        )?.sku || question.inventory_lot_id}
                      </p>
                      {question.claim_ids.length ? (
                        <a
                          className="text-link"
                          href={`#claim-${question.claim_ids[0]}`}
                        >
                          Review {question.claim_ids.length} candidate record
                          {question.claim_ids.length === 1 ? "" : "s"}{" "}
                          <ArrowRight size={14} />
                        </a>
                      ) : (
                        <p>
                          Import the relevant delivery record below, or inspect
                          the stock and record a confirmed answer.
                        </p>
                      )}
                      <DirectAnswer
                        incidentId={detail.incident.id}
                        inventoryId={question.inventory_lot_id}
                      />
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <p className="evidence-intro">
                No missing-information questions are recorded. Check the
                conclusions for conflicts or pending actions.
              </p>
            )}
          </Panel>
          <DeliveryImport incidentId={detail.incident.id} />
          <Panel
            title="Delivery evidence"
            caption="A matching barcode suggests a candidate. Confirm that the record describes this specific stock before accepting its claim."
          >
            <ErrorBox error={sourceError} />
            {!data.documents.length ? (
              <Empty title="No delivery records imported">
                Import a delivery CSV or text-based PDF to search for missing
                batch information.
              </Empty>
            ) : (
              <div className="investigator-documents">
                {data.documents.map((document) => (
                  <div key={document.id}>
                    <div>
                      <strong>{document.filename}</strong>
                      <small>
                        {document.claim_count} claims ·{" "}
                        {document.text_status.replaceAll("_", " ")} ·{" "}
                        {when(document.created_at)}
                      </small>
                      {document.errors?.map((issue, index) => (
                        <small key={index}>
                          {issue.row !== null ? `Row ${issue.row}: ` : ""}
                          {issue.message}
                        </small>
                      ))}
                    </div>
                    <Button
                      variant="outline"
                      onClick={() =>
                        void sourceDownload(document.id, document.filename)
                      }
                    >
                      <Download size={14} />
                      Source
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <div className="investigator-claims">
              {data.claims.map((claim) => (
                <ClaimCard
                  key={claim.id}
                  incidentId={detail.incident.id}
                  claim={claim}
                  inventory={data.inventory}
                  documentName={
                    data.documents.find(
                      (document) => document.id === claim.document_id,
                    )?.filename || "Delivery record"
                  }
                />
              ))}
            </div>
          </Panel>
          <DecisionChanges detail={detail} />
          <EvidenceSimulation detail={detail} />
          <ResolutionForm detail={detail} overview={data} />
          <Panel
            title="Evidence quality & retrieval memory"
            caption="Previous investigations can help locate a source. They do not establish the batch or safety of today's stock."
          >
            <div className="investigator-quality">
              <h3>Known limitations</h3>
              {data.limitations.length ? (
                <ul>
                  {data.limitations.map((limitation, i) => (
                    <li key={i}>{limitation}</li>
                  ))}
                </ul>
              ) : (
                <p>No additional source limitations were reported.</p>
              )}
              <h3>Retrieval hints</h3>
              {data.retrieval_hints.length ? (
                data.retrieval_hints.map((hint, i) => (
                  <details key={i}>
                    <summary>
                      {String(
                        hint.description ||
                          hint.label ||
                          hint.document_name ||
                          "Previously useful retrieval approach",
                      )}
                    </summary>
                    <Json value={hint} />
                  </details>
                ))
              ) : (
                <p>
                  No reusable retrieval hints are recorded yet. Memory is a
                  source-finding aid; improvement is not assumed.
                </p>
              )}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

function DeliveryImport({ incidentId }: { incidentId: string }) {
  const [file, setFile] = useState<File | null>(null);
  const client = useQueryClient();
  const upload = useMutation({
    mutationFn: () => {
      const body = new FormData();
      body.append("file", file!);
      return api<ImportResult>(`${endpoint(incidentId)}/deliveries`, {
        method: "POST",
        body,
      });
    },
    onSuccess: () => void client.invalidateQueries(),
  });
  const template =
    "delivery_id,sku,gtin,lot,quantity,expires_on,reference\nDELIVERY-001,REPLACE-WITH-YOUR-STOCK-SKU,REPLACE-WITH-BARCODE,REPLACE-WITH-BATCH,24,2026-12-20,Delivery note reference\n";
  return (
    <Panel
      title="Import delivery records"
      caption="CSV and PDFs containing selectable text. Original sources and extracted claims are retained."
    >
      <form
        className="evidence-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (file) upload.mutate();
        }}
      >
        <div className="evidence-form-grid">
          <label>
            Delivery CSV or PDF
            <input
              type="file"
              accept=".csv,.pdf,text/csv,application/pdf"
              required
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                upload.reset();
              }}
            />
          </label>
          <div className="investigator-import-help">
            <a
              className="text-link"
              download="recallops-delivery-template.csv"
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(template)}`}
            >
              <Download size={15} />
              Download delivery CSV template
            </a>
            <small>
              Replace every example value with your record. Import does not
              confirm a stock association.
            </small>
          </div>
        </div>
        <div className="evidence-form-footer">
          <p>
            Scanned images require a text-based source. An unreadable document
            stays unresolved.
          </p>
          <Button type="submit" disabled={!file || upload.isPending}>
            <Upload size={15} />
            {upload.isPending
              ? "Importing evidence…"
              : "Import delivery evidence"}
          </Button>
        </div>
        <ErrorBox error={upload.error} />
        {upload.data && (
          <div className="investigator-import-result" role="status">
            <strong>{upload.data.message}</strong>
            <p>
              {upload.data.claims_count} claims ·{" "}
              {upload.data.text_status.replaceAll("_", " ")}
              {upload.data.duplicate ? " · Existing document reused" : ""}
            </p>
            {upload.data.errors.length > 0 && (
              <ul>
                {upload.data.errors.map((item, i) => (
                  <li key={i}>
                    {item.row !== null ? `Row ${item.row}: ` : ""}
                    {item.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </form>
    </Panel>
  );
}

export function ClaimCard({
  incidentId,
  claim,
  inventory,
  documentName,
}: {
  incidentId: string;
  claim: DeliveryClaim;
  inventory: Inventory[];
  documentName: string;
}) {
  const [stockId, setStockId] = useState(claim.inventory_lot_id || "");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [editing, setEditing] = useState(false);
  const client = useQueryClient();
  const validate = useMutation({
    mutationFn: (accept: boolean) =>
      post<{ message: string }>(
        `${endpoint(incidentId)}/claims/${claim.id}/validate`,
        {
          inventory_lot_id:
            !accept && claim.status === "accepted"
              ? claim.inventory_lot_id
              : stockId,
          reason: reason.trim(),
          accept,
        },
      ),
    onSuccess: () => {
      setConfirm(false);
      setEditing(false);
      setReason("");
      void client.invalidateQueries();
    },
  });
  const candidates = inventory.filter(
    (item) =>
      claim.candidate_inventory_lot_ids.includes(item.id) ||
      item.id === claim.inventory_lot_id,
  );
  return (
    <article id={`claim-${claim.id}`} className="investigator-claim">
      <div className="investigator-claim-heading">
        <div>
          <strong>{documentName}</strong>
          <small>
            {claim.locator} ·{" "}
            {claim.delivery_id || claim.reference || "No delivery reference"}
          </small>
        </div>
        <Badge value={claim.status} />
      </div>
      <blockquote>
        {claim.excerpt ||
          "No source excerpt was extracted. Inspect the original document."}
      </blockquote>
      <dl className="investigator-claim-fields">
        <div>
          <dt>Barcode</dt>
          <dd>{claim.gtin || "Missing"}</dd>
        </div>
        <div>
          <dt>Stated batch</dt>
          <dd>{claim.lot || "Missing"}</dd>
        </div>
        <div>
          <dt>Quantity</dt>
          <dd>{claim.quantity ?? "Missing"}</dd>
        </div>
        <div>
          <dt>Expiry</dt>
          <dd>{claim.expires_on || "Missing"}</dd>
        </div>
      </dl>
      {claim.status !== "unconfirmed" && (
        <div className="investigator-validation-record">
          <p>
            {claim.status === "accepted"
              ? `Accepted for ${inventory.find((item) => item.id === claim.inventory_lot_id)?.sku || "the associated stock"}.`
              : "Rejected during operator review."}
            {claim.validated_by && ` Reviewed by ${claim.validated_by}.`}
            {claim.validation_reason && ` ${claim.validation_reason}`}
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={validate.isPending}
            onClick={() => {
              setEditing(!editing);
              setStockId(claim.inventory_lot_id || "");
              setReason("");
              setConfirm(false);
              validate.reset();
            }}
          >
            {editing ? "Cancel revision" : "Revise evidence decision"}
          </Button>
          <small>
            A revision appends a new decision to the evidence history and
            triggers reassessment. Existing holds remain.
          </small>
        </div>
      )}
      {claim.status === "unconfirmed" || editing ? (
        <form
          className="evidence-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (confirm) validate.mutate(true);
          }}
        >
          <div className="evidence-form-grid">
            <label>
              Stock described by this record
              <select
                required
                disabled={claim.status === "accepted"}
                value={stockId}
                onChange={(e) => {
                  setStockId(e.target.value);
                  setConfirm(false);
                }}
              >
                <option value="">
                  Choose only after checking the shipment
                </option>
                {candidates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.sku} · {item.quantity} units ·{" "}
                    {item.lot || "Batch unknown"}
                  </option>
                ))}
              </select>
              {!candidates.length && (
                <small>
                  No matching stock candidate. This claim cannot establish an
                  association.
                </small>
              )}
            </label>
            <label>
              Reason for this evidence decision
              <textarea
                required
                minLength={10}
                maxLength={2000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Explain the delivery reference or physical check that links this source to the selected stock."
              />
            </label>
          </div>
          <label className="investigator-check">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            I checked the source and confirm this claim describes the selected
            stock.
          </label>
          <div className="evidence-form-footer">
            <p>
              Requires an operator token in{" "}
              <Link to="/settings">Data & settings</Link>. Accepted claims
              trigger reassessment; existing holds remain.
            </p>
            <div className="button-row">
              <Button
                type="button"
                variant="outline"
                disabled={
                  validate.isPending || !stockId || reason.trim().length < 10
                }
                onClick={() => validate.mutate(false)}
              >
                Reject claim
              </Button>
              <Button
                type="submit"
                disabled={
                  validate.isPending ||
                  !stockId ||
                  !confirm ||
                  reason.trim().length < 10
                }
              >
                {validate.isPending
                  ? "Recording…"
                  : "Confirm association & reassess"}
              </Button>
            </div>
          </div>
          <ErrorBox error={validate.error} />
          {validate.data && <p role="status">{validate.data.message}</p>}
        </form>
      ) : (
        claim.validation_evidence_id && (
          <p className="evidence-intro">
            Validation retained in evidence {claim.validation_evidence_id}.
          </p>
        )
      )}
    </article>
  );
}

function DirectAnswer({
  incidentId,
  inventoryId,
}: {
  incidentId: string;
  inventoryId: string;
}) {
  const [open, setOpen] = useState(false),
    [lot, setLot] = useState(""),
    [reason, setReason] = useState(""),
    [reference, setReference] = useState(""),
    [expiresOn, setExpiresOn] = useState("");
  const client = useQueryClient();
  const answer = useMutation({
    mutationFn: () =>
      post<{ message: string }>(`${endpoint(incidentId)}/answers`, {
        inventory_lot_id: inventoryId,
        lot: lot.trim(),
        reference: reference.trim(),
        expires_on: expiresOn || null,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries();
    },
  });
  return (
    <div className="investigator-answer">
      <Button variant="outline" onClick={() => setOpen(!open)}>
        {open ? "Close answer" : "Record a checked batch"}
      </Button>
      {open && (
        <form
          className="evidence-form"
          onSubmit={(event) => {
            event.preventDefault();
            answer.mutate();
          }}
        >
          <label>
            Confirmed batch
            <input
              required
              value={lot}
              onChange={(event) => setLot(event.target.value)}
              maxLength={300}
            />
          </label>
          <label>
            Confirmed expiry date (if checked)
            <input
              type="date"
              value={expiresOn}
              onChange={(event) => setExpiresOn(event.target.value)}
            />
          </label>
          <label>
            Observation or source reference
            <input
              required
              minLength={3}
              maxLength={200}
              value={reference}
              onChange={(event) => setReference(event.target.value)}
              placeholder="Physical label check or delivery reference"
            />
          </label>
          <label>
            How did you verify this stock?
            <textarea
              minLength={10}
              maxLength={2000}
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Record the physical label or source you checked."
            />
          </label>
          <p>
            Requires an operator token. This answer becomes attributed evidence
            and triggers reassessment.
          </p>
          <Button
            type="submit"
            disabled={
              !lot.trim() ||
              reference.trim().length < 3 ||
              reason.trim().length < 10 ||
              answer.isPending
            }
          >
            {answer.isPending ? "Saving…" : "Save checked answer"}
          </Button>
        </form>
      )}
      <ErrorBox error={answer.error} />
      {answer.data && <p role="status">{answer.data.message}</p>}
    </div>
  );
}

export function DecisionChanges({ detail }: { detail: Detail }) {
  const latest = detail.runs.at(-1),
    previous = detail.runs.at(-2);
  const decisions = detail.decisions.filter(
    (d) => (d as typeof d & { run_id: string }).run_id === latest?.id,
  );
  return (
    <Panel
      title="Why the decision changed"
      caption={
        previous
          ? `Comparing investigations from ${when(previous.created_at)} and ${when(latest?.created_at)}`
          : "A second investigation is needed for a before-and-after comparison."
      }
    >
      {previous ? (
        <div className="investigator-changes">
          {decisions.map((decision) => {
            const before = detail.decisions.find(
              (d) =>
                (d as typeof d & { run_id: string }).run_id === previous.id &&
                d.inventory_lot_id === decision.inventory_lot_id,
            );
            const added = decision.evidence_ids.filter(
              (id) => !before?.evidence_ids.includes(id),
            );
            return (
              <article key={decision.id}>
                <strong>
                  {decision.quantity} units ·{" "}
                  {detail.inventory.find(
                    (i) => i.id === decision.inventory_lot_id,
                  )?.sku || "Stock"}
                </strong>
                <div className="investigator-verdict-change">
                  <Badge value={before?.verdict || "not_assessed"} />
                  <ArrowRight size={16} />
                  <Badge value={decision.verdict} />
                </div>
                {before && (
                  <p>
                    <b>Before:</b> {before.explanation}
                  </p>
                )}
                <p>
                  <b>Now:</b> {decision.explanation}
                </p>
                <p>
                  <b>Newly cited evidence:</b>{" "}
                  {added.length
                    ? added
                        .map(
                          (id) =>
                            detail.evidence.find((e) => e.id === id)?.label ||
                            id,
                        )
                        .join("; ")
                    : "No additional evidence cited. Check the recorded run for source or stock changes."}
                </p>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="evidence-intro">
          The first decision establishes the baseline. New evidence and
          subsequent decisions remain in the history.
        </p>
      )}
    </Panel>
  );
}

interface SimulationResult {
  run_id: string;
  recall_version_id: string;
  decisions: {
    inventory_lot_id: string;
    verdict: string;
    explanation: string;
    quantity: number;
    previous_verdict?: string | null;
    changed: boolean;
  }[];
  changed_count: number;
  limitations: string[];
  read_only: boolean;
}
interface SimulationOptions {
  run_id: string;
  recall_version_id: string;
  evidence: {
    id: string;
    kind: string;
    label: string;
    inventory_lot_id: string | null;
    required_ids: string[];
    fixed?: boolean;
  }[];
  default_evidence_ids: string[];
}
export function EvidenceSimulation({ detail }: { detail: Detail }) {
  const [runId, setRunId] = useState(
    detail.runs.filter((run) => run.status === "completed").at(-1)?.id || "",
  );
  const [selected, setSelected] = useState<string[]>([]);
  const options = useApi<SimulationOptions>(
    `${endpoint(detail.incident.id)}/simulation-options?run_id=${encodeURIComponent(runId)}`,
  );
  const simulation = useMutation({
    mutationFn: () =>
      post<SimulationResult>(`${endpoint(detail.incident.id)}/simulate`, {
        run_id: runId,
        evidence_ids: selected,
      }),
  });
  const toggle = (id: string, checked: boolean) => {
    const evidence = options.data?.evidence || [];
    if (checked) {
      const ids = new Set([...selected, id]);
      let count = 0;
      do {
        count = ids.size;
        evidence
          .filter((item) => ids.has(item.id))
          .forEach((item) =>
            item.required_ids.forEach((required) => ids.add(required)),
          );
      } while (count !== ids.size);
      setSelected([...ids]);
    } else {
      const ids = new Set(selected.filter((value) => value !== id));
      let count = 0;
      do {
        count = ids.size;
        evidence
          .filter(
            (item) =>
              ids.has(item.id) &&
              item.required_ids.some((required) => !ids.has(required)),
          )
          .forEach((item) => ids.delete(item.id));
      } while (count !== ids.size);
      setSelected([...ids]);
    }
    simulation.reset();
  };
  return (
    <Panel
      title="What changed the answer?"
      caption="Recompute against a saved run using selected evidence. This experiment never creates or releases an operational hold."
    >
      <form
        className="evidence-form"
        onSubmit={(event) => {
          event.preventDefault();
          simulation.mutate();
        }}
      >
        <label>
          Frozen investigation
          <select
            value={runId}
            onChange={(event) => {
              setRunId(event.target.value);
              setSelected([]);
              simulation.reset();
            }}
          >
            {detail.runs
              .filter((run) => run.status === "completed")
              .map((run) => (
                <option key={run.id} value={run.id}>
                  {when(run.created_at)} · {run.id.slice(0, 8)}
                </option>
              ))}
          </select>
        </label>
        <ErrorBox error={options.error} />
        <fieldset className="investigator-evidence-picker">
          <legend>Evidence to include</legend>
          <p>
            The official recall and stock snapshot come from the selected run.
            Leave optional evidence unchecked to inspect that baseline.
            Selecting a claim also selects its required source and validation.
          </p>
          {options.data?.evidence.map((evidence) => (
            <label className="investigator-check" key={evidence.id}>
              <input
                type="checkbox"
                checked={
                  Boolean(evidence.fixed) || selected.includes(evidence.id)
                }
                disabled={evidence.fixed}
                onChange={(event) => toggle(evidence.id, event.target.checked)}
              />
              <span>
                {evidence.label}
                <small>
                  {evidence.kind.replaceAll("_", " ")}
                  {evidence.fixed ? " · fixed snapshot" : ""}
                </small>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="button-row">
          <Button
            type="button"
            variant="outline"
            disabled={!options.data}
            onClick={() => {
              setSelected(options.data?.default_evidence_ids || []);
              simulation.reset();
            }}
          >
            Select saved evidence
          </Button>
          <Button
            type="submit"
            disabled={!runId || !options.data || simulation.isPending}
          >
            {simulation.isPending
              ? "Comparing evidence…"
              : "Run isolated comparison"}
          </Button>
        </div>
        <ErrorBox error={simulation.error} />
      </form>
      {simulation.data && (
        <div className="investigator-simulation" role="status">
          <strong>
            Simulation only · {simulation.data.changed_count} changed conclusion
            {simulation.data.changed_count === 1 ? "" : "s"} · saved run{" "}
            {simulation.data.run_id.slice(0, 8)}
          </strong>
          {simulation.data.decisions.map((decision, i) => (
            <article key={`${decision.inventory_lot_id}-${i}`}>
              <div className="investigator-verdict-change">
                {decision.previous_verdict && (
                  <>
                    <Badge value={decision.previous_verdict} />
                    <ArrowRight size={14} />
                  </>
                )}
                <Badge value={decision.verdict} />
                <strong>{decision.quantity} units</strong>
              </div>
              <p>{decision.explanation}</p>
            </article>
          ))}
          {simulation.data.limitations.map((limitation, i) => (
            <p key={i}>{limitation}</p>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function ResolutionForm({
  detail,
  overview,
}: {
  detail: Detail;
  overview: InvestigatorOverview;
}) {
  const [reason, setReason] = useState(""),
    [selected, setSelected] = useState<string[]>([]);
  const [reviewedRunId, setReviewedRunId] = useState<string | null>(null);
  const latestRunId = detail.runs.at(-1)?.id;
  const staleReview = reviewedRunId !== null && reviewedRunId !== latestRunId;
  const client = useQueryClient();
  const resolution = useMutation({
    mutationFn: () =>
      post<{ message: string }>(`${endpoint(detail.incident.id)}/resolve`, {
        reason: reason.trim(),
        evidence_ids: selected,
        expected_run_id: reviewedRunId || latestRunId,
      }),
    onSuccess: () => {
      setReason("");
      setSelected([]);
      setReviewedRunId(null);
      void client.invalidateQueries();
    },
  });
  return (
    <Panel
      title="Document the human resolution"
      caption={`Review status: ${overview.review_status.replaceAll("_", " ")}. Resolution records the finding; hold release remains a separate authorized action.`}
    >
      <form
        className="evidence-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!staleReview && !overview.reassessment_pending)
            resolution.mutate();
        }}
      >
        <label>
          Reviewed finding and reason
          <textarea
            minLength={10}
            maxLength={2000}
            required
            value={reason}
            onChange={(event) => {
              setReviewedRunId((current) => current || latestRunId || null);
              setReason(event.target.value);
            }}
            placeholder="Explain the accepted finding, the evidence reviewed, and any remaining action."
          />
        </label>
        <fieldset className="investigator-evidence-picker">
          <legend>Evidence reviewed</legend>
          {detail.evidence.map((evidence) => (
            <label key={evidence.id} className="investigator-check">
              <input
                type="checkbox"
                checked={selected.includes(evidence.id)}
                onChange={(event) => {
                  setReviewedRunId((current) => current || latestRunId || null);
                  setSelected(
                    event.target.checked
                      ? [...selected, evidence.id]
                      : selected.filter((id) => id !== evidence.id),
                  );
                }}
              />
              {evidence.label}
            </label>
          ))}
        </fieldset>
        {staleReview && (
          <div className="mode-notice" role="alert">
            <span>
              A newer investigation completed while you were reviewing. Recheck
              its conclusions before recording a resolution.
            </span>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setReason("");
                setSelected([]);
                setReviewedRunId(null);
                resolution.reset();
              }}
            >
              Start review of latest investigation
            </Button>
          </div>
        )}
        <div className="evidence-form-footer">
          <p>
            Requires an operator token. New relevant evidence can reopen the
            review. Active holds are retained.
          </p>
          <Button
            type="submit"
            disabled={
              resolution.isPending ||
              overview.reassessment_pending ||
              staleReview ||
              reason.trim().length < 10 ||
              !selected.length
            }
          >
            <CheckCheck size={15} />
            {resolution.isPending
              ? "Recording resolution…"
              : "Record review resolution"}
          </Button>
        </div>
        <ErrorBox error={resolution.error} />
        {resolution.data && <p role="status">{resolution.data.message}</p>}
      </form>
      {overview.resolutions.length > 0 && (
        <div className="investigator-resolutions">
          {overview.resolutions.map((item) => (
            <article key={item.id}>
              <strong>
                {item.actor} · {when(item.created_at)}
              </strong>
              <p>{item.reason}</p>
              <small>
                {item.evidence_ids.length} reviewed evidence records
              </small>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
