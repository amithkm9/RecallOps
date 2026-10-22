import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMode } from "./App";
import { useApi, type Detail, type Decision, type Incident } from "./api";
import { Empty, ErrorBox, Json, PageHeader, Panel } from "./components/common";

export function GraphPage() {
  const { mode } = useMode();
  const [params, setParams] = useSearchParams();
  const incidents = useApi<{ items: Incident[] }>(`/incidents?mode=${mode}`);
  const id = params.get("incident") || incidents.data?.items[0]?.id;
  const { data, error } = useApi<Detail | null>(
    id ? `/incidents/${id}` : "/incidents/empty",
  );
  const [selected, setSelected] = useState<Node | null>(null);
  const graph = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    function node(
      id: string,
      label: string,
      x: number,
      y: number,
      payload: unknown,
      kind: string,
    ) {
      if (!nodes.some((n) => n.id === id))
        nodes.push({
          id,
          position: { x, y },
          data: { label, payload, kind },
          className: `graph-${kind}`,
        });
    }
    function edge(source: string, target: string) {
      if (!edges.some((e) => e.id === `${source}-${target}`))
        edges.push({ id: `${source}-${target}`, source, target });
    }
    node(
      "recall",
      `Official recall\n${data.incident.reference}`,
      0,
      130,
      data.recall,
      "official",
    );
    data.targets.forEach((t, n) => {
      const gid = `gtin-${t.gtin}`;
      node(
        gid,
        `GTIN\n${t.gtin}`,
        220,
        n * 130,
        { gtin: t.gtin, recall_version_id: t.recall_version_id },
        "official",
      );
      node(
        t.id,
        `Official target\n${String((t.scope.lots as string[])?.join(", ") || "Date / all-lots scope")}`,
        440,
        n * 130,
        t,
        "official",
      );
      edge("recall", gid);
      edge(gid, t.id);
    });
    data.inventory.forEach((i, n) => {
      node(
        i.id,
        `${i.sku}\nLot ${i.lot || "missing"} · ${i.quantity} units`,
        670,
        n * 160,
        { ...i, store_name: data.incident.store_name },
        i.lot ? "inventory" : "missing",
      );
      data.targets
        .filter((t) => t.gtin.padStart(14, "0") === i.gtin.padStart(14, "0"))
        .forEach((t) => edge(t.id, i.id));
    });
    const latest = data.runs.at(-1);
    const decisions = data.decisions.filter(
      (d) => (d as Decision & { run_id: string }).run_id === latest?.id,
    );
    const contributingIds = new Set(decisions.flatMap((d) => d.evidence_ids));
    data.evidence
      .filter((e) => contributingIds.has(e.id))
      .forEach((e, n) => {
        const stock = data.inventory.find(
          (i) => i.id === String(e.payload.inventory_lot_id || ""),
        );
        const normalizeLot = (lot: string) =>
          lot.normalize("NFKC").trim().toLowerCase();
        const supplierKind =
          !stock?.lot || !e.payload.lot
            ? "missing"
            : normalizeLot(stock.lot) === normalizeLot(String(e.payload.lot))
              ? "inventory"
              : "conflict";
        const kind =
          e.kind === "supplier"
            ? supplierKind
            : e.kind === "official"
              ? "official"
              : "inventory";
        node(
          e.id,
          `${e.kind.replaceAll("_", " ")} evidence\n${e.synthetic ? "Synthetic record" : e.kind === "official" ? "Official record" : "Operator / inventory record"}`,
          900,
          n * 120,
          e,
          kind,
        );
        const lotId = String(e.payload.inventory_lot_id || e.payload.id || "");
        if (e.kind === "official") edge("recall", e.id);
        else if (data.inventory.some((i) => i.id === lotId)) edge(lotId, e.id);
      });
    decisions.forEach((d, n) => {
      node(
        d.id,
        `${d.verdict.toUpperCase()}\n${d.action.replaceAll("_", " ")}`,
        1170,
        n * 180,
        d,
        d.verdict,
      );
      edge(d.inventory_lot_id, d.id);
      d.evidence_ids.forEach((e) => {
        if (nodes.some((n) => n.id === e)) edge(e, d.id);
      });
      data.holds
        .filter((h) => h.inventory_lot_id === d.inventory_lot_id)
        .forEach((h) => {
          node(
            h.id,
            `${h.status} internal hold\n${h.quantity} units`,
            1410,
            n * 180,
            h,
            "held",
          );
          edge(d.id, h.id);
        });
    });
    return { nodes, edges };
  }, [data]);
  return (
    <>
      <PageHeader
        eyebrow="FOLLOW THE PROVENANCE"
        title="Evidence graph"
        description="Every conclusion leads back to a source. Select any node to inspect its stored record."
      />
      <div className="toolbar">
        <select
          aria-label="Select incident"
          value={id || ""}
          onChange={(e) => {
            setParams({ incident: e.target.value });
            setSelected(null);
          }}
        >
          {incidents.data?.items.map((i) => (
            <option key={i.id} value={i.id}>
              {i.reference} · {i.product_name}
            </option>
          ))}
        </select>
        <span className="graph-key">
          <i className="dot green" /> Confirmed <i className="dot" /> Missing{" "}
          <i className="dot red" /> Contradictory / held
        </span>
      </div>
      <ErrorBox error={error} />
      {!id ? (
        <Empty title="No evidence graph yet" />
      ) : (
        <div className="graph-layout">
          <div className="graph-canvas">
            <ReactFlow
              nodes={graph.nodes}
              edges={graph.edges}
              fitView
              onNodeClick={(_, node) => setSelected(node)}
              nodesDraggable={false}
              nodesConnectable={false}
            >
              <Background color="#dce1e9" gap={22} />
              <Controls />
            </ReactFlow>
          </div>
          <Panel
            title={selected ? "Stored node record" : "Inspect the evidence"}
            caption={
              selected
                ? String(selected.data.kind)
                : "Click a node in the graph"
            }
          >
            {selected ? (
              <div className="node-data">
                <Json value={selected.data.payload} />
                {selected.id === "recall" && data && (
                  <a
                    className="text-link"
                    href={data.recall.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Official source ↗
                  </a>
                )}
              </div>
            ) : (
              <Empty title="A decision is only as good as its evidence">
                Select an official recall, target, stock lot, evidence record,
                decision, or hold to see the underlying stored data.
              </Empty>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
