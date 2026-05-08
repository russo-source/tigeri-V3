"use client";

import { ExternalLink, MapPin, Star } from "lucide-react";

/** Shape produced by the orchestrator's `find_place` tool — see
 *  src/tigeri/agents/orchestrator/tools.py. We accept partial data because
 *  geocode_address returns a subset (no name / no rating). */
export type PlaceLike = {
  ok?: boolean;
  name?: string;
  formatted_address?: string;
  place_id?: string;
  lat?: number | null;
  lng?: number | null;
  rating?: number | null;
  open_now?: boolean | null;
  types?: string[];
};

const _MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY ?? "";

/** Build a Maps Embed URL. Prefer place_id when we have it (resolves to the
 *  canonical place pin); otherwise fall back to "lat,lng" or free-text address. */
function _embedUrl(p: PlaceLike): string | null {
  if (!_MAPS_KEY) return null;
  const params = new URLSearchParams({ key: _MAPS_KEY });
  if (p.place_id) {
    params.set("q", `place_id:${p.place_id}`);
  } else if (typeof p.lat === "number" && typeof p.lng === "number") {
    params.set("q", `${p.lat},${p.lng}`);
  } else if (p.formatted_address) {
    params.set("q", p.formatted_address);
  } else {
    return null;
  }
  return `https://www.google.com/maps/embed/v1/place?${params.toString()}`;
}

/** Public Google Maps URL — no API key needed, opens the regular maps UI
 *  with a marker. Used for the "Open in Maps" link AND as a fallback when
 *  no browser API key is configured. */
function _openInMapsUrl(p: PlaceLike): string {
  if (p.place_id) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
      p.name ?? "place",
    )}&query_place_id=${encodeURIComponent(p.place_id)}`;
  }
  if (typeof p.lat === "number" && typeof p.lng === "number") {
    return `https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}`;
  }
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    p.formatted_address ?? p.name ?? "",
  )}`;
}

export function PlaceCard({ place }: { place: PlaceLike }) {
  if (!place || place.ok === false) return null;
  const embed = _embedUrl(place);
  const open = _openInMapsUrl(place);

  return (
    <div className="mt-3 overflow-hidden rounded-md border border-border bg-surface-elevated">
      {embed ? (
        <iframe
          src={embed}
          title={place.name ?? place.formatted_address ?? "Map"}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          allowFullScreen
          className="h-[260px] w-full border-0"
        />
      ) : (
        <div className="flex h-[120px] w-full items-center justify-center bg-background text-xs text-text-muted">
          (Map preview disabled — set NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY)
        </div>
      )}

      <div className="space-y-2 p-3">
        {place.name ? (
          <p className="text-sm font-semibold text-text-primary">{place.name}</p>
        ) : null}
        {place.formatted_address ? (
          <p className="flex items-start gap-1.5 text-xs text-text-secondary">
            <MapPin className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{place.formatted_address}</span>
          </p>
        ) : null}

        <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-wide">
          {typeof place.rating === "number" ? (
            <span className="inline-flex items-center gap-0.5 rounded-sm border border-border bg-surface px-1.5 py-0.5 text-text-primary">
              <Star className="h-3 w-3" />
              {place.rating.toFixed(1)}
            </span>
          ) : null}
          {place.open_now === true ? (
            <span className="rounded-sm border border-success/40 bg-surface-blue px-1.5 py-0.5 text-success">
              Open now
            </span>
          ) : place.open_now === false ? (
            <span className="rounded-sm border border-warning/40 bg-surface-blue px-1.5 py-0.5 text-warning">
              Closed
            </span>
          ) : null}
          {typeof place.lat === "number" && typeof place.lng === "number" ? (
            <span className="rounded-sm border border-border bg-surface px-1.5 py-0.5 text-text-muted">
              {place.lat.toFixed(4)}, {place.lng.toFixed(4)}
            </span>
          ) : null}
        </div>

        <a
          href={open}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs font-medium text-navy hover:underline"
        >
          Open in Google Maps
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
  );
}

/** Renderer for `list_calendar_events` — small list of upcoming events with
 *  Meet links. No map. Kept here so chat-related visualisations live in one
 *  module. */
export function CalendarEventsList({
  events,
}: {
  events: Array<{
    id?: string;
    summary?: string;
    start?: string;
    end?: string;
    attendees?: string[];
    meet_link?: string;
    html_link?: string;
  }>;
}) {
  if (!events || events.length === 0) {
    return (
      <p className="mt-3 text-xs text-text-muted">No upcoming events in window.</p>
    );
  }
  return (
    <ul className="mt-3 space-y-2">
      {events.map((e, idx) => (
        <li
          key={e.id ?? idx}
          className="rounded-md border border-border bg-surface-elevated p-2 text-xs"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-semibold text-text-primary">
                {e.summary || "(untitled)"}
              </p>
              <p className="font-mono text-[10px] text-text-muted">
                {e.start ?? ""} → {e.end ?? ""}
              </p>
              {e.attendees && e.attendees.length ? (
                <p className="mt-1 text-text-secondary">
                  {e.attendees.join(", ")}
                </p>
              ) : null}
            </div>
            <div className="flex flex-col items-end gap-1 text-[11px] font-mono">
              {e.meet_link ? (
                <a
                  href={e.meet_link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-navy hover:underline"
                >
                  Meet ↗
                </a>
              ) : null}
              {e.html_link ? (
                <a
                  href={e.html_link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-text-muted hover:text-text-primary hover:underline"
                >
                  Calendar ↗
                </a>
              ) : null}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
