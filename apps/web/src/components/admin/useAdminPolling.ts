import { useCallback, useEffect, useState } from "react";
import { adminFetch, AdminError } from "@/lib/admin";
import type {
  ActivityWindow, ErrorEvent, IpActivity, Page, PageViewRow, SeoSummary,
  SeoPage, SeoRun, Summary, SystemStatus,
} from "@/lib/admin";
import type { AdminAuthState } from "./useAdminAuth";
import { message } from "./admin-lifecycle";

type AdminSnapshot = {
  system?: SystemStatus;
  summary?: Summary;
  ips?: Page<IpActivity>;
  pageViews?: Page<PageViewRow>;
  errors?: Page<ErrorEvent>;
  seoSummary?: SeoSummary;
  seoPages?: Page<SeoPage>;
  seoRuns?: Page<SeoRun>;
};

type PollingOptions = {
  auth: AdminAuthState; window: ActivityWindow; ipPage: number;
  viewPage: number; viewsFrom: string; viewsTo: string; errorPage: number;
  seoPage: number; seoRunPage: number; status: string; errorCode: string;
  refresh: number; onUnauthorized: () => void;
};

const resourceLabels: Record<keyof AdminSnapshot, string> = {
  system: "System", summary: "Activity", ips: "IP activity", pageViews: "Page views",
  errors: "Errors", seoSummary: "Generated pages", seoPages: "Generated page list",
  seoRuns: "Generation history",
};
const fulfilled = <T,>(result: PromiseSettledResult<T>): T | undefined =>
  result.status === "fulfilled" ? result.value : undefined;

export function useAdminPolling({
  auth, window, ipPage, viewPage, viewsFrom, viewsTo, errorPage,
  seoPage, seoRunPage, status, errorCode, refresh, onUnauthorized,
}: PollingOptions) {
  const [snapshot, setSnapshot] = useState<AdminSnapshot>({});
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState<number>();
  const [failures, setFailures] = useState<string[]>([]);
  const clearFields = useCallback((...fields: (keyof AdminSnapshot)[]) => {
    setSnapshot((current) => {
      const next = { ...current };
      for (const field of fields) next[field] = undefined;
      return next;
    });
  }, []);
  const clearPrivateData = useCallback(() => {
    clearFields("system", "summary", "ips", "pageViews", "errors", "seoSummary", "seoPages", "seoRuns");
  }, [clearFields]);

  useEffect(() => {
    if (auth !== "ready") return;
    const controller = new AbortController();
    let inFlight = false;
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      setLoading(true);
      const opts = { signal: controller.signal };
      const query = new URLSearchParams({ page: String(errorPage), page_size: "25" });
      if (status) query.set("status", status);
      if (errorCode) query.set("error_code", errorCode);
      const [system, summary, ips, pageViews, errors, seoSummary, seoPages, seoRuns] = await Promise.allSettled([
        adminFetch<SystemStatus>("/system", opts),
        adminFetch<Summary>(`/summary?window=${window}`, opts),
        adminFetch<Page<IpActivity>>(`/ip-activity?window=${window}&page=${ipPage}&page_size=25`, opts),
        adminFetch<Page<PageViewRow>>(`/page-views?from=${viewsFrom}&to=${viewsTo}&page=${viewPage}&page_size=25`, opts),
        adminFetch<Page<ErrorEvent>>(`/errors?${query}`, opts),
        adminFetch<SeoSummary>("/seo/summary", opts),
        adminFetch<Page<SeoPage>>(`/seo/pages?page=${seoPage}&page_size=25`, opts),
        adminFetch<Page<SeoRun>>(`/seo/runs?page=${seoRunPage}&page_size=25`, opts),
      ] as const);
      if (controller.signal.aborted) return;
      const results = { system, summary, ips, pageViews, errors, seoSummary, seoPages, seoRuns };
      if (Object.values(results).some((result) =>
        result.status === "rejected" && result.reason instanceof AdminError && result.reason.status === 401,
      )) {
        clearPrivateData();
        onUnauthorized();
      } else {
        setSnapshot({
          system: fulfilled(system), summary: fulfilled(summary), ips: fulfilled(ips),
          pageViews: fulfilled(pageViews), errors: fulfilled(errors), seoSummary: fulfilled(seoSummary),
          seoPages: fulfilled(seoPages), seoRuns: fulfilled(seoRuns),
        });
        setFailures(Object.entries(results).flatMap(([key, result]) =>
          result.status === "rejected" ? [`${resourceLabels[key as keyof AdminSnapshot]}: ${message(result.reason)}`] : [],
        ));
        setUpdated(Date.now() / 1000);
      }
      setLoading(false);
      inFlight = false;
    };
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [auth, window, ipPage, viewPage, viewsFrom, viewsTo, errorPage, seoPage, seoRunPage, status, errorCode, refresh, clearPrivateData, onUnauthorized]);

  return { snapshot, loading, updated, failures, setFailures, clearFields, clearPrivateData };
}
