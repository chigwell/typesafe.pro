import { permanentRedirect } from "next/navigation";

// Former static pagination (/use-cases/page/N) now lives at /use-cases?page=N.
export default async function LegacyPage({ params }: { params: Promise<{ page: string }> }) {
  const { page } = await params;
  const number = Number.parseInt(page, 10);
  permanentRedirect(Number.isFinite(number) && number > 1 ? `/use-cases?page=${number}` : "/use-cases");
}
