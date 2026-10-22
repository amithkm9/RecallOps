import { Operations } from "./components/operations";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileSearch,
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  Clock3,
  Database,
  Download,
  PackageCheck,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  Upload,
  TriangleAlert,
  ArrowDownRight,
  ShieldCheck,
  ScanLine,
} from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import {
  api,
  post,
  useApi,
  when,
  type Dashboard,
  type Incident,
  type Inventory,
  type Replay,
  type Settings,
} from "./api";
import { useMode } from "./App";
import { Button } from "./components/ui/button";
import {
  Badge,
  Empty,
  ErrorBox,
  IncidentTable,
  Loading,
  PageHeader,
  Panel,
} from "./components/common";
export function DashboardPage() {
  const { mode, setMode } = useMode();
  const { data, error } = useApi<Dashboard>(`/dashboard?mode=${mode}`);
  const navigate = useNavigate();
  const client = useQueryClient();
  const [queue, setQueue] = useState("all");
  const simulation = useMutation({
    mutationFn: () => post<Replay>("/demo/replay/start"),
    onSuccess: (r) => {
      setMode("replay");
      sessionStorage.setItem("replay-id", r.id);
      void client.invalidateQueries();
      navigate("/time-machine");
    },
  });
  const investigatorDemo = useMutation({
    mutationFn: () =>
      post<{
        incident_id: string;
        unresolved_incident_id: string;
        message: string;
      }>("/investigator/demo"),
    onSuccess: (result) => {
      setMode("replay");
      void client.invalidateQueries();
      navigate(
        `/incidents/${result.incident_id}?section=investigator&unresolved=${result.unresolved_incident_id}`,
      );
    },
  });
  return (
    <>
      <PageHeader
        eyebrow="THE BIG PICTURE"
        title="Command overview"
        description="A clearer view of your recalls. A confident next move."
        action={
          <Button variant="outline" asChild>
            <Link to="/inventory">
              <Upload size={15} /> Import inventory
            </Link>
          </Button>
        }
      />
      <ErrorBox error={error || simulation.error || investigatorDemo.error} />
      <section className="overview-hero">
        <div className="hero-copy">
          <div className="hero-kicker">
            <span className="dot" /> PRODUCT SAFETY, CONNECTED
          </div>
          <h2>
            Every recall has a story.
            <br />
            <span>Stay one step ahead.</span>
          </h2>
          <p>
            Connect the source, find affected stock, and give your team the
            evidence to act.
          </p>
          <div className="button-row">
            {mode === "live" ? (
              <Button asChild>
                <Link to="/incidents?attention=review">
                  Review priority cases <ArrowRight size={15} />
                </Link>
              </Button>
            ) : (
              <Button
                onClick={() => simulation.mutate()}
                disabled={simulation.isPending}
              >
                <Play size={15} />
                {simulation.isPending
                  ? "Starting investigation…"
                  : "Run incident simulation"}
                <ArrowRight size={15} />
              </Button>
            )}
            <Link className="hero-link" to="/incidents">
              View investigations <ArrowUpRight size={15} />
            </Link>
          </div>
        </div>
        <div
          className="hero-diagram"
          aria-label="Workflow: official recall, stock verification, operator response"
        >
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="diagram-center">
            <ShieldCheck size={36} strokeWidth={1.3} />
          </div>
          <div className="diagram-node node-source">
            <Database size={16} />
            <div>
              <small>01 / SOURCE</small>
              <strong>Official recall</strong>
            </div>
            <CheckCheck size={14} />
          </div>
          <div className="diagram-node node-stock">
            <ScanLine size={16} />
            <div>
              <small>02 / VERIFY</small>
              <strong>Trace affected stock</strong>
            </div>
          </div>
          <div className="diagram-node node-action">
            <ShieldCheck size={16} />
            <div>
              <small>03 / RESPOND</small>
              <strong>Act with evidence</strong>
            </div>
            <ArrowUpRight size={14} />
          </div>
          <span className="diagram-caption">ONE CONNECTED INVESTIGATION</span>
        </div>
      </section>
      <div className="mode-notice">
        <span className="dot" />
        <strong>
          {mode === "replay"
            ? "Replay demo environment"
            : "Live data workspace"}
        </strong>
        <span>
          {mode === "replay"
            ? "Genuine archived recall. Fictional store inventory. Real agent execution."
            : "Official RappelConso records checked against your uploaded inventory."}
        </span>
        <Link to="/settings">
          Source details <ArrowUpRight size={14} />
        </Link>
      </div>
      {mode === "replay" && (
        <section className="investigator-demo">
          <div>
            <h2>Can the investigator find the missing batch?</h2>
            <p>
              Start a fictional delivery investigation. Inspect source excerpts,
              confirm a stock association, and see why the decision changes.
              Includes a case that must remain unresolved.
            </p>
          </div>
          <Button
            disabled={investigatorDemo.isPending}
            onClick={() => investigatorDemo.mutate()}
          >
            <FileSearch size={16} />
            {investigatorDemo.isPending
              ? "Preparing cases…"
              : "Start investigator demo"}
          </Button>
        </section>
      )}
      {!data ? (
        !error && <Loading />
      ) : (
        <>
          <div className="stat-grid">
            {[
              [
                ShieldAlert,
                "Active incidents",
                data.active_incidents,
                "Investigations requiring attention",
                "red",
              ],
              [
                PackageCheck,
                "Units on internal hold",
                data.affected_units,
                "Verified matches, protective holds",
                "navy",
              ],
              [
                TriangleAlert,
                "Awaiting review",
                data.awaiting_review,
                "Evidence needs a human decision",
                "amber",
              ],
              [
                CheckCheck,
                "Recorded hold actions",
                data.completed_actions,
                "Recorded internal hold actions",
                "green",
              ],
            ].map(([Icon, label, value, hint, color]) => {
              const I = Icon as typeof ShieldAlert;
              return (
                <Link
                  className={`stat stat-${color}`}
                  to={
                    label === "Awaiting review"
                      ? "/incidents?attention=review"
                      : label === "Units on internal hold"
                        ? "/incidents?attention=held"
                        : "/incidents"
                  }
                  key={String(label)}
                >
                  <div className="stat-top">
                    <span>{String(label)}</span>
                    <div className={`stat-icon ${color}`}>
                      <I size={19} />
                    </div>
                  </div>
                  <strong>{String(value).padStart(2, "0")}</strong>
                  <small>
                    {String(hint)} <ArrowUpRight size={13} />
                  </small>
                </Link>
              );
            })}
          </div>
          <div className="overview-grid">
            <Panel
              title="Your investigation queue"
              caption="Recent cases, with the next step in focus"
              action={
                <Link className="text-link" to="/incidents">
                  View all <ArrowRight size={15} />
                </Link>
              }
            >
              <div
                className="queue-filters"
                aria-label="Filter recent investigations"
              >
                {[
                  ["all", "All recent"],
                  ["review", "Needs review"],
                  ["held", "On hold"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    aria-pressed={queue === value}
                    className={queue === value ? "selected" : ""}
                    onClick={() => setQueue(value)}
                  >
                    {label}
                    <span>
                      {
                        data.latest_incidents.filter(
                          (i) =>
                            value === "all" ||
                            (value === "review"
                              ? ["review", "conflict"].includes(i.status)
                              : i.affected_quantity > 0),
                        ).length
                      }
                    </span>
                  </button>
                ))}
              </div>
              <IncidentTable
                compact
                items={data.latest_incidents.filter(
                  (i) =>
                    queue === "all" ||
                    (queue === "review"
                      ? ["review", "conflict"].includes(i.status)
                      : i.affected_quantity > 0),
                )}
              />
              {data.awaiting_review > 0 && (
                <Link className="queue-next" to="/incidents?attention=review">
                  <span className="next-icon">
                    <TriangleAlert size={18} />
                  </span>
                  <div>
                    <strong>
                      {data.awaiting_review}{" "}
                      {data.awaiting_review === 1 ? "case needs" : "cases need"}{" "}
                      a second look
                    </strong>
                    <p>
                      Resolve missing or conflicting evidence with your team.
                    </p>
                  </div>
                  <ArrowUpRight size={17} />
                </Link>
              )}
              <div className="panel-foot">
                <span className="dot green" /> Decisions and actions are linked
                to their supporting evidence.
              </div>
            </Panel>
            <Panel
              title="Decision outcomes"
              caption="Latest decision per inventory lot"
            >
              {data.outcomes.some((o) => o.value > 0) ? (
                <>
                  <div className="donut">
                    <ResponsiveContainer width="100%" height={190}>
                      <PieChart>
                        <Pie
                          data={data.outcomes}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={60}
                          outerRadius={79}
                          paddingAngle={4}
                          stroke="none"
                          isAnimationActive={false}
                        >
                          {data.outcomes.map((o, i) => (
                            <Cell
                              key={o.name}
                              fill={["#e25763", "#e7ac4a", "#51a48a"][i % 3]}
                            />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="donut-label">
                      <strong>
                        {data.outcomes.reduce((n, o) => n + o.value, 0)}
                      </strong>
                      <span>assessed lots</span>
                    </div>
                  </div>
                  <div className="legend">
                    {data.outcomes.map((o, i) => (
                      <div key={o.name}>
                        <span
                          style={{
                            background: ["#e25763", "#e7ac4a", "#51a48a"][
                              i % 3
                            ],
                          }}
                        />
                        {o.name}
                        <strong>{o.value}</strong>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <Empty title="No decisions yet">
                  Run a simulation to see measured outcomes.
                </Empty>
              )}
            </Panel>
          </div>
          <div className="section-label">
            <span>BEHIND THE DECISION</span>
            <ArrowDownRight size={17} />
          </div>
          <div className="lower-grid">
            <div className="time-promo">
              <div className="eyebrow">
                <Clock3 size={14} /> THE DECISION TIME MACHINE
              </div>
              <h2>
                New evidence.
                <br />A better-informed decision.
              </h2>
              <p>
                Watch an investigation evolve from missing lot information to a
                verified hold — and then a contradiction.
              </p>
              <Button variant="outline" asChild>
                <Link to="/time-machine">
                  Explore the replay <ArrowRight size={16} />
                </Link>
              </Button>
              <div className="mini-flow">
                <span>
                  <Search size={15} /> Verify
                </span>
                <i />
                <span>
                  <PackageCheck size={15} /> Hold
                </span>
                <i />
                <span>
                  <RefreshCw size={15} /> Reconsider
                </span>
              </div>
            </div>
            <Panel
              title="Operations feed"
              caption="A chronological record of what happened"
            >
              {data.activity.length ? (
                <div className="feed">
                  {data.activity.slice(0, 5).map((e) => (
                    <div key={e.id}>
                      <span className="feed-dot" />
                      <div>
                        <strong>{e.kind.replaceAll("_", " ")}</strong>
                        <p>
                          {String(
                            e.payload.message ||
                              e.payload.node ||
                              e.payload.action ||
                              "Evidence and investigation state recorded",
                          )}
                        </p>
                      </div>
                      <time>{when(e.created_at)}</time>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="Ready for your first investigation" />
              )}
            </Panel>
          </div>
          <div className="source-strip">
            <Database size={19} />
            <div>
              <strong>RappelConso · Official French recall data</strong>
              <span>
                Last successful refresh:{" "}
                {when(data.settings.last_successful_sync)} · {data.recall_count}{" "}
                stored recalls
              </span>
            </div>
            <Link to="/settings">
              Manage source <ArrowUpRight size={15} />
            </Link>
          </div>
        </>
      )}
    </>
  );
}
export function IncidentsPage() {
  const { mode } = useMode();
  const [params, setParams] = useSearchParams();
  const search = params.get("search") || "";
  const status = params.get("status") || "";
  const attention = params.get("attention") || "";
  function filter(key: string, value: string) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  }
  const { data, error } = useApi<{ items: Incident[] }>(
    `/incidents?mode=${mode}&search=${encodeURIComponent(search)}&status=${status}`,
  );
  const items = data?.items.filter(
    (i) =>
      !attention ||
      (attention === "review"
        ? ["review", "conflict"].includes(i.status)
        : i.affected_quantity > 0),
  );
  return (
    <>
      <PageHeader
        eyebrow="INVESTIGATE & RESPOND"
        title="Incidents"
        description="Each case connects an official recall, store inventory, and a defensible decision."
      />
      <div className="toolbar">
        <label className="search">
          <Search size={17} />
          <input
            placeholder="Search products or recall references"
            value={search}
            aria-label="Search incidents"
            onChange={(e) => filter("search", e.target.value)}
          />
        </label>
        <select
          aria-label="Filter incident status"
          value={status}
          onChange={(e) => filter("status", e.target.value)}
        >
          <option value="">All statuses</option>
          {["review", "held", "conflict", "unaffected", "investigating"].map(
            (s) => (
              <option key={s} value={s}>
                {s === "review"
                  ? "Needs review"
                  : s === "held"
                    ? "On hold"
                    : s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ),
          )}
        </select>
      </div>
      {attention && (
        <div className="filter-notice">
          <span>
            {attention === "review"
              ? "Showing cases that need human review, including conflicting evidence."
              : "Showing all cases with units on hold."}
          </span>
          <button onClick={() => filter("attention", "")}>Clear view ×</button>
        </div>
      )}
      <ErrorBox error={error} />
      <Panel
        title="Investigation register"
        caption={`${items?.length ?? 0} incidents · ${mode} mode`}
      >
        {items ? (
          items.length ? (
            <IncidentTable items={items} />
          ) : (
            <Empty
              title={
                search || status || attention
                  ? "No incidents match these filters"
                  : "Your investigation queue is clear"
              }
            >
              {search || status || attention ? (
                <Button variant="outline" onClick={() => setParams({})}>
                  Clear filters
                </Button>
              ) : (
                <Link className="text-link" to="/time-machine">
                  Try an incident simulation <ArrowRight size={14} />
                </Link>
              )}
            </Empty>
          )
        ) : (
          !error && <Loading />
        )}
      </Panel>
    </>
  );
}
export function InventoryPage() {
  const { mode } = useMode();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [storeId, setStoreId] = useState("");
  const stores =
    useApi<{ id: string; name: string; mode: string }[]>("/stores");
  const [file, setFile] = useState<File | null>(null);
  const [sampleError, setSampleError] = useState<Error | null>(null);
  const client = useQueryClient();
  const { data, error } = useApi<{ items: Inventory[]; total: number }>(
    `/inventory?mode=${mode}&search=${encodeURIComponent(search)}&page=${page}`,
  );
  const upload = useMutation({
    mutationFn: () => {
      const body = new FormData();
      if (file) body.append("file", file);
      body.append("mode", mode);
      if (storeId) body.append("store_id", storeId);
      return api<{
        imported: number;
        errors: { row: number; message: string }[];
      }>("/inventory/import", { method: "POST", body });
    },
    onSuccess: () => void client.invalidateQueries(),
  });
  async function sample() {
    setSampleError(null);
    try {
      const res = await fetch("/api/inventory/sample");
      if (!res.ok)
        throw new Error(
          "The sample could not be downloaded. Please try again.",
        );
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "recallops-inventory.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (error) {
      setSampleError(
        error instanceof Error ? error : new Error("Download failed."),
      );
    }
  }
  return (
    <>
      <PageHeader
        eyebrow="KNOW YOUR STOCK"
        title="Inventory & lots"
        description="GTINs identify the product. Lots and dates establish whether it is affected."
        action={
          <Button variant="outline" onClick={() => void sample()}>
            <Download size={16} /> Sample CSV
          </Button>
        }
      />
      <Panel
        title="Import inventory"
        caption="CSV columns: sku, product_name, gtin, lot, quantity, supplier, expires_on"
      >
        <div className="upload-row">
          <Upload size={23} />
          <select
            aria-label="Inventory import store"
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
          >
            <option value="">Default active store</option>
            {stores.data
              ?.filter((s) => s.mode === mode)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
          </select>
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="Inventory CSV"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <Button
            disabled={!file || upload.isPending}
            onClick={() => upload.mutate()}
          >
            {upload.isPending ? "Validating…" : "Validate & import"}
          </Button>
        </div>
        {upload.data && (
          <div className="import-result" role="status">
            <strong>{upload.data.imported} rows imported</strong>
            {upload.data.errors.map((e) => (
              <div className="error" key={e.row}>
                Row {e.row}: {e.message}
              </div>
            ))}
          </div>
        )}
      </Panel>
      <ErrorBox error={error || upload.error || sampleError} />
      <div className="toolbar">
        <label className="search">
          <Search size={17} />
          <input
            placeholder="Search SKU, GTIN, product or lot"
            aria-label="Search inventory"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <span className="muted">
          {data?.total ?? 0} lots ·{" "}
          {mode === "replay" ? "fictional demo inventory" : "store inventory"}
        </span>
      </div>
      <Panel title="Stock register">
        {!data ? (
          !error && <Loading />
        ) : !data.items.length ? (
          <Empty
            title={
              search
                ? "No stock matches your search"
                : "No inventory in this workspace"
            }
          >
            {search ? (
              <Button
                variant="outline"
                onClick={() => {
                  setSearch("");
                  setPage(1);
                }}
              >
                Clear search
              </Button>
            ) : (
              "Import a CSV or start the recorded scenario."
            )}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product / SKU</th>
                  <th>GTIN</th>
                  <th>Lot</th>
                  <th>Expiry</th>
                  <th>Units</th>
                  <th>Supplier</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <strong>{i.product_name}</strong>
                      <small>{i.sku}</small>
                    </td>
                    <td className="mono">{i.gtin}</td>
                    <td className="mono">
                      {i.lot || <span className="missing">Missing lot</span>}
                    </td>
                    <td>{i.expires_on || "—"}</td>
                    <td>{i.quantity}</td>
                    <td>{i.supplier}</td>
                    <td>
                      <Badge value={i.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pagination">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 1}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </Button>
          <span>Page {page}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={page * 20 >= (data?.total || 0)}
            onClick={() => setPage(page + 1)}
          >
            Next
          </Button>
        </div>
      </Panel>
    </>
  );
}
export function SettingsPage() {
  const { data, error } = useApi<Settings>("/settings");
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState(false);
  const client = useQueryClient();
  const modelCheck = useMutation({
    mutationFn: () =>
      post<{
        success: boolean;
        model: string;
        latency_ms: number | null;
        checked_at: string;
        message: string;
      }>("/settings/model-check"),
  });
  const sync = useMutation({
    mutationFn: (source: string) =>
      post<{ message: string }>("/recalls/sync", { source }),
    onSuccess: () => void client.invalidateQueries(),
  });
  return (
    <>
      <PageHeader
        eyebrow="CONNECTED & ACCOUNTABLE"
        title="Data & settings"
        description="Transparent sources, explicit capabilities, and controlled access."
      />
      <ErrorBox error={error || sync.error || modelCheck.error} />
      <div className="two-col">
        <Panel
          title="Official recall source"
          caption="French Ministry of Economy · RappelConso"
        >
          <div className="settings-body">
            <Database size={30} />
            <h3>Explore API 2.1</h3>
            <code>rappelconso-v2-gtin-trie</code>
            <p>
              {data?.coverage ||
                "The GTIN-based dataset does not include every recall."}
            </p>
            <dl>
              <dt>Last successful live refresh</dt>
              <dd>{when(data?.last_successful_sync)}</dd>
              <dt>Stored recall records</dt>
              <dd>{data?.source_count ?? 0}</dd>
              <dt>Automatic live refresh</dt>
              <dd>
                {data?.refresh_interval_seconds
                  ? `Every ${data.refresh_interval_seconds}s`
                  : "Manual only"}
              </dd>
            </dl>
            {data?.last_sync_error && (
              <p className="error">{data.last_sync_error}</p>
            )}
            <div className="button-row">
              <Button
                disabled={sync.isPending}
                onClick={() => sync.mutate("live")}
              >
                <RefreshCw size={15} /> Sync official data
              </Button>
              <Button
                variant="outline"
                disabled={sync.isPending}
                onClick={() => sync.mutate("snapshot")}
              >
                Load archived fixture
              </Button>
            </div>
            {sync.data && <p role="status">{sync.data.message}</p>}
            <a
              className="text-link"
              href={
                data?.dataset_url ||
                "https://www.data.gouv.fr/datasets/rappelconso-v2-rappels-de-produits"
              }
              target="_blank"
              rel="noreferrer"
            >
              Official dataset <ArrowUpRight size={14} />
            </a>
          </div>
        </Panel>
        <Panel
          title="Investigation engine"
          caption="Real tools. Explicit safety boundaries."
        >
          <div className="settings-body">
            <Badge
              value={
                data?.llm_enabled ? "llm_enabled" : "deterministic_fallback"
              }
            />
            <h3>
              {data?.llm_enabled
                ? data.llm_model
                : "Deterministic investigation mode"}
            </h3>
            <p>
              {data?.llm_enabled
                ? "An OpenAI-compatible model assists investigation planning and drafts. Deterministic checks control inventory actions."
                : "No model key is configured. LangGraph runs evidence retrieval, deterministic verification and safety tools without claiming an LLM call."}
            </p>
            <div className="model-check">
              <Button
                variant="outline"
                disabled={!data?.llm_enabled || modelCheck.isPending}
                onClick={() => modelCheck.mutate()}
              >
                <RefreshCw
                  size={15}
                  className={modelCheck.isPending ? "spin" : ""}
                />
                {modelCheck.isPending
                  ? "Testing provider…"
                  : "Test model connection"}
              </Button>
              <small>
                Makes one real request with fictional sample data using your
                server credentials.
              </small>
              {modelCheck.data && (
                <div
                  className={
                    modelCheck.data.success ? "connection-result" : "error"
                  }
                  role="status"
                >
                  <strong>
                    {modelCheck.data.success
                      ? "Connection verified"
                      : "Connection needs attention"}
                  </strong>
                  <p>{modelCheck.data.message}</p>
                  <small>
                    {modelCheck.data.model} ·{" "}
                    {modelCheck.data.latency_ms === null
                      ? "No request sent"
                      : `${(modelCheck.data.latency_ms / 1000).toFixed(2)}s`}{" "}
                    · {when(modelCheck.data.checked_at)}
                  </small>
                </div>
              )}
            </div>
            <ul className="policy-list">
              <li>
                <CheckCheck size={16} /> Confirmed matches create internal
                holds.
              </li>
              <li>
                <TriangleAlert size={16} /> Uncertainty escalates for human
                review.
              </li>
              <li>
                <ShieldAlert size={16} /> Contradictions never release existing
                holds.
              </li>
              <li>
                <Clock3 size={16} /> Supplier communications remain drafts.
              </li>
            </ul>
            <label className="field-label" htmlFor="access-token">
              Operator access token
            </label>
            <input
              id="access-token"
              type="password"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setSaved(false);
              }}
              placeholder="Required when server authentication is enabled"
            />
            <Button
              variant="outline"
              onClick={() => {
                sessionStorage.setItem("recallops-token", key);
                window.dispatchEvent(new Event("recallops-auth-change"));
                setSaved(true);
                void client.invalidateQueries();
              }}
            >
              Save for this session
            </Button>
            {saved && <p role="status">Token saved to this browser session.</p>}
            <small>
              Model credentials are configured on the server and never sent to
              the browser.
            </small>
          </div>
        </Panel>
      </div>
      <Operations settings={data} />
    </>
  );
}
