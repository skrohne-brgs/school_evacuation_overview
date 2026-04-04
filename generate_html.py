#!/usr/bin/env python3
"""
Erzeugt docs/index.html für die Evakuierungsübersicht.

Voraussetzungen:
- GitHub Secrets liefern die WebUntis-Zugangsdaten als Umgebungsvariablen
- Das Skript läuft in GitHub Actions oder lokal

WICHTIG:
- Zugangsdaten niemals im Code eintragen
- Alle ANPASSEN-Markierungen prüfen
"""

from __future__ import annotations

import datetime as dt
import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
from zoneinfo import ZoneInfo

import webuntis


# ============================================================
# ANPASSEN: Grundeinstellungen
# ============================================================

LOCAL_TIMEZONE = ZoneInfo("Europe/Berlin")
OUTPUT_FILE = Path("docs/index.html")

# Diese Unterrichtsfenster bestimmen, welche Stunde "gerade relevant" ist.
# Die Startzeiten entsprechen deiner Vorgabe.
# Die Endzeiten sind pragmatisch bis zum Beginn des nächsten Blocks gewählt.
# Die letzte Einheit läuft hier beispielhaft bis 16:00.
#
# ANPASSEN: Falls eure Schule andere Enden / Pausenzeiten / Blockdefinitionen nutzt.
LESSON_SLOTS = [
    {"label": "1. Stunde", "start": dt.time(8, 0), "end": dt.time(8, 45)},
    {"label": "2. Stunde", "start": dt.time(8, 45), "end": dt.time(9, 35)},
    {"label": "3. Stunde", "start": dt.time(9, 35), "end": dt.time(10, 35)},
    {"label": "4. Stunde", "start": dt.time(10, 35), "end": dt.time(11, 25)},
    {"label": "5. Stunde", "start": dt.time(11, 25), "end": dt.time(12, 25)},
    {"label": "6. Stunde", "start": dt.time(12, 25), "end": dt.time(13, 15)},
    {"label": "7. Stunde", "start": dt.time(13, 15), "end": dt.time(14, 30)},
    {"label": "8. Stunde", "start": dt.time(14, 30), "end": dt.time(15, 15)},
    {"label": "9./10. Stunde", "start": dt.time(15, 15), "end": dt.time(16, 0)},
]

# Optional: Titel der Seite
# ANPASSEN:
SCHOOL_TITLE = "Evakuierungsübersicht Schule"

# Optional: User-Agent für WebUntis
WEBUNTIS_USERAGENT = "SchoolEvacuationOverview/1.0"


@dataclass
class EvacuationRow:
    class_name: str
    room_name: str
    teacher_name: str


@dataclass
class ActiveLessonSlot:
    label: str
    start: dt.datetime
    end: dt.datetime


# ============================================================
# Hilfsfunktionen Zeit
# ============================================================

def now_local() -> dt.datetime:
    return dt.datetime.now(tz=LOCAL_TIMEZONE)


def build_slot_for_today(slot_def: dict, today: dt.date) -> ActiveLessonSlot:
    start_dt = dt.datetime.combine(today, slot_def["start"], tzinfo=LOCAL_TIMEZONE)
    end_dt = dt.datetime.combine(today, slot_def["end"], tzinfo=LOCAL_TIMEZONE)
    return ActiveLessonSlot(label=slot_def["label"], start=start_dt, end=end_dt)


def determine_relevant_slot(current_time: dt.datetime) -> ActiveLessonSlot | None:
    """
    Liefert die aktuell relevante Unterrichtseinheit.
    Verhalten:
    - Wenn current_time innerhalb eines Slots liegt: diesen Slot zurückgeben
    - Wenn current_time vor dem ersten Slot liegt: ersten Slot zurückgeben
    - Wenn current_time zwischen zwei Slots liegt: letzten begonnenen Slot zurückgeben
      (praktisch für manuelle Tests kurz nach Stundenwechseln)
    - Wenn current_time nach dem letzten Slot liegt: letzten Slot zurückgeben
    """
    today = current_time.date()
    slots = [build_slot_for_today(slot, today) for slot in LESSON_SLOTS]

    for slot in slots:
        if slot.start <= current_time < slot.end:
            return slot

    if current_time < slots[0].start:
        return slots[0]

    past_or_current = [slot for slot in slots if slot.start <= current_time]
    if past_or_current:
        return past_or_current[-1]

    return None


def overlaps(period_start: dt.datetime, period_end: dt.datetime, slot: ActiveLessonSlot) -> bool:
    return period_start < slot.end and period_end > slot.start


# ============================================================
# WebUntis Zugriff
# ============================================================

def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Fehlende Umgebungsvariable: {name}")
    return value


def create_webuntis_session() -> webuntis.Session:
    """
    Erwartete Secrets / Umgebungsvariablen:
    - WEBUNTIS_SERVER
    - WEBUNTIS_SCHOOL
    - WEBUNTIS_USERNAME
    - WEBUNTIS_PASSWORD

    Beispiel für WEBUNTIS_SERVER:
    - neilo.webuntis.com
    - oder euer genauer Hostname

    WICHTIG:
    Die korrekte Server-Adresse ist schulabhängig.
    """
    server = get_required_env("WEBUNTIS_SERVER")
    school = get_required_env("WEBUNTIS_SCHOOL")
    username = get_required_env("WEBUNTIS_USERNAME")
    password = get_required_env("WEBUNTIS_PASSWORD")

    return webuntis.Session(
        server=server,
        school=school,
        username=username,
        password=password,
        useragent=WEBUNTIS_USERAGENT,
    )


# ============================================================
# Adapter-Schicht
# ============================================================

def safe_display_name(obj) -> str:
    """
    Liefert einen robusten Anzeigenamen für Lehrer/Raum/Klasse.
    Die Datenqualität ist je nach Schule unterschiedlich.

    ANPASSEN:
    Falls deine Schule andere Felder bevorzugt, hier umstellen.
    """
    for attr_name in ("name", "long_name", "fore_name", "surname"):
        value = getattr(obj, attr_name, None)
        if value:
            return str(value).strip()
    return "-"


def join_names(objects: Iterable) -> str:
    values = [safe_display_name(obj) for obj in objects if safe_display_name(obj) != "-"]
    return ", ".join(values) if values else "-"


def extract_row_from_period(period) -> EvacuationRow | None:
    """
    Wandelt einen WebUntis-Period-Eintrag in eine Tabellenzeile um.

    ANPASSEN:
    Falls bei deiner Schule Perioden anders strukturiert sind oder du
    z. B. Originalräume / Originallehrkräfte bevorzugst, hier ändern.
    """
    class_name = join_names(getattr(period, "klassen", []))
    room_name = join_names(getattr(period, "rooms", []))
    teacher_name = join_names(getattr(period, "teachers", []))

    if not class_name or class_name == "-":
        return None

    return EvacuationRow(
        class_name=class_name,
        room_name=room_name or "-",
        teacher_name=teacher_name or "-",
    )


# ============================================================
# Datenaufbereitung
# ============================================================

def fetch_rows_for_active_slot(slot: ActiveLessonSlot) -> List[EvacuationRow]:
    """
    Lädt alle Klassen und sucht pro Klasse den Unterricht,
    der mit dem relevanten Zeitfenster überlappt.
    """
    rows: List[EvacuationRow] = []
    seen_classes: set[str] = set()

    with create_webuntis_session().login() as session:
        classes = session.klassen()

        for school_class in classes:
            # Tagesstundenplan der Klasse laden
            periods = session.timetable(
                klasse=school_class,
                start=slot.start.date(),
                end=slot.start.date(),
            )

            matching_periods = [
                period
                for period in periods
                if overlaps(period.start, period.end, slot)
            ]

            if not matching_periods:
                continue

            # Falls es mehrere überlappende Einträge gibt:
            # Wir nehmen den ersten regulären Treffer.
            selected_period = matching_periods[0]
            row = extract_row_from_period(selected_period)

            if row is None:
                continue

            # Eindeutigkeit pro Klasse
            if row.class_name in seen_classes:
                continue

            seen_classes.add(row.class_name)
            rows.append(row)

    rows.sort(key=lambda item: item.class_name.lower())
    return rows


# ============================================================
# HTML-Erzeugung
# ============================================================

def render_html(
    rows: List[EvacuationRow],
    generated_at: dt.datetime,
    active_slot: ActiveLessonSlot | None,
) -> str:
    timestamp_text = generated_at.strftime("%d.%m.%Y %H:%M:%S")
    slot_text = active_slot.label if active_slot else "Unbekannt"

    table_rows_html = "\n".join(
        f"""
        <tr data-class="{html.escape(row.class_name.lower())}" data-teacher="{html.escape(row.teacher_name.lower())}">
          <td data-label="Klasse">{html.escape(row.class_name)}</td>
          <td data-label="Raum">{html.escape(row.room_name)}</td>
          <td data-label="Lehrkraft">{html.escape(row.teacher_name)}</td>
          <td data-label="alle anwesend" class="center">
            <input
              type="checkbox"
              class="attendance-checkbox"
              data-key="present::{html.escape(row.class_name)}"
              aria-label="Alle anwesend für {html.escape(row.class_name)}"
            />
          </td>
          <td data-label="fehlende Personen">
            <input
              type="text"
              class="missing-input"
              data-key="missing::{html.escape(row.class_name)}"
              placeholder="z. B. Max M., Frau Beispiel"
              aria-label="Fehlende Personen für {html.escape(row.class_name)}"
            />
          </td>
        </tr>
        """.strip()
        for row in rows
    )

    if not table_rows_html:
        table_rows_html = """
        <tr>
          <td colspan="5">
            Für die aktuell gewählte Unterrichtseinheit wurden keine Klassen gefunden.
            Prüfe die WebUntis-Rechte, die Stundenzeiten oder die Adapter-Funktion.
          </td>
        </tr>
        """.strip()

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html.escape(SCHOOL_TITLE)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --surface: #ffffff;
      --line: #d7deea;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: #0f766e;
      --accent-soft: #e6fffb;
      --danger: #b91c1c;
      --shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      --radius: 14px;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.4;
    }}

    .page {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 16px;
    }}

    .header {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 18px;
      margin-bottom: 16px;
    }}

    .header h1 {{
      margin: 0 0 8px 0;
      font-size: 1.6rem;
    }}

    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      color: var(--muted);
      font-size: 0.98rem;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid #b8f3ec;
      border-radius: 999px;
      padding: 6px 12px;
      font-weight: 600;
    }}

    .controls {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 14px;
      margin-bottom: 16px;
      display: grid;
      gap: 12px;
    }}

    .controls label {{
      font-weight: 600;
      display: block;
      margin-bottom: 6px;
    }}

    .controls input[type="search"] {{
      width: 100%;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 10px;
      font-size: 1rem;
      background: #fff;
    }}

    .card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .table-wrap {{
      width: 100%;
      overflow-x: auto;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 840px;
    }}

    thead th {{
      text-align: left;
      font-size: 0.95rem;
      background: #eef4ff;
      color: #243247;
      padding: 14px 12px;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 1;
    }}

    tbody td {{
      padding: 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: middle;
      background: #fff;
    }}

    tbody tr:last-child td {{
      border-bottom: none;
    }}

    .center {{
      text-align: center;
    }}

    input[type="checkbox"] {{
      width: 22px;
      height: 22px;
      cursor: pointer;
    }}

    input[type="text"] {{
      width: 100%;
      min-width: 220px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      font-size: 0.98rem;
    }}

    .footer-note {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.92rem;
    }}

    .hidden-row {{
      display: none;
    }}

    @media (max-width: 768px) {{
      .page {{
        padding: 10px;
      }}

      .header h1 {{
        font-size: 1.25rem;
      }}

      .meta {{
        font-size: 0.92rem;
      }}

      table {{
        min-width: 100%;
      }}

      thead {{
        display: none;
      }}

      table, tbody, tr, td {{
        display: block;
        width: 100%;
      }}

      tbody tr {{
        border-bottom: 1px solid var(--line);
        padding: 10px 0;
      }}

      tbody td {{
        border: none;
        padding: 8px 12px;
      }}

      tbody td::before {{
        content: attr(data-label);
        display: block;
        font-weight: 700;
        color: var(--muted);
        margin-bottom: 4px;
      }}

      .center {{
        text-align: left;
      }}

      input[type="text"] {{
        min-width: 0;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="header">
      <h1>{html.escape(SCHOOL_TITLE)}</h1>
      <div class="meta">
        <span class="badge">Aktive Einheit: {html.escape(slot_text)}</span>
        <span><strong>Stand:</strong> {html.escape(timestamp_text)}</span>
        <span>Speicherung von Häkchen und Notizen erfolgt lokal im Browser.</span>
      </div>
    </section>

    <section class="controls">
      <div>
        <label for="table-filter">Suche nach Klasse oder Lehrkraft</label>
        <input
          id="table-filter"
          type="search"
          placeholder="z. B. 7a oder Müller"
          autocomplete="off"
        />
      </div>
    </section>

    <section class="card">
      <div class="table-wrap">
        <table aria-label="Evakuierungsübersicht">
          <thead>
            <tr>
              <th>Klasse</th>
              <th>Raum</th>
              <th>Lehrkraft</th>
              <th>alle anwesend</th>
              <th>fehlende Personen</th>
            </tr>
          </thead>
          <tbody id="evacuation-table-body">
            {table_rows_html}
          </tbody>
        </table>
      </div>
    </section>

    <p class="footer-note">
      Hinweis: Wenn eine Klasse fehlt, sind meist WebUntis-Rechte, Stundenzeiten oder die Adapter-Funktion zu prüfen.
    </p>
  </main>

  <script>
    (function () {{
      "use strict";

      const STORAGE_PREFIX = "evacuation-overview::";
      const filterInput = document.getElementById("table-filter");
      const rows = Array.from(document.querySelectorAll("#evacuation-table-body tr"));

      function getStorageKey(rawKey) {{
        return STORAGE_PREFIX + rawKey;
      }}

      function restoreCheckboxes() {{
        const checkboxes = document.querySelectorAll(".attendance-checkbox");
        checkboxes.forEach((checkbox) => {{
          const rawKey = checkbox.dataset.key;
          const savedValue = localStorage.getItem(getStorageKey(rawKey));
          checkbox.checked = savedValue === "true";

          checkbox.addEventListener("change", () => {{
            localStorage.setItem(getStorageKey(rawKey), String(checkbox.checked));
          }});
        }});
      }}

      function restoreTextInputs() {{
        const textInputs = document.querySelectorAll(".missing-input");
        textInputs.forEach((input) => {{
          const rawKey = input.dataset.key;
          const savedValue = localStorage.getItem(getStorageKey(rawKey));
          if (savedValue !== null) {{
            input.value = savedValue;
          }}

          input.addEventListener("input", () => {{
            localStorage.setItem(getStorageKey(rawKey), input.value);
          }});
        }});
      }}

      function applyFilter() {{
        const searchTerm = (filterInput.value || "").trim().toLowerCase();

        rows.forEach((row) => {{
          const classValue = row.dataset.class || "";
          const teacherValue = row.dataset.teacher || "";
          const match = !searchTerm
            || classValue.includes(searchTerm)
            || teacherValue.includes(searchTerm);

          row.classList.toggle("hidden-row", !match);
        }});
      }}

      restoreCheckboxes();
      restoreTextInputs();

      if (filterInput) {{
        filterInput.addEventListener("input", applyFilter);
      }}
    }})();
  </script>
</body>
</html>
"""


def write_output_file(content: str) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(content, encoding="utf-8")


def main() -> None:
    generated_at = now_local()
    active_slot = determine_relevant_slot(generated_at)

    if active_slot is None:
        raise RuntimeError("Konnte keine relevante Unterrichtseinheit bestimmen.")

    rows = fetch_rows_for_active_slot(active_slot)
    html_content = render_html(rows=rows, generated_at=generated_at, active_slot=active_slot)
    write_output_file(html_content)

    print(f"HTML erfolgreich erzeugt: {OUTPUT_FILE}")
    print(f"Aktive Einheit: {active_slot.label}")
    print(f"Zeilen: {len(rows)}")


if __name__ == "__main__":
    main()
