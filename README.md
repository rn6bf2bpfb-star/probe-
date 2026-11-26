# Trading Center – KI-Börsenanalyse & Planspiel

Ein persönliches Trading-Center, das komplett in der GitHub-Cloud läuft und am Handy wie eine App funktioniert.
**Börsen-Planspiel mit 10.000 € virtuellem Kapital. Es werden keine echten Orders ausgeführt.**

| Bereich | Was es tut |
|---|---|
| Dashboard | Marktübersicht (DAX, MDAX, S&P 500, NASDAQ 100, Dow, MSCI World, Gold, Silber, Öl, Bitcoin, Ethereum) mit Tag/Woche/Monat, Trend, Zeitstempel und Datenqualität; Marktumfeld positiv/neutral/negativ mit Begründung; eigener Angst-/Gier-Indikator, VIX, Zinsen, Inflation |
| KI-Aktienanalyst | ~80 Aktien & ETFs: Fundamental- (Umsatz, Gewinn, KGV, KBV, EK-Quote, Verschuldung, Cashflow, Dividende), Technik- (SMA 20/50/200, RSI, MACD, S/R, Volumen, Trendkanal, rel. Stärke, Volatilität) und Nachrichtenanalyse |
| Signale | STRONG BUY … STRONG SELL, getrennt für **Trading** und **Investment**, jeweils mit allen 11 Pflichtangaben inkl. Szenarien, Verlustbereich, Unsicherheit, Ungültigkeitsbedingungen und Gegenargumenten. Nie aus einem einzelnen Indikator (mind. 3 bestätigende Faktorgruppen) |
| Depot | Virtuelle Käufe/Verkäufe von Aktien & ETFs, Market/Limit/Stop, Stop-Loss/Take-Profit (OCO), Stück oder Euro-Betrag, Gebühren, Slippage, vereinfachte Abgeltungsteuer mit Freibetrag & Verlusttöpfen, G/V realisiert/unrealisiert, Verteilung, Performance je Strategie |
| Alerts | Kaufgelegenheiten, Verkaufssignale im Depot, Kursmarken, Volumenspitzen, starke Bewegungen, Nachrichten, Quartalszahlen, Stimmungswechsel, Depotrisiken – per Website, Telegram, Push (ntfy), E-Mail |
| Berichte | Morgen-, Zwischen- und Abendbericht an jedem Handelstag, optional mit KI-Kommentar |
| Kalender | Fed- und EZB-Termine (mit Quelle), US-Konjunkturdaten, Quartalszahlen, Dividenden, eigene Termine |
| Screener | 11 Filterkriterien + tägliche KI-Auswahl je Branche mit Begründung |
| Risiko | Positionsgrößenrechner, CRV, Stop-/Take-Profit-Simulation, Diversifikation, Korrelationen, Drawdown, Warnungen (Klumpen, Volatilität, Verlustserien, Overtrading) |
| Trefferquote | Jede Signaländerung wird gespeichert und nach 5/20 bzw. 60/120 Handelstagen ausgewertet – inkl. Fehlschlägen und Kosten |

## So funktioniert es

```
GitHub Actions (Zeitplan, werktags stündlich + abends, Wochenende 1×)
   │  Python-Backend: Daten holen → Orders ausführen → analysieren → Alerts → Bericht
   │  Zustand (Depot, Signale, Alerts, Berichte) wird ins Repository committet
   ▼
GitHub Pages: statische Website (dunkel, responsiv) liest die erzeugten JSON-Dateien
   ▲
Website-Button „Order senden“ → GitHub API → Workflow mit deinem Befehl
```

Die Überwachung läuft **nur, wenn der Workflow läuft** (planmäßig stündlich). Die Website zeigt immer den
Zeitpunkt des letzten Laufs und warnt, wenn er zu lange zurückliegt. Echtzeit wird nie behauptet.

## Einrichtung (einmalig, ca. 20 Minuten, geht am Handy)

1. **GitHub-Konto** anlegen und ein neues Repository `trading-center` erstellen.
   * Kostenloses Konto: GitHub Pages geht nur bei **öffentlichen** Repositories. Dann sind dein virtuelles Depot
     und die Website öffentlich einsehbar (ohne Schlüssel – die bleiben in Secrets). Die Seite ist für Suchmaschinen
     gesperrt. Beachte: Öffentlich angezeigte Yahoo-Kurse sind lizenzrechtlich heikel.
   * **Privat** (empfohlen): GitHub Pro (ca. 4 $/Monat) erlaubt Pages aus privaten Repositories.
2. **Projektinhalt hochladen** (ZIP entpacken, alle Dateien inkl. `.github/` ins Repository). Am einfachsten am PC
   per „Add file → Upload files“ oder mit GitHub Desktop.
3. **Pages aktivieren:** Settings → Pages → Source: **GitHub Actions**.
4. **Actions-Rechte:** Settings → Actions → General → Workflow permissions: **Read and write**.
5. **Secrets** anlegen unter Settings → Secrets and variables → Actions (alle optional, je mehr desto besser):

| Secret | Wofür | Woher (kostenlos) |
|---|---|---|
| `FINNHUB_API_KEY` | Marktnachrichten, mehr Unternehmensnews (US) | finnhub.io → Get free API key |
| `FRED_API_KEY` | US-Leitzins, CPI, Arbeitslosigkeit, Termine von CPI/Arbeitsmarkt/BIP | fred.stlouisfed.org → My Account → API Keys |
| `FMP_API_KEY` | ergänzende Kennzahlen (US) | financialmodelingprep.com |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Alerts & Berichte per Telegram | @BotFather → `/newbot`; Chat-ID über @userinfobot |
| `NTFY_TOPIC` | Push aufs Handy | App „ntfy“ installieren, langes zufälliges Thema abonnieren |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | E-Mail | z. B. Gmail mit App-Passwort |
| `ANTHROPIC_API_KEY` | KI-Kommentar in Berichten (kostenpflichtig je Nutzung) | console.anthropic.com |

   Ohne jeden Schlüssel läuft alles mit Yahoo Finance (Kurse, Fundamentaldaten, News, Analysten, Termine) und
   der EZB (Einlagesatz, Inflation Euroraum). Optional unter **Variables**: `SITE_URL` = Adresse deiner Website (für Links in Alerts).
6. **Erster Lauf:** Actions → Trading Center → **Run workflow** → Bericht `morning`. Dauert beim ersten Mal 5–10 Minuten.
   Danach ist die Website unter `https://<name>.github.io/trading-center/` erreichbar. Am Handy „Zum Home-Bildschirm“ hinzufügen.
7. **Orders aus der Website senden:** GitHub → Settings (Profil) → Developer settings → Fine-grained tokens →
   Token nur für dieses Repository, Berechtigung **Actions: Read and write**. In der Website unter Einstellungen
   eintragen. Der Token bleibt nur in deinem Browser. Ohne Token: Befehl kopieren und in der GitHub-App bei
   „Run workflow“ ins Feld `command` einfügen.

## Gut zu wissen

* **Kosten:** Öffentliche Repositories haben unbegrenzte Actions-Minuten. Privat sind 2.000 Min./Monat frei; der
  Zeitplan braucht grob 1.200–1.600 Min. (Verbrauch unter Settings → Billing prüfen, sonst in der Workflow-Datei seltener planen).
* GitHub startet geplante Läufe oft 5–30 Minuten verspätet. Eine Order wird im nächsten Lauf verarbeitet und zum
  ersten Kursbalken **danach** ausgeführt – nie zu einem vergangenen Kurs.
* Yahoo-Kurse sind meist 15–20 Min. verzögert; jede Zahl zeigt Quelle, Zeitpunkt und Qualität
  (verzögert / Schlusskurs / veraltet / nicht verfügbar). Bei Ausfällen bleibt der letzte Stand sichtbar.
* MSCI World wird über den iShares-ETF (EUNL) abgebildet, weil der Index frei nicht verfügbar ist.
* Der Angst-/Gier-Wert ist eine eigene, offengelegte Berechnung (VIX, Marktbreite, 52-W-Hochs/-Tiefs, Momentum,
  Aktien vs. Gold), nicht der CNN-Index.
* Nachrichten-Tonalität ist eine Stichwortanalyse, kein Textverständnis – Originalquelle lesen.
* Termine von Hauptversammlungen und Euroraum-Konjunkturdaten gibt es nicht als freie API: in `config/events.yaml` eintragen.
* Alle Einstellungen (Gebühren, Steuern, Grenzwerte, Universum) liegen in `config/`.

## Lokal testen (optional, PC)

```bash
cd backend
pip install -r requirements.txt
python -m pytest ../tests -q          # 16 Offline-Tests
python -m tc demo                     # Demo mit synthetischen Daten (eigener Zustand, deutlich markiert)
python -m tc run --no-send            # echter Lauf ohne Versand
cd ../site && python -m http.server 8000   # Website unter http://localhost:8000
```

## Aufbau

```
backend/tc/
  data/        yahoo.py (yfinance), rest.py (Finnhub, FMP, FRED, EZB), synthetic.py (nur Demo/Tests), hub.py (Cache, Lücken, Quellen)
  indicators.py  SMA, RSI, MACD, Bollinger, ATR, ADX, Volumen, S/R-Zonen, Trendkanal
  market.py      Marktübersicht, Stimmung, Umfeld
  analyst.py     Fundamental-/Technik-/News-Bewertung, Signale mit Bestätigungsregel
  signals.py     Signal-Historie & Trefferquote
  depot.py       Planspiel-Engine (Orders, Gebühren, Steuern, OCO)
  risk.py        Kennzahlen, Diversifikation, Warnungen
  alerts.py      Meldungen, Entdoppelung, Telegram/ntfy/E-Mail
  reports.py     Morgen-/Zwischen-/Abendbericht
  econ_calendar.py, llm.py (optionaler KI-Kommentar), pipeline.py (ein Lauf), __main__.py (CLI)
site/            index.html, app.js, charts.js, style.css – ohne externe Bibliotheken
config/          settings.yaml, universe.yaml, events.yaml, price_alerts.yaml
state/           Depot, Signale, Alerts, Berichte (vom Workflow gepflegt)
```

**Keine Anlageberatung.** Signale, Berichte und Szenarien sind analytische Orientierung für das Planspiel.
