import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { post, useApi, when } from "../api";
import { Badge, ErrorBox, Json, Panel } from "./common";
import { Button } from "./ui/button";
interface InvestigatorEvaluationResult {
  id: string;
  created_at: string;
  sample_size: number;
  benchmark: string;
  results: {
    method: string;
    strategy: string;
    accuracy: number;
    resolved_rate: number;
    review_request_rate: number;
    incorrect_exclusions: number;
    incorrect_holds: number;
    tool_calls: number;
    operator_interventions: number;
    setup_confirmations: number;
    p50_latency_ms: number;
    p95_latency_ms: number;
    model_calls: number;
    input_tokens: number;
    output_tokens: number;
    mode: string;
    actual_modes?: string[];
  }[];
  cases: {
    name: string;
    expected?: string;
    predictions: Record<string, unknown>;
    run_ids: Record<string, unknown>;
    tool_calls: Record<string, unknown>;
  }[];
}
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
interface InvestigationDataset {
  source: string;
  labeler: string;
  independent_review_declared: boolean;
  cases: {
    name: string;
    expected: string;
    split?: string;
    claims?: unknown[];
  }[];
}
export function parseInvestigationDataset(text: string): InvestigationDataset {
  const value = JSON.parse(text);
  if (
    !value ||
    typeof value !== "object" ||
    typeof value.source !== "string" ||
    value.source.trim().length < 3 ||
    typeof value.labeler !== "string" ||
    value.labeler.trim().length < 3
  )
    throw new Error(
      "Dataset source and labeler are required (at least 3 characters each).",
    );
  if (
    !Array.isArray(value.cases) ||
    value.cases.length < 1 ||
    value.cases.length > 100
  )
    throw new Error("Provide between 1 and 100 labeled cases.");
  value.cases.forEach(
    (item: InvestigationDataset["cases"][number], index: number) => {
      if (
        !item ||
        typeof item.name !== "string" ||
        !item.name.trim() ||
        !["affected", "unaffected", "review", "conflict"].includes(
          item.expected,
        )
      )
        throw new Error(
          `Case ${index + 1} needs a name and an expected verdict: affected, unaffected, review, or conflict.`,
        );
      if (item.split && !["development", "held_out"].includes(item.split))
        throw new Error(
          `Case ${index + 1} split must be development or held_out.`,
        );
      if (
        item.claims &&
        (!Array.isArray(item.claims) || item.claims.length > 10)
      )
        throw new Error(`Case ${index + 1} can contain at most 10 claims.`);
    },
  );
  return value;
}
const sampleDataset = {
  source: "Replace with the dataset provenance",
  labeler: "Replace with the label author",
  independent_review_declared: false,
  cases: [
    {
      name: "Example: missing batch remains unresolved",
      lot: null,
      claims: [],
      expected: "review",
      split: "development",
    },
  ],
};
export function InvestigatorEvaluation() {
  const query = useApi<InvestigatorEvaluationResult | null>(
    "/investigator/evaluation/latest",
  );
  const [includeModel, setIncludeModel] = useState(false),
    [includeMemory, setIncludeMemory] = useState(true);
  const [dataset, setDataset] = useState<InvestigationDataset | null>(null);
  const [importError, setImportError] = useState<Error | null>(null);
  const [reading, setReading] = useState(false);
  const [importKey, setImportKey] = useState(0);
  const client = useQueryClient();
  const run = useMutation({
    mutationFn: () =>
      post<InvestigatorEvaluationResult>("/investigator/evaluation", {
        include_model: includeModel,
        include_memory: includeMemory,
        ...(dataset ? { dataset } : {}),
      }),
    onSuccess: () => void client.invalidateQueries(),
  });
  const result = run.data || query.data;
  return (
    <Panel
      title="Does investigation improve the outcome?"
      caption="Compare the existing workflow, fixed retrieval, and adaptive investigation on the same labeled cases."
    >
      <form
        className="evidence-form"
        onSubmit={(event) => {
          event.preventDefault();
          run.mutate();
        }}
      >
        <details className="investigator-dataset-import">
          <summary>Use a separately labeled investigation dataset</summary>
          <label>
            Investigator evaluation JSON (optional, maximum 2 MB)
            <input
              key={importKey}
              type="file"
              accept=".json,application/json"
              disabled={run.isPending || reading}
              onChange={async (event) => {
                const file = event.target.files?.[0];
                setDataset(null);
                setImportError(null);
                if (!file) return;
                if (file.size > 2 * 1024 * 1024) {
                  setImportError(
                    new Error("The evaluation file must be 2 MB or smaller."),
                  );
                  return;
                }
                setReading(true);
                try {
                  setDataset(parseInvestigationDataset(await file.text()));
                } catch (error) {
                  setImportError(
                    error instanceof Error
                      ? error
                      : new Error("Could not read the evaluation dataset."),
                  );
                } finally {
                  setReading(false);
                }
              }}
            />
          </label>
          <a
            className="text-link"
            download="investigator-evaluation-example.json"
            href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(sampleDataset, null, 2))}`}
          >
            Download example JSON
          </a>
          {dataset && (
            <div role="status">
              <p>
                <strong>{dataset.cases.length} cases loaded</strong> · Source:{" "}
                {dataset.source} · Labeler: {dataset.labeler}
              </p>
              <p>
                Independent review{" "}
                {dataset.independent_review_declared
                  ? "declared"
                  : "not declared"}
                . Independence and held-out status are author declarations, not
                verified by RecallOps.
              </p>
            </div>
          )}
          <ErrorBox error={importError} />
          {(dataset || importError) && (
            <Button
              variant="outline"
              type="button"
              disabled={run.isPending || reading}
              onClick={() => {
                setDataset(null);
                setImportError(null);
                setImportKey((value) => value + 1);
              }}
            >
              Use built-in development cases
            </Button>
          )}
        </details>
        <div className="investigator-evaluation-options">
          <label className="investigator-check">
            <input
              type="checkbox"
              checked={includeMemory}
              onChange={(event) => setIncludeMemory(event.target.checked)}
              disabled={run.isPending}
            />
            Include retrieval-memory comparison
          </label>
          <label className="investigator-check">
            <input
              type="checkbox"
              checked={includeModel}
              onChange={(event) => setIncludeModel(event.target.checked)}
              disabled={run.isPending}
            />
            Also run the configured language model (uses provider tokens)
          </label>
        </div>
        <p className="investigator-evaluation-note">
          Developer-authored synthetic labels are not independent customer
          validation. Offline adaptive retrieval measures a policy; it does not
          demonstrate language-model reasoning. Latency and calls reflect this
          run. Setup confirmations count human validation supplied before
          retrieval; a resolved case does not mean the agent accepted evidence
          autonomously.
        </p>
        <Button
          type="submit"
          disabled={run.isPending || reading || Boolean(importError)}
        >
          <Play size={15} />
          {run.isPending
            ? "Running investigation comparison…"
            : "Compare investigation strategies"}
        </Button>
        <ErrorBox error={run.error || query.error} />
      </form>
      {result && (
        <>
          <div className="mode-notice">
            <strong>{result.sample_size} cases</strong>
            <span>
              {result.benchmark} · {when(result.created_at)}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <caption className="sr-only">
                Measured investigator strategy comparison
              </caption>
              <thead>
                <tr>
                  <th>Strategy / execution</th>
                  <th>Correct conclusions</th>
                  <th>Resolved</th>
                  <th>Review rate</th>
                  <th>Incorrect exclusions / holds</th>
                  <th>Total tool calls</th>
                  <th>Operator interventions / setup confirmations</th>
                  <th>p50 / p95 latency</th>
                  <th>Model calls / input / output tokens</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => (
                  <tr key={`${row.method}-${row.mode}`}>
                    <td>
                      <strong>{row.method}</strong>
                      <small className="investigator-cell-note">
                        {row.actual_modes?.join(", ") || row.mode}
                      </small>
                    </td>
                    <td>{percent(row.accuracy)}</td>
                    <td>{percent(row.resolved_rate)}</td>
                    <td>{percent(row.review_request_rate)}</td>
                    <td>
                      {row.incorrect_exclusions} / {row.incorrect_holds}
                    </td>
                    <td>{row.tool_calls}</td>
                    <td>
                      {row.operator_interventions} / {row.setup_confirmations}
                    </td>
                    <td>
                      {row.p50_latency_ms.toFixed(1)} /{" "}
                      {row.p95_latency_ms.toFixed(1)} ms
                    </td>
                    <td>
                      {row.model_calls} / {row.input_tokens} /{" "}
                      {row.output_tokens}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="evidence-list">
            {result.cases.map((item, i) => (
              <details key={i}>
                <summary>
                  <strong>{item.name}</strong>
                  {item.expected && <Badge value={item.expected} />}
                </summary>
                <Json value={item} />
              </details>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}
