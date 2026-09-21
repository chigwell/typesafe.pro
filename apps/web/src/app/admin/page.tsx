import type { Metadata } from "next";
import AdminDashboard from "@/components/AdminDashboard";
import "./admin.css";

export const metadata: Metadata = {
  title: "Admin | TypeSafe.pro",
  robots: { index: false, follow: false },
  alternates: { canonical: "https://typesafe.pro/admin" },
};

export default function AdminPage() {
  return <AdminDashboard />;
}
