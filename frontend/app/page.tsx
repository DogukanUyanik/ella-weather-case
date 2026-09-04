"use client";

import { useEffect, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ForecastEntry,
  HistoryEntry,
  getCities,
  getForecastHistory,
  getLatestForecast,
} from "@/lib/api";

export default function Home() {
  const [cities, setCities] = useState<string[]>([]);
  const [selectedCity, setSelectedCity] = useState<string | null>(null);
  const [forecast, setForecast] = useState<ForecastEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedHour, setSelectedHour] = useState<ForecastEntry | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    getCities()
      .then((data) => {
        setCities(data);
        if (data.length > 0) {
          setSelectedCity(data[0]);
        }
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (!selectedCity) return;

    setLoading(true);
    setError(null);
    setSelectedHour(null);
    getLatestForecast(selectedCity)
      .then((data) => setForecast(data))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, [selectedCity]);

  useEffect(() => {
    if (!selectedCity || !selectedHour) return;

    setHistoryLoading(true);
    setHistoryError(null);
    getForecastHistory(selectedCity, selectedHour.target_time)
      .then((data) => setHistory(data))
      .catch((err) => setHistoryError(String(err)))
      .finally(() => setHistoryLoading(false));
  }, [selectedCity, selectedHour]);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Belgian Weather Forecast</h1>

      <Select
        value={selectedCity}
        onValueChange={(value) => setSelectedCity(value as string)}
        itemToStringLabel={(value) => value as string}
      >
        <SelectTrigger>
          <SelectValue placeholder="Select a city" />
        </SelectTrigger>
        <SelectContent>
          {cities.map((city) => (
            <SelectItem key={city} value={city}>
              {city}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {loading && <p>Loading...</p>}
      {error && <p>Something went wrong: {error}</p>}

      {!loading && !error && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Temperature (°C)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {forecast.map((entry) => (
              <TableRow
                key={entry.target_time}
                onClick={() => setSelectedHour(entry)}
                className="cursor-pointer"
              >
                <TableCell>
                  {new Date(entry.target_time).toLocaleString("nl-BE")}
                </TableCell>
                <TableCell>{entry.temperature_c}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {selectedHour && (
        <div className="flex flex-col gap-3 rounded-lg border p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">
              History for{" "}
              {new Date(selectedHour.target_time).toLocaleString("nl-BE")}
            </h2>
            <button
              onClick={() => setSelectedHour(null)}
              className="text-sm text-muted-foreground hover:underline"
            >
              Close
            </button>
          </div>

          {historyLoading && <p>Loading...</p>}
          {historyError && <p>Something went wrong: {historyError}</p>}

          {!historyLoading && !historyError && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ingested at</TableHead>
                  <TableHead>Temperature (°C)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.map((entry) => (
                  <TableRow key={entry.ingested_at}>
                    <TableCell>
                      {new Date(entry.ingested_at).toLocaleString("nl-BE")}
                    </TableCell>
                    <TableCell>{entry.temperature_c}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      )}
    </div>
  );
}
