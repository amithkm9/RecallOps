import { InvestigatorPanel } from "./components/investigator";
import { InvestigatorEvaluation } from "./components/investigator-evaluation";
import { OfficialDocuments } from "./components/official-documents";
import { BenchmarkImport } from "./components/benchmark-import";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  ChevronRight,
  GitBranch,
  Pause,
  Play,
  RotateCcw,
  ShieldAlert,
  Timer,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  post,
  useApi,
  when,
  type Decision,
  type Detail,
  type Evaluation,
  type Incident,
  type Replay,
  type Run,
} from "./api";
import { useMode } from "./App";
import {
  Badge,
  Empty,
  ErrorBox,
  Json,
  Loading,
  PageHeader,
  Panel,
} from "./components/common";
import { Button } from "./components/ui/button";
import { SupplierEvidenceForm } from "./components/supplier-evidence";
function Decisions({ decisions }: { decisions: Decision[] }) {
  return (
    <div className="decisions">
      {decisions.map((d) => (
        <article key={d.id} className={`decision decision-${d.verdict}`}>
          <div>
            <Badge value={d.verdict} />
            <strong>
              {d.quantity} units · Lot {d.lot || "unknown"}
            </strong>
          </div>
          <p>{d.explanation}</p>
          <small>
            {d.action.replaceAll("_", " ")} · {d.evidence_ids.length} evidence
            records
          </small>
        </article>
      ))}
    </div>
  );
}
function RunSteps({ run }: { run: Run }) {
  return (
    <div className="steps">
      {run.steps.map((s, i) => (
        <details key={i}>
          <summary>
            <span className="step-number">{i + 1}</span>
            <div>
              <strong>{s.tool.replaceAll("_", " ")}</strong>
              <small>
                {s.node} · {when(s.timestamp)}
              </small>
            </div>
            <span>{s.latency_ms.toFixed(1)} ms</span>
            <ChevronRight size={15} />
          </summary>
          <Json value={{ input: s.input, output: s.output }} />
        </details>
      ))}
    </div>
  );
}
export function IncidentPage() {
  const { id } = useParams();
  const { data, error } = useApi<Detail>(`/incidents/${id}`);
  const client = useQueryClient();
  const [reason, setReason] = useState("");
  const [params] = useSearchParams();
  const [section, setSection] = useState(
    params.get("section") === "investigator" ? "investigator" : "overview",
  );
  const [release, setRelease] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const action = useMutation({
    mutationFn: ({ type, hold }: { type: string; hold?: string }) =>
      type === "investigate"
        ? post(`/incidents/${id}/investigate`)
        : post(`/incidents/${id}/review`, {
            action: type,
            hold_id: hold,
            reason,
            expected_run_id: data?.runs.at(-1)?.id,
            evidence_ids:
              data?.decisions
                .filter(
                  (d) =>
                    (d as Decision & { run_id: string }).run_id ===
                    data?.runs.at(-1)?.id,
                )
                .flatMap((d) => d.evidence_ids) || [],
          }),
    onSuccess: () => {
      setReason("");
      setRelease(null);
      void client.invalidateQueries();
    },
  });
  if (!data)
    return (
      <>
        <ErrorBox error={error} />
        {!error && <Loading />}
      </>
    );
  const latest = data.runs.at(-1);
  // Older saved runs appended model prose. Keep it in the trace, outside the operator response.
  const recordedSummary = latest?.summary.split(
    " Model commentary (not verification evidence): ",
  )[0];
  const responseDraft =
    latest?.draft.split(
      "\n\nUNVERIFIED MODEL WORDING — HUMAN REVIEW REQUIRED:\n",
    )[0] || "";
  const decisions = data.decisions.filter(
    (d) => latest?.id === (d as Decision & { run_id: string }).run_id,
  );
  return (
    <>
      <Link to="/incidents" className="back-link">
        <ArrowLeft size={15} /> All incidents
      </Link>
      <PageHeader
        eyebrow={`${data.incident.reference} · ${data.incident.mode.toUpperCase()} MODE`}
        title={data.incident.product_name}
        description={`${data.incident.store_name} · Last investigated ${when(data.incident.updated_at)}`}
        action={
          <Button
            disabled={action.isPending}
            onClick={() => action.mutate({ type: "investigate" })}
          >
            <Play size={15} /> Investigate again
          </Button>
        }
      />
      <ErrorBox error={error || action.error} />
      <div className="incident-status">
        <Badge value={data.incident.status} />
        <span>{data.incident.affected_quantity} units on internal hold</span>
        <Link className="text-link" to={`/evidence?incident=${id}`}>
          <GitBranch size={16} /> Explore evidence graph
        </Link>
      </div>
      <div className="incident-sections" aria-label="Incident sections">
        {[
          ["overview", "Decision & response"],
          ["investigator", "Investigator"],
          ["evidence", "Evidence & execution"],
          ["history", "Activity history"],
        ].map(([value, label]) => (
          <button
            key={value}
            aria-pressed={section === value}
            onClick={() => setSection(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {section === "investigator" && (
        <InvestigatorPanel key={data.incident.id} detail={data} />
      )}
      {section === "overview" && (
        <div className="two-col">
          <Panel
            title="Official recall"
            caption={`Version ${data.recall.official_version} · Published ${when(data.recall.published_at)}`}
          >
            <div className="settings-body">
              <h3>{data.recall.brand}</h3>
              {data.recall.clock_warnings?.map((w) => (
                <p className="mode-notice" key={w}>
                  {w}
                </p>
              ))}
              <p>{data.recall.reason}</p>
              <div className="risk-box">
                <ShieldAlert size={18} />
                {data.recall.risk}
              </div>
              <dl>
                <dt>Ingested</dt>
                <dd>{when(data.recall.ingested_at)}</dd>
                <dt>Source identifier</dt>
                <dd>{data.recall.source_id}</dd>
              </dl>
              <a
                href={data.recall.source_url}
                className="text-link"
                target="_blank"
                rel="noreferrer"
              >
                Open official recall <ArrowUpRight size={15} />
              </a>
              <details>
                <summary>Original source record</summary>
                <Json value={data.recall.raw} />
              </details>
            </div>
          </Panel>
          <Panel
            title="Latest conclusions"
            caption={
              latest
                ? `${latest.llm_mode} · ${latest.latency_ms?.toFixed(1) ?? "Running"} ms · ${latest.active_node}`
                : "Awaiting investigation"
            }
          >
            <Decisions decisions={decisions} />
            {recordedSummary && (
              <p className="summary-text">{recordedSummary}</p>
            )}
          </Panel>
        </div>
      )}
      {section === "evidence" && (
        <>
          <SupplierEvidenceForm key={data.incident.id} detail={data} />
          <OfficialDocuments detail={data} />
          <div className="two-col">
            <Panel
              title="Agent execution trace"
              caption="Persisted tool inputs, outputs and measured timings"
            >
              {latest ? <RunSteps run={latest} /> : <Empty />}
            </Panel>
            <Panel
              title="Evidence & contradictions"
              caption="Actual stored records used in the investigation"
            >
              <div className="evidence-list">
                {data.evidence.map((e) => (
                  <details key={e.id}>
                    <summary>
                      <Badge value={e.kind} />
                      <strong>{e.label}</strong>
                      <small>
                        {e.synthetic
                          ? "Synthetic evidence"
                          : e.kind === "official"
                            ? "Official source"
                            : "Operator / inventory record"}{" "}
                        · {when(e.created_at)}
                      </small>
                    </summary>
                    {e.kind === "supplier" && (
                      <div className="supplier-summary">
                        <dl>
                          <dt>Supplier</dt>
                          <dd>
                            {String(e.payload.supplier || "Not recorded")}
                          </dd>
                          <dt>Stated lot</dt>
                          <dd>{String(e.payload.lot || "Not recorded")}</dd>
                          <dt>Reference</dt>
                          <dd>
                            {String(e.payload.reference || "Scenario record")}
                          </dd>
                        </dl>
                        <p>{String(e.payload.message || "")}</p>
                      </div>
                    )}
                    <details>
                      <summary>View stored record</summary>
                      <Json value={e.payload} />
                    </details>
                    {e.source_url && (
                      <a href={e.source_url} target="_blank" rel="noreferrer">
                        Source record ↗
                      </a>
                    )}
                  </details>
                ))}
              </div>
            </Panel>
          </div>
        </>
      )}
      {section === "overview" && (
        <div className="two-col">
          <Panel
            title="Human review"
            caption="Hold releases require an operator token and a recorded reason."
          >
            <div className="settings-body">
              <p>
                Owner: {data.incident.assigned_to || "Unassigned"} · Review:{" "}
                {data.incident.review_status || "open"}
              </p>
              <label className="field-label" htmlFor="reason">
                Review notes
              </label>
              <textarea
                id="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Record the evidence and reason for your decision…"
              />
              <small>
                Use at least 10 characters to explain the evidence behind your
                decision.
              </small>
              <Button
                variant="outline"
                disabled={reason.trim().length < 10 || action.isPending}
                onClick={() => action.mutate({ type: "acknowledge" })}
              >
                Record review note
              </Button>
              <div className="button-row">
                <Button
                  variant="outline"
                  disabled={reason.trim().length < 10 || action.isPending}
                  onClick={() => action.mutate({ type: "assign" })}
                >
                  Assign to me
                </Button>
                <Button
                  variant="outline"
                  disabled={
                    reason.trim().length < 10 ||
                    action.isPending ||
                    decisions.some((d) => d.verdict !== "unaffected") ||
                    data.holds.some((h) => h.status === "active")
                  }
                  onClick={() => action.mutate({ type: "close" })}
                >
                  Close reviewed case
                </Button>
                {data.incident.review_status === "closed" && (
                  <Button
                    variant="outline"
                    disabled={reason.trim().length < 10 || action.isPending}
                    onClick={() => action.mutate({ type: "reopen" })}
                  >
                    Reopen review
                  </Button>
                )}
              </div>
              {data.holds
                .filter((h) => h.status === "active")
                .map((h) => (
                  <div className="hold-row" key={h.id}>
                    <span>
                      <Badge value="held" /> {h.quantity} units
                    </span>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={reason.trim().length < 10 || action.isPending}
                      onClick={() => setRelease(h.id)}
                    >
                      Authorize release
                    </Button>
                  </div>
                ))}
              {release && (
                <div
                  className="release-confirm"
                  role="region"
                  aria-label="Confirm hold release"
                >
                  <strong>
                    Release {data.holds.find((h) => h.id === release)?.quantity}{" "}
                    units from internal hold?
                  </strong>
                  <p>
                    Your review notes will be saved with this release. Check the
                    supporting evidence before continuing.
                  </p>
                  <div className="button-row">
                    <Button
                      variant="destructive"
                      disabled={reason.trim().length < 10 || action.isPending}
                      onClick={() =>
                        action.mutate({ type: "release_hold", hold: release })
                      }
                    >
                      Confirm release
                    </Button>
                    <Button variant="outline" onClick={() => setRelease(null)}>
                      Keep hold
                    </Button>
                  </div>
                </div>
              )}
              {action.isSuccess && <p role="status">Action recorded.</p>}
            </div>
          </Panel>
          <Panel
            title="Supplier notification draft"
            caption="Built from recorded decisions. Review before sharing; no message has been sent."
          >
            <div className="settings-body">
              <p className="draft">
                {responseDraft ||
                  "A draft will be prepared after investigation."}
              </p>
              <Button
                variant="outline"
                disabled={!responseDraft}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(responseDraft);
                    setCopyStatus("Draft copied to clipboard.");
                  } catch {
                    setCopyStatus(
                      "Could not copy. Select and copy the draft text above.",
                    );
                  }
                }}
              >
                Copy draft
              </Button>
              {copyStatus && <small role="status">{copyStatus}</small>}
            </div>
          </Panel>
        </div>
      )}
      {section === "history" && (
        <Panel
          title="Incident history"
          caption="Append-only chronological events"
        >
          <div className="feed">
            {data.history.map((e) => (
              <div key={e.id}>
                <span className="feed-dot" />
                <div>
                  <strong>{e.kind.replaceAll("_", " ")}</strong>
                  <p>
                    {String(
                      e.payload.message || e.payload.node || "State persisted",
                    )}
                  </p>
                </div>
                <time>{when(e.created_at)}</time>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </>
  );
}
export function TimeMachinePage() {
  const [replayId, setReplayId] = useState(
    sessionStorage.getItem("replay-id") || "",
  );
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);
  const client = useQueryClient();
  const { setMode } = useMode();
  const query = useApi<Replay | null>(
    replayId ? `/demo/replay/${replayId}` : "/demo/replay/latest",
  );
  const replay = query.data;
  useEffect(() => {
    if (replay && !replayId) {
      setReplayId(replay.id);
      setSelected(replay.step);
    }
  }, [replay, replayId]);
  const start = useMutation({
    mutationFn: () => post<Replay>("/demo/replay/start"),
    onSuccess: (r) => {
      setMode("replay");
      setReplayId(r.id);
      sessionStorage.setItem("replay-id", r.id);
      setSelected(0);
      void client.invalidateQueries();
    },
  });
  const next = useMutation({
    mutationFn: () =>
      post<Replay>("/demo/replay/next", {
        replay_id: replayId,
        expected_step: replay?.step ?? 0,
      }),
    onSuccess: (r) => {
      setSelected(r.step);
      void client.invalidateQueries();
    },
  });
  useEffect(() => {
    if (!playing) return;
    if (!replay || replay.step >= 2) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => next.mutate(), 2000);
    return () => clearTimeout(t);
  }, [playing, replay?.step, next.mutate]);
  const runs = replay?.detail.runs || [];
  const runId = replay?.events.find((e) => e.step === selected)?.run_id;
  const current = runs.find((r) => r.id === runId);
  const prevId = replay?.events.find(
    (e) => e.step === Math.max(0, selected - 1),
  )?.run_id;
  const previous = runs.find((r) => r.id === prevId);
  const selectDecisions = (run?: Run) =>
    replay?.detail.decisions.filter(
      (d) => (d as Decision & { run_id: string }).run_id === run?.id,
    ) || [];
  return (
    <>
      <PageHeader
        eyebrow="THE SAME CASE. NEW EVIDENCE. A REVISED DECISION."
        title="Decision time machine"
        description="Travel through an actual investigation and see exactly why its conclusions changed."
        action={
          <Button
            variant="outline"
            disabled={start.isPending}
            onClick={() => {
              setPlaying(false);
              start.mutate();
            }}
          >
            <RotateCcw size={16} />
            {replay ? "Reset & start new replay" : "Start recorded scenario"}
          </Button>
        }
      />
      <ErrorBox error={query.error || start.error || next.error} />
      <div className="mode-notice">
        <Timer size={16} />
        <strong>Historical record + synthetic events</strong>
        <span>
          Official recall stays immutable. Warehouse and supplier updates are
          fictional.
        </span>
      </div>
      {!replay ? (
        <Empty title="Meet your next investigation">
          Start the recorded scenario to load a genuine archived recall and
          fictional store inventory.
        </Empty>
      ) : (
        <>
          <div className="replay-controls">
            <Button
              variant="outline"
              disabled={replay.step >= 2 || next.isPending}
              onClick={() => setPlaying(!playing)}
            >
              {playing ? <Pause size={16} /> : <Play size={16} />}{" "}
              {playing ? "Pause" : "Play scenario"}
            </Button>
            <Button
              disabled={replay.step >= 2 || next.isPending}
              onClick={() => next.mutate()}
            >
              {next.isPending ? "Investigating…" : "Inject next evidence"}
              <ArrowRight size={16} />
            </Button>
            <span>
              Stage {replay.step + 1} of 3 ·{" "}
              {replay.step === 2 ? "Scenario complete" : "Ready for next event"}
            </span>
            <Link className="text-link" to={`/incidents/${replay.incident_id}`}>
              Open incident <ArrowUpRight size={14} />
            </Link>
          </div>
          <div className="replay-track">
            {[
              "Initial lot verification",
              "Warehouse confirms 24 units",
              "Supplier contradicts stock",
            ].map((label, i) => (
              <button
                key={label}
                className={`${selected === i ? "selected" : ""} ${i <= replay.step ? "recorded" : ""}`}
                disabled={i > replay.step}
                onClick={() => setSelected(i)}
              >
                <span>
                  {i < replay.step ? (
                    <CheckCheck size={17} />
                  ) : (
                    String(i + 1).padStart(2, "0")
                  )}
                </span>
                <div>
                  <strong>{label}</strong>
                  <small>
                    {replay.events.find((e) => e.step === i)
                      ? when(
                          replay.events.find((e) => e.step === i)!.created_at,
                        )
                      : "Not yet received"}
                  </small>
                </div>
              </button>
            ))}
          </div>
          <div className="two-col compare">
            <Panel
              title={
                selected === 0 ? "Official scope at start" : "Previous decision"
              }
              caption={
                selected === 0
                  ? "Ground truth from the archived source"
                  : `Before: ${previous?.llm_mode || ""}`
              }
            >
              {selected === 0 ? (
                <div className="settings-body">
                  <Badge value="official" />
                  <h3>{replay.detail.recall.product_name}</h3>
                  <p>{replay.detail.recall.reason}</p>
                  <code>
                    {String(replay.detail.recall.raw.identification_produits)}
                  </code>
                  <p>
                    Known different lot: no hold. Unknown lot: human review.
                  </p>
                  <a
                    className="text-link"
                    href={replay.detail.recall.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View original source <ArrowUpRight size={14} />
                  </a>
                </div>
              ) : (
                <Decisions decisions={selectDecisions(previous)} />
              )}
            </Panel>
            <Panel
              title="Decision at selected moment"
              caption={`${current?.llm_mode || "Running"} · ${current?.latency_ms?.toFixed(1) ?? "…"} ms`}
              className="current-panel"
            >
              <Decisions decisions={selectDecisions(current)} />
            </Panel>
          </div>
          <div className="change-callout">
            <GitBranch size={21} />
            <div>
              <strong>What changed</strong>
              <p>
                {selected === 0
                  ? "The agent distinguishes an unrelated lot from inventory that needs more evidence."
                  : selected === 1
                    ? "A warehouse update resolves 24 unknown-lot units to the recalled lot. The incident reopens and a 24-unit internal hold is created."
                    : "A supplier record disputes the warehouse lot. The agent records the contradiction, escalates for review, and preserves the 24-unit protective hold."}
              </p>
            </div>
          </div>
          <Panel
            title="Tools executed at this moment"
            caption="Select a tool to inspect its recorded input and output."
          >
            {current ? <RunSteps run={current} /> : <Loading />}
          </Panel>
        </>
      )}
    </>
  );
}
export { GraphPage } from "./evidence-graph";
export function EvaluationPage() {
  const { data, error } = useApi<Evaluation | null>("/evaluation/latest");
  const client = useQueryClient();
  const run = useMutation({
    mutationFn: () => post<Evaluation>("/evaluation/run"),
    onSuccess: () => void client.invalidateQueries(),
  });
  return (
    <>
      <PageHeader
        eyebrow="MEASURED, NOT CLAIMED"
        title="Evaluation lab"
        description="Compare simple matching with evidence-aware verification on labeled development cases or a separately supplied evaluation set."
        action={
          <Button disabled={run.isPending} onClick={() => run.mutate()}>
            <Play size={16} />
            {run.isPending ? "Running benchmark…" : "Run benchmark"}
          </Button>
        }
      />
      <ErrorBox error={error || run.error} />
      <InvestigatorEvaluation />
      <BenchmarkImport />
      {!data ? (
        <Empty title="Put the system to the test">
          Run the benchmark to calculate real precision, recall, review handling
          and latency.
        </Empty>
      ) : (
        <>
          <div className="mode-notice">
            <CheckCheck size={16} />
            <strong>{data.sample_size} labeled cases</strong>
            <span>
              {data.benchmark} · Run {when(data.created_at)}
            </span>
          </div>
          <Panel
            title="Matching quality"
            caption="Scores calculated from benchmark predictions · higher is better"
          >
            <ResponsiveContainer width="100%" height={300}>
              <BarChart
                data={data.results}
                margin={{ top: 25, right: 30, left: 0, bottom: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="method" tick={{ fontSize: 12 }} />
                <YAxis
                  domain={[0, 1]}
                  tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
                />
                <Tooltip
                  formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`}
                />
                <Legend />
                <Bar dataKey="precision" fill="#182b4e" radius={[4, 4, 0, 0]} />
                <Bar dataKey="recall" fill="#51a48a" radius={[4, 4, 0, 0]} />
                <Bar dataKey="f1" fill="#8b9db9" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
          <Panel
            title="Measured results"
            caption="False-hold rate = false holds / nonaffected cases. Review accuracy = correct review requests / ambiguous cases."
          >
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Method</th>
                    <th>Precision</th>
                    <th>Recall</th>
                    <th>F1</th>
                    <th>False holds</th>
                    <th>Review accuracy</th>
                    <th>Mean latency</th>
                    <th>p50 / p95</th>
                    <th>Missed holds / review burden</th>
                    <th>Revision success</th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((r) => (
                    <tr key={r.method}>
                      <td>
                        <strong>{r.method}</strong>
                      </td>
                      {[
                        r.precision,
                        r.recall,
                        r.f1,
                        r.false_hold_rate,
                        r.review_accuracy,
                      ].map((v, i) => (
                        <td key={i}>{(v * 100).toFixed(1)}%</td>
                      ))}
                      <td>{r.latency_ms.toFixed(2)} ms</td>
                      <td>
                        {r.p50_latency_ms?.toFixed(1) ?? "—"} /{" "}
                        {r.p95_latency_ms?.toFixed(1) ?? "—"} ms
                      </td>
                      <td>
                        {r.missed_hold_rate === undefined
                          ? "—"
                          : `${(r.missed_hold_rate * 100).toFixed(1)}%`}{" "}
                        /{" "}
                        {r.review_request_rate === undefined
                          ? "—"
                          : `${(r.review_request_rate * 100).toFixed(1)}%`}
                      </td>
                      <td>
                        {r.revision_rate === null
                          ? "Not applicable"
                          : `${(r.revision_rate * 100).toFixed(1)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel
            title="Case-level evidence"
            caption="Synthetic benchmark labels are system tests, not official government claims."
          >
            <div className="evidence-list">
              {data.cases.map((c, i) => (
                <details key={i}>
                  <summary>
                    <strong>{String(c.name)}</strong>
                    {typeof c.expected === "string" && (
                      <Badge value={c.expected} />
                    )}
                  </summary>
                  <Json value={c} />
                </details>
              ))}
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
