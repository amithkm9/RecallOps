import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post, token, type Detail } from "../api";
import { ErrorBox, Panel, Json } from "./common";
import { Button } from "./ui/button";
import { useState } from "react";

export function OfficialDocuments({ detail }: { detail: Detail }) {
  const client = useQueryClient();
  const [downloadError, setDownloadError] = useState<Error | null>(null);
  const fetchDocument = useMutation({
    mutationFn: (field: string) =>
      post(`/incidents/${detail.incident.id}/documents`, { field }),
    onSuccess: () => void client.invalidateQueries(),
  });
  const fields = [
    ["lien_vers_affichette_pdf", "Official recall PDF"],
    ["lien_vers_la_liste_des_produits", "Additional product list"],
    ["lien_vers_la_liste_des_distributeurs", "Distributor list"],
  ];
  const documents = detail.evidence.filter(
    (e) => e.kind === "official_document",
  );
  return (
    <Panel
      title="Official attachments"
      caption="Archived bytes, checksum and extracted text. Document text alone never proves a stock match."
    >
      <div className="settings-body">
        <ErrorBox error={fetchDocument.error || downloadError} />
        <div className="button-row">
          {fields
            .filter(
              ([field]) =>
                typeof detail.recall.raw[field] === "string" &&
                detail.recall.raw[field],
            )
            .map(([field, label]) => (
              <Button
                key={field}
                variant="outline"
                disabled={fetchDocument.isPending}
                onClick={() => fetchDocument.mutate(field)}
              >
                Retrieve {label}
              </Button>
            ))}
        </div>
        {!fields.some(([field]) => detail.recall.raw[field]) && (
          <p>No attachment links are supplied by this official record.</p>
        )}
        {fetchDocument.isSuccess && (
          <p role="status">Document evidence saved; reassessment queued.</p>
        )}
        {documents.map((e) => (
          <details key={e.id}>
            <summary>
              {e.label} · {String(e.payload.text_status)}
            </summary>
            <Json value={e.payload} />
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  const response = await fetch(
                    `/api/incidents/${detail.incident.id}/documents/${e.id}`,
                    {
                      headers: token()
                        ? { Authorization: `Bearer ${token()}` }
                        : {},
                    },
                  );
                  if (!response.ok)
                    throw new Error(
                      "Document download was not authorized or could not complete.",
                    );
                  const url = URL.createObjectURL(await response.blob());
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `official-${e.id}.pdf`;
                  a.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                } catch (error) {
                  setDownloadError(
                    error instanceof Error
                      ? error
                      : new Error("Download failed"),
                  );
                }
              }}
            >
              Download preserved PDF
            </Button>
          </details>
        ))}
      </div>
    </Panel>
  );
}
