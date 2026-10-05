import { Cpu, HardDrive } from "lucide-react";
import type { SystemStatus } from "@/lib/admin";
import { number, percent, bytes, Metric, History } from "./AdminPrimitives";

export function SystemHealth({ system }: { system?: SystemStatus }) {
  const current = system?.current;
  return (
    <section className="admin-section" aria-labelledby="system-heading">
      <div className="admin-section-heading">
        <h2 id="system-heading">
          <Cpu size={18} /> VPS health
        </h2>
        <span>Last 5 minutes</span>
      </div>
      <div className="admin-health-grid">
        <Metric
          label="CPU"
          value={percent(current?.cpu_percent)}
          detail={
            current?.load
              ? `Load ${current.load.map((value) => number(value)).join(" / ")}`
              : "Load unavailable"
          }
        >
          <History samples={system?.history ?? []} kind="cpu" />
        </Metric>
        <Metric
          label="Memory"
          value={percent(current?.memory?.percent)}
          detail={
            current?.memory
              ? `${bytes(current.memory.used_bytes)} / ${bytes(current.memory.total_bytes)}`
              : undefined
          }
        >
          <History samples={system?.history ?? []} kind="memory" />
        </Metric>
        <Metric
          label="Disk"
          value={percent(current?.disk?.percent)}
          detail={
            current?.disk
              ? `${bytes(current.disk.used_bytes)} / ${bytes(current.disk.total_bytes)}`
              : undefined
          }
        >
          <div className="admin-disk">
            <HardDrive size={22} />
            <meter
              aria-label="Disk usage"
              min="0"
              max="100"
              value={current?.disk?.percent ?? 0}
            />
          </div>
        </Metric>
      </div>
      <div className="admin-service-row">
        {(["redis", "postgres"] as const).map((name) => (
          <span key={name}>
            <i className={system?.[name].ok ? "ok" : "unknown"} />
            {name === "redis" ? "Redis" : "Postgres"}{" "}
            <b>
              {system?.[name].ok
                ? `${number(system[name].latency_ms)} ms`
                : "Unavailable"}
            </b>
          </span>
        ))}
        <span>
          In flight{" "}
          <b>
            {system
              ? `${system.queue.inflight} / ${system.queue.max_inflight}`
              : "Unavailable"}
          </b>
        </span>
        <span>
          Queued{" "}
          <b>
            {system
              ? number(
                  Object.values(system.queue.pending).reduce(
                    (sum, value) => sum + value,
                    0,
                  ),
                )
              : "Unavailable"}
          </b>
        </span>
        <span className="admin-release">
          Release{" "}
          <code>{system?.release.slice(0, 12) ?? "Unavailable"}</code>
        </span>
      </div>
    </section>
  );
}
