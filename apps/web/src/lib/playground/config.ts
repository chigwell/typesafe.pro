import { DEFAULT_API_BASE } from "../typesafe";

export const API_BASE =
  process.env.NEXT_PUBLIC_TYPESAFE_API_BASE?.replace(/\/+$/, "") || DEFAULT_API_BASE;

