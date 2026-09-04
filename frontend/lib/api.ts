const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ForecastEntry {
  target_time: string;
  temperature_c: number;
}

export interface HistoryEntry {
  ingested_at: string;
  temperature_c: number;
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) {
    throw new Error(`Request to ${path} failed: ${res.status}`);
  }
  return res.json();
}

export function getCities(): Promise<string[]> {
  return fetchJson<{ cities: string[] }>("/cities").then((data) => data.cities);
}

export function getLatestForecast(city: string): Promise<ForecastEntry[]> {
  return fetchJson(`/forecasts/${encodeURIComponent(city)}/latest`);
}

export function getForecastHistory(
  city: string,
  targetTime: string
): Promise<HistoryEntry[]> {
  const qs = new URLSearchParams({ target_time: targetTime });
  return fetchJson(`/forecasts/${encodeURIComponent(city)}/history?${qs}`);
}
