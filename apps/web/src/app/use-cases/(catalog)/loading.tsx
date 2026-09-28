import { UseCaseCardSkeletons } from "@/components/UseCaseCatalog";

export default function Loading() {
  return <main className="container use-cases-main" aria-busy="true">
    <span className="skeleton skeleton-line is-short" />
    <span className="skeleton skeleton-heading" />
    <span className="skeleton skeleton-line" />
    <UseCaseCardSkeletons count={6} />
  </main>;
}
