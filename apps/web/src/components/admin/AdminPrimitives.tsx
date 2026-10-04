import { ArrowLeft, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import type { Page, Sample } from "@/lib/admin";

export const number = (value?: number | null) =>
  value == null
    ? "Unavailable"
    : new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
export const percent = (value?: number | null) =>
  value == null ? "Unavailable" : `${number(value)}%`;
export const bytes = (value?: number | null) =>
  value == null
    ? "Unavailable"
    : value >= 1073741824
      ? `${number(value / 1073741824)} GB`
      : `${number(value / 1048576)} MB`;
export const date = (value?: number | string | null) =>
  value == null
    ? "Unavailable"
    : new Date(
        typeof value === "number" ? value * 1000 : value,
      ).toLocaleString();
export function Metric({
  label,
  value,
  detail,
  children,
}: {
  label: string;
  value: string;
  detail?: string;
  children?: ReactNode;
}) {
  return (
    <div className="admin-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
      {children}
    </div>
  );
}

export function History({
  samples,
  kind,
}: {
  samples: Sample[];
  kind: "cpu" | "memory";
}) {
  const end = samples.at(-1)?.at ?? Date.now() / 1000;
  const segments: string[] = [];
  let segment: string[] = [];
  for (const sample of samples) {
    const value = kind === "cpu" ? sample.cpu_percent : sample.memory?.percent;
    if (value == null) {
      if (segment.length) segments.push(segment.join(" "));
      segment = [];
      continue;
    }
    segment.push(
      `${Math.max(0, Math.min(600, (sample.at - end + 300) * 2))},${100 - value}`,
    );
  }
  if (segment.length) segments.push(segment.join(" "));
  return (
    <div className={`admin-history ${kind}`}>
      <svg
        viewBox="0 0 600 100"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${kind === "cpu" ? "CPU" : "Memory"} usage over the last five minutes`}
      >
        {[0, 50, 100].map((y) => (
          <line
            key={y}
            x1="0"
            x2="600"
            y1={y}
            y2={y}
            className="admin-gridline"
          />
        ))}
        {segments.map((points, index) => (
          <polyline
            key={index}
            points={points}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      {segments.length === 0 && (
        <span className="admin-chart-empty">Awaiting samples</span>
      )}
      <div className="admin-chart-axis">
        <span>5 min ago</span>
        <span>Now</span>
      </div>
    </div>
  );
}

export function Pagination({
  label,
  data,
  page,
  onPage,
  disabled,
}: {
  label: string;
  data?: Page<unknown>;
  page: number;
  onPage: (page: number) => void;
  disabled: boolean;
}) {
  const pages = Math.max(
    1,
    Math.ceil((data?.total ?? 0) / (data?.page_size ?? 25)),
  );
  return (
    <div className="admin-pagination">
      <span>{data ? `${number(data.total)} records` : "Loading"}</span>
      <div>
        <button
          className="admin-icon"
          title={`Previous ${label} page`}
          aria-label={`Previous ${label} page`}
          disabled={disabled || page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ArrowLeft size={16} />
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button
          className="admin-icon"
          title={`Next ${label} page`}
          aria-label={`Next ${label} page`}
          disabled={disabled || page >= pages}
          onClick={() => onPage(page + 1)}
        >
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
