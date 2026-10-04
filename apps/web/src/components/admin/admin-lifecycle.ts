export const dayInput = (offsetDays = 0) => {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + offsetDays);
  return value.toISOString().slice(0, 10);
};

export const message = (error: unknown) =>
  error instanceof Error ? error.message : "Connection unavailable";
