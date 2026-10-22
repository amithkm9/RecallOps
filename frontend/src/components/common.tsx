import type { ReactNode } from "react";
import {
  ArrowUpRight,
  LoaderCircle,
  ShieldCheck,
  AlertCircle,
  Package,
  ArrowRight,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { Incident } from "../api";
import { ApiError, saveToken, when } from "../api";
import { Button } from "./ui/button";
export function Badge({ value }: { value: string }) {
  return (
    <span className={`badge badge-${value}`}>{value.replaceAll("_", " ")}</span>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </header>
  );
}
export function Panel({
  title,
  caption,
  children,
  action,
  className = "",
}: {
  title: string;
  caption?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {caption && <p>{caption}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Empty({
  title = "Your evidence starts here",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <ShieldCheck size={30} />
      <h3>{title}</h3>
      <div className="empty-description">
        {children ||
          "Run an incident simulation or synchronize the official source to begin."}
      </div>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} /> Loading recorded data…
    </div>
  );
}
export function ErrorBox({ error }: { error: Error | null }) {
  return error ? (
    <div className="error" role="alert">
      <AlertCircle size={18} />
      {error.message}
      {error instanceof ApiError && error.status === 401 && (
        <Button
          variant="outline"
          onClick={() => {
            saveToken("");
            window.location.assign("/settings");
          }}
        >
          Clear saved token & open settings
        </Button>
      )}
    </div>
  ) : null;
}
export function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
export function IncidentTable({
  items,
  compact = false,
}: {
  items: Incident[];
  compact?: boolean;
}) {
  return items.length ? (
    <div className="table-wrap">
      <table className={compact ? "incident-table compact" : "incident-table"}>
        <thead>
          <tr>
            <th>Recall / product</th>
            <th>Status</th>
            {!compact && <th>Store</th>}
            <th>Held units</th>
            {!compact && <th>Investigated</th>}
            <th>
              {compact ? (
                "Next step"
              ) : (
                <span className="sr-only">Open incident</span>
              )}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.id}>
              <td>
                <div className="product-cell">
                  <span className={`product-icon product-${i.status}`}>
                    <Package size={19} strokeWidth={1.5} />
                  </span>
                  <div>
                    <Link className="product-link" to={`/incidents/${i.id}`}>
                      {i.product_name}
                    </Link>
                    <small>
                      {i.reference}
                      {!compact && ` · Published ${when(i.published_at)}`}
                    </small>
                  </div>
                </div>
              </td>
              <td>
                <Badge value={i.status} />
              </td>
              {!compact && <td>{i.store_name}</td>}
              <td className="numeric">{i.affected_quantity}</td>
              {!compact && <td>{when(i.updated_at)}</td>}
              <td>
                <Link
                  className="icon-link"
                  aria-label={`Open ${i.product_name}`}
                  to={`/incidents/${i.id}`}
                >
                  {compact ? (
                    <>
                      <span>
                        {["review", "conflict"].includes(i.status)
                          ? "Review"
                          : "Inspect"}
                      </span>
                      <ArrowRight size={14} />
                    </>
                  ) : (
                    <ArrowUpRight size={17} />
                  )}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty title="No investigations in this view" />
  );
}
