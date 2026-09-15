// The demo budget left as a whole percentage, which reads better than cents on a
// budget this small. Rounded up, so it only says 0% once nothing is left; the
// toFixed first drops float noise (0.43 / 0.5 is 86.00000000000001, not 86).
export function creditsLeft(remaining: number, budget: number): number {
  if (budget <= 0) return 0;
  const percent = Math.ceil(Number(((remaining / budget) * 100).toFixed(6)));
  return Math.min(100, Math.max(0, percent));
}
