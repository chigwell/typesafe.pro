"use client";

import {
  BookOpen,
  Bug,
  Check,
  Copy,
  FileCheck,
  Grid3X3,
  Mail,
  Receipt,
  Route,
  Star,
  Tag,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { Preset } from "@/lib/typesafe";

const presetIcons: Record<Preset["icon"], LucideIcon> = {
  mail: Mail,
  zap: Zap,
  star: Star,
  book: BookOpen,
  receipt: Receipt,
  route: Route,
  tag: Tag,
  "file-check": FileCheck,
  bug: Bug,
};

export function PresetIcon({ name }: { name: Preset["icon"] }) {
  const Icon = presetIcons[name] ?? Grid3X3;
  return <Icon aria-hidden="true" />;
}

export function BrandMark({ className = "brand-mark" }: { className?: string }) {
  return (
    <svg className={className} aria-hidden="true" viewBox="0 0 64 72" fill="none">
      <path
        d="M21 13h-7c-4 0-7 3-7 7v32c0 4 3 7 7 7h7M43 13h7c4 0 7 3 7 7v32c0 4-3 7-7 7h-7"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <path
        d="m25 37 7 7 13-19"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Brand() {
  return (
    <a className="brand" href="/" aria-label="typesafe.pro home">
      <BrandMark />
      <span className="brand-word">
        typesafe<span className="suffix">.pro</span>
      </span>
    </a>
  );
}

function AppleMark({ className = "app-store-badge-icon" }: { className?: string }) {
  return (
    <svg className={className} aria-hidden="true" viewBox="0 0 384 512" fill="currentColor">
      <path d="M318.7 268.7c-.2-36.7 16.4-64.4 50-84.8-18.8-26.9-47.2-41.7-84.7-44.6-35.5-2.8-74.3 20.7-88.5 20.7-15 0-49.4-19.7-76-19.7C63.3 141.2 4 184.8 4 273.5q0 39.3 14.4 81.2c12.8 36.7 59 126.7 107.2 125.2 25.2-.6 43-17.9 75.8-17.9 31.8 0 48.3 17.9 76.4 17.9 48.6-.7 90.4-82.5 102.6-119.3-65.2-30.7-61.7-90-61.7-91.9zm-56.6-164.2c27.3-32.4 24.8-61.9 24-72.5-24.1 1.4-52 16.4-67.9 34.9-17.5 19.8-27.8 44.3-25.6 71.9 26.1 2 49.9-11.4 69.5-34.3z" />
    </svg>
  );
}

export function AppStoreBadge() {
  return (
    <a
      className="app-store-badge"
      href="https://apps.apple.com/us/app/typesafe-pro/id6814756562"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Download TypeSafe Pro on the App Store"
    >
      <AppleMark />
      <span className="app-store-badge-text">
        <span className="app-store-badge-eyebrow">Download on the</span>
        <span className="app-store-badge-title">App Store</span>
      </span>
    </a>
  );
}

export { Check, Copy };
