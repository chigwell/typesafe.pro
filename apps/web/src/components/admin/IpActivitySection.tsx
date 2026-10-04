import type { Page, IpActivity, ActivityWindow } from "@/lib/admin";
import { number, date, Pagination } from "./AdminPrimitives";

export function IpActivitySection({ ips, window, ipPage, loading, onPage }: { ips?: Page<IpActivity>; window: ActivityWindow; ipPage: number; loading: boolean; onPage: (value: number) => void }) {
  return (
    <section className="admin-section" aria-labelledby="ips-heading">
      <div className="admin-section-heading">
        <h2 id="ips-heading">IP activity</h2>
        <span>{window} window</span>
      </div>
      <div className="admin-table-wrap">
        <table>
          <thead>
            <tr>
              <th>IP address</th>
              <th>Requests</th>
              <th>Errors</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {ips?.items.map((row) => (
              <tr key={row.ip}>
                <td>
                  <code>{row.ip}</code>
                </td>
                <td>{number(row.requests)}</td>
                <td>{number(row.errors)}</td>
                <td>{date(row.last_seen)}</td>
              </tr>
            ))}
            {!ips?.items.length && (
              <tr>
                <td colSpan={4} className="admin-empty">
                  {ips
                    ? "No requests in this window"
                    : loading
                      ? "Loading IP activity..."
                      : "IP activity unavailable"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        label="IP"
        data={ips}
        page={ipPage}
        onPage={onPage}
        disabled={loading || !ips}
      />
    </section>
  );
}
