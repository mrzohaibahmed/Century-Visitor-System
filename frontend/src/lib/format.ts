/** Display helpers shared by the visit screens. Times are shown in the browser's time zone. */

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** "45 min", "2 h 05 min", "3 d 4 h" between two instants (or until now). */
export function formatDuration(fromIso: string, toIso?: string | null, now: Date = new Date()): string {
  const end = toIso ? new Date(toIso) : now;
  const minutes = Math.max(0, Math.floor((end.getTime() - new Date(fromIso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

/** YYYY-MM-DD for a date in the browser's time zone (for <input type="date">). */
export function isoDay(date: Date = new Date()): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Belongings typed as "laptop, bag;  umbrella" → ["laptop", "bag", "umbrella"]. */
export function parseList(text: string): string[] {
  return text.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
}
