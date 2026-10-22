import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, post, when, type Settings } from "../api";
import { Panel, ErrorBox, Json, Badge } from "./common";
import { Button } from "./ui/button";

interface Refresh {
  id: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  details: {
    created?: number;
    skipped?: number;
    errors?: string[];
    records_received?: number;
    next_offset?: number;
    truncated?: boolean;
    origin?: string;
    scans?: unknown[];
  };
}
interface QueuedEvent {
  id: string;
  status: string;
  kind: string;
  attempts: number;
  error: string | null;
  available_at: string;
  incident_id: string | null;
}
interface Credential {
  id: string;
  name: string;
  role: string;
  active: boolean;
  store_ids: string[];
  token?: string;
}
interface Store {
  id: string;
  name: string;
  mode: string;
}

export function Operations({ settings }: { settings?: Settings }) {
  const [tab, setTab] = useState("sources");
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("operator");
  const [store, setStore] = useState("");
  const [secret, setSecret] = useState("");
  const [storeName, setStoreName] = useState("");
  const client = useQueryClient();
  const health = useQuery({
    queryKey: ["/operations/health"],
    queryFn: () =>
      api<{
        status: string;
        worker_heartbeat: string | null;
        alerts: string[];
      }>("/operations/health"),
    enabled: tab === "recovery",
    retry: false,
    refetchInterval: 15000,
  });
  const refreshes = useQuery({
    queryKey: ["/operations/refreshes"],
    queryFn: () => api<Refresh[]>("/operations/refreshes"),
    enabled: tab === "sources",
    retry: false,
  });
  const failures = useQuery({
    queryKey: ["/operations/events"],
    queryFn: () => api<QueuedEvent[]>("/operations/events"),
    enabled: tab === "recovery",
    retry: false,
    refetchInterval: 5000,
  });
  const credentials = useQuery({
    queryKey: ["/operations/credentials"],
    queryFn: () => api<Credential[]>("/operations/credentials"),
    enabled: tab === "access",
    retry: false,
  });
  const stores = useQuery({
    queryKey: ["/stores"],
    queryFn: () => api<Store[]>("/stores"),
    enabled: tab === "access",
    retry: false,
  });
  const rejected = useQuery({
    queryKey: ["source-rejections", selected],
    queryFn: () =>
      api<unknown[]>(`/operations/refreshes/${selected}/rejections`),
    enabled: !!selected && tab === "sources",
    retry: false,
  });
  const mutate = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) =>
      post<Credential | { message: string }>(path, body),
    onSuccess: (result) => {
      if ("token" in result && result.token) setSecret(result.token);
      void client.invalidateQueries();
    },
  });
  const error =
    mutate.error ||
    (tab === "sources"
      ? refreshes.error || rejected.error
      : tab === "access"
        ? credentials.error || stores.error
        : failures.error);
  return (
    <Panel
      title="Operations & access"
      caption="Recorded refreshes, controlled recovery and named credentials."
    >
      <div className="settings-body">
        {!settings?.auth_required && (
          <p className="mode-notice">
            Local development access is open. Configure OPERATOR_TOKEN and
            ENVIRONMENT=production before exposing this server online.
          </p>
        )}
        <div className="button-row">
          {[
            ["sources", "Source history"],
            ["recovery", "Worker recovery"],
            ["access", "Access & stores"],
          ].map(([id, label]) => (
            <Button
              key={id}
              variant={tab === id ? "default" : "outline"}
              onClick={() => setTab(id)}
            >
              {label}
            </Button>
          ))}
        </div>
        <ErrorBox error={error} />
        {tab === "sources" && (
          <>
            <p>
              Bounded scans do not cover the whole catalog. A missing record
              never releases stock or proves a recall was withdrawn.
            </p>
            {!refreshes.data?.length && !refreshes.error && (
              <p>
                No refresh history yet. Synchronize official data to record a
                run.
              </p>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Started</th>
                    <th>Status</th>
                    <th>Received</th>
                    <th>New / duplicate</th>
                    <th>Coverage</th>
                    <th>Inspect</th>
                  </tr>
                </thead>
                <tbody>
                  {refreshes.data?.map((r) => (
                    <tr key={r.id}>
                      <td>{when(r.created_at)}</td>
                      <td>
                        <Badge value={r.status} />
                      </td>
                      <td>{r.details.records_received ?? "—"}</td>
                      <td>
                        {r.details.created ?? 0} / {r.details.skipped ?? 0}
                      </td>
                      <td>
                        {r.details.truncated
                          ? "More records remain"
                          : r.details.origin || "See trace"}
                      </td>
                      <td>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setSelected(r.id)}
                        >
                          Inspect refresh
                        </Button>
                        {r.details.next_offset != null && (
                          <Button
                            size="sm"
                            disabled={mutate.isPending}
                            onClick={() =>
                              mutate.mutate({
                                path: "/recalls/sync",
                                body: {
                                  source: "live",
                                  start_offset: r.details.next_offset,
                                },
                              })
                            }
                          >
                            Scan next page
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {selected && (
              <>
                <h3>Refresh details & rejected records</h3>
                <Json value={refreshes.data?.find((r) => r.id === selected)} />
                <Json value={rejected.data || []} />
              </>
            )}
          </>
        )}
        {tab === "recovery" && (
          <>
            {health.data && (
              <div>
                <Badge value={health.data.status} />
                <p>Worker heartbeat: {when(health.data.worker_heartbeat)}</p>
                {health.data.alerts.map((a) => (
                  <p className="mode-notice" key={a}>
                    {a}
                  </p>
                ))}
              </div>
            )}
            <label className="field-label" htmlFor="retry-reason">
              Reason for retry
            </label>
            <input
              id="retry-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain what was fixed before retrying"
            />
            {!failures.data?.length && !failures.error && (
              <p>No pending, processing or failed events.</p>
            )}
            {failures.data?.map((e) => (
              <article className="hold-row" key={e.id}>
                <div>
                  <strong>{e.kind.replaceAll("_", " ")}</strong>
                  <p>
                    <Badge value={e.status} /> · {e.attempts} attempts ·{" "}
                    {e.error || "No error"}
                  </p>
                  <small>Available {when(e.available_at)}</small>
                </div>
                <Button
                  variant="outline"
                  disabled={
                    e.status !== "failed" ||
                    reason.trim().length < 10 ||
                    mutate.isPending
                  }
                  onClick={() =>
                    mutate.mutate({
                      path: `/operations/events/${e.id}/retry`,
                      body: { reason },
                    })
                  }
                >
                  Retry failed event
                </Button>
              </article>
            ))}
          </>
        )}
        {tab === "access" && (
          <>
            <label className="field-label" htmlFor="new-store-name">
              New store name
            </label>
            <input
              id="new-store-name"
              value={storeName}
              onChange={(e) => setStoreName(e.target.value)}
            />
            <Button
              variant="outline"
              disabled={storeName.trim().length < 2 || mutate.isPending}
              onClick={() =>
                mutate.mutate({ path: "/stores", body: { name: storeName } })
              }
            >
              Create store
            </Button>
            <p>
              Credentials are stored as hashes. Operators and integrations are
              restricted to the selected store; viewers cannot change data.
            </p>
            <label className="field-label" htmlFor="credential-name">
              Person or integration name
            </label>
            <input
              id="credential-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <div className="button-row">
              <select
                aria-label="Credential role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {["operator", "viewer", "integration", "admin"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
              <select
                aria-label="Credential store"
                value={store}
                onChange={(e) => setStore(e.target.value)}
                disabled={role === "admin"}
              >
                <option value="">Select a store</option>
                {stores.data?.map((s) => (
                  <option value={s.id} key={s.id}>
                    {s.name} · {s.mode}
                  </option>
                ))}
              </select>
            </div>
            <Button
              disabled={
                name.trim().length < 2 ||
                (role !== "admin" && !store) ||
                mutate.isPending
              }
              onClick={() =>
                mutate.mutate({
                  path: "/operations/credentials",
                  body: {
                    name,
                    role,
                    store_ids: role === "admin" ? [] : [store],
                  },
                })
              }
            >
              Create scoped credential
            </Button>
            {secret && (
              <div className="mode-notice">
                <strong>
                  Save this token now. It will not be retrievable again.
                </strong>
                <input aria-label="New access token" readOnly value={secret} />
                <Button variant="outline" onClick={() => setSecret("")}>
                  Hide token
                </Button>
              </div>
            )}
            {credentials.data?.map((c) => (
              <div className="hold-row" key={c.id}>
                <span>
                  {c.name} · {c.role} · {c.active ? "active" : "revoked"}
                </span>
                <Button
                  variant="outline"
                  disabled={!c.active || mutate.isPending}
                  onClick={() =>
                    mutate.mutate({
                      path: `/operations/credentials/${c.id}/revoke`,
                    })
                  }
                >
                  Revoke
                </Button>
              </div>
            ))}
          </>
        )}
        {mutate.isSuccess && <p role="status">Operation recorded.</p>}
      </div>
    </Panel>
  );
}
