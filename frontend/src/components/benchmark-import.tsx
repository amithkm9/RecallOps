import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api";
import { Panel, ErrorBox } from "./common";

export function BenchmarkImport() {
  const client = useQueryClient();
  const upload = useMutation({
    mutationFn: async (file: File) => {
      if (file.size > 1_000_000)
        throw new Error("Benchmark JSON must be under 1 MB.");
      return post("/evaluation/labeled", JSON.parse(await file.text()));
    },
    onSuccess: () => void client.invalidateQueries(),
  });
  return (
    <Panel
      title="Evaluate separately labeled cases"
      caption="Labels must exist before predictions. Uploaded provenance is a declaration, not an independent audit."
    >
      <div className="settings-body">
        <p>
          Upload JSON containing source, labeler, split (development or
          held_out), and 2–200 labeled cases. This uses the persisted
          deterministic safety workflow without model charges.
        </p>
        <input
          type="file"
          aria-label="Labeled benchmark JSON"
          accept=".json,application/json"
          disabled={upload.isPending}
          onChange={(e) => {
            if (e.target.files?.[0]) upload.mutate(e.target.files[0]);
            e.target.value = "";
          }}
        />
        <ErrorBox error={upload.error} />
        {upload.isPending && <p role="status">Evaluating uploaded cases…</p>}
        {upload.isSuccess && (
          <p role="status">
            Measured results saved with dataset hash and declared labeler.
          </p>
        )}
      </div>
    </Panel>
  );
}
