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

export { Check, Copy };
