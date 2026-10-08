# Pflichtenheft: KNX Arranger

**Version:** 3.33
**Datum:** 08.10.2026
**Projekt:** KNX Arranger
**Rechteinhaber:** Michael Mueller SmartHome&EnergieManagement
**Status:** Entwurf

### Aenderungshistorie

| Version | Datum | Autor | Aenderungen |
|---------|-------|-------|-------------|
| 1.0 | 13.02.2026 | M. Mueller / Claude AI | Erstversion: Grundstruktur, funktionale und nicht-funktionale Anforderungen |
| 2.0 | 13.02.2026 | M. Mueller / Claude AI | Umfassende Ueberarbeitung: XLSX-Import, Gewerke-Katalog, Adressblock-Schemata, Topologie-Regeln, Datenmodell, Anwendungsfaelle |
| 2.1 | 13.02.2026 | M. Mueller / Claude AI | ETS6-XLSX-Topologie-Report-Import, erweiterte Validierung, Topologie-Report-Ansichten |
| 2.2 | 13.02.2026 | M. Mueller / Claude AI | GUI-Design (KNX-Farben, Drag-and-Drop), Personalisierung/Firmenprofil, Urheberrecht, Softwareschutz und Lizenzierung, Lizenzserver-Infrastruktur, Namensaenderung zu KNiX Arranger |
| 3.0 | 13.02.2026 | M. Mueller / Claude AI | MoSCoW-Priorisierung, Systemvoraussetzungen, Update-Mechanismus, Datenschutz, Installer, Logging, Internationalisierung, Online-Hilfe |
| 3.1 | 13.02.2026 | M. Mueller / Claude AI | 10-Schritt-Wizard (FA-1002), Wohnungen/Zonen (FA-107), HV/UV und Linienzuteilung (FA-208-210), Produktdatenblaetter (FA-1200), Aktor-/Sensor-Ermittlung (FA-1300/1400), Bauherr-Funktionsdefinition (FA-1500), Offertanfragen (FA-1600), Kundenofferte (FA-1700) |
| 3.2 | 14.02.2026 | M. Mueller / Claude AI | Szenen-Definition (FA-1800), Abnahmeprotokoll/Inbetriebnahme (FA-1900), Bauherr-Bedienungsanleitung (FA-2000), Revisionsunterlagen/As-Built (FA-2100), Nachkalkulation (FA-2200) |
| 3.3 | 16.02.2026 | M. Mueller / Claude AI | Wizard-Projektdatenladung (FA-1016), manuelle Topologie-Anpassung (FA-213 praezisiert), Topologie-Darstellung erweitert (FA-1007 praezisiert: Speisegeraete, bedingte Bereichskoppler, Linienkoppler), automatische Spaltenbreitenanpassung (NFA-034) |
| 3.4 | 24.02.2026 | M. Mueller / Claude AI | Wizard-Schrittstruktur korrigiert: Schritt 4 in zwei Einzelschritte aufgeteilt (FA-1002 aktualisiert), Schritte 6 und 8 (Aktoren/Sensoren) als noch nicht integriert gekennzeichnet, Gesamtzahl neu 11 Schritte (NFA-033 aktualisiert); FA-1007: Speisegeraete als eigenstaendige Baumelemente und bedingte Anzeige von Bereichskopplern praezisiert |
| 3.5 | 25.02.2026 | M. Mueller / Claude AI | Materiallisten-Funktionalitaet hinzugefuegt (FA-2301 bis FA-2308): Datenmodell MaterialList, Produktkatalog um Infrastruktur-Geraete erweitert, KNXPROD-Import (FA-2304), Produktauswahl-Dialog (FA-2303), Materiallisten-Ansicht (FA-2302), Wizard-Integration Step06/08 (FA-2305), Sidebar-Eintrag, Menuepunkt KNXPROD-Import |
| 3.6 | 04.03.2026 | M. Mueller / Claude AI | 8 neue Anforderungsbereiche ergaenzt: KNXPROJ-Export (FA-2400), Sensor-Aktor-Verknuepfungsmatrix (FA-2500), Leitungslaengenberechnung (FA-2600), KNX Secure (FA-2700), DALI-Detailkonfiguration (FA-2800), Zeitsteuerungsplanung (FA-2900), CO-Auto-Linking (FA-3000), ETS COM-Server (FA-3100) |
| 3.7 | 05.03.2026 | M. Mueller / Claude AI | Sensortyp-Override pro Raum ergaenzt (FA-1407): Integrator kann automatisch ermittelten Sensortyp in Wizard Schritt 8 per Doppelklick manuell ueberschreiben; Override wird im Datenmodell (GewerkAssignment.sensor_type_override) persistiert und bei Neuberechnung beibehalten |
| 3.8 | 05.03.2026 | M. Mueller / Claude AI | Eingabe-Effizienz und Workflow-Optimierung (FA-3201 bis FA-3211): Schnelleingabe Stockwerke, Auto-Zone, Raum-Klonen, Inline-Bearbeitung, Massenerfassung Raeume, Return-Taste in Formularen, Multi-Select Gewerke, Auf-alle-gleichen-Raeume, Schnell-Buttons Gewerke, erweiterte Gebaeudevorlagen, Wizard-Schritt-Statusanzeige |
| 3.9 | 06.03.2026 | M. Mueller / Claude AI | Zeitsteuerungsplanung detailliert (FA-3301 bis FA-3308): Datenmodell TimeProgram/DayProfile/SwitchPoint, Zeitprogramm-Editor-Ansicht mit Wochenraster, Astro-Timer-Konfiguration (Standortkoordinaten, SPA-Algorithmus), Feiertagskalender CH/DE/AT als JSON, Wochenprogramm-Vorlagen (Beschattung, Licht, Heizung, Lueftung), GA-Verknuepfungs-Validierung, Zeitsteuerungsplan-Dokumentationsexport, Zentralgruppen-GA-Anlage fuer Astro-Gruppen |
| 3.10 | 07.03.2026 | M. Mueller / Claude AI | Gateway-Gewerke und Systemsensoren ergaenzt (FA-1307, FA-1308, FA-1408, FA-1409): Gewerk.interface_type unterscheidet "actor", "gateway" (WP, MM, LDA) und "system_sensor" (W); Device.device_type um "gateway" erweitert; Gewerk-Katalog-Tabelle um Schnittstellentyp-Spalte ergaenzt; Aktor-Ermittlung und Sensor-Ermittlung fuer Gateway-Gewerke und projektweite Systemsensoren spezifiziert |
| 3.11 | 05.04.2026 | M. Mueller / Claude AI | Sensorfunktion-Konzept eingefuehrt (FA-1410): Bedienelement.control_functions ersetzt durch Bedienelement.funktionen (Liste von SensorFunktion); eine SensorFunktion buendelt alle Primaer- und Rueckmelde-GAs einer Gewerk-Instanz; direkte GA-Zuweisung als degenerierte Einzelfunktion; Dialog zeigt eine Zeile pro logischer Steuereinheit; Abwaertskompatibilitaet durch automatische Migration alter control_functions-Daten |
| 3.12 | 19.06.2026 | M. Mueller / Claude AI | Nachfuehrung auf Code-Stand v1.1.2: Wizard-Schrittstruktur auf 13 Schritte korrigiert (FA-1002: Tastereinheiten-Matrix, Szenen-Definition vor GA-Generierung); Workspace-Konzept fuer Projekt- und Berichtsablage neu dokumentiert (FA-3401 bis FA-3408); Bauherren-Beratungsansicht mit persistenten Anmerkungen ergaenzt (FA-1508 bis FA-1511); KNXPROJ-Passwortimport erweitert (FA-524, FA-525 ueberarbeitet: neueres ETS6-Containerformat, AES-Erkennung, ETS6-Cloud-Lizenz als nicht entschluesselbarer Sonderfall, Passwort-Dialog); ETS6 Gruppenadress-Report (XLSX) als eigenstaendiges Importformat ergaenzt (FA-519b); FA-854 um Zwischenablage-Import fuer Firmenlogo/Projektfoto ergaenzt |
| 3.13 | 23.09.2026 | M. Mueller / Claude AI | Nachfuehrung auf Code-Stand v1.1.16: Uebernahme importierter Projekte in die Planung dokumentiert (FA-521b bis FA-521g: Verteiler-Raeume aus Einbauort, Funktionszuordnungen aus KO-Verknuepfungen, Kanal-Gewerk-Konflikte, Wiedererkennung importierter GAs, manuelle Kanal-Zuweisung, Gewerk-Vorschlaege mit Pruefdialog); Szenen-Erkennung aus ETS-Importen ergaenzt (FA-1808 bis FA-1810: Erkennung, Szenen-Schaltwerte, Szenen-Ausloeser); Internet-Produktvorschlag konkretisiert (FA-1303a bis FA-1303d: Online-Produktkatalog im Release-Repository, Zwischenspeicher, Vorrang eigener Importe); KNXPROD-Import praezisiert (FA-2304a bis FA-2304c: Applikationszuordnung aus Hardware.xml, zusammengefasste Objektvarianten, manueller GA-Bedarf); Lizenzschluessel per Copy-Paste (NFA-098a) |
| 3.14 | 25.09.2026 | M. Mueller / Claude AI | KNXPROJ-Export entfallen (FA-2401 bis FA-2406 sowie die davon abhaengigen Teile von FA-2706, FA-2806, FA-3005, FA-3308c): ETS6 akzeptiert nur von ETS signierte Projektdateien, mit ETS6 getestet (ETS6- und ETS5-Format, Basis-Projekt mit Original-Signatur); Weg nach ETS6 ist der CSV-Gruppenadress-Export. Produktdaten ergaenzt (FA-2304d bis FA-2304f: KNX-Hersteller-ID als Schluessel mit einheitlichen Herstellernamen, Produktabgleich ueber normalisierte Bestellnummer, ETS-Kennungen der Produkte). Passwortgeschuetzter Import korrigiert (FA-525b/c: abgeleitetes ZIP-Passwort, Cloud-Lizenz-Zertifikat kein Hinderungsgrund) |
| 3.15 | 26.09.2026 | M. Mueller / Claude AI | Validierungsbericht Gruppenadressen neu gegliedert (FA-901): je Stufe ein Abschnitt, je Regel Bedeutung, Massnahme und eigene Spalten, DPT-Vorschlag aus der Bezeichnung (FA-604), Luecken nur noch als Hinweis (FA-605), viele Bezeichnungs-Hinweise als Beispielliste (FA-610). Einheitliches PDF-Layout (FA-858): Firmenschrift Inter mitgeliefert, farbiger Abschnittsbalken, Fortsetzungstitel bei Seitenumbruch. Projektzusammenfassung zaehlt Gewerke importierter Projekte aus der Topologie (FA-903), Anzahlen in Schritt 5 aus der Topologie uebernehmbar (FA-903a). Topologie-Bericht mit Prinzipschema, Kennzahlen je Linie und Geraetelisten nach Linie und nach Einbauort (FA-904); Spannungsversorgungen ohne ETS-Adresse als B.L.- (FA-516); Bericht Bedienelemente und Sensoren nach Stockwerk/Raum mit Tastenplan (FA-906); PDF-Lesezeichen in allen Berichten; Bauherr-Formular nur mit Bedienelementen, Stockwerk bei mehrdeutigen Raumnummern, Einlesen ueber Blattname und Geraeteadresse (FA-1501/1503); Theben thePixa & Co. als Praesenzmelder erkannt |
| 3.16 | 28.09.2026 | M. Mueller / Claude AI | Bericht Aktoren und Gateways im einheitlichen Berichtslayout (FA-907): Uebersicht mit belegten Kanaelen und Seitenzahlen, je Einbauort (Verteiler zuerst) Geraetekarten, geplante Projekte eine Zeile je Kanal mit Gewerk und Raum, importierte Projekte eine Zeile je Kommunikationsobjekt nach Kanal gegliedert. Topologie-Bericht zusaetzlich mit Topologie-Diagramm (FA-904), gleicher Aufbau wie die Ansicht. Koppler und Speisegeraete in Ansicht, Diagramm und Bericht nur, wenn als Geraet vorhanden (FA-1007). PDF-Berichte in allen Viewern durchsuchbar (bereinigte Unicode-Zuordnung der eingebetteten Schrift) und oeffnen mit sichtbarer Lesezeichen-Leiste (FA-858). Geraete ohne Einbauort aus der ETS: Topologie- und Aktoren-Bericht verwenden den zugeordneten Raum als Einbauort, die Topologie-Ansicht zeigt ihn grau und kursiv als Hinweis (Einbauort bleibt leer). Bericht Raeume nach Gewerken neu gegliedert, Raumzuordnung ueber die Bezeichnung statt ueber Aktoren im Verteiler, fehlende Raeume separat (FA-908). Szenenreport nach Szenen-Gruppenadresse gegliedert, Visualisierungs-Szenen und nicht eindeutige Erkennungen separat (FA-1811). Projekt neu aus ETS aufbauen (FA-527); automatische Sicherung vor Import und Neuaufbau (NFA-042). GA-Kommentar als Klartext importiert, Szenennamen daraus, Re-Import behaelt DPT-Nummern (FA-1810a). Szenen-Verwaltung nach Szenen-Adresse gegliedert (FA-1812), Szenenreport mit verknuepften Sendern und Empfaengern (FA-1811) |
| 3.17 | 28.09.2026 | M. Mueller / Claude AI | Gemeinsamer Import-Ablauf fuer alle ETS-Import-Wege, Report-Pfade im Projekt, Anzeige fehlgeschlagener Import-Schritte (FA-528). KNX Secure: kein Klartext von FDSK/Projektpasswort in Projektdatei und Sicherungen, Master-Passwort beim Import, alte Staende beim Speichern entfernt (FA-2706). Speichern-Frage beim Beenden nur bei Aenderungen, Speicherfehler sichtbar (NFA-045) |
| 3.18 | 29.09.2026 | M. Mueller / Claude AI | Ansichten lesen nur: Bedienelemente und Tastenbelegung werden nach Aenderungen statt beim Anzeigen neu berechnet; Aenderungen in der Verknuepfungsmatrix setzen Aenderungsmarkierung und Rueckgaengig-Punkt (NFA-046). Verknuepfungsmatrix als Uebersicht, Bearbeiten in der Bauherren-Beratung mit langem Tastendruck (FA-2503); Werkzeugleiste Rueckgaengig/Wiederholen, Wiederholen repariert (NFA-043). ETS-Projektdaten als XML ohne Schluessel fuer Partnerprogramme (FA-2407) |
| 3.19 | 30.09.2026 | M. Mueller / Claude AI | Auslieferung mit Nuitka nativ kompiliert, kein Quellcode im Bundle, Selbsttest des Bundles im Release-Workflow (NFA-071a). Lizenznehmer im Info-Dialog, in der Berichts-Fusszeile und in den PDF-Eigenschaften (NFA-098b). Zurueckgestellte Systemuhr verlaengert keine Lizenz (NFA-098c) |
| 3.20 | 01.10.2026 | M. Mueller / Claude AI | Pro Sensorkanal nur eine sendende GA (FA-614): weitere GAs an sendenden Tasten-KOs werden eingeordnet (Variante B: MG 6/7 = Rueckmeldung, sonst nach sendendem KO), zweite sendende GA als Warnung in Validierung, Validierungsbericht, Bericht Bedienelemente, Schritt 12, Topologie, Verknuepfungsmatrix und Bauherrenberatung (Rolle "Mithoeren - pruefen"). Bauherrenberatung zeigt GA-Nummern und Rollen; GA von Taste trennen in Bauherrenberatung und Topologie trennt auch die KO-Verknuepfung des Geraets (FA-614a). Validierungsansicht als Baum Stufe > Regel > Meldung mit Stufenfilter und Suche (FA-615). Bedienungsanleitung fuer den Bauherrn neu (FA-2001 bis FA-2004): je Taster Tastenplan und Bedienung in Alltagssprache aus den ETS-Parametern, Szenennamen aus dem GA-Kommentar, keine GA-Nummern. Kundenprofil in den Projekteigenschaften, Kundenofferte uebernimmt Name, Adresse und Anrede. Korrekturschicht fuer importierte Projekte (FA-616), Projektart und Richtlinien-Abstufung (FA-617). Inbetriebnahme-Checkliste je Taste eine Zeile nach Stockwerk gegliedert (FA-1904), Abnahmeprotokoll als Formular mit Umfang, Unterlagen und Maengelliste (FA-1911 bis FA-1914), Revisionspaket mit Abnahmeprotokoll und Seitenzahlen im Inhaltsverzeichnis, DALI-Liste nur mit erfassten EVGs, KNX-Secure-Bericht mit Linie und Geraetenamen aus der Topologie. Checkliste Excel: Blaetter Uebersicht (Fortschritt per Formel), je Stockwerk, Verteiler; Spalte OK als Auswahlliste mit Farbe; ausgefuellte Datei in der Inbetriebnahme einlesbar (Ergebnisse und Bemerkungen, "offen" ueberschreibt nichts) |
| 3.21 | 01.10.2026 | M. Mueller / Claude AI | Korrekturschicht erweitert: Raum eines Geraets (FA-616a, Topologie "Raum zuordnen...") und getrennte KO-Verknuepfungen (FA-616b) ueberstehen Re-Import und Neuaufbau; Hinweis nach dem Re-Import auf GAs, die in KNiX getrennt, in der ETS aber noch verbunden sind. Re-Import und Neuaufbau aus der .knxproj behalten Tastenparameter und Szenenwerte aus den Reports (FA-528a). ETS-Arbeitsliste (FA-618), knapp in ETS-Begriffen, mit Abgleich erledigt/neu/offen nach dem Re-Import |
| 3.22 | 02.10.2026 | M. Mueller / Claude AI | Frei stehende Nebengebaeude im Wizard: Gebaeudeauswahl in Schritt 1-3 mit Anlegen, Umbenennen und Entfernen (FA-101a); Hauptgruppen im ganzen Areal eindeutig, Validierung warnt bei mehrfach vergebener HG (FA-411a). Raumnummern frei gestaltbar im Pruefrahmen A-Z, 0-9, - und . (BZ-03a), z.B. Zonen-Praefix SEG02 oder S-EG02; Schritt 3 warnt bei Raumnummern ausserhalb des Pruefrahmens und bei doppelten Nummern im Projekt und schlaegt fuer neue Raeume die Nummer im Schema der Zone vor (FA-102a). Bezeichnungspruefung (FA-610) bei geplanten Projekten gegen die Gebaeudestruktur: der Raumteil muss ein vorhandener Raum sein. "Speichern" bei umbenanntem oder verschobenem Projektordner fuehrt zu "Speichern unter" mit Ordnervorschlag. Variante B: Rueckmeldungen eingebetteter 10er-Bloecke (LDA, LC, LCT, LCW, DMX) in MG 6, jeweils unter der Untergruppe ihres Befehls; Rueckmeldebloecke werden deckungsgleich zum Befehlsblock platziert statt angehaengt (FA-608a); Validierung prueft Rueckmeldungen in MG 0/1 und abweichende Untergruppen (FA-608). Projektzusammenfassung: Gebaeudestruktur je Gebaeude mit Stockwerk, HG und Zonen; HG-Namen von Stockwerken in Nebengebaeuden mit Gebaeudename (z.B. "Einstellhalle Erdgeschoss"). Szenen: Auswahl "Gilt fuer" mit jeder Zone einmal (auch ueber mehrere Stockwerke), eine Szenen-GA je Zone; bestehende Szenen-GA in der Planung auf Wunsch fuer den neuen Geltungsbereich neu erzeugen (FA-1812a); umbenannte feste Zentraladressen behalten ihren Namen. Berichte gliedern Stockwerke von Nebengebaeuden mit Gebaeudename. Einbauort der Aktoren: Verteiler je Linie (automatisch: Verteiler der Linie, sonst HV) waehlbar in Schritt 8, abweichend je Aktortyp, auch in der Topologie-Ansicht (FA-1305a). Steigschema (FA-905a): Gebaeudeschnitt mit dem Verlauf der Linien als Ansicht und im Topologie-Bericht (Querformat-Seite) |
| 3.23 | 06.10.2026 | M. Mueller / Claude AI | Klartext je Gewerk-Element (FA-403): Spalte "Bezeichnung" in Schritt 5, z.B. "Decke; Wand" bei LDA x2; steht in jeder GA des Elements nach dem Raumnamen (`LDA_E01_01 E/A (Wohnen Decke)`), auch ohne Klartext steht der Raumname nun in jeder GA statt nur in der ersten; Auswahllisten zeigen den Klartext statt der Elementnummer; Adressen neu ordnen fuer geplante Projekte mit Vorschau, Sicherung und Nachfuehrung der Verweise (FA-701 bis FA-706, UC-03); Vollstaendigkeitspruefung der Revisionsunterlagen mit Rueckfrage und offenen Punkten im Inhaltsverzeichnis, Materialliste im Revisionspaket (FA-2104, FA-2102); Topologie-Pruefungen in der Validierung: Geraeteanzahl je Linie, KO-Verknuepfungen, physikalische Adressen, Spannungsversorgung (FA-609, FA-611 bis FA-613); Revisionspaket: Bestandteile waehlbar (FA-2105), Revisionsbezeichnung, -datum und Anlass mit Ordner je Revision und Revisionsliste (FA-2106), Produktdatenblaetter als Anhang (FA-1204), akzeptierte Kundenofferte (FA-2102 Nr. 13); Bedienungsanleitung anpassen: eigene Texte, Abschnitte ein-/ausblenden, eigene Abschnitte, Text je Raum, Foto je Taster (FA-2005); Offertanfrage als PDF und E-Mail-Entwurf mit PDF-Anhang (FA-1614); Zeitsteuerung vervollstaendigt: Duplizieren, Umbenennen, aktiv/inaktiv, eigene Vorlagen, Wochenraster, Datumsbereich, GA-Filter, Astro-Vorschau, Feiertagsanzahl, DPT-Pruefung und Einfaerbung, Kennzeichnung zeitgesteuerter GAs (Programmname bzw. Uhr-Symbol statt [T]), Zeitsteuerungsplan und Abschnitt in der Bedienungsanleitung (FA-3302 bis FA-3307) |
| 3.24 | 06.10.2026 | M. Mueller / Claude AI | Sammel-Offertanfrage an mehrere Lieferanten (FA-1615); Offerten erfassen mit Rabatt und Lieferfrist, Status "Erhalten" automatisch, Versanddatum (FA-1621, FA-1622); Preisvergleich mit Hervorhebung des guenstigsten Anbieters und PDF (FA-1623, FA-1624); Zuschlag mit Nettopreisen und Ablehnung der uebrigen Anfragen der Sammelanfrage (FA-1625); Bedienungsanleitung in Deutsch, Franzoesisch, Italienisch und Englisch (FA-2006); Nachkalkulation aller Projekte mit Marge, Abweichungen, Verlauf und Vorschlaegen fuer die Richtwerte (FA-2205, FA-2206); Bezeichnung je Gewerk-Element: Tooltip mit Zuordnung, Warnung bei mehr Texten als Elementen, breitere Spalte, Anleitung in Hilfe und Handbuch (FA-403); DALI in geplanten Projekten: Gruppen je LDA-Element mit allen GAs, Namen aus der Bezeichnung, keine Gruppen-GAs als Broadcast (FA-2803); Gateways gemeinsam fuer das Projekt oder je Linie, waehlbar je Gewerk in Schritt 8 (FA-1307); Projektstatus "in ETS uebertragen" (FA-617a); DALI-Geraeteliste im Revisionspaket auch ohne EVGs (FA-2805) |
| 3.25 | 06.10.2026 | M. Mueller / Claude AI | Zeilenpruefung der NFA: unerwartete Fehler im Betrieb werden abgefangen, protokolliert und gemeldet, Crash-Report mit RAM, Bildschirm und letzter Aktion (NFA-041a, NFA-143a); Menue "Hilfe > Logdateien oeffnen" (NFA-146); Einstellungen ohne wirkungslose Projektstandards, Update-Pruefung wirksam (NFA-114a); Copyright in den PDF-Eigenschaften (NFA-082a); Stand und Abgrenzungen festgehalten: Performance gemessen (NFA-023a), Konfigurationsdateien (NFA-053a), Lizenzserver, Code-Signatur, Integritaetspruefung und Datenschutz zurueckgestellt bis Verkaufsstart (NFA-060a), Bildschirm/RAM (NFA-103a), Oberflaeche nur Deutsch (NFA-156a) |
| 3.26 | 07.10.2026 | M. Mueller / Claude AI | Zeilenpruefung der NFA abgeschlossen: Protokollstufe in den Einstellungen (NFA-142a); Programmeinstellungen im Benutzerordner "KNiX Arranger" wie alle Benutzerdaten (NFA-134a); Installer mit Herausgeber und Pruefung der Bildschirmaufloesung (NFA-132, NFA-133a); Inbetriebnahme-Checkliste passt die Spalten an (NFA-034a); ohne gueltige Lizenz Lesemodus statt Programmende (NFA-066a); Stand festgehalten zu Lizenzschluessel, Schutz, EULA, Datenuebermittlung und Installergroesse (NFA-062a, NFA-072a, NFA-081a, NFA-124a, NFA-135a) |
| 3.27 | 07.10.2026 | M. Mueller / Claude AI | Validierung: Hinweis auf schaltbare Elemente ohne Bedienung (FA-619); gemeinsames Gateway ermittelt nur sein eigenes Gewerk (FA-1307); Einzeltaster "Taste" ohne Nummer gilt in Berichten, Checkliste und Bedienungsanleitung als Taste 1 |
| 3.28 | 07.10.2026 | M. Mueller / Claude AI | Bauherrenberatung: Funktionen aus einer Liste auf eine Taste ziehen, auch aus einem anderen Raum, mit Markierung der Elemente ohne Bedienung; Tasten verschieben und tauschen; Taster direkt entfernen (FA-1015a) |
| 3.29 | 07.10.2026 | M. Mueller / Claude AI | Bauherrenberatung: alle Raeume als Baum, Bedienelemente und Praesenz-/Bewegungsmelder hinzufuegen und Leuchten darauf legen (FA-1015b) |
| 3.30 | 07.10.2026 | M. Mueller / Claude AI | Spannungsversorgungen nach T-06: SV der Bereichslinie 0.0 ergaenzt, SV auf B.0.- als Hauptlinie bezeichnet und auch bei einem Bereich mit mehreren Linien angelegt, Pruefung FA-613 fuer Haupt- und Bereichslinie, Begriffe in Topologie-Ansicht und Diagramm (Linienkoppler verbindet Linie mit Hauptlinie, Bereichskoppler Hauptlinie mit Bereichslinie); Topologie-Diagramm mit Bereichslinie, Hauptlinie als Busleitung und jeder SV an ihrer Linie (FA-904); Praesenz- und Bewegungsmelder mit Kanaelen statt Tasten, nur Schaltbefehl (FA-1015b) |
| 3.31 | 07.10.2026 | M. Mueller / Claude AI | Drag-and-Drop (a) bis (d) umgesetzt (FA-1015c): Raeume auf Wohnung/Zone oder Stockwerk ziehen; Geraete auf eine andere Linie ziehen (geplant: der Raum wechselt die Linie, importiert/manuell: das Geraet wandert mit freier Teilnehmernummer); Gewerke aus dem Katalog auf einen Raum ziehen oder eine Zuweisung in einen anderen Raum; Gruppenadressen tauschen oder in eine Mittelgruppe verschieben (nur geplante Projekte), Verweise werden nachgefuehrt und die Neuberechnung behaelt die Position |
| 3.32 | 08.10.2026 | M. Mueller / Claude AI | Raeume zusammenfuehren in Schritt 3 (FA-3203c); Spaltenfilter in der Topologie-Ansicht (FA-1007a); "Raum zuordnen..." bei geplanten Geraeten durch Hinweis ersetzt (FA-616a); erkannte Szenen folgen der Umbenennung ihrer GA (FA-1808); Schnell-Buttons Schritt 5: LDA ergaenzt, S = Steckdose, V = Ventilator (FA-3209a) |
| 3.33 | 08.10.2026 | M. Mueller / Claude AI | Gewerke-Uebersicht: Spalte "Bezeichnung" wie in Schritt 5 (FA-403), Tabelle mit voller Hoehe und ohne horizontales Scrollen (NFA-034); Statusmeldungen nur im festen Feld rechts der Statusleiste (NFA-023) |

---

## 1. Einleitung

### 1.1 Zweck des Dokuments
Dieses Pflichtenheft beschreibt die funktionalen und nicht-funktionalen Anforderungen an das Softwaretool **KNX Arranger**. Es dient als verbindliche Grundlage fuer die Entwicklung, Abnahme und Weiterentwicklung der Software.

### 1.2 Projektbeschreibung
Der KNX Arranger ist ein Desktop-Tool zur automatisierten Erstellung, Analyse, Validierung und Reorganisation von KNX-Projekten. Er kann bestehende ETS6-Dateien einlesen (Gruppenadress-Export als CSV sowie Topologie-Report als XLSX) oder neue KNX-Projekte von Grund auf erstellen. Er erstellt Gebaeudestrukturen, macht Vorschlaege fuer die KNX-Topologie nach den Dokumenten "04_Topology_DE0921a" (KNX TP-Topologie) und "KNX_Projektrichtlinien_2024" (KNX Swiss Projektrichtlinien). Er definiert die Gewerke und leitet daraus die Gruppenadressen ab und erstellt diese automatisiert. Die erzeugten Daten koennen als ETS6-kompatible CSV-Dateien exportiert werden.

### 1.3 Zielgruppe
- KNX-Systemintegratoren
- Elektroplanungsbueros
- Gebaeudeautomations-Ingenieure
- Projektleiter fuer KNX-Installationen
- Neueinsteiger als Basis fuer die firmeninterne KNX-Projektstrukturierung
- Ausbildungsstaetten zur Integration in ihre Kursunterlagen

### 1.4 Glossar

| Begriff | Beschreibung |
|---------|-------------|
| **ETS6** | Engineering Tool Software 6 -- Standardsoftware zur Konfiguration von KNX-Anlagen |
| **Gruppenadresse (GA)** | Logische Adresse im KNX-System im Format Haupt/Mittel/Sub (z.B. 2/0/15) |
| **Hauptgruppe** | Oberste Hierarchieebene der GA-Struktur (z.B. Stockwerk oder Zone), Bereich 0-31 |
| **Mittelgruppe** | Mittlere Hierarchieebene (z.B. Funktionsbereich wie Licht, Jalousie), Bereich 0-7 |
| **Untergruppe** | Unterste Ebene mit der eigentlichen Geraeteadresse, Bereich 0-255 |
| **Datenpunkttyp (DPT/DPST)** | Standardisierter Datentyp fuer KNX-Kommunikationsobjekte |
| **CSV** | Comma-Separated Values -- Exportformat der ETS6 fuer Gruppenadressen |
| **KNXPROJ** | Natives ETS-Projektformat -- ZIP-Archiv mit XML-Struktur (gemaess KNX-Standard), enthaelt alle Projektdaten (Gebaeudestruktur, Topologie, Gruppenadressen, Geraetekonfiguration) |
| **Physikalische Adresse** | Eindeutige Geraete-Identifikation im Format Bereich.Linie.Teilnehmer (z.B. 1.2.15) |
| **Linie** | Kleinste topologische Installationseinheit, max. 256 Busteilnehmer (TP-256) |
| **Bereich** | Zusammenfassung von bis zu 15 Linien ueber eine Hauptlinie |
| **Backbone / Bereichslinie** | Verbindung von bis zu 15 Bereichen (TP oder IP) |
| **Linienkoppler (LK)** | Verbindet untergeordnete Linie mit Hauptlinie, besitzt Filtertabelle |
| **Bereichskoppler (BK)** | Verbindet Hauptlinie mit Bereichslinie/Backbone |
| **Segmentkoppler (SK)** | Teilt eine Linie in Haupt- und Untersegmente (ab ETS6) |
| **KNX-IP-Router** | Verbindet KNX-TP mit Ethernet/IP-Backbone |
| **Gewerk** | Funktionsbereich im Gebaeude (z.B. Beleuchtung, Jalousie, Heizung) |
| **KNX Swiss** | Schweizerischer KNX-Verband, Herausgeber der Projektrichtlinien |

### 1.5 Urheberrecht und Nutzungsrechte
Alle Rechte an der Software **KNX Arranger** -- einschliesslich Quellcode, Design, Dokumentation und zugehoeriger Materialien -- liegen bei **Michael Mueller SmartHome&EnergieManagement**. Jede Vervielfaeltigung, Verbreitung oder Bearbeitung der Software bedarf der ausdruecklichen schriftlichen Genehmigung des Rechteinhabers.

**Hinweis zum Produktnamen:** Da "KNX" eine eingetragene Marke der KNX Association ist, wird der Produktname vorsorglich von **"KNX Arranger"** zu **"KNiX Arranger"** geaendert, um markenrechtliche Konflikte zu vermeiden. In diesem Dokument wird weiterhin der Arbeitstitel "KNX Arranger" verwendet; der endgueltige Produktname fuer die Veroeffentlichung lautet **KNiX Arranger**.

### 1.6 Referenzdokumente

| Dokument | Beschreibung |
|----------|-------------|
| 04_Topology_DE0921a.pdf | KNX Association: KNX TP-Topologie (Grundkurs) |
| KNX_Projektrichtlinien_2024.pdf | KNX Swiss Projektrichtlinien -- Update 2024 |
| ETS6_Chalet.csv | Beispiel-Gruppenadress-Export (Referenzprojekt Chalet) |
| Topologie.xlsx | ETS6-Topologie-Report mit Zusatzwahl "Objekte" (Referenzprojekt Chalet) |

### 1.7 Priorisierung der Anforderungen (MoSCoW)

Alle Anforderungen in diesem Pflichtenheft sind nach der MoSCoW-Methode priorisiert:

| Prioritaet | Kuerzel | Bedeutung |
|------------|---------|-----------|
| **Must** | **(M)** | Zwingend erforderlich fuer die erste Version. Ohne diese Anforderung ist die Software nicht lieferfaehig. |
| **Should** | **(S)** | Wichtig und erwartet. Sollte in der ersten Version enthalten sein, kann aber im Notfall nachgeliefert werden. |
| **Could** | **(C)** | Wuenschenswert. Wird implementiert, wenn Zeit und Budget es erlauben. |
| **Won't (yet)** | **(W)** | Nicht in der ersten Version. Fuer spaeteren Ausbau vorgemerkt. |

**Priorisierung aller Anforderungen:**

| Bereich | IDs | Prio | Begruendung |
|---------|-----|------|-------------|
| Gebaeudestruktur | FA-101, FA-102, FA-103, FA-105, FA-106, FA-107 | **(M)** | Kernfunktionalitaet |
| Gebaeudevorlagen | FA-104 | **(S)** | Beschleunigt den Einstieg |
| Topologie-Regeln | FA-201 bis FA-210 | **(M)** | Kernfunktionalitaet (inkl. HV/UV, Linienzuteilung) |
| Topologie-Varianten | FA-211, FA-213 | **(M)** | Notwendig fuer verschiedene Projekttypen |
| Topologie-Visualisierung | FA-212 | **(S)** | Wichtig fuer Verstaendnis |
| Physikalische Adressen | FA-221 bis FA-223 | **(M)** | Kernfunktionalitaet |
| Topologie-Beispiele | FA-231, FA-232 | **(S)** | Hilft bei der Validierung |
| Gewerke-Definition | FA-301, FA-302, FA-304, FA-305 | **(M)** | Kernfunktionalitaet |
| Eigene Gewerke | FA-303 | **(S)** | Flexibilitaet fuer Spezialfaelle |
| Gewerke-Vorlagen | FA-306 | **(C)** | Komfortfunktion |
| Gruppenadress-Bezeichnung | FA-401 bis FA-403 | **(M)** | Kernfunktionalitaet |
| Hauptgruppen-Zuordnung | FA-411 | **(M)** | Kernfunktionalitaet |
| Hauptgruppen anpassen | FA-412, FA-413 | **(S)** | Flexibilitaet |
| Mittelgruppen Variante A/B | FA-421 bis FA-423 | **(M)** | Kernfunktionalitaet |
| Untergruppen-Erstellung | FA-431 bis FA-436 | **(M)** | Kernfunktionalitaet |
| Zentraladressen | FA-441, FA-442 | **(M)** | Grundfunktionalitaet |
| Vordefinierte Zentral-Fkt. | FA-443 | **(S)** | Komfortfunktion |
| CSV-Import | FA-501 bis FA-506 | **(M)** | Kernfunktionalitaet |
| XLSX-Import | FA-511 bis FA-520 | **(S)** | Erweiterte Analysefaehigkeit |
| KNXPROJ-Import | FA-521 bis FA-526 | **(C)** | Vollstaendiger Projektimport in einem Schritt |
| Uebernahme importierter Projekte | FA-521b bis FA-521g | **(S)** | Importierte Projekte ohne Doppelungen weiterplanen |
| Validierung (Basis) | FA-601 bis FA-608, FA-610 | **(M)** | Kernfunktionalitaet |
| Validierung (Topologie) | FA-609, FA-611 bis FA-614 | **(S)** | Erweiterte Pruefungen |
| Reorganisation | FA-701 bis FA-706 | **(M)** | Kernfunktionalitaet |
| CSV-Export | FA-801 bis FA-805 | **(M)** | Kernfunktionalitaet |
| Personalisierung | FA-851 bis FA-854 | **(S)** | Professionelle Berichte |
| Personalisierung auf Berichten | FA-855 bis FA-858 | **(S)** | Professionelle Berichte |
| Berichtswesen Basis | FA-901, FA-902 | **(M)** | Kernfunktionalitaet |
| Berichtswesen erweitert | FA-903 bis FA-905 | **(S)** | Erweiterte Dokumentation |
| GUI Basis | FA-1001, FA-1002, FA-1003, FA-1004, FA-1008 | **(M)** | Grundlegende Bedienbarkeit |
| GUI Fehlermeldungen/Suche | FA-1005, FA-1006 | **(M)** | Grundlegende Bedienbarkeit |
| GUI Topologie-Ansicht | FA-1007 | **(S)** | Visuelle Unterstuetzung |
| GUI Topologie-Report | FA-1009, FA-1010, FA-1011 | **(S)** | Erweiterte Ansichten |
| GUI Design/KNX-Farben | FA-1012 | **(S)** | Professionelles Erscheinungsbild |
| GUI Grafik/Intuitiv | FA-1013, FA-1014 | **(S)** | Benutzerfreundlichkeit |
| GUI Drag-and-Drop | FA-1015 | **(C)** | Komfortfunktion |
| GUI Wizard-Datenladung | FA-1016 | **(M)** | Grundlegende Bedienbarkeit |
| Plattform/Technologie | NFA-011 bis NFA-013 | **(M)** | Lieferfaehigkeit |
| Performance | NFA-021 bis NFA-023 | **(S)** | Benutzererlebnis |
| Benutzbarkeit | NFA-031 bis NFA-034 | **(M)** | Zielgruppe muss bedienen koennen |
| Zuverlaessigkeit | NFA-041 bis NFA-044 | **(M)** | Stabilitaet |
| Wartbarkeit | NFA-051 bis NFA-053 | **(S)** | Langfristige Pflege |
| Lizenzsystem | NFA-061 bis NFA-067 | **(M)** | Softwareschutz |
| Code-Schutz | NFA-071 bis NFA-074 | **(M)** | Softwareschutz |
| Rechtlicher Schutz | NFA-081 bis NFA-083 | **(M)** | Rechtliche Absicherung |
| Lizenzserver (online) | NFA-091 bis NFA-097 | **(S)** | Kann anfangs durch Offline-Modus ersetzt werden |
| Offline-Lizenz | NFA-098 | **(M)** | Mindestschutz fuer Anfangsbetrieb |
| Systemvoraussetzungen | NFA-101 bis NFA-103 | **(M)** | Definiert Mindestanforderungen |
| Update-Pruefung | NFA-111 bis NFA-115 | **(S)** | Wichtig fuer Wartung und Support |
| In-App-Update | NFA-116 | **(W)** | Fuer spaetere Version vorgemerkt |
| Datenschutz | NFA-121 bis NFA-125 | **(M)** | Gesetzliche Pflicht (DSG/DSGVO) |
| Installation/Installer | NFA-131 bis NFA-135 | **(M)** | Professionelle Auslieferung |
| Logging | NFA-141 bis NFA-146 | **(S)** | Wichtig fuer Support und Fehlerbehebung |
| Internationalisierung (Architektur) | NFA-152, NFA-153 | **(M)** | Muss von Beginn an vorbereitet sein |
| Internationalisierung (DE) | NFA-151 | **(M)** | Erstsprache |
| Internationalisierung (FR, EN) | NFA-154 | **(S)** | Wichtige Maerkte CH/international |
| Internationalisierung (IT) | NFA-154 (IT) | **(C)** | Optionaler Markt |
| Internationalisierung (Locale) | NFA-155, NFA-156 | **(S)** | Konsistente Darstellung |
| Hilfesystem integriert | FA-1101 bis FA-1104 | **(S)** | Benutzerunterstuetzung |
| Benutzerhandbuch | FA-1105 | **(S)** | Dokumentation |
| Onboarding-Tour | FA-1106 | **(C)** | Komfortfunktion fuer Neueinsteiger |
| Produktdatenblaetter | FA-1201 bis FA-1205 | **(S)** | Professionelle Projektdokumentation |
| Aktor-Ermittlung (Basis) | FA-1301, FA-1302, FA-1305, FA-1306 | **(M)** | Kernfunktionalitaet Wizard Schritt 8 |
| Gateway-Gewerke (Aktor-Ermittlung) | FA-1307, FA-1308 | **(M)** | Gateway statt Aktor fuer WP, MM, LDA |
| Aktor-Vorschlag Internet | FA-1303, FA-1304 | **(S)** | Internet-Anbindung, bevorzugte Hersteller |
| Sensor-Ermittlung (Basis) | FA-1401, FA-1404, FA-1405, FA-1406, FA-1407 | **(M)** | Kernfunktionalitaet Wizard Schritt 6 |
| Systemsensoren (Sensor-Ermittlung) | FA-1408, FA-1409 | **(M)** | Projektweite Geraete (Wetterstation etc.) |
| Sensor-Vorschlag Internet | FA-1402, FA-1403 | **(S)** | Internet-Anbindung, bevorzugte Hersteller |
| Bauherr-Formular | FA-1501 bis FA-1511 | **(M)** | Kernfunktionalitaet Wizard Schritt 12 |
| Lieferantenverwaltung | FA-1601 bis FA-1603 | **(S)** | Grundlage fuer Offertanfragen |
| Offertanfrage-Erstellung | FA-1611 bis FA-1615 | **(S)** | Professionelle Beschaffung |
| Offertverwaltung/Preisvergl. | FA-1621 bis FA-1625 | **(C)** | Komfortfunktion fuer Beschaffungsprozess |
| Kundenofferte Kalkulation | FA-1701 bis FA-1706 | **(S)** | Kerngeschaeftsprozess Systemintegrator |
| Kundenofferte Dokument | FA-1711 bis FA-1715 | **(S)** | Professionelle Offertstellung |
| Kundenofferte Verwaltung | FA-1721 bis FA-1724 | **(C)** | Komfortfunktion Offertverwaltung |
| Szenen-Definition | FA-1801 bis FA-1805 | **(S)** | Wichtiger Bestandteil professioneller KNX-Projekte |
| Szenen in Dokumentation | FA-1806, FA-1807 | **(S)** | Integration in Bauherr-Workflow |
| Szenen-Erkennung aus Import | FA-1808 bis FA-1810 | **(S)** | Bestehende Szenen importierter Projekte uebernehmen |
| Inbetriebnahme-Checkliste | FA-1901 bis FA-1905 | **(M)** | Zwingend fuer professionelle Uebergabe |
| Abnahmeprotokoll | FA-1911 bis FA-1914 | **(M)** | Zwingend fuer professionelle Uebergabe |
| Bauherr-Bedienungsanleitung | FA-2001 bis FA-2004 | **(M)** | Zwingend fuer professionelle Uebergabe |
| Bedienungsanleitung anpassen | FA-2005, FA-2006 | **(S)** | Individualisierung und Mehrsprachigkeit |
| Revisionsunterlagen Paket | FA-2101 bis FA-2104 | **(M)** | Zwingend fuer Projektabschluss |
| Revisionsunterlagen Optionen | FA-2105, FA-2106 | **(S)** | Flexibilitaet und Versionierung |
| Nachkalkulation Basis | FA-2201 bis FA-2204 | **(S)** | Wichtig fuer Geschaeftserfolg |
| Nachkalkulation erweitert | FA-2205, FA-2206 | **(C)** | Langfristige Optimierung |
| Materialliste (Kern) | FA-2301, FA-2302, FA-2305, FA-2306 | **(M)** | Grundlage fuer Beschaffung und Dokumentation |
| Produktkatalog lokal | FA-2303 | **(M)** | Geraeteauswahl aus validiertem KNX-Katalog |
| KNXPROD-Import | FA-2304 | **(S)** | Herstellerdaten direkt einlesen |
| Materialliste Export | FA-2307, FA-2308 | **(S)** | Offertanfrage und Revisionsunterlagen |
| KNXPROJ-Export | FA-2401 bis FA-2406 | **entfallen** | ETS6 akzeptiert nur von ETS signierte Projekte (siehe 3.25) |
| Sensor-Aktor-Matrix | FA-2501 bis FA-2505 | **(S)** | Vollstaendige Verlinkungsuebersicht fuer Programmierung und Doku |
| Leitungslaengenberechnung | FA-2601 bis FA-2604 | **(S)** | Normkonformitaet sicherstellen (KNX TP Grenzwerte) |
| KNX Secure | FA-2701 bis FA-2706 | **(C)** | Zukunftssicher, wachsende Marktanforderung |
| DALI-Detailkonfiguration | FA-2801 bis FA-2806 | **(C)** | Vollstaendige DALI-Projektierung (Gruppen, Szenen, Notlicht) |
| Zeitsteuerungsplanung | FA-2901 bis FA-2906 | **(C)** | Astro-Timer, Wochenprogramme, Feiertagskalender |
| CO-Auto-Linking | FA-3001 bis FA-3005 | **(S)** | Groesster Zeitgewinn bei ETS-Programmierung |
| ETS COM-Server | FA-3101 bis FA-3104 | **(W)** | Inbetriebnahme-Unterstuetzung, spaeteren Ausbau vorgemerkt |
| Eingabe-Effizienz | FA-3201 bis FA-3211 | **(S/C)** | Workflow-Optimierung fuer den Integrator: Schnelleingaben, Multi-Select, Massenerfassung |
| Zeitsteuerung Datenmodell | FA-3301 | **(C)** | Grundlage fuer alle weiteren Zeitsteuerungsfunktionen |
| Zeitprogramm-Editor | FA-3302 | **(C)** | Hauptansicht zur Wochenprogramm-Pflege |
| Astro-Timer | FA-3303 | **(C)** | Sonnenauf-/-untergangs-Berechnung (SPA-Algorithmus) |
| Feiertagskalender | FA-3304 | **(C)** | CH/DE/AT-Feiertage lokal als JSON |
| Zeitprogramm-Vorlagen | FA-3305 | **(C)** | Schnellstart fuer haeufige Szenarien |
| GA-Verknuepfungs-Validierung | FA-3306 | **(C)** | Konsistenz zwischen Zeitprogrammen und GA-Struktur |
| Zeitprogramm-Dokumentation | FA-3307 | **(C)** | Integration in Bauherr-Anleitung und Revisionspaket |
| Zentralgruppen-GA-Anlage | FA-3308 | **(C)** | Astro-GAs in HG 0 automatisch anlegen |

---

## 2. Ausgangssituation und Zielsetzung

### 2.1 Ausgangssituation
Die Planung und Konfiguration von KNX-Projekten ist eine komplexe, zeitaufwendige Aufgabe:

- Die Gebaeudestruktur muss manuell in Bereiche, Linien und Segmente aufgeteilt werden
- Die KNX-Topologie muss unter Beruecksichtigung zahlreicher Regeln (max. Teilnehmer pro Linie, Stromversorgung, Leitungslaengen) geplant werden
- Gewerke muessen definiert und den Raeumen zugeordnet werden
- Hunderte bis tausende Gruppenadressen muessen manuell erstellt, benannt und mit Datenpunkttypen versehen werden
- Die Einhaltung der KNX Swiss Projektrichtlinien (Bezeichnungskonzept, Adressblockgroessen, Mittelgruppen-Zuordnung) muss manuell sichergestellt werden
- Bei bestehenden Projekten treten haeufig Inkonsistenzen auf: unterschiedliche Namensgebung, fehlende DPTs, lueckenhafte Adressierung, Abweichungen von Richtlinien

### 2.2 Zielsetzung
Der KNX Arranger soll den gesamten Planungsprozess automatisieren und strukturieren:

1. **Gebaeudestruktur erstellen** -- Areale, Gebaeude, Stockwerke und Raeume erfassen
2. **Gewerke den Raeumen zuweisen** -- Funktionsbereiche (Licht, Jalousie, Heizung, Alarm etc.) pro Raum festlegen; die Gewerke gehoeren zum Gebaeude
3. **Aktoren ableiten und Topologie erstellen** -- Die Gewerke bestimmen die benoetigen Aktoren (Schaltaktoren, Jalousieaktoren etc.); aus der Aktoranzahl wird die KNX-Topologie (Bereiche, Linien, Koppler) nach den Regeln der KNX TP-Topologie und den KNX Swiss Projektrichtlinien automatisch abgeleitet
4. **Gruppenadressen automatisiert erstellen** -- Die Gewerke werden ueber Gruppenadressen gesteuert; basierend auf Gebaeudestruktur, Topologie und Gewerken werden vollstaendige Gruppenadress-Strukturen generiert (inkl. Bezeichnungen, DPTs, Adressblocking)
5. **Sensoren zuweisen** -- Die Gruppenadressen werden durch Sensoren ausgeloest, die im Gebaeude montiert sind (i.d.R. im Raum des zu steuernden Gewerks); Sensor-GA-Zuordnungen werden pro Taste/Kanal definiert
6. **Bestehende Projekte analysieren und validieren** -- ETS6-Exporte (CSV, XLSX, KNXPROJ) einlesen, pruefen und Abweichungen melden
7. **Projekte reorganisieren** -- Bestehende Gruppenadress-Strukturen normgerecht umstrukturieren
8. **ETS6-kompatible Exporte erzeugen** -- Generierte oder reorganisierte Daten als CSV fuer den ETS6-Import bereitstellen

### 2.3 Logischer Planungsprozess

Der Planungsprozess folgt einem kausalen Datenfluss von der physischen Gebaeude-ebene bis zur logischen Steuerungsebene:

```
1. Gebaeude          (Was wird gebaut?)
        |
        v
2. Gewerke           (Was wird gesteuert? Licht, Jalousie, Heizung...)
        |
        v
3. Aktoren           (Welche Geraete steuern die Gewerke?)
        |
        v
4. Topologie         (Wie viele Linien/Bereiche braucht es fuer die Aktoren?)
        |
        v
5. Gruppenadressen   (Wie werden die Gewerke logisch angesprochen?)
        |
        v
6. Sensoren          (Wer loest die Gruppenadressen aus? Montiert im Gebaeude.)
```

**Begruendung der Reihenfolge:**

| Schritt | Abhaengigkeit | Erlaeuterung |
|---------|--------------|--------------|
| Gebaeude | (Basis) | Definiert Raeume als Bezugspunkt fuer alle weiteren Schritte |
| Gewerke | braucht Gebaeude | Gewerke werden Raeumen zugewiesen; ohne Raeume keine Zuweisung |
| Aktoren | braucht Gewerke | Anzahl und Typ der Aktoren ergeben sich direkt aus den Gewerken |
| Topologie | braucht Aktoren | Geraeteanzahl (Aktoren + Sensoren) bestimmt Linien- und Bereichsaufteilung |
| Gruppenadressen | braucht Gewerke + Topologie | GA-Struktur spiegelt Gebaeudestruktur und Gewerke wider; Topologie bestimmt Hauptgruppen |
| Sensoren | braucht GAs + Gebaeude | Sensoren sind physisch im Gebaeude montiert und loesen logische GAs aus |

---

## 3. Funktionale Anforderungen

### 3.1 Gebaeudestruktur-Erfassung (FA-100)

| ID | Anforderung |
|----|-------------|
| FA-101 | Das System muss die Erfassung einer Gebaeudestruktur mit folgender Hierarchie ermoeglichen: Areal > Gebaeude > Gebaeude-Fluegel > Stockwerk > Wohnung/Zone > Raum. |
| FA-101a | Frei stehende Nebengebaeude (z.B. Einstellhalle) werden im Wizard als eigenes Gebaeude erfasst: Schritt 1 hat eine Gebaeudeauswahl mit "+ Gebaeude", Umbenennen und Entfernen; die Auswahl gilt auch fuer Schritt 2 (Zonen) und 3 (Raeume). Bearbeitet wird der erste Fluegel des Gebaeudes. Jedes Gebaeude wird in der Topologie ein eigener Bereich. Kleinstbauten (z.B. Gartenhaus mit einer Steckdose) koennen als Zone im Hauptgebaeude bleiben. |
| FA-102 | Pro Wohnung/Zone muessen beliebig viele Raeume mit eindeutiger Raumnummer angelegt werden koennen (z.B. E01, E02, ... oder UG01, EG01, OG01). |
| FA-102a | Fuer einen neuen Raum schlaegt das System die naechste freie Nummer im Schema der Zone vor, gelernt aus deren Raeumen (auch auf anderen Stockwerken): Zonen-Praefix + Stockwerkkuerzel + Trennzeichen + laufende Nummer (z.B. SEG04, LEG01). Neue Zone in einem Projekt mit Zonen-Praefixen: erster noch freier Buchstabe des Zonennamens. Sonst Stockwerkkuerzel + Nummer. Raumnummern ausserhalb des Pruefrahmens (BZ-03a) oder im Projekt doppelt werden in Schritt 3 orange markiert (Tooltip mit Grund) und nach Uebernehmen, Massenerfassung und Einfuegen gemeldet. |
| FA-103 | Das System muss die gaengigen Stockwerksbezeichnungen unterstuetzen: UG (Untergeschoss), EG (Erdgeschoss), OG (Obergeschoss), DG (Dachgeschoss), sowie nummerierte Varianten (1.OG, 2.OG etc.). |
| FA-104 | Das System muss vordefinierte Gebaeudevorlagen anbieten (z.B. EFH, MFH, Zweckbau), die als Ausgangsbasis fuer die Strukturerfassung dienen. |
| FA-105 | Der Benutzer muss die Gebaeudestruktur manuell anpassen koennen (Stockwerke, Wohnungen/Zonen und Raeume hinzufuegen, entfernen, umbenennen, verschieben). |
| FA-106 | Das System muss die Anzahl der geplanten KNX-Geraete pro Raum erfassen koennen, um die Topologieplanung zu unterstuetzen. Als Standardwert werden pro Raum 4 Sensoren und 2 Aktoren als Linienteilnehmer angenommen. Diese Werte muessen vom Benutzer pro Raum angepasst werden koennen. |
| FA-107 | Pro Stockwerk muessen beliebig viele Wohnungen bzw. Zonen angelegt werden koennen (z.B. "Wohnung 1", "Wohnung 2" oder "Zone Nord", "Zone Sued"). Fuer ein EFH kann die Wohnungs-/Zonen-Ebene entfallen (ein Stockwerk = eine Zone). |

### 3.2 KNX-Topologievorschlag (FA-200)

#### 3.2.1 Topologie-Regeln gemaess KNX-Standard und KNX Swiss Richtlinien

| ID | Anforderung |
|----|-------------|
| FA-201 | Das System muss basierend auf der Gebaeudestruktur und der geschaetzten Geraeteanzahl einen Vorschlag fuer die KNX-TP-Topologie generieren. |
| FA-202 | Die Topologiezuordnung muss folgender Logik entsprechen: Bereichsadresse = Gebaeude-/Fluegelnummer, Linienadresse = Zone/Wohnung (EFH: alle Raeume in einer Linie; MFH/Zweckbau: eine Linie pro Wohnung/Zone, stockwerkuebergreifend zusammengefasst; gemaess Kap. 17 Topologie-Dokument und Kap. 7/8 Projektrichtlinien). |
| FA-203 | Das System muss die maximale Teilnehmeranzahl pro Linie beruecksichtigen: max. 256 Geraete fuer TP-256-Anlagen (empfohlen: 85 Geraete planen, max. 100 realisieren, gemaess KNX Swiss Kap. 8.3.2). |
| FA-204 | Fuer Bestandsanlagen (vor 2019) muss das System die alte Regel von max. 64 Teilnehmern pro Liniensegment unterstuetzen (TP-64-Modus). |
| FA-205 | Das System muss erkennen, wann eine Linie voll ist und automatisch eine neue Linie vorschlagen. |
| FA-206 | Das System muss die Spannungsversorgung beruecksichtigen: jede Linie, Hauptlinie und Bereichslinie benoetigt eine eigene KNX-Spannungsversorgung. |
| FA-207 | Das System muss die Koppler-Hierarchie korrekt abbilden: Bereichskoppler (B.0.0), Linienkoppler (B.L.0), Segmentkoppler (B.L.T > 0). |
| FA-208 | Das System muss die Erfassung der elektrischen Verteilungsraeume ermoeglichen: Raum der Hauptverteilung (HV) und Raeume der Unterverteilungen (UV). Die Aktoren befinden sich in den HV-/UV-Raeumen und muessen den jeweiligen Linien zugeordnet werden. |
| FA-209 | Das System muss anhand der Geraeteanzahl pro Raum (Standardwert: 4 Sensoren + 2 Aktoren, gemaess FA-106) die optimale Linienzuteilung automatisch berechnen. Dabei muss die Zuordnung der Raeume zu Linien unter Beruecksichtigung folgender Kriterien erfolgen: a) Max. Teilnehmeranzahl pro Linie (gemaess FA-203), b) Raeumliche Naehe der Raeume zueinander, c) Zuordnung zu Stockwerken/Zonen, d) Gleichmaessige Auslastung der Linien. |
| FA-210 | Das System muss die Zuordnung der Aktoren in den HV-/UV-Raeumen zu den Linien der zugehoerigen Sensoren automatisch vorschlagen. Der Benutzer muss diese Zuordnung manuell anpassen koennen. |

#### 3.2.2 Topologie-Varianten

| ID | Anforderung |
|----|-------------|
| FA-211 | Das System muss folgende Topologie-Varianten unterstuetzen: |
| | a) Klassische TP-Topologie mit Linien- und Bereichskopplern |
| | b) IP-Backbone-Topologie mit KNX-IP-Routern als Linien- oder Bereichskoppler |
| | c) Gemischte Topologie (TP + IP) |
| FA-212 | Das System muss den Topologievorschlag als Prinzipschema visualisieren (Bereiche, Linien, Koppler, Geraeteanzahl). |
| FA-213 | Der Benutzer muss den generierten Topologievorschlag manuell anpassen koennen: Bereiche hinzufuegen/entfernen (Name, Bereichsnummer 1-15, Backbone-Typ TP/IP), Linien hinzufuegen/entfernen (Name, Liniennummer 0-15, Geraeteanzahl), Koppleradressen automatisch aktualisieren. Aenderungen muessen sofort validiert werden. |

#### 3.2.3 Physikalische Adressen

| ID | Anforderung |
|----|-------------|
| FA-221 | Das System muss physikalische Adressen im Format B.L.T (Bereich.Linie.Teilnehmer) automatisch vorschlagen. |
| FA-222 | Die Adressierung muss der KNX Swiss Empfehlung folgen: Aktoren (1-100), Sensoren (101-199), Reservebereich (200-249), Schnittstellen (250-255). Fuer kleine Projekte: Aktoren (1-20), Sensoren (21-40), Reserve (41-62), Schnittstellen (250-255). |
| FA-223 | Der Linienkoppler muss immer die Adresse B.L.0 erhalten. |

#### 3.2.4 Topologie-Beispiele

| ID | Anforderung |
|----|-------------|
| FA-231 | Fuer ein EFH muss das System eine einfache Topologie vorschlagen koennen: 1 Bereich, 1 Hauptlinie, in der Regel hoechstens 2 Linien. Die Anzahl der Linien ist abhaengig davon, wie viele KNX-Geraete pro Stockwerk installiert werden (z.B. Bereich 1: Linie 1.1=UG/EG, 1.2=OG/DG). Bei wenigen Geraeten kann eine einzelne Linie fuer das gesamte EFH genuegen. |
| FA-232 | Fuer einen Zweckbau muss das System eine komplexere Topologie vorschlagen koennen: mehrere Bereiche (pro Gebaeude-/Fluegel), Linien pro Energiezone/Stockwerk (gemaess Kap. 8.1.3 Projektrichtlinien). |

### 3.3 Gewerke-Definition (FA-300)

| ID | Anforderung |
|----|-------------|
| FA-301 | Das System muss die Zuweisung von Gewerken pro Raum ermoeglichen. |
| FA-302 | Das System muss die vollstaendige Gewerke-Liste gemaess KNX Swiss Projektrichtlinien Kap. 10.1 unterstuetzen: |

**Gewerke-Katalog (KNX Swiss Standard):**

| Kuerzel | Funktion | Anz. GA pro Element | Schnittstellentyp |
|---------|----------|---------------------|-------------------|
| A | Alarm-Magnetkontakte (Sammelalarme/Alarmanlage) | 5 | Aktor |
| BL | Beamer-Lift | 5 | Aktor |
| BW | Bewaesserung | 5 | Aktor |
| DF | Dachfenster | 5 | Aktor |
| DMX | DMX | 5 | Aktor |
| E | Energiezaehler und Monitoring | 10 | Aktor |
| F | Fenster | 5 | Aktor |
| FG | Fliegengitter | 5 | Aktor |
| FK | Fensterkontakt | 5 | Aktor |
| G | Garagentor (Tore allgemein) | 5 | Aktor |
| GS | Gong/Sonnerie | 5 | Aktor |
| H | Heizung | 10 | Aktor |
| J | Jalousie | 5 oder 10 * | Aktor |
| L | Licht | 5 | Aktor |
| LD | Licht dimmbar | 5 | Aktor |
| LDA | Licht dimmbar DALI | 5 | Gateway (DALI-Gateway) |
| LW | Leinwand | 5 | Aktor |
| M | Markise (Stoffstoren) | 5 | Aktor |
| MM | Multimedia | 5 | Gateway (z.B. IP-KNX-Gateway) |
| P | Pumpe | 5 | Aktor |
| R | Rollladen | 5 oder 10 * | Aktor |
| RK | Riegelkontakte | 5 | Aktor |
| S | Steckdose | 5 | Aktor |
| SD | Steckdose dimmbar | 5 | Aktor |
| T | Tagesvorhang | 5 | Aktor |
| TE | Tuere | 5 | Aktor |
| TK | Tuerkontakte | 5 | Aktor |
| TF | Temperaturfuehler | 10 | Aktor |
| TVL | TV Lift | 5 | Aktor |
| U | Uhren | 5 | Aktor |
| V | Ventilatoren | 5 | Aktor |
| W | Wetterstation | 10 | Systemsensor (projektweite Einbindung) |
| WP | Waermepumpe | 10 | Gateway (z.B. Modbus-KNX-Gateway) |

\* Jalousien und Rolllaeden koennen je nach Umfang der Steuerung (mit/ohne Rueckmeldung, Beschattung, Sperren) 5er- oder 10er-Bloecke verwenden.

**Schnittstellentypen:**
- **Aktor**: Standard-KNX-Aktor (Schalt-, Dimm-, Jalousie-, Heizungsaktor etc.); wird in Wizard Schritt 8 als Aktor geplant.
- **Gateway**: Fremdsystem-Schnittstelle (DALI, Multimedia, Waermepumpe etc.); kommuniziert ueber ein Schnittstellengeraet (KNX-Gateway) mit dem KNX-Bus. Wird in Wizard Schritt 8 als Gateway-Geraet (device_type="gateway") geplant, nicht als klassischer Aktor.
- **Systemsensor**: Gewerkeuebergreifendes Messgeraet (z.B. Wetterstation); wird nicht raumweise, sondern einmalig pro Projekt geplant. Erscheint in Wizard Schritt 6 im Abschnitt "Systemgeraete".

| ID | Anforderung |
|----|-------------|
| FA-303 | Der Benutzer muss eigene Gewerke-Kuerzel definieren und zur Liste hinzufuegen koennen. |
| FA-304 | Pro Raum muss der Benutzer die Anzahl der Elemente je Gewerk eingeben koennen (z.B. Raum E01: 2x LD, 1x J, 1x H). |
| FA-305 | Das System muss die empfohlene Anzahl Gruppenadressen pro Gewerk-Element (5er- oder 10er-Bloecke) automatisch anwenden. |
| FA-306 | Das System muss Gewerke-Vorlagen anbieten (z.B. "Standardraum Wohnen": 2x LD, 2x J, 1x H, 1x TF; "Badezimmer": 2x L, 1x V, 1x H, 1x TF). |

### 3.4 Automatisierte Gruppenadress-Erstellung (FA-400)

#### 3.4.1 Bezeichnungskonzept (gemaess KNX Swiss Kap. 10)

| ID | Anforderung |
|----|-------------|
| FA-401 | Das System muss Gruppenadress-Bezeichnungen automatisch nach dem KNX Swiss Bezeichnungskonzept generieren: `[Gewerk]_[Raum]_[Nummer] [Funktion] ([Klartext])`. Beispiel: `LD_E05_01 E/A (Eingang Decke)`. |
| FA-402 | Das Bezeichnungslabel muss aus drei Teilen bestehen: Gewerke-/Funktionslabel (Kuerzel aus FA-302), Raumnummer (eindeutig pro Stockwerk), fortlaufende Nummer (beginnt pro Raum und Gewerk bei 01). |
| FA-403 | Der Benutzer muss optional eine ergaenzende Klartext-Beschreibung in Klammern anfuegen koennen (z.B. "Schlafzimmer Decke", "Eingang Wand links"). Umsetzung: In Schritt 5 (Spalte "Bezeichnung") wird je Element einer Gewerk-Zuweisung ein Klartext erfasst (bei Anzahl > 1 mit ";" getrennt, z.B. "Decke; Wand"). Er steht in jeder GA des Elements nach dem Raumnamen, z.B. `LDA_E01_01 E/A (Wohnen Decke)`, bleibt bei Neuberechnung und Neuordnen erhalten und ersetzt in den Auswahllisten (Bedienelemente, Bauherrenberatung) die Elementnummer. Der Tooltip der Zelle zeigt die Zuordnung Text zu Element (01, 02 ...); mehr Texte als Elemente: Zelle orange, die ueberzaehligen Texte bleiben gespeichert. Mindestbreite der Spalte fuer die Eingabe. Dieselbe Spalte steht in der Gewerke-Uebersicht (Doppelklick oder F2, Rueckgaengig-Punkt, Neuberechnung der GA-Namen). |

#### 3.4.2 Hauptgruppen-Zuordnung (gemaess KNX Swiss Kap. 13.1)

| ID | Anforderung |
|----|-------------|
| FA-411 | Das System muss die Hauptgruppen automatisch nach Stockwerken zuordnen: |

| Hauptgruppe | Zuordnung |
|-------------|-----------|
| 0 | Zentraladressen (stockwerkuebergreifende Funktionen) |
| 1 | Untergeschoss |
| 2 | Erdgeschoss |
| 3 | 1. Obergeschoss |
| 4 | 2. Obergeschoss / Dachgeschoss |
| ... | Weitere Stockwerke aufsteigend |
| 14 / 15 | Reserviert fuer Zentraladressen (Alternative) |

| ID | Anforderung |
|----|-------------|
| FA-411a | Hauptgruppen sind im ganzen Areal eindeutig: Ein neues Stockwerk (Schritt 1, Schnelleingabe, Vorlage, Gebaeude-Ansicht) erhaelt die HG gemaess Tabelle, wenn sie frei ist, sonst die kleinste freie. Eine von Hand mehrfach vergebene HG wird in Schritt 1 orange markiert und gemeldet; die Validierung warnt bei geplanten Projekten (Regel FA-411). |

| ID | Anforderung |
|----|-------------|
| FA-412 | Der Benutzer muss die Hauptgruppen-Zuordnung manuell anpassen koennen. |
| FA-413 | Sonderbereiche (z.B. Multimedia/Revox) muessen eigenen Hauptgruppen zugewiesen werden koennen (z.B. Hauptgruppe 12). |

#### 3.4.3 Mittelgruppen-Zuordnung (gemaess KNX Swiss Kap. 13.2)

| ID | Anforderung |
|----|-------------|
| FA-421 | Das System muss zwei Varianten fuer die Mittelgruppen-Struktur unterstuetzen: |

**Variante A -- Rueckmeldung in derselben Mittelgruppe (Standard):**

| Mittelgruppe | Funktion |
|--------------|----------|
| 0 | Licht inkl. Rueckmeldungen |
| 1 | Jalousie inkl. Rueckmeldungen |
| 2 | Heizung / HLK |
| 3 | Alarm |
| 4 | Allgemein |
| 5-7 | Frei verfuegbar |

**Variante B -- Separate Mittelgruppe fuer Rueckmeldungen:**

| Mittelgruppe | Funktion |
|--------------|----------|
| 0 | Licht (ohne Rueckmeldungen) |
| 1 | Jalousie (ohne Rueckmeldungen) |
| 2 | Heizung / HLK |
| 3 | Alarm |
| 4 | Allgemein |
| 5 | Frei verfuegbar |
| 6 | Rueckmeldungen Licht |
| 7 | Rueckmeldungen Jalousie |

| ID | Anforderung |
|----|-------------|
| FA-422 | Der Benutzer muss zu Projektbeginn die gewuenschte Variante (A oder B) waehlen koennen. |
| FA-423 | Bei Variante B muessen die Untergruppenadressen der Rueckmeldungen in MG 6/7 denselben Untergruppenadressen wie die Schaltgruppen in MG 0/1 entsprechen. |

#### 3.4.4 Untergruppen-Erstellung (gemaess KNX Swiss Kap. 13.3-13.6)

| ID | Anforderung |
|----|-------------|
| FA-431 | Das System muss die Untergruppen-Adressen automatisch in Bloecken generieren: 5er-Bloecke fuer Licht, 10er-Bloecke fuer Jalousie und Heizung. |

**Adressblock-Schema Licht (5er-Block, Variante A):**

| Offset | Funktion | Bezeichnung | DPT |
|--------|----------|-------------|-----|
| +0 | Ein/Aus | E/A | DPST-1-1 |
| +1 | Dimmen | DIM | DPST-3-7 |
| +2 | Wert senden | WERT | DPST-5-1 |
| +3 | Rueckmeldung E/A | RM | DPST-1-1 |
| +4 | Rueckmeldung Wert | RM WERT | DPST-5-1 |

**Adressblock-Schema Jalousie (10er-Block, Variante A):**

| Offset | Funktion | Bezeichnung | DPT |
|--------|----------|-------------|-----|
| +0 | Auf/Ab | AUF/AB | DPST-1-8 |
| +1 | Stopp/Lamellen | STOPP | DPST-1-7 |
| +2 | Position Hoehe | POSITION HOEHE | DPST-5-1 |
| +3 | Position Lamellen | POSITION LAMELLEN | DPST-5-1 |
| +4 | Beschattung | BESCHATTUNG | DPST-1-8 |
| +5 | Sperren | SPERREN | DPST-1-1 |
| +6 | Status Position Hoehe | STATUS POSITION HOEHE | DPST-5-1 |
| +7 | Status Position Lamellen | STATUS POSITION LAMELLEN | DPST-5-1 |
| +8 | Reserve | -- | -- |
| +9 | Reserve | -- | -- |

**Adressblock-Schema Heizung (10er-Block):**

| Offset | Funktion | Bezeichnung | DPT |
|--------|----------|-------------|-----|
| +0 | Stellgroesse | STELLGROESSE | DPST-1-1 oder DPST-5-1 |
| +1 | Ist-Temperatur | IST | DPST-9-1 |
| +2 | Basis-Sollwert | BASIS-SOLL | DPST-9-1 |
| +3 | RM aktueller Sollwert | RM AKTUELLER SOLLWERT | DPST-9-1 |
| +4 | Umschalten Betriebsart | UMSCHALTEN BETRIEBSART | DPST-20-102 |
| +5 | Status Betriebsart | STATUS BETRIEBSART | DPST-20-102 |
| +6 | Reserve | -- | -- |
| +7 | Reserve | -- | -- |
| +8 | Stoerung | STOERUNG | DPST-1-1 |
| +9 | Sperren | SPERREN | DPST-1-1 |

| ID | Anforderung |
|----|-------------|
| FA-432 | Bei Variante B muessen die Licht-Bloecke 5 Adressen belegen (E/A, DIM, WERT + 2 Reserve), und die Rueckmeldungen (RM, RM WERT) in Mittelgruppe 6 mit identischer Untergruppen-Adresse erzeugt werden. |
| FA-433 | Bei Variante B muessen die Jalousie-Bloecke 10 Adressen belegen (AUF/AB, STOPP, POSITION HOEHE, POSITION LAMELLEN, BESCHATTUNG, SPERREN + 4 Reserve), und die Rueckmeldungen (STATUS POSITION HOEHE, STATUS POSITION LAMELLEN) in Mittelgruppe 7 mit identischer Untergruppen-Adresse erzeugt werden. |
| FA-434 | Nicht verwendete Positionen innerhalb eines Blocks muessen als leere Platzhalter-Adressen reserviert werden, um die Blockstruktur beizubehalten. |
| FA-435 | Die Datenpunkttypen (DPT) muessen automatisch basierend auf der Funktion zugewiesen werden (siehe Adressblock-Schemata oben). |
| FA-436 | Das System muss fuer Gewerke, die nicht in den Standard-Schemata enthalten sind (z.B. BW, DMX, TVL), generische 5er-Bloecke mit konfigurierbaren Funktionen erzeugen. |

#### 3.4.5 Zentraladressen (Hauptgruppe 0)

| ID | Anforderung |
|----|-------------|
| FA-441 | Das System muss in Hauptgruppe 0 automatisch zentrale/stockwerkuebergreifende Gruppenadressen anlegen koennen (z.B. "Alle Lichter AUS", "Zentral Jalousien Beschattung", Szenensteuerung). |
| FA-442 | Zentraladressen muessen eigene Mittelgruppen-Zuordnung nutzen (0/0=Licht, 0/1=Jalousie, 0/2=Heizung, 0/4=Szenen, 0/5=Wetterstation). |
| FA-443 | Das System muss vordefinierte Zentral-Funktionen anbieten (z.B. "Alles AUS", "Panik", "Abwesenheit", "Beschattung zentral"). |
| FA-444 | Das System darf die Gruppenadresse 0/0/0 nicht verwenden. 0/0/0 ist eine KNX-Systemadresse (GA-08). Zentraladressen in HG 0 muessen bei Untergruppe 1 beginnen (z.B. 0/0/1 = "Alle Lichter AUS"). **(M)** |

### 3.5 ETS6-Datenimport bestehender Projekte (FA-500)

#### 3.5.1 Unterstuetzte ETS6-Exportformate

| ID | Anforderung |
|----|-------------|
| FA-500 | Das System muss folgende ETS6-Exportformate einlesen koennen: a) Gruppenadress-Export (CSV), b) Gruppenadress-Report (XLSX, FA-519b), c) Topologie-Report mit Zusatzwahl "Objekte" (XLSX) und d) Natives ETS-Projektformat (.knxproj). Fuer Gruppenadressen ist der XLSX-Report (b) das empfohlene Format, da er reichhaltigere Metadaten liefert als der CSV-Export (a); dieser bleibt aus Kompatibilitaetsgruenden weiterhin unterstuetzt. |

#### 3.5.2 CSV-Import (Gruppenadressen)

| ID | Anforderung |
|----|-------------|
| FA-501 | Das System muss ETS6-Gruppenadress-Exporte im CSV-Format (Semikolon-getrennt, UTF-8/ANSI) einlesen koennen. |
| FA-502 | Folgende CSV-Spalten muessen unterstuetzt werden: Main, Middle, Sub, Address, Central, Unfiltered, Description, DatapointType, Security. |
| FA-503 | Das System muss die hierarchische Struktur (Hauptgruppe > Mittelgruppe > Untergruppe) korrekt erkennen und abbilden. |
| FA-504 | Leere Felder in Main/Middle-Spalten muessen als Zugehoerigkeit zur letzten nicht-leeren uebergeordneten Gruppe interpretiert werden. |
| FA-505 | Das System muss eine Fehlermeldung ausgeben, wenn das CSV-Format nicht dem ETS6-Exportformat entspricht. |
| FA-506 | Das System muss aus einer importierten CSV-Datei die Gebaeudestruktur, Gewerke und Topologie rueckwaerts ableiten koennen (Reverse Engineering). |

#### 3.5.3 XLSX-Import (Topologie-Report mit Objekte)

| ID | Anforderung |
|----|-------------|
| FA-511 | Das System muss den ETS6-Topologie-Report (XLSX-Format, Report "Topologie" mit Zusatzwahl "Objekte") einlesen koennen. |
| FA-512 | Das System muss folgende Projektmetadaten aus dem Report extrahieren: Projektname, Startdatum, Importdatum, Druckdatum. |
| FA-513 | Das System muss die physikalische Topologie-Hierarchie aus dem Report erkennen: Backbone (IP/TP), Bereiche (Bereich-Nr., Medium, Name), Linien (Linien-Nr., Medium, Name). |
| FA-514 | Das System muss pro Linie alle Busteilnehmer (Geraete) mit folgenden Informationen extrahieren: |

**Geraete-Informationen aus dem Topologie-Report:**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Physikalische Adresse | Format B.L.T | 1.1.1 |
| Hersteller | Geraetehersteller | ABB AG - STOTZ-KONTAKT |
| Bestellnummer | Artikelnummer | GH Q631 0047 R0111 |
| Produkt | Produktbezeichnung | AT/S8.16.5 Schaltaktor, 8fach, 16A, REG |
| Applikationsprogramm | Geladene Applikation | Schalten Logik Status Zeit/5 |
| Einbauort | Verteilung/Unterverteilung | UV2 (Steigzone) |
| Seriennummer | Geraete-Seriennummer (falls vorhanden) | 0002:0E390051 |

| ID | Anforderung |
|----|-------------|
| FA-515 | Das System muss pro Geraet die Kommunikationsobjekte mit folgenden Informationen extrahieren: Objektnummer, Objektname, Objektfunktion, Prioritaet, Flags (K/L/S/Ue/A), Datentyp, verbundene Gruppenadressen (inkl. aller Mehrfachzuordnungen). |
| FA-516 | Das System muss Spannungsversorgungen (Adressformat B.L.-) als separate Geraetekategorie erkennen und zuordnen. |
| FA-517 | Das System muss Koppler (Adresse B.L.0) als Linienkoppler erkennen und in der Topologieansicht darstellen. |
| FA-518 | Das System muss die Geraeteanzahl pro Linie automatisch zaehlen und mit den Topologie-Empfehlungen abgleichen (Warnung bei > 85, Fehler bei > 100). |
| FA-519 | Das System muss aus den verbundenen Gruppenadressen der Kommunikationsobjekte (Spalte "Verbunden mit") die Verknuepfung zwischen physikalischer Topologie und logischer Gruppenadress-Struktur herstellen. |
| FA-519b | Das System muss zusaetzlich den ETS6-Gruppenadress-Report (XLSX-Format, eigenstaendiger Report -- nicht der CSV-Export) einlesen koennen. Daraus werden Hauptgruppen, Mittelgruppen, Gruppenadressen (inkl. Bezeichnung und Datenpunkttyp) sowie Projektmetadaten (Projektname, Start-/Import-/Druckdatum) extrahiert. Wird der GA-Report nach einem bereits importierten Topologie-Report eingelesen, muss das System damit die Kommunikationsobjekt-Verbindungen der Topologie anreichern und Gewerk-Zuweisungen aus den GA-Bezeichnungen ableiten, ohne den Topologie-Import zu wiederholen. |
| FA-520 | Das System muss den Topologie-Report und den Gruppenadress-Export (CSV oder XLSX-Report) desselben Projekts zusammenfuehren und eine vollstaendige Projektansicht erstellen koennen. |

#### 3.5.4 KNXPROJ-Import (Natives ETS-Projektformat)

| ID | Anforderung |
|----|-------------|
| FA-521 | Das System kann ETS6-Projektdateien im `.knxproj`-Format (ZIP-Archiv mit XML-Struktur gemaess KNX-Standard, Formatversionen ETS 5 und ETS 6) einlesen koennen. **(C)** |
| FA-522 | Das System muss folgende Daten aus dem `.knxproj` extrahieren koennen: Projektmetadaten (Name, Beschreibung), Gebaeudestruktur, vollstaendige Gruppenadress-Hierarchie (inkl. DPT, Flags), Topologie (Bereiche, Linien, Geraete mit physikalischer Adresse, Hersteller, Produkt, Applikation) sowie Kommunikationsobjekte mit ihren GA-Zuordnungen. **(C)** |
| FA-523 | Das System muss die Gebaeudestruktur aus dem `.knxproj` vollstaendig extrahieren: Gebaeude, Gebaeudeteile, Stockwerke und Raeume (inkl. Bezeichnungen und Hierarchie). Die extrahierte Gebaeudestruktur dient als Grundlage fuer die Gruppenadress-Generierung und Reorganisation. **(C)** |
| FA-524 | Der KNXPROJ-Import vereint die Daten von CSV- und XLSX-Import in einem einzigen Schritt -- eine separate Zusammenfuehrung (FA-520) ist nicht erforderlich. Das System muss neben dem klassischen Format (Projektordner `P-XXXX/` direkt im aeusseren ZIP) auch das neuere ETS6-Containerformat unterstuetzen, bei dem die Projektdaten in einem verschachtelten Archiv `P-XXXX.zip` innerhalb des aeusseren ZIP liegen. **(C)** |
| FA-525 | Das System muss erkennen, ob ein `.knxproj` passwortgeschuetzt ist, und danach unterscheiden: |

**FA-525 Detailanforderungen (Passwortschutz):**

| Nr. | Anforderung |
|-----|-------------|
| FA-525a | Klassisches Format: Ist ein Eintrag im aeusseren ZIP verschluesselt (WinZip-AES-Flag), muss das System eine verstaendliche Fehlermeldung mit Hinweis auf die ETS6-Exportalternative (Gruppenadress-Report bzw. Topologie-Report als XLSX) ausgeben. **(C)** |
| FA-525b | Neueres Containerformat: Ist das innere `P-XXXX.zip` AES-verschluesselt (ETS6-Export mit Passwort), muss das System das ZIP-Passwort aus dem Projektpasswort ableiten (PBKDF2-HMAC-SHA256 ueber das Passwort in UTF-16-LE, Salt "21.project.ets.knx.org", 65536 Iterationen, Base64) und ersatzweise das Passwort unveraendert versuchen. Ein Cloud-Lizenz-Zertifikat (`P-XXXX.certificate`) verhindert die Entschluesselung nicht (mit ETS6-Export geprueft, 25.09.2026). **(C)** |
| FA-525c | Fuer verschluesselte Projekte muss das System den Benutzer ueber einen Passwort-Dialog zur Eingabe des ETS6-Projektpassworts auffordern und den Import mit dem eingegebenen Passwort fortsetzen. Bei falschem Passwort muss eine verstaendliche Fehlermeldung erscheinen und eine erneute Eingabe moeglich sein. **(C)** |
| FA-526 | Das System muss eine Fehlermeldung ausgeben, wenn die `.knxproj`-Datei beschaedigt, unvollstaendig oder nicht dem KNX-Standard entspricht. **(C)** |
| FA-527 | Das System muss ein Projekt frisch aus einer `.knxproj`-Datei neu aufbauen koennen ("Projekt neu aus ETS aufbauen"), ohne den Re-Import-Abgleich: Gebaeudestruktur, Topologie, Gruppenadressen, Szenen, DALI und Materialliste entstehen neu aus der ETS. Der Anwender waehlt, was behalten wird (Standard: Projekteigenschaften, Kundenprofil, KNX-Secure-Archiv, Offerten/Lieferanten, eigene Gewerke, Aenderungsprotokoll; optional Verteiler-Raumzuordnung, Zeitprogramme, Inbetriebnahme). Beim behaltenen Secure-Archiv erhalten die Geraete ihre bisherige ID ueber die physikalische Adresse, damit die Zertifikate zugeordnet bleiben. Vorher wird gespeichert und gesichert (NFA-042); bricht der Import ab, bleibt der bisherige Stand. |
| FA-528 | Alle Import-Wege (`.knxproj`, Topologie-, Gruppenadress- und Gebaeude-Report) muessen nach dem Einlesen ihrer Primaerdaten denselben Ablauf in fester Reihenfolge durchlaufen: Topologie mit Gebaeude und Gruppenadressen verbinden (nur Excel-Wege, mit allen frueher importierten Reports des Projekts), Bedienelemente und Tastenbelegung aus den Kommunikationsobjekten ableiten, Gewerke und GA-Metadaten ableiten, Re-Import-Abgleich (FA-521), danach Gewerk-Verknuepfung der Gruppenadressen, Szenen-Erkennung, DALI-Konfiguration und Aenderungsprotokoll. Die Pfade der importierten Reports gehoeren zum Projekt, nicht zur Sitzung. Beim Abgleich gewinnt fuer ETS-Geraete die Tastenbelegung aus den Kommunikationsobjekten; KNiX-Daten des Bedienelements (Datenblaetter, Bauherr-Anmerkung, Loeschmarkierung) bleiben erhalten. Scheitert ein Schritt, laeuft der Import weiter und zeigt am Ende die fehlgeschlagenen Schritte an. |
| FA-528a | Tastenparameter, Szenenwerte und Szenenausloeser liefern nur die ETS-Reports (Excel), nicht die `.knxproj`. Ein Re-Import oder Neuaufbau aus der `.knxproj` muss sie vom bisherigen Stand uebernehmen (frische Werte aus einem Report haben Vorrang) und danach knapp darauf hinweisen, dass sie aus dem frueher eingelesenen Report (mit Datum, falls bekannt) stammen und bei in der ETS geaenderten Parametern der Topologie- oder Gebaeude-Report neu einzulesen ist. |

#### 3.5.5 Uebernahme importierter Projekte in die Planung

Nach einem Import (KNXPROJ oder XLSX-Reports) soll das Projekt im Wizard weitergeplant werden koennen, ohne dass bereits bestehende Gruppenadressen doppelt erzeugt oder ueberschrieben werden.

| ID | Anforderung |
|----|-------------|
| FA-521b | Beim XLSX-Import muss das System Verteiler (HV, UV, NV, TV) aus den Einbauort-Texten der Topologie-Geraete ableiten (z.B. "HV", "UV2 (Steigzone)") und dafuer Raeume mit Verteiler-Objekt anlegen -- analog zur strukturellen Verteiler-Erkennung beim KNXPROJ-Import. Der Anwender muss einen erkannten Verteiler einem echten Raum zuordnen koennen; die Zuordnung bleibt bei einem erneuten Import erhalten. **(S)** |
| FA-521c | Das System muss die Funktionszuordnungen der Bedienelemente direkt aus den Verknuepfungen der Kommunikationsobjekte mit Gruppenadressen importierter Geraete uebernehmen. **(S)** |
| FA-521d | Das System muss Kommunikationsobjekte erkennen, deren verbundene Gruppenadressen zu unterschiedlichen Gewerken gehoeren (z.B. ein Aktorkanal mit GAs fuer zwei Gewerke). Solche Kanaele werden nicht automatisch einem Gewerk zugeordnet; das System muss den Anwender nach dem Import darauf hinweisen, damit er die Zuordnung in Schritt 5 (Gewerke) prueft. **(S)** |
| FA-521e | Nach einem (erneuten) Import muss das System importierte Gruppenadressen mit der passenden Gewerk-Zuweisung verknuepfen, damit eine spaetere Neugenerierung der Gruppenadressen sie wiedererkennt und keine doppelten Adressbloecke erzeugt. **(S)** |
| FA-521f | Der Anwender muss eine Gewerk-Zuweisung manuell mit einem bestehenden Aktorkanal eines importierten Geraets verknuepfen koennen (Geraet waehlen, Kanal waehlen, Vorschau der automatisch erkannten Funktionszuordnung mit Korrekturmoeglichkeit). Verknuepfte Gruppenadressen werden als manuell markiert und bei einer Neugenerierung weder verschoben noch umbenannt; nur noch nicht belegte Funktionen erhalten neue Adressen. Bei importierten Projekten erzeugt der Gewerke-Schritt beim Verlassen keine Gruppenadressen automatisch, damit vorher verknuepft werden kann. **(S)** |
| FA-521g | Das System muss die importierte Topologie nach noch nicht zugewiesenen Aktorkanaelen durchsuchen und daraus Raum-/Gewerk-Vorschlaege ableiten. Vorgeschlagen wird nur bei eindeutigem Treffer (genau ein Gewerk mit mindestens einer Kernfunktion); unterstuetzt werden Gewerke, deren Funktionen sich aus den Objektnamen sicher erkennen lassen (Licht, Beschattung, DALI). Die Vorschlaege muessen in einem Pruefdialog einzeln an- und abgewaehlt und im Gewerk-Code korrigiert werden koennen; erst nach Bestaetigung werden Gewerk-Zuweisungen angelegt und Gruppenadressen verknuepft. **(S)** |

### 3.6 Analyse und Validierung (FA-600)

| ID | Anforderung |
|----|-------------|
| FA-601 | Das System muss pruefen, ob jede Gruppenadresse eine gueltige Adresse im Format H/M/S besitzt (H: 0-31, M: 0-7, S: 0-255). |
| FA-602 | Das System muss doppelte Gruppenadressen erkennen und als Fehler melden. |
| FA-603 | Das System muss pruefen, ob der zugewiesene Datenpunkttyp (DPT) zur Funktion passt (z.B. E/A erwartet DPST-1-x, WERT erwartet DPST-5-1). |
| FA-604 | Das System muss fehlende Datenpunkttypen erkennen und Vorschlaege basierend auf der Funktion machen. Ohne Funktion wird der DPT aus typischen Bestandteilen der Bezeichnung abgeleitet (_ea, _status, Temp, Helligkeit, Szene, Ventil ...); ist nichts eindeutig erkennbar, bleibt der Vorschlag leer. |
| FA-605 | Das System muss Luecken in der Adressierung erkennen (z.B. unvollstaendige 5er-/10er-Bloecke). Luecken werden als Hinweis gemeldet, da sie in importierten Projekten meist gewollte Reserven sind. |
| FA-606 | Das System muss die Konsistenz der Namensgebung pruefen: Geraete gleichen Typs muessen gleiche Bezeichnungsmuster verwenden. |
| FA-607 | Das System muss pruefen, ob die Mittelgruppen-Zuordnung korrekt ist (z.B. Licht-Gewerke in Mittelgruppe 0, Jalousie in Mittelgruppe 1). |
| FA-608 | Das System muss bei Variante B pruefen, ob zu jedem Schalt-Element die zugehoerigen Rueckmeldungen in MG 6 (Licht) bzw. MG 7 (Jalousie) vorhanden sind und identische Untergruppenadressen haben. |
| FA-608a | Variante B, Generator: Enthaelt ein Block in MG 0/1 Rueckmeldungen (z.B. LDA, Farblicht), werden sie dort zu Reserven und in einem gleich grossen Block in MG 6/7 unter der Untergruppe ihres Befehls angelegt (RM - E/A, RM WERT - WERT bzw. HELLIGKEIT, RM HELL - HELLIGKEIT, RM CCT - FARBTEMPERATUR, RM FARBE - FARBE, STATUS X - X). Rueckmeldebloecke werden deckungsgleich zum Befehlsblock platziert; bestehende Rueckmeldungen behalten ihre Adresse nur, wenn sie bereits deckungsgleich liegen. Die Validierung meldet Rueckmeldungen in MG 0/1 und Rueckmeldungen in MG 6/7 ohne Befehl desselben Elements unter gleicher Untergruppe. |
| FA-609 | Das System muss die Einhaltung der empfohlenen Geraeteanzahl pro Linie pruefen (Warnung bei > 85, Fehler bei > 100 bzw. > 256 Geraeten). Umsetzung in der Validierungsansicht (Busteilnehmer ohne Spannungsversorgungen, Grenze 100 bzw. 64 im Modus TP-64). |
| FA-610 | Das System muss die Bezeichnungen auf Konformitaet mit dem KNX Swiss Bezeichnungskonzept pruefen (Format: Gewerk_Raum_Nummer, Raumnummer im Pruefrahmen BZ-03a). Bei mit KNiX geplanten Projekten muss der Raumteil zudem eine Raumnummer der Gebaeudestruktur sein (Befund "Raum fehlt", z.B. nach Umbenennen eines Raums ohne neue Adressen). |
| FA-611 | Bei importiertem Topologie-Report: Das System muss pruefen, ob alle in Kommunikationsobjekten referenzierten Gruppenadressen in der Gruppenadress-Struktur vorhanden sind (und umgekehrt). Umsetzung: fehlende GA an einem KO = Warnung; GA ohne KO-Verknuepfung = Hinweis, nur bei importierten Projekten. |
| FA-612 | Bei importiertem Topologie-Report: Das System muss pruefen, ob die physikalischen Adressen lueckenlos und korrekt den Linien zugeordnet sind. Umsetzung (Validierung, auch bei geplanten Projekten): Format B.L.T, Adresse passend zu Bereich und Linie, keine doppelten Adressen, Teilnehmer 0 nur fuer Koppler (FA-223). Luecken in der Teilnehmernummerierung werden nicht gemeldet, da sie gemaess FA-222 als Reserve ueblich sind. |
| FA-613 | Bei importiertem Topologie-Report: Das System muss pruefen, ob jede Linie eine Spannungsversorgung besitzt. Umsetzung: geplante Projekte Warnung, importierte Projekte Hinweis (Spannungsversorgungen ohne Busanschluss fehlen in vielen ETS-Projekten); IP-Hauptlinien ausgenommen. Bei geplanten Projekten prueft sie zusaetzlich die Spannungsversorgung der Hauptlinie je Bereich und der Bereichslinie 0.0 (T-06). |
| FA-614 | Das System muss pruefen, dass pro Sensorkanal (sendendes Tasten-KO) nur eine sendende Gruppenadresse verknuepft ist. Jede weitere GA am KO wird eingeordnet: bei Variante B sind Mittelgruppen 6 und 7 immer Rueckmeldungen (in Ordnung); sonst entscheidet das KO, das die GA sendet -- Status-KO (Name Status/Rueckmeldung oder ohne Schreiben-Flag) = Rueckmeldung, Befehls-KO einer anderen Bedienstelle oder kein Sender = "Mithoeren - pruefen": Fehler, wenn nachweislich ein Befehls-KO eines anderen Geraets die GA sendet (Planungsregel, die ETS erlaubt es technisch), sonst Warnung (nicht eindeutig). Rueckmeldungen ausserhalb MG 6/7 bei Variante B sind ein Hinweis. Kategorie "Verknuepfung". Warnungen erscheinen in Validierung, Validierungsbericht, Bericht Bedienelemente (eigener Abschnitt), Schritt 12, Topologie, Verknuepfungsmatrix und Bauherrenberatung. |
| FA-614a | Eine weitere GA muss in der Bauherrenberatung (Chip an der Taste, mit GA-Nummer und Rolle) und in der Topologie (Kontextmenue an der KO-Verknuepfung) nach Rueckfrage von der Taste getrennt werden koennen. Getrennt wird wie in der ETS: die GA wird aus der KO-Verknuepfung des Geraets und aus der Tastenbelegung entfernt, andere Geraete an derselben GA bleiben unveraendert; mit Rueckgaengig-Punkt. |
| FA-615 | Die Validierungsansicht muss die Meldungen als Baum Stufe (Fehler/Warnungen/Hinweise) > Regel (Titel, Anzahl) > Meldung zeigen, mit Ein-/Ausblenden je Stufe und einem Suchfeld (Adresse, Geraet, Bezeichnung, Regel). Regeln mit mehr als 20 Meldungen sind zugeklappt. |
| FA-616 | Bei aus der ETS importierten Projekten bleibt die ETS massgebend. Korrekturen (zunaechst das Gewerk einer GA, z.B. T -> G, wenn das ETS-Kuerzel nicht den Projektrichtlinien entspricht) werden getrennt von den ETS-Daten je GA-Adresse gespeichert, nach Oeffnen, Import und Neuaufbau wieder angewendet und von allen Berichten, Gewerke-Zahlen und Dokumenten verwendet. Jede Korrektur erscheint in der Validierung als Hinweis "Abweichung zur ETS". Zuordnung in den GA-Ansichten per Rechtsklick "Gewerk zuordnen" (Mehrfachauswahl). Ebenfalls in der Korrekturschicht: Bezeichnung jeder Taste fuer den Bauherrn (z.B. "Hell" statt "Szene High"), in der Bauherrenberatung im Feld "In der Anleitung" bearbeitbar (leer = automatische Bezeichnung), je Geraet und Taste gespeichert und in der Bedienungsanleitung verwendet. |
| FA-616a | Raum eines Geraets korrigieren: in der Topologie per Rechtsklick "Raum zuordnen..."; das Bedienelement zieht mit. Bei importierten Projekten als Korrektur je physikalischer Adresse gespeichert (Raumschluessel Stockwerk + Raumnummer, unnummeriert Stockwerk + Name, damit sie auch einen Neuaufbau uebersteht), zusammen mit dem Raum laut ETS; zurueck in den ETS-Raum hebt die Korrektur auf. In der Validierung als "Abweichung zur ETS" (Angabe Raum). Bei geplanten Projekten ergeben sich Taster, Sensoren und Aktoren aus den Gewerken ihres Raums; fuer sie zeigt "Raum zuordnen..." einen Hinweis (Gewerke in Schritt 5 oder per Ziehen in der Gebaeudestruktur verschieben), manuell hinzugefuegte Geraete bleiben zuordenbar. |
| FA-616b | Getrennte KO-Verknuepfungen (FA-614a) werden bei importierten Projekten als Korrektur gespeichert (Geraet, KO, GA) und nach Oeffnen, Import und Neuaufbau erneut getrennt. Liefert ein Re-Import (knxproj, Topologie- oder GA-Report) die Verknuepfung noch, erscheint nach dem Import ein Hinweis mit den betroffenen Geraeten, KOs und GAs ("in der ETS noch verbunden - bitte auch dort trennen"). Liefert die ETS sie nicht mehr, entfaellt die Korrektur. In der Validierung als "Abweichung zur ETS" (Angabe Verknuepfung). |
| FA-617 | Die Projektart (aus der ETS importiert / mit KNiX geplant) wird in den Projekteigenschaften angezeigt. Abweichungen von den Projektrichtlinien (FA-607, FA-608, FA-610) meldet die Validierung bei importierten Projekten als Hinweis, bei mit KNiX geplanten als Fehler. |
| FA-617a | Projektstatus "in ETS uebertragen" fuer mit KNiX geplante Projekte: in den Projekteigenschaften setzen und zuruecksetzen (mit Rueckfrage), nach dem CSV-Export fuer die ETS angeboten, mit Datum und Eintrag im Aenderungsprotokoll. Ab der Uebertragung stehen die Adressen fest wie bei importierten Projekten: "Adressen neu ordnen" (FA-701 bis FA-706) ist gesperrt, mit Hinweis zum Zuruecksetzen. |
| FA-618 | ETS-Arbeitsliste fuer importierte Projekte (PDF und Excel; Berichte -> Dokumentation und Knopf in der Validierung): alle Fehler und Warnungen der Validierung sowie die Abweichungen zur ETS als Aufgaben, gegliedert in 1 "Muss behoben werden" (wirkt auf den Bus, z.B. zweite sendende GA, in KNiX getrennte GA), 2 "Pruefen" (Warnungen), 3 "Unterlagen nachfuehren" (Gewerk, Raum; kein Programmieren). Je Aufgabe Ort in der ETS (Geraet/KO bzw. GA) und die Aufgabe knapp in ETS-Begriffen (z.B. "12/1/64 trennen", "Umbenennen in ..."), ohne Bedienanleitung der ETS (Grundkurs vorausgesetzt). Hinweise (z.B. Namensschema) gehoeren nicht dazu. Der Stand wird im Projekt gemerkt (beim ersten Erstellen als Ausgangsstand); nach jedem Import gilt, was die Validierung nicht mehr meldet, als erledigt (mit Datum), Neues ist markiert. Nach dem Re-Import zeigt KNiX die Zahl erledigter, neuer und offener Aufgaben. Excel: Blatt Arbeitsliste mit Auswahlliste offen/erledigt/spaeter und Bemerkung, Blatt Erledigt. |
| FA-619 | Die Validierung meldet bei mit KNiX geplanten Projekten als Hinweis jedes schaltbare Element (Licht, Steckdose, Beschattung, Vorhang), das von keiner Taste, keinem Praesenzmelder, keiner Szene und keinem aktiven Zeitprogramm angesprochen wird, mit der Befehls-GA des Elements. Funktionen, die einer Taste in einem anderen Raum zugewiesen sind, gelten als bedient; entfernte Bedienelemente zaehlen nicht; zentrale Funktionen (HG 0) zaehlen nicht. Massnahme: in der Bauherrenberatung einer Taste zuweisen oder belassen, wenn das Element anders bedient wird (z.B. Visualisierung, Logik). |

### 3.7 Reorganisation bestehender Projekte (FA-700)

| ID | Anforderung |
|----|-------------|
| FA-701 | Das System muss Gruppenadressen nach definierten Regeln automatisch neu anordnen koennen (Sortierung nach Stockwerk > Mittelgruppe > Raum > Geraet > Funktion). |
| FA-702 | Das System muss zusammengehoerige Geraetegruppen (z.B. alle Adressen eines Dimmers: E/A, DIM, WERT, RM, RM WERT) als Block erkennen und zusammenhalten. |
| FA-703 | Das System muss bei der Reorganisation die Zentraladressen (Hauptgruppe 0) separat behandeln. |
| FA-704 | Das System muss eine Vorschau der geplanten Aenderungen anzeigen (Vorher-/Nachher-Vergleich). Umsetzung: Bearbeiten -> "Adressen neu ordnen..." nur bei mit KNiX geplanten Projekten (bei importierten ist die ETS massgebend, Entscheid 06.10.2026). Die Stockwerk-Hauptgruppen werden wie bei einer Erstgenerierung lueckenlos aufgebaut (Bloecke mit Reserven, Variante-B-Rueckmeldungen deckungsgleich), HG 0 und manuelle GAs bleiben. Jede GA behaelt id, Central/Unfiltered/Security, Beschreibung und Kommentar; Verweise (Taster mit direkter GA, Szenen, DALI, Kommunikationsobjekte) werden nachgefuehrt. Vorschau mit alter/neuer Adresse und Bezeichnung, vorher Sicherung (NFA-042), Rueckgaengig moeglich. |
| FA-705 | Das System muss die Central-, Unfiltered- und Security-Felder bei der Reorganisation beibehalten. |
| FA-706 | Das System muss bestehende Bezeichnungen auf Wunsch an das KNX Swiss Bezeichnungskonzept anpassen koennen. |

### 3.8 CSV-Export (FA-800)

| ID | Anforderung |
|----|-------------|
| FA-801 | Das System muss die Gruppenadress-Struktur (generiert oder reorganisiert) als ETS6-kompatible CSV-Datei exportieren koennen. |
| FA-802 | Das Exportformat muss dem ETS6-Importformat entsprechen (Semikolon-getrennt, Spalten: Main, Middle, Sub, Address, Central, Unfiltered, Description, DatapointType, Security). |
| FA-803 | Das System muss die hierarchische Darstellung im Export beibehalten (leere Main/Middle-Felder fuer untergeordnete Eintraege). |
| FA-804 | Der Benutzer muss den Speicherpfad und Dateinamen fuer den Export waehlen koennen. |
| FA-805 | Das System muss vor dem Ueberschreiben einer bestehenden Datei eine Warnung anzeigen. |

### 3.9 Personalisierung und Firmenprofil (FA-850)

#### 3.9.1 Anwender- und Firmendaten

| ID | Anforderung |
|----|-------------|
| FA-851 | Das System muss ein Firmenprofil mit folgenden Angaben erfassen und persistent speichern koennen: |

**Pflichtfelder des Firmenprofils:**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Firmenname | Name der Firma/des Betriebs | Elektro Muster AG |
| Firmenlogo | Bilddatei (PNG, JPG, SVG) | logo_muster.png |
| Anwendername | Vor- und Nachname des Bearbeiters | Max Mustermann |
| Funktion/Rolle | Berufliche Funktion | KNX-Systemintegrator |

**Optionale Felder des Firmenprofils:**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Firmenadresse | Strasse, PLZ, Ort | Musterstrasse 1, 8000 Zuerich |
| Telefon | Geschaeftstelefon | +41 44 123 45 67 |
| E-Mail | Geschaeftliche E-Mail-Adresse | info@muster-elektro.ch |
| Webseite | Firmen-URL | www.muster-elektro.ch |
| Kundennummer/Referenz | Interne Referenznummer | KNX-2024-0815 |

| ID | Anforderung |
|----|-------------|
| FA-852 | Das Firmenprofil muss einmalig erfasst und fuer alle Projekte wiederverwendet werden koennen (globale Einstellung). |
| FA-853 | Pro Projekt muessen zusaetzlich projektspezifische Angaben erfasst werden koennen: Projektname, Projektnummer, Auftraggeber/Kunde, Projektadresse/Standort, Bearbeitungsdatum, sowie optional ein Projekt-/Kundenfoto (Kundenprofil-Dialog). |
| FA-854 | Das Firmenlogo muss als Bilddatei (PNG, JPG, SVG) importiert werden koennen und in der Groesse automatisch fuer die Verwendung in Berichten angepasst werden. Firmenlogo und Projektfoto muessen zusaetzlich direkt per "Aus Zwischenablage einfuegen" gesetzt werden koennen (ohne Umweg ueber eine Datei). |

#### 3.9.2 Verwendung auf Berichten und Exporten

| ID | Anforderung |
|----|-------------|
| FA-855 | Alle generierten Berichte und Dokumentationen muessen einen Kopfbereich (Header) mit Firmenlogo, Firmenname, Projektname und Bearbeitungsdatum enthalten. |
| FA-856 | Alle generierten Berichte muessen einen Fussbereich (Footer) mit Anwendername, Funktion, Kontaktdaten und Seitennummerierung enthalten. |
| FA-857 | Das Topologie-Prinzipschema (FA-904) muss ein Titelfeld mit Firmenlogo, Projektangaben und Bearbeiterinformationen enthalten. |
| FA-858 | Alle PDF-Dokumente (Berichte, Offerten, Exporte) und Excel-Berichte muessen die Firmenschrift Inter verwenden; die Schrift wird mit der Anwendung ausgeliefert. PDF-Berichte markieren jeden Abschnitt mit einem farbigen Balken am linken Rand und wiederholen bei einem Seitenumbruch innerhalb einer Tabelle Abschnitt und Unterabschnitt als Fortsetzungstitel. **(S)** |

### 3.10 Berichtswesen und Dokumentation (FA-900)

| ID | Anforderung |
|----|-------------|
| FA-901 | Das System muss einen Validierungsbericht Gruppenadressen generieren koennen, der alle Fehler, Warnungen und Hinweise auflistet: Zusammenfassung mit Uebersicht nach Regel, danach je Stufe ein Abschnitt (Balken rot/orange/blau) und je Regel ein Block mit Bedeutung, Massnahme und regelspezifischen Spalten. Betreffen Bezeichnungs-Hinweise (FA-610) mehr als die Haelfte aller GAs, werden nur 20 Beispiele aufgefuehrt. |
| FA-902 | Jeder Berichtseintrag muss die betroffene Gruppenadresse, den Fehlertyp und einen Loesungsvorschlag enthalten. |
| FA-903 | Das System muss eine Projektzusammenfassung/Statistik ausgeben: Gebaeudestruktur, Anzahl Bereiche/Linien, Gewerke-Verteilung, Anzahl Gruppenadressen pro Mittelgruppe, Fehler und Warnungen. Bei importierten Projekten zaehlt die Gewerke-Verteilung die von Aktoren/Gateways gesteuerten Elemente (Element = Gewerk, Stockwerk, Raum und Element-Nr. aus der Bezeichnung einer mit einem Aktor verbundenen GA); Gewerke ohne Aktoren aus der Gewerk-Zuweisung. Zentraladressen = Anzahl GAs in HG 0. |
| FA-903a | In Schritt 5 (Gewerke) muss der Anwender die Anzahlen je Raum und Gewerk aus diesen gesteuerten Elementen uebernehmen koennen: Vorschau der Aenderungen, bestehende Zuweisungen bleiben erhalten (nur Anzahl), Hinweis auf Raeume, die in der Gebaeudestruktur fehlen. |
| FA-904 | Das System muss ein Prinzipschema der Topologie als druckbares Dokument/Grafik exportieren koennen (fuer die Projektdokumentation gemaess KNX Swiss Kap. 8/15). Der Topologie-Bericht enthaelt: Topologie-Diagramm wie in der Ansicht "Topologie-Diagramm" (je Bereich eine Spalte, Backbone bei mehreren Bereichen, Bereichskoppler, Speisegeraet, Linien mit Koppler, SV und Geraetezahlen, Leitungslaengen-Warnung farbig gemaess FA-2603; hoechstens vier Bereiche nebeneinander), Schema (Bereiche, Linien mit Koppler, Auslastungsbalken und Geraetezahlen), Kennzahlen je Linie, Geraeteliste je Linie (Adresse, Geraet mit Hersteller/Bestell-/Seriennummer als zweite Zeile, Typ, Einbauort) und Geraeteliste je Einbauort (Verteiler zuerst). Schema der Spannungsversorgungen (T-06): die SV der Bereichslinie haengt an der Bereichslinie, je Bereich verlaeuft unter dem Bereichskoppler die Hauptlinie als Busleitung, an der ihre SV und die Linien abzweigen; die SV einer Linie steht als gruenes Band in der Linie. Gleich in der Ansicht "Topologie-Diagramm" und im Topologie-Bericht. |
| FA-905a | Steigschema: Gebaeudeschnitt mit Stockwerken uebereinander (Dach oben, Keller unten, Hoehenlage aus dem Stockwerkkuerzel), Nebengebaeude daneben auf gleicher Hoehe. Je Stockwerk die Raeume nach Zonen, die Verteiler (Schritt 4) und die Steigzone, in der jede Linie als farbige Spur vom Verteiler ihres Linienkopplers (FA-1305a) zu ihren Stockwerken laeuft; je Stockwerk ein Abzweig unter den Raeumen mit Punkt je angeschlossenem Raum (Raeume mit Teilnehmern, in frueher Planung alle Raeume der Zone). Linien in ein anderes Gebaeude als Erdleitung unter dem Terrain. Legende je Linie mit Teilnehmern, Verteiler und Leitungslaenge. Ansicht "Steigschema" (Seitenleiste) mit Hervorheben einer Linie per Klick, Zoom, Tooltips und Export als PNG/PDF; im Topologie-Bericht als eigene Querformat-Seite nach dem Topologie-Diagramm. |
| FA-905 | Alle Berichte und exportierten Dokumente muessen die Firmenprofil- und Projektdaten gemaess FA-855 bis FA-857 enthalten. |
| FA-906 | Das System muss einen Bericht "Bedienelemente und Sensoren" erzeugen, gegliedert nach Stockwerk und Raum (jeder Raum auf neuer Seite): Uebersicht mit Seitenzahlen und PDF-Lesezeichen (Stockwerk, Raum, Geraet); je Bedienelement (vom Bauherrn bedienbar: Tastereinheit, Raumthermostat, Touchpanel, Raumbediengeraet) eine Karte mit Tastenplan (Gewerk oder Szene je Taste) und einer Zeile je Taste mit allen Gruppenadressen und LED-Rueckmeldung; danach die Sensoren des Raums (Praesenz-/Bewegungsmelder, Wasser-/Rauchmelder, Kontakte, Fuehler ...) kompakt mit Gruppenadressen, inkl. Topologie-Sensoren mit Raumzuordnung, die nicht als Bedienelement erfasst sind. |
| FA-907 | Das System muss einen Bericht "Aktoren und Gateways" erzeugen, gegliedert nach Einbauort (Verteiler zuerst, jeder Einbauort auf neuer Seite): Uebersicht mit Anzahl Aktoren/Gateways, je Geraet Adresse, Geraet (Hersteller/Bestell-/Seriennummer als zweite Zeile), Typ, Einbauort, belegte Kanaele / Kanalzahl laut Produktbezeichnung und Seitenzahl; PDF-Lesezeichen (Einbauort, Geraet). Je Geraet eine Karte: bei geplanten Projekten eine Zeile je Kanal mit Gewerk, Stockwerk/Raum und allen Gruppenadressen (Zentral- und Szenenadressen separat); bei importierten Projekten eine Zeile je Kommunikationsobjekt mit Gruppenadressen, nach dem Kanal im Objektnamen gegliedert (z.B. "Ausgang A", "Kanal 1", "Group 1", "ON/OFF_1"), Objekte ohne erkennbaren Kanal zuletzt unter "Weitere". |
| FA-908 | Das System muss einen Bericht "Raeume nach Gewerken" erzeugen: Uebersicht je Raum mit den Gewerken (Code und Anzahl Elemente), Anzahl GAs und Seitenzahl; danach je Stockwerk (neue Seite) und Raum eine Zeile je Element (Gewerk + Element-Nr.) mit allen Gruppenadressen (Adresse, Bezeichnung, DPT, Beschreibung); PDF-Lesezeichen (Stockwerk, Raum). Raum einer GA: aus der Planung, sonst aus der Bezeichnung GEWERK.STOCKWERK.RAUM.ELEMENT (Raumnummer je Stockwerk), sonst ueber Taster/Sensoren im Raum; Aktoren und Gateways ordnen keine GAs zu. Adressen in HG 0 erscheinen je Raum als "Zentral". Raeume aus Bezeichnungen, die in der Gebaeudestruktur fehlen, werden in einem eigenen Abschnitt aufgefuehrt. |

### 3.11 Benutzeroberflaeche (FA-1000)

#### 3.11.1 Design und Gestaltung

| ID | Anforderung |
|----|-------------|
| FA-1001 | Das System muss ueber eine grafische Benutzeroberflaeche (GUI) bedienbar sein. |
| FA-1012 | Die GUI muss in einem zeitgemaessen, modernen Design gestaltet sein und die offiziellen KNX-Signet-Farben (KNX-Gruen #5EA126, KNX-Dunkelgruen, KNX-Blau, Weiss, Grau) als Designbasis verwenden. |
| FA-1013 | Wo die Komplexitaet der Daten hoch ist, muessen grafische Darstellungen verwendet werden, insbesondere: Gebaeudestrukturen (grafische Stockwerk-/Raum-Uebersicht), Topologie-Prinzipschema (Bereiche, Linien, Koppler als Diagramm), Gewerke-Verteilung pro Raum/Stockwerk. |
| FA-1014 | Die GUI muss intuitiv bedienbar sein: klare Navigation, konsistente Bedienelemente, kontextsensitive Tooltips und Hilfetexte, logischer Arbeitsfluss ohne Handbuch-Studium. |
| FA-1015 | Die GUI muss Drag-and-Drop-Funktionalitaet unterstuetzen, um haeufige Aktionen zu beschleunigen, insbesondere: Raeume in Stockwerke verschieben (Gebaeudestruktur), Geraete zwischen Linien verschieben (Topologie), Gewerke per Drag-and-Drop auf Raeume zuweisen, Gruppenadressen per Drag-and-Drop reorganisieren/umsortieren. |
| FA-1015a | Zusaetzlich (e): In der Bauherrenberatung lassen sich Gewerk-Elemente aus einer Funktionsliste (gegliedert nach Raum) auf eine Taste ziehen, auch aus einem anderen Raum, z.B. Licht Technik auf den Taster in der Waschkueche. Das Ablegen wirkt wie die Auswahl in der Liste der Taste (Rueckgaengig-Punkt, Neuberechnung). Elemente ohne Bedienung (FA-619) sind in der Liste orange markiert, "Nur ohne Bedienung" blendet die uebrigen aus. Eine belegte Taste laesst sich am Griff auf eine andere Taste desselben Raums ziehen: auf eine freie verschieben (bei geplanten Projekten ans Ende der Tastereinheit), auf eine belegte tauschen; langer Tastendruck und eigene Bezeichnung fuer die Bedienungsanleitung wandern mit, Positionen importierter Tasten ("Taste 2, links") bleiben. "Taster entfernen" entfernt ein Bedienelement direkt in der Bauherrenberatung wie in Schritt 9 (nur geplante Projekte); ein Raum ohne Bedienelement faellt aus der Raumliste. Stand 07.10.2026: (a) bis (e) umgesetzt, Umsetzung von (a) bis (d) siehe FA-1015c. |
| FA-1015b | Die Bauherrenberatung zeigt alle Raeume des Hauses als Baum (Gebaeude bei mehreren, Stockwerk, Wohnung/Zone, Raum); Raeume ohne Bedienelement grau, sonst mit Anzahl. Mit "+ Bedienelement / Sensor" wird in den gewaehlten Raum eine Tastereinheit, ein Raumthermostat, ein Praesenz- oder Bewegungsmelder gesetzt (manuell angelegt wie in Schritt 9, nur geplante Projekte). Praesenz- und Bewegungsmelder erscheinen mit Kanaelen (K1, K2 ...) statt Tasten; Leuchten werden wie bei Tasten gewaehlt oder aus der Funktionsliste darauf gezogen. Die Neuberechnung legt den Melder in der Topologie an und verknuepft die Gruppenadressen. |
| FA-1015c | Umsetzung (a) bis (d), jeweils mit Rueckgaengig-Punkt; das Ziel wird beim Ziehen hervorgehoben, wo Ablegen nicht geht, erscheint das Verbotszeichen. (a) Gebaeudestruktur: einen oder mehrere Raeume auf eine Wohnung/Zone oder ein Stockwerk ziehen (auf ein Stockwerk: dieselbe Zone, falls sie dort vorkommt, sonst die erste); die Gruppenadressen folgen bei der Neuberechnung dem Stockwerk, die Raumnummer bleibt. (b) Topologie: Geraet auf eine Linie oder ein Geraet dieser Linie ziehen (auch "Auf andere Linie verschieben..."). Bei geplanten Projekten ergeben sich die Geraete aus der Zuordnung Raum zu Linie: ein Taster oder Sensor haengt nach Rueckfrage seinen Raum auf die Ziellinie um, Aktoren lassen sich nicht einzeln ziehen. Importierte und manuell hinzugefuegte Geraete wandern selbst und behalten ihre Teilnehmernummer, wenn sie auf der Ziellinie frei ist, sonst die kleinste freie. Programmierte Geraete bleiben. (c) Gewerke-Uebersicht: Gewerk aus dem Katalog auf einen Raum ziehen (neu mit Anzahl 1 oder ein Element mehr) oder eine Zeile auf einen anderen Raum ziehen; nicht, wenn der Zielraum das Gewerk schon hat. Tasten, die die Elemente bedienen, bedienen sie weiterhin. (d) Gruppenadressen-Baum, nur geplante Projekte (nicht importiert, nicht in die ETS uebertragen): GA auf eine GA derselben Hauptgruppe ziehen tauscht die Adressen, GA(s) auf eine Mittelgruppe derselben Hauptgruppe ziehen setzt sie auf die naechsten freien Untergruppen. HG 0 bleibt fest (wie FA-703); Variante-B-Rueckmeldungen in MG 6/7 wandern mit ihrem Befehl. Verweise (Taster, Szenen, DALI, KOs) werden nachgefuehrt; die Neuberechnung ordnet bestehende GAs ueber Element und Funktion zu und behaelt die neue Position, "Adressen neu ordnen" setzt sie wieder in die Standardreihenfolge. |
| FA-1016 | Beim Oeffnen eines Wizard-Schritts muessen bereits vorhandene Projektdaten automatisch geladen und angezeigt werden. Berechnungsschritte (Aktoren, Sensoren, Gruppenadressen) muessen bei vorhandenen Eingabedaten automatisch ausgefuehrt werden. |

#### 3.11.2 Ansichten und Navigation

| ID | Anforderung |
|----|-------------|
| FA-1002 | Die GUI muss einen Assistenten (Wizard) fuer die Neuerstellung eines KNX-Projekts bieten mit folgenden 13 Schritten: |

**Wizard-Schritte fuer Neuprojekt:**

| Schritt | Bezeichnung | Beschreibung |
|---------|-------------|-------------|
| 1 | Gebaeudestruktur (Etagen) | Erstellen der Gebaeudestruktur mit Stockwerken/Etagen (UG, EG, OG, DG etc.). |
| 2 | Wohnungen / Zonen | Innerhalb der Gebaeudestruktur werden pro Stockwerk die Wohnungen bzw. Zonen erstellt (z.B. Wohnung 1, Wohnung 2 oder Zone Nord, Zone Sued). Eine Zone kann mehrere Stockwerke umfassen (Maisonette). |
| 3 | Raeume | Innerhalb der Wohnungen/Zonen werden die einzelnen Raeume erstellt (z.B. Wohnzimmer, Schlafzimmer, Kueche, Bad). |
| 4 | Elektroverteilungen (HV / UV) | Es werden pro Raum die elektrischen Verteilungen (Hauptverteilung HV, Unterverteilungen UV) angelegt, in denen die Aktoren installiert sind. |
| 5 | Gewerke-Definition | Pro Raum werden die Gewerke definiert (z.B. 2x LD, 1x J, 1x H). Pro Gewerk kann ein Produktdatenblatt (PDF) hinterlegt werden, das in die Projektdokumentation einfliesst. |
| 6 | Geraetekonfiguration pro Raum | Alle physischen Bedienelemente (Tastereinheiten, Bewegungs-/Praesenzmelder, Thermostate usw.) werden pro Raum festgelegt -- noch vor der Topologieberechnung, damit die Linienzuteilung bereits alle Geraete kennt. Eine Tastereinheit kann mehreren Gewerken gleichzeitig zugeordnet werden. |
| 7 | Topologie und Linienzuteilung | Anhand der in Schritt 6 konfigurierten Geraete errechnet das System eine topologisch sinnvolle Linienzuteilung unter Beruecksichtigung der Vorgabedokumente (KNX TP-Topologie, KNX Swiss Richtlinien). Der Benutzer kann die berechnete Topologie manuell anpassen (Bereiche/Linien hinzufuegen/entfernen, Backbone-Typ TP/IP festlegen). |
| 8 | Aktor-Ermittlung | Das System errechnet anhand der definierten Gewerke, welche Aktorentypen (Schaltaktor, Dimmaktor, Jalousieaktor etc.) pro Linie benoetigt werden, und schlaegt passende Aktoren aus dem Internet vor. Der Anwender kann bevorzugte Hersteller definieren. Die ausgewaehlten Aktoren werden mit Produktdatenblatt fuer die Dokumentation gespeichert. |
| 9 | Szenen-Definition | Lichtszenen und andere Szenen werden definiert, bevor die Gruppenadressen generiert werden, damit Szenen-GAs von Anfang an in der GA-Struktur beruecksichtigt sind. |
| 10 | Gruppenadress-Generierung | Basierend auf Gebaeudestruktur, Topologie, Gewerken, Aktoren und Szenen werden die vollstaendigen Gruppenadressen automatisch generiert (inkl. Bezeichnungen, DPTs, Adressblocking). |
| 11 | Funktionszuordnung | Jedem in Schritt 6 angelegten Bedienelement werden die passenden Gruppenadressen je Kanal zugewiesen (Sensorfunktionen gemaess FA-1410). Das System schlaegt passende Sensorprodukte aus dem Internet vor; die Auswahl wird mit Produktdatenblatt gespeichert. |
| 12 | Funktionsdefinition (Bauherr-Formular) | Die Funktionen der Sensoren werden durch den Anwender bzw. den Bauherrn genau definiert: Welcher Taster steuert welches Licht, welche Jalousie etc. Dafuer wird ein Formular generiert, das an den Bauherrn/Auftraggeber gesendet und nach Ausfuellung wieder eingelesen werden kann, oder die Zuordnung erfolgt live in der Bauherren-Beratungsansicht (FA-1508 bis FA-1511). |
| 13 | Export | Die Gruppenadress-Struktur wird als ETS6-kompatible CSV-Datei exportiert. Zusaetzlich wird eine vollstaendige Projektdokumentation generiert. |
| FA-1003 | Die GUI muss eine Baumansicht der Gruppenadress-Hierarchie darstellen (Hauptgruppe > Mittelgruppe > Untergruppe). |
| FA-1004 | Die GUI muss eine tabellarische Ansicht aller Gruppenadressen mit allen Feldern anbieten. |
| FA-1005 | Fehlerhafte oder inkonsistente Eintraege muessen farblich hervorgehoben werden (Rot: Fehler, Gelb: Warnung). |
| FA-1006 | Die GUI muss eine Such- und Filterfunktion bereitstellen (nach Adresse, Name, Gewerk, Funktionsbereich, Stockwerk, Raum). |
| FA-1007 | Die GUI muss eine visuelle Darstellung der Topologie (Prinzipschema) als hierarchische Baumansicht anzeigen. Jedes Element wird als eigenstaendiger Knoten dargestellt (nicht nur als Text in einer Spalte). Die Baumhierarchie lautet: **Speisegeraet Bereichslinie 0.0.-** (bei mehreren Bereichen mit TP-Backbone, oberster Knoten) > **Bereich** (Bereich-Nr., Name, Medium der Hauptlinie) > **Bereichskoppler B.0.0** (nur bei mehr als einem Bereich sichtbar) + **Speisegeraet Hauptlinie B.0.-** (sobald der Bereich eine TP-Hauptlinie hat: mehrere Bereiche oder mehrere Linien) > **Linie** (Linie-Nr., Name, Geraeteanzahl, Statusmarkierung bei Ueberlast) > **Linienkoppler B.L.0** + **Speisegeraet Linie B.L.-**. Bereichskoppler (B.0.0) werden nur bei mehr als einem Bereich als Kindknoten angezeigt; bei Einzelbereich entfaellt dieser Knoten. Koppler und Speisegeraete erscheinen in der Topologie-Ansicht, im Topologie-Diagramm und im Topologie-Bericht nach derselben Regel nur, wenn sie als Geraet vorhanden sind (Koppler auf B.0.0 bzw. B.L.0, Speisegeraete mit Adresse B.L.-); die Koppleradresse der Linie allein genuegt nicht. Nur Wizard-Schritt 4 zeigt bei der Planung die geplanten Koppler und Speisegeraete, bevor sie als Geraete erzeugt sind. Die Linienzeile zeigt die Linienadresse B.L. |
| FA-1007a | Ueber jeder Spalte der Topologie-Ansicht (Element, Adresse, Geraete, Einbauort, Details) steht ein Filterfeld. Angezeigt werden Eintraege, die in jeder ausgefuellten Spalte den Text enthalten (Teiltext, Gross-/Kleinschreibung egal), samt Unterknoten; Bereich und Linie bleiben als Zusammenhang sichtbar und aufgeklappt. Der Filter bleibt nach Aenderungen aktiv. |
| FA-1008 | Die GUI muss einen Modus "Neues Projekt erstellen" und einen Modus "Bestehendes Projekt importieren/analysieren" anbieten. |

#### 3.11.3 Topologie-Report-Ansichten

| ID | Anforderung |
|----|-------------|
| FA-1009 | Bei importiertem Topologie-Report muss die GUI eine Geraete-Detailansicht pro Linie bieten: physikalische Adresse, Hersteller, Produkt, Applikation, Einbauort. |
| FA-1010 | Bei importiertem Topologie-Report muss die GUI eine Kommunikationsobjekt-Ansicht pro Geraet bieten, die alle Objekte mit ihren verbundenen Gruppenadressen zeigt. |
| FA-1011 | Die GUI muss eine Kreuzreferenz-Ansicht bieten, die zeigt, welche Geraete/Objekte mit welchen Gruppenadressen verbunden sind (bidirektionale Navigation: GA -> Geraete und Geraet -> GAs). |

### 3.12 Hilfesystem und Dokumentation (FA-1100)

| ID | Anforderung |
|----|-------------|
| FA-1101 | Die Software muss ein integriertes Hilfesystem bereitstellen, das ueber das Menue ("Hilfe > Hilfe anzeigen" oder F1-Taste) aufgerufen werden kann. **(S)** |
| FA-1102 | Das Hilfesystem muss kontextsensitiv sein: Der Benutzer erhaelt je nach aktuellem Bildschirm/Funktion die passende Hilfeseite. **(S)** |
| FA-1103 | Das Hilfesystem muss folgende Inhalte abdecken: a) Schnellstartanleitung (Getting Started), b) Beschreibung aller Funktionsbereiche (Gebaeudestruktur, Topologie, Gewerke, Gruppenadressen, Import/Export), c) Erklaerung der KNX-Konzepte (Topologie, Adressierung, Gewerke), d) Schritt-fuer-Schritt-Anleitungen fuer die wichtigsten Arbeitsablaeufe, e) FAQ / Haeufige Fragen. |
| FA-1104 | Die Hilfeinhalte muessen als externe Dateien (z.B. HTML oder Markdown) mitgeliefert werden, um Aktualisierungen ohne Programmupdate zu ermoeglichen. |
| FA-1105 | Die Software muss ein Benutzerhandbuch als PDF-Dokument bereitstellen, das ueber das Hilfemenue aufgerufen werden kann. **(S)** |
| FA-1106 | Die Software muss beim ersten Start eines neuen Benutzers optional eine interaktive Einfuehrungstour (Onboarding-Wizard) anbieten, die die wichtigsten Bedienelemente erklaert. **(C)** |

### 3.13 Produktdatenblaetter und Dokumentation (FA-1200)

| ID | Anforderung |
|----|-------------|
| FA-1201 | Das System muss die Speicherung von Produktdatenblaettern (PDF-Dateien) ermoeglichen, die mit folgenden Elementen verknuepft werden koennen: a) Gewerke-Elemente (z.B. Datenblatt einer Leuchte, eines Jalousie-Antriebs), b) Aktoren (z.B. Datenblatt eines Schaltaktors), c) Sensoren (z.B. Datenblatt eines Tasters, Praesenzmelders). |
| FA-1202 | Produktdatenblaetter muessen als PDF-Dateien importiert und im Projekt gespeichert werden koennen. Pro Element koennen mehrere Datenblaetter hinterlegt werden. |
| FA-1203 | Die Produktdatenblaetter muessen in der GUI als Vorschau angezeigt und geoeffnet werden koennen. |
| FA-1204 | Bei der Erstellung der Projektdokumentation (FA-900) muessen die hinterlegten Produktdatenblaetter automatisch in die Dokumentation eingebunden oder als Anhang beigefuegt werden koennen. Umsetzung: Im Revisionspaket werden die hinterlegten Datenblaetter (Geraete, Bedienelemente, Gewerke) je Datei einmal in den Unterordner "Datenblaetter" kopiert; das Inhaltsverzeichnis listet Produkt und Datei, Links (URL) und nicht gefundene Dateien. |
| FA-1205 | Das System muss pro Produkt (Aktor, Sensor, Gewerk-Element) folgende Stammdaten erfassen: Hersteller, Bestellnummer/Artikelnummer, Produktbezeichnung, ETS-Applikationsprogramm (falls zutreffend), Preis (optional). |

### 3.14 Aktor-Ermittlung und Herstellerpraeferenzen (FA-1300)

| ID | Anforderung |
|----|-------------|
| FA-1301 | Das System muss anhand der definierten Gewerke pro Raum automatisch ermitteln, welche Aktorentypen auf den zugeordneten Linien benoetigt werden. Folgende Zuordnung muss unterstuetzt werden: |

**Standard-Aktortyp-Zuordnung nach Gewerk:**

| Gewerk | Aktortyp | Beschreibung |
|--------|----------|-------------|
| L | Schaltaktor | Ein/Aus-Schalten von Licht |
| LD | Dimmaktor | Dimmbares Licht (0-10V oder Phasenanschnitt) |
| LDA | DALI-Gateway | Dimmbares Licht ueber DALI-Bus (interface_type="gateway") |
| J, R, M, T | Jalousieaktor | Auf/Ab, Positionierung, Lamellen |
| H | Heizungsaktor | Stellantrieb, Ventilsteuerung |
| S, SD | Schaltaktor | Schaltbare Steckdosen |
| V | Schaltaktor | Ventilatoren Ein/Aus/Stufen |
| G, DF | Schaltaktor | Garagentor, Dachfenster |
| BW | Schaltaktor | Bewaesserung |
| MM | KNX-Schnittstelle / Gateway | Multimedia-System (z.B. Revox, Sonos) via IP-KNX-Gateway (interface_type="gateway") |
| WP | KNX-Schnittstelle / Gateway | Waermepumpe via Modbus-KNX- oder propriaetaeres KNX-Gateway (interface_type="gateway") |

| ID | Anforderung |
|----|-------------|
| FA-1302 | Das System muss die Aktor-Kanaele zusammenfassen: Wenn ein Raum z.B. 3x L hat, benoetigt er 3 Kanaele eines Schaltaktors. Das System muss ermitteln, welche Mehrkanalaktoren (z.B. 4-fach, 8-fach, 12-fach Schaltaktor) optimal eingesetzt werden koennen. |
| FA-1303 | Das System muss passende Aktoren aus dem Internet vorschlagen koennen. Dazu muss es Produktdatenbanken / Online-Kataloge von KNX-Herstellern abfragen oder eine integrierte/herunterladbare Produktdatenbank nutzen. |
| FA-1303a | Umsetzung als herunterladbare Produktdatenbank: Der Hersteller von KNX Arranger pflegt einen Online-Produktkatalog (JSON-Datei `product_catalog_online.json` im oeffentlichen Release-Repository, gleiche Produktfelder wie die mitgelieferte Datenbank). Der Anwender kann ihn im Produkt-Auswahldialog ueber "Online-Katalog aktualisieren" herunterladen; Anzahl Produkte und Stand werden angezeigt. |
| FA-1303b | Der heruntergeladene Katalog muss lokal zwischengespeichert werden (Benutzerprofil, nicht Programmordner), damit die Vorschlaege auch ohne Internetverbindung und nach einem Neustart verfuegbar sind. Schlaegt der Download fehl, bleibt der bisherige Stand erhalten und der Anwender erhaelt eine verstaendliche Meldung. |
| FA-1303c | Online-Produkte muessen zusammen mit der mitgelieferten Datenbank und den eigenen KNXPROD-Importen durchsucht und in der Ergebnisliste erkennbar markiert werden. Bei gleichem Hersteller und gleicher Bestellnummer hat ein eigener Import Vorrang vor dem Online-Katalog, der Online-Katalog Vorrang vor der mitgelieferten Datenbank. Unvollstaendige Eintraege (ohne Hersteller, Bestellnummer oder gueltige Kategorie) werden verworfen. |
| FA-1303d | Fuer die Pflege des Online-Katalogs muss ein Werkzeug zur Verfuegung stehen, das die Katalogdatei prueft und Produkte aus den eigenen KNXPROD-Importen (optional nach Hersteller gefiltert) uebernimmt. |
| FA-1304 | Der Anwender muss eine Liste bevorzugter Hersteller definieren koennen (z.B. ABB, MDT, Theben, Gira, Jung). Die Produktvorschlaege muessen bevorzugt Produkte dieser Hersteller anzeigen. |
| FA-1305 | Die vom Benutzer ausgewaehlten Aktoren muessen mit Produktdatenblatt (gemaess FA-1201) im Projekt gespeichert und der entsprechenden Linie in der Topologie zugeordnet werden. |
| FA-1305a | Einbauort der Aktoren: Jede Linie erhaelt einen Verteiler aus Schritt 4 - automatisch den ersten Verteiler in ihren Raeumen, sonst die erste HV, sonst den ersten Verteiler im Projekt - oder einen in Schritt 8 gewaehlten. Je Aktortyp kann ein anderer Verteiler gelten (z.B. Jalousieaktoren in der UV des Stockwerks), damit Leitungslaengen kurz bleiben. Linienkoppler und Spannungsversorgung sitzen im Verteiler der Linie. Die Wahl bleibt bei Neuberechnung der Aktoren und der Topologie erhalten (Zuordnung ueber den Liniennamen) und fuellt die Aktorliste der Verteiler. In der Topologie-Ansicht ist der Einbauort von Linie und Aktor eine Auswahl der Verteiler mit Freitext; die Wahl fuer einen Aktor gilt fuer alle Aktoren desselben Typs der Linie. Programmierte Geraete und eigene Freitexte bleiben unveraendert. |
| FA-1306 | Das System muss eine Zusammenfassung der benoetigten Aktoren pro UV/HV erstellen koennen (Stueckliste / Materialliste). |
| FA-1307 | Das System muss Gateway-basierte Gewerke (interface_type="gateway": LDA, MM, WP) in Wizard Schritt 8 gesondert behandeln: Statt eines klassischen Aktors wird ein Schnittstellengeraet (Device mit device_type="gateway") auf der zugeordneten Linie eingeplant. Das Gateway-Geraet erhaelt die dem Gewerk zugehoerigen Gruppenadressen. **(M)** Je Gateway-Gewerk waehlbar in Schritt 8 (Bereich "Gateways"): "gemeinsam fuer das Projekt" (ein Gateway fuer alle Raeume dieses Gewerks, Kapazitaet nach Anzahl Elemente, auf der Linie mit der HV oder einer gewaehlten Linie; z.B. Revox mit Studio und Wohnung) oder "je Linie". Vorgabe gemeinsam: MM, WP, PV, SP, EV, LU, KL; je Linie: LDA, DMX (Entscheid 06.10.2026). Die Gruppenadressen bleiben je Raum. |
| FA-1308 | Gateway-Geraete muessen in der Materialliste (FA-1306) als eigene Kategorie "Gateways / Schnittstellen" gefuehrt werden und pro Eintrag den Gewerk-Code, den Gateway-Typ (z.B. "DALI-Gateway", "Modbus-KNX-Gateway") sowie Hersteller und Bestellnummer aufnehmen koennen. **(M)** |

### 3.15 Sensor-Ermittlung und Herstellerpraeferenzen (FA-1400)

| ID | Anforderung |
|----|-------------|
| FA-1401 | Das System muss anhand der generierten Gruppenadressen und der Gewerke pro Raum automatisch ermitteln, welche Sensortypen benoetigt werden. Folgende Zuordnung muss unterstuetzt werden: |

**Standard-Sensortyp-Zuordnung nach Gewerk:**

| Gewerk | Sensortyp | Beschreibung |
|--------|-----------|-------------|
| L, LD, LDA | Taster / Praesenzmelder | Schalten, Dimmen, Szenen |
| J, R, M, T | Taster (mit Jalousie-Wippe) | Auf/Ab, Stopp, Lamellen |
| H | Raumthermostat / Temperaturfuehler | Sollwert, Betriebsart |
| A | Magnetkontakt / Bewegungsmelder | Alarmierung |
| FK, TK, RK | Fensterkontakt / Tuerkontakt | Zustandsueberwachung |
| W | Wetterstation (**Systemsensor**) | Wind, Regen, Helligkeit, Temperatur -- einmalig pro Projekt, nicht raumweise |
| E | Energiezaehler / Stromwandler | Verbrauchsmessung |

| ID | Anforderung |
|----|-------------|
| FA-1402 | Das System muss passende Sensoren aus dem Internet vorschlagen koennen (analog zu FA-1303 fuer Aktoren; derselbe Online-Produktkatalog gemaess FA-1303a bis FA-1303d). |
| FA-1403 | Der Anwender muss bevorzugte Hersteller fuer Sensoren definieren koennen (analog zu FA-1304, kann dieselbe Liste sein). |
| FA-1404 | Die vom Benutzer ausgewaehlten Sensoren muessen mit Produktdatenblatt (gemaess FA-1201) im Projekt gespeichert und dem jeweiligen Raum zugeordnet werden. |
| FA-1405 | Das System muss eine Zusammenfassung der benoetigten Sensoren pro Raum/Stockwerk/Gesamtprojekt erstellen koennen (Stueckliste / Materialliste). |
| FA-1406 | Die Materiallisten fuer Aktoren (FA-1306) und Sensoren (FA-1405) muessen zu einer Gesamt-Materialliste mit Mengen und optionalen Preisen zusammengefuehrt werden koennen. |
| FA-1407 | Der Integrator muss den automatisch ermittelten Sensortyp pro Gewerk-Zuweisung in einem Raum manuell ueberschreiben koennen (Sensortyp-Override). Folgende Anforderungen gelten: |

**FA-1407 Detailanforderungen:**

| Nr. | Anforderung |
|-----|-------------|
| FA-1407a | In Wizard Schritt 6 muss der Benutzer per Doppelklick auf eine Sensorzeile einen Dialog oeffnen koennen, in dem der Sensortyp aus einer vordefinierten Liste geaendert werden kann. |
| FA-1407b | Die vordefinierten Sensortypen zur Auswahl umfassen mindestens: Taster 1-fach, Taster 2-fach, Taster 4-fach, Praesenzmelder, Bewegungsmelder, Raumthermostat, Temperaturfuehler, Fensterkontakt, Tuerkontakt, Magnetkontakt, Wetterstation, Energiezaehler. |
| FA-1407c | Ein gesetzter Override muss visuell hervorgehoben werden (z.B. kursive Schrift oder abweichende Farbe) damit der Unterschied zum automatisch berechneten Wert erkennbar ist. |
| FA-1407d | Der Override-Wert muss im Datenmodell auf der `GewerkAssignment`-Ebene als `sensor_type_override` (optionaler String) persistiert werden. Ist `sensor_type_override` gesetzt, hat er Vorrang vor dem automatisch ermittelten Sensortyp. |
| FA-1407e | Eine erneute Berechnung in Schritt 6 (Button "Alle automatisch berechnen") darf gesetzte Overrides nicht loeschen. |
| FA-1407f | Der Benutzer muss einen Override mit einem "Zuruecksetzen"-Button im Override-Dialog auf den automatisch berechneten Wert zuruecksetzen koennen. |

| ID | Anforderung |
|----|-------------|
| FA-1408 | Gewerke vom Typ interface_type="system_sensor" (z.B. W = Wetterstation) werden in Wizard Schritt 6 nicht raumweise, sondern projektweise geplant. Das System muss pruefen, ob ein Gewerk dieses Typs im Projekt vorhanden ist, und automatisch einen Systemsensor-Eintrag in der Materialliste anlegen -- unabhaengig von der Raumanzahl. Pro Projekt wird genau ein Systemsensor-Eintrag pro interface_type="system_sensor"-Gewerk erstellt. **(M)** |
| FA-1409 | In Wizard Schritt 6 muss ein separater Abschnitt "Systemgeraete" angezeigt werden, der alle geplanten Systemsensoren (interface_type="system_sensor") auflistet. Systemgeraete sind keinem Raum, sondern dem Gesamtprojekt zugeordnet. Ihre Gruppenadressen erscheinen in den empfangenden Gewerken (z.B. Wetterstation-GA "Helligkeit" wird von Gewerk J/Jalousie empfangen). Der Integrator kann Hersteller und Produkt fuer jeden Systemsensor hinterlegen. **(M)** |

| ID | Anforderung |
|----|-------------|
| FA-1410 | Das System fuehrt das Konzept der «Sensorfunktion» ein. Eine Sensorfunktion ist die logische Steuereinheit an einem Bedienelement: Sie beinhaltet alle zugehoerigen Gruppenadressen (Primaerfunktionen und Rueckmeldungen) einer Gewerk-Instanz. Das Datenmodell speichert Bedienelemente mit einer Liste von Sensorfunktionen (`Bedienelement.funktionen`). **(M)** |
| FA-1410a | Eine Sensorfunktion referenziert entweder (a) eine Gewerk-Instanz (gewerk_code + element_number + source_room_id, wobei source_room_id leer = eigener Raum) oder (b) eine einzelne direkte Gruppenadresse (ga_designation gesetzt, gewerk_code leer). Fall (b) ist ein degenerierter Sonderfall mit genau einer GA. **(M)** |
| FA-1410b | Fuer gewerk-basierte Sensorfunktionen werden alle Primaer- und Rueckmelde-GAs des referenzierten Gewerks automatisch und implizit abgeleitet. Der Benutzer muss die Rueckmeldung nicht separat hinzufuegen; sie ist immer inbegriffen. **(M)** |
| FA-1410c | Im Konfigurationsdialog (Wizard Schritt 11) wird dem Benutzer pro Bedienelement eine Liste von Sensorfunktionen angezeigt – eine Zeile pro logischer Steuereinheit, nicht pro einzelner Gruppenadresse. Das Hinzufuegen erfolgt durch Auswahl eines Gewerks (Tab «Eigener Raum» / «Anderer Raum») oder einer direkten GA (Tab «Direkte GA»). **(M)** |
| FA-1410d | Beim Einlesen von Projektdaten mit dem alten Feld «control_functions» migriert das System automatisch: Eintraege gleicher (gewerk_code, element_number, source_room_id) werden zu einer einzigen Sensorfunktion zusammengefasst; Eintraege mit ga_designation bleiben als degenerierte Einzelfunktionen erhalten. **(M)** |

### 3.16 Funktionsdefinition durch Bauherrn (FA-1500)

| ID | Anforderung |
|----|-------------|
| FA-1501 | Das System muss ein Funktionsdefinitions-Formular generieren koennen, das pro Raum auflistet: alle vorhandenen Sensoren (Taster, Praesenzmelder etc.) mit ihren verfuegbaren Tasten/Kanaelen, alle schaltbaren Gewerke im Raum (Licht, Jalousie, Heizung etc.). |
| FA-1502 | Das Formular muss dem Bauherrn/Auftraggeber die Moeglichkeit geben, pro Sensor-Taste/-Kanal zu definieren, welche Funktion ausgefuehrt werden soll (z.B. "Taste 1 oben = Licht Decke EIN", "Taste 1 unten = Licht Decke AUS", "Taste 2 lang = Jalousie Sued AUF"). |
| FA-1503 | Das Formular muss in einem austauschbaren Format exportiert werden koennen: a) PDF-Formular (zum Ausdrucken und handschriftlichen Ausfuellen), b) Excel-Datei (.xlsx, zum digitalen Ausfuellen), c) Eigenes Formularformat (optional, fuer direktes Einlesen). |
| FA-1504 | Das System muss ein ausgefuelltes Formular (Excel oder eigenes Format) wieder einlesen und die Funktionszuordnungen automatisch in die Projektdaten uebernehmen koennen. |
| FA-1505 | Die importierten Funktionszuordnungen muessen in der GUI angezeigt und vom Anwender nachbearbeitet werden koennen. |
| FA-1506 | Das System muss die Funktionsdefinitionen in die Projektdokumentation einbinden: Pro Raum eine Uebersicht, welcher Sensor welche Funktionen steuert. |
| FA-1507 | Das Formular muss Firmenprofil-Daten (FA-855) und Projektangaben (FA-853) im Kopf-/Fussbereich enthalten, um ein professionelles Erscheinungsbild zu gewaehrleisten. |

#### 3.16.1 Bauherren-Beratungsansicht (Live-Funktionszuordnung)

| ID | Anforderung |
|----|-------------|
| FA-1508 | Das System muss als Alternative zum Papier-/Excel-Formular (FA-1501 bis FA-1504) eine interaktive Beratungsansicht anbieten, in der der Integrator die Funktionszuordnung gemeinsam mit dem Bauherrn direkt am Bildschirm erfasst -- pro Raum eine Liste aller Bedienelemente mit ihren Sensorfunktionen (FA-1410). |
| FA-1509 | In der Beratungsansicht muss der Integrator pro Bedienelement und pro Raum eine freie Anmerkung (Freitext) erfassen koennen, die unabhaengig von der Funktionszuordnung im Projekt gespeichert wird. |
| FA-1510 | Aenderungen an Anmerkungen muessen ein einfaches Autosave des Projekts ausloesen; Aenderungen an Funktionszuordnungen muessen die volle Neuberechnung der Bedienelemente (gemaess FA-1410, FA-1407e) ausloesen. |
| FA-1511 | In der Beratungsansicht erfasste oder geaenderte Funktionszuordnungen muessen als manuell markiert (nicht automatisch ueberschreibbar) im Projekt gespeichert werden, damit eine spaetere Neuberechnung (z.B. nach Aenderungen in Schritt 6) die Bauherren-Wuensche nicht verwirft. |

### 3.17 Offertanfragen und Beschaffung (FA-1600)

#### 3.17.1 Lieferanten-/Haendlerverwaltung

| ID | Anforderung |
|----|-------------|
| FA-1601 | Das System muss eine Lieferanten-/Haendler-Datenbank fuehren, in der folgende Angaben pro Lieferant gespeichert werden koennen: |

**Lieferanten-Stammdaten:**

| Feld | Pflicht | Beschreibung | Beispiel |
|------|---------|-------------|---------|
| Firmenname | Ja | Name des Lieferanten/Haendlers | Elektro-Material AG |
| Kontaktperson | Ja | Ansprechpartner fuer Offerten | Hans Muster |
| E-Mail | Ja | E-Mail-Adresse fuer Offertversand | offerten@em-ag.ch |
| Telefon | Nein | Geschaeftstelefon | +41 44 987 65 43 |
| Adresse | Nein | Firmenadresse | Industriestrasse 10, 8005 Zuerich |
| Webseite | Nein | Webshop / Firmen-URL | www.em-ag.ch |
| Kundennummer | Nein | Eigene Kundennummer beim Lieferanten | KD-2024-1234 |
| Kategorie | Nein | Hersteller / Grosshaendler / Fachhandel | Grosshaendler |
| Vertretene Marken | Nein | Welche KNX-Hersteller der Lieferant fuehrt | ABB, MDT, Theben |
| Bemerkungen | Nein | Interne Notizen | Rabattstaffel ab CHF 5000 |

| ID | Anforderung |
|----|-------------|
| FA-1602 | Die Lieferantendaten muessen global (projektuebergreifend) gespeichert und fuer alle Projekte wiederverwendet werden koennen. |
| FA-1603 | Das System muss eine Zuordnung von bevorzugten Herstellern (FA-1304) zu Lieferanten ermoeglichen: Welcher Lieferant wird fuer welchen Hersteller angefragt. |

#### 3.17.2 Automatische Offertanfrage-Erstellung

| ID | Anforderung |
|----|-------------|
| FA-1611 | Das System muss basierend auf der Gesamt-Materialliste (FA-1406) automatisch Offertanfragen generieren koennen. Die Materialliste wird dabei nach Lieferanten/Herstellern aufgeteilt, sodass jeder Lieferant nur die fuer ihn relevanten Positionen erhaelt. |
| FA-1612 | Jede Offertanfrage muss folgende Angaben enthalten: |

**Inhalt einer Offertanfrage:**

| Bereich | Inhalt |
|---------|--------|
| Kopfbereich | Firmenprofil des Anwenders (FA-855), Datum, Offertanfrage-Nummer (automatisch generiert) |
| Adressfeld | Lieferant (Name, Adresse, Kontaktperson, E-Mail) |
| Projektangaben | Projektname, Projektnummer, Projektadresse/Standort, geplanter Liefertermin |
| Positionsliste | Pos.-Nr., Hersteller, Bestellnummer, Produktbezeichnung, Menge, Einheit |
| Fussbereich | Gewuenschtes Offertdatum, Lieferbedingungen, Kontaktdaten Anwender, Unterschriftsfeld |

| ID | Anforderung |
|----|-------------|
| FA-1613 | Der Benutzer muss vor der Erstellung die Positionen der Offertanfrage pruefen und anpassen koennen: Positionen hinzufuegen, entfernen, Mengen aendern, Bemerkungen pro Position ergaenzen. |
| FA-1614 | Das System muss Offertanfragen in folgenden Formaten exportieren koennen: a) PDF (druckfertig, professionelles Layout mit Firmenlogo), b) Excel (.xlsx, zur elektronischen Weiterverarbeitung durch den Lieferanten), c) E-Mail (automatische Erstellung einer E-Mail mit PDF-Anhang an den Lieferanten, sofern ein E-Mail-Client konfiguriert ist). Umsetzung: Knoepfe "Als PDF..." und "Per E-Mail..." in der Offertanfrage. PDF im einheitlichen Berichtslayout mit den Angaben nach FA-1612 (Offerte erbeten bis Erstelldatum + 14 Tage). E-Mail als Entwurf (.eml mit PDF-Anhang, X-Unsent) im Standard-Mailprogramm; danach Rueckfrage, ob die Anfrage als "Versendet" markiert wird. Ablage im Projektordner unter Berichte/Offertanfragen. |
| FA-1615 | Das System muss eine Sammel-Offertanfrage unterstuetzen: Dieselbe Materialliste wird gleichzeitig an mehrere Lieferanten gesendet, um Preisvergleiche zu ermoeglichen. Umsetzung: "An weitere Lieferanten..." kopiert die Positionen der gewaehlten Anfrage ohne Preise fuer weitere Lieferanten; die Anfragen bilden eine Sammelanfrage (Spalte "Sammelanfrage"). |

#### 3.17.3 Offertverwaltung und Preisvergleich

| ID | Anforderung |
|----|-------------|
| FA-1621 | Das System muss den Status jeder Offertanfrage verfolgen koennen: |

**Offert-Status:**

| Status | Beschreibung |
|--------|-------------|
| Entwurf | Offertanfrage erstellt, noch nicht versendet |
| Versendet | Offertanfrage an Lieferant gesendet (Datum wird gespeichert) |
| Erhalten | Offerte vom Lieferanten eingegangen |
| Zugeschlagen | Dieser Lieferant hat den Zuschlag erhalten |
| Abgelehnt | Offerte wurde nicht beruecksichtigt |

| ID | Anforderung |
|----|-------------|
| FA-1622 | Das System muss eingegangene Offerten erfassen koennen: Pro Position der Einzelpreis, Gesamtpreis, Lieferfrist, Rabatte und Bemerkungen des Lieferanten. Umsetzung: Positionstabelle mit Einzelpreis, Rabatt %, Netto gesamt (berechnet), Lieferfrist und Bemerkung. Mit dem ersten Preis wechselt der Status auf "Erhalten". Die Excel-Anfrage enthaelt die Spalten zum Ausfuellen. |
| FA-1623 | Das System muss einen Preisvergleich ueber mehrere eingegangene Offerten erstellen koennen: Tabellarische Gegenuberstellung der Positionen mit Preisen aller angefragten Lieferanten, Hervorhebung des guenstigsten Anbieters pro Position und gesamt, Berechnung von Gesamtkosten pro Lieferant. Umsetzung: "Preisvergleich..." stellt die Offerten der Sammelanfrage (sonst alle Anfragen mit Preisen) nebeneinander, Nettobetraege je Position, guenstigster je Position und gesamt gruen; gesamt nur unter Anbietern, die alle Positionen offeriert haben. |
| FA-1624 | Der Preisvergleich muss als druckbarer Bericht (PDF) exportiert werden koennen, um als Entscheidungsgrundlage zu dienen. Umsetzung: "Als PDF..." im Preisvergleich, guenstigster mit * markiert, Lieferfristen unter den Betraegen. |
| FA-1625 | Bei Zuschlagserteilung muessen die Preise aus der akzeptierten Offerte automatisch in die Materialliste und Projektdokumentation uebernommen werden koennen. Umsetzung: Zuschlag uebernimmt die Nettopreise (nach Rabatt) in die Materialliste und setzt die uebrigen Anfragen der Sammelanfrage auf "Abgelehnt". |

### 3.18 Kundenofferte fuer KNX-Integration (FA-1700)

#### 3.18.1 Kalkulation und Preisgestaltung

| ID | Anforderung |
|----|-------------|
| FA-1701 | Das System muss basierend auf den akzeptierten Beschaffungspreisen (FA-1625) und benutzerdefinierten Aufschlaegen eine Kundenofferte fuer den Bauherrn kalkulieren koennen. |
| FA-1702 | Das System muss folgende Kostenarten pro Position unterstuetzen: |

**Kostenarten der Kundenofferte:**

| Kostenart | Beschreibung | Beispiel |
|-----------|-------------|---------|
| Material | Einkaufspreis der KNX-Geraete (aus Beschaffungsofferte) | CHF 1'250.00 |
| Material-Aufschlag | Prozentualer oder fixer Aufschlag auf den Materialpreis | 15% oder CHF 187.50 |
| Montage | Arbeitszeit fuer die physische Installation der Geraete | 2.5 h x CHF 125.00/h |
| Programmierung | Arbeitszeit fuer ETS6-Programmierung und Inbetriebnahme | 1.5 h x CHF 145.00/h |
| Inbetriebnahme | Funktionstest, Einregulierung, Kundeneinweisung | 0.5 h x CHF 145.00/h |
| Nebenkosten | Kleinmaterial, Beschriftung, Kabelverbrauch etc. | Pauschale CHF 50.00 |

| ID | Anforderung |
|----|-------------|
| FA-1703 | Das System muss konfigurierbare Stundensaetze und Aufschlagssaetze speichern koennen (globale Einstellung, pro Projekt ueberschreibbar): a) Stundensatz Montage (CHF/h), b) Stundensatz Programmierung (CHF/h), c) Stundensatz Inbetriebnahme (CHF/h), d) Material-Aufschlag (% oder fix), e) Nebenkostenpauschale (CHF pro Geraet oder gesamt). |
| FA-1704 | Das System muss Richtwerte fuer den Zeitaufwand pro Geraetetyp vorschlagen: |

**Richtwerte Zeitaufwand pro Geraet (konfigurierbar):**

| Geraetetyp | Montage | Programmierung | Inbetriebnahme |
|------------|---------|----------------|----------------|
| Schaltaktor (REG) | 0.25 h | 0.5 h pro Kanal | 0.15 h pro Kanal |
| Dimmaktor (REG) | 0.25 h | 0.75 h pro Kanal | 0.25 h pro Kanal |
| Jalousieaktor (REG) | 0.25 h | 0.75 h pro Kanal | 0.25 h pro Kanal |
| Heizungsaktor (REG) | 0.25 h | 0.5 h pro Kanal | 0.2 h pro Kanal |
| Taster (UP) | 0.5 h | 0.5 h | 0.15 h |
| Praesenzmelder (AP/Decke) | 0.75 h | 0.5 h | 0.25 h |
| Raumthermostat (UP) | 0.5 h | 0.5 h | 0.25 h |
| Wetterstation (AP/Dach) | 1.5 h | 1.0 h | 0.5 h |
| Spannungsversorgung (REG) | 0.25 h | 0.1 h | 0.1 h |
| Linienkoppler (REG) | 0.25 h | 0.5 h | 0.25 h |

| ID | Anforderung |
|----|-------------|
| FA-1705 | Der Benutzer muss die Richtwerte pro Projekt und pro Position manuell anpassen koennen. Die angepassten Werte muessen als neue Standardwerte uebernehmbar sein. |
| FA-1706 | Das System muss den Gesamtpreis der Offerte automatisch berechnen: Summe Material (inkl. Aufschlag) + Summe Arbeitszeit (Montage + Programmierung + Inbetriebnahme) + Nebenkosten. Zusaetzlich muss ein optionaler Gesamtrabatt (% oder fix) und die MwSt. berechnet werden koennen. |

#### 3.18.2 Offert-Dokument fuer den Bauherrn

| ID | Anforderung |
|----|-------------|
| FA-1711 | Das System muss eine professionelle, handelsuebliche Kundenofferte als druckfertiges Dokument generieren koennen. Das Dokument muss folgende Bereiche enthalten: |

**Aufbau der Kundenofferte:**

| Bereich | Inhalt |
|---------|--------|
| Deckblatt | Firmenlogo, Firmenname, Offert-Nummer, Datum, Projektbezeichnung, Bauherr-Adresse |
| Begleitschreiben | Anrede, kurze Projektbeschreibung, Verweis auf beiliegende Positionsliste, Gueltigkeitsdauer der Offerte |
| Positionsliste (detailliert) | Pos.-Nr., Bezeichnung, Menge, Einheit, Einzelpreis, Gesamtpreis -- gruppiert nach Raeumen oder Gewerken |
| Zusammenfassung | Zwischensumme Material, Zwischensumme Arbeitsleistungen, Nebenkosten, Rabatt, Nettobetrag, MwSt., Gesamtbetrag |
| Konditionen | Zahlungsbedingungen, Lieferfrist, Gueltigkeitsdauer, Ausfuehrungsfristen, Vorbehalte |
| Anhang (optional) | Leistungsbeschreibung KNX-System, Prinzipschema Topologie, Funktionsuebersicht pro Raum |

| ID | Anforderung |
|----|-------------|
| FA-1712 | Die Offerte muss in zwei Detailstufen generiert werden koennen: a) **Detaillierte Offerte**: Alle Einzelpositionen mit Geraeten, Stueckzahlen, Arbeitszeiten sichtbar (fuer technisch versierte Bauherren oder Ausschreibungen), b) **Zusammenfassende Offerte**: Gruppierung nach Raeumen oder Gewerken mit Pauschalpreisen (z.B. "KNX-Installation Wohnzimmer: CHF 3'450.00"), ohne Offenlegung der Einzelpreise. |
| FA-1713 | Die Offerte muss in folgenden Formaten exportiert werden koennen: a) PDF (druckfertig, professionelles Layout), b) Excel (.xlsx, zur Weiterverarbeitung). |
| FA-1714 | Der Benutzer muss die generierten Offertpositionen vor dem Export pruefen, anpassen und ergaenzen koennen: Positionen hinzufuegen/entfernen, Texte anpassen, Preise manuell ueberschreiben, Zwischentitel und Bemerkungen einfuegen. |
| FA-1715 | Das Konditionen-Feld muss konfigurierbare Standardtexte verwenden, die global gespeichert und pro Offerte angepasst werden koennen (z.B. Zahlungsbedingungen: "30 Tage netto", Gueltigkeitsdauer: "60 Tage"). |

#### 3.18.3 Offertverwaltung

| ID | Anforderung |
|----|-------------|
| FA-1721 | Das System muss alle erstellten Kundenofferten pro Projekt verwalten und archivieren (Offert-Nummer, Datum, Version, Status, Gesamtbetrag). |
| FA-1722 | Das System muss die Versionierung von Offerten unterstuetzen: Wird eine bestehende Offerte ueberarbeitet, wird automatisch eine neue Version erstellt (z.B. Offerte OF-2026-001 Rev. A, Rev. B), wobei die vorherigen Versionen erhalten bleiben. |
| FA-1723 | Das System muss den Status einer Kundenofferte verfolgen: Entwurf, Versendet, Akzeptiert, Abgelehnt, Ueberarbeitung angefordert. |
| FA-1724 | Bei Status "Akzeptiert" muss die Offerte als Auftragsbestaetigung markiert und in die Projektdokumentation uebernommen werden koennen. |

### 3.19 Szenen-Definition (FA-1800)

| ID | Anforderung |
|----|-------------|
| FA-1801 | Das System muss die Definition von KNX-Szenen ermoeglichen. Eine Szene ist eine vordefinierte Kombination von Schaltbefehlen fuer mehrere Gewerke, die mit einem einzigen Tastendruck oder Trigger ausgeloest wird. |
| FA-1802 | Das System muss pro Raum, pro Wohnung/Zone oder projektuebergreifend (zentral) Szenen definieren koennen. Pro Szene muessen folgende Angaben erfasst werden: |

**Szenen-Definition:**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Szenen-Name | Eindeutiger, sprechender Name | "Kino" |
| Szenen-Nummer | KNX-Szenennummer (1-64 pro Szenen-Aktor) | 3 |
| Geltungsbereich | Raum / Wohnung / Zone / Zentral | Raum E01 (Wohnzimmer) |
| Ausloeser / Trigger | Taster, Zeitschaltuhr, Praesenzmelder, Zentral | Taster Eingang, Taste 4 lang |

**Szenen-Aktionen (pro Szene):**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Gewerk/GA | Betroffene Gruppenadresse | LD_E01_01 WERT |
| Aktion | Zu sendender Wert | 20% |
| Verzoegerung | Optionale Zeitverzoegerung | 0s / 2s |

| ID | Anforderung |
|----|-------------|
| FA-1803 | Das System muss vordefinierte Szenen-Vorlagen anbieten: |

**Szenen-Vorlagen (konfigurierbar):**

| Szene | Licht | Jalousie | Beschreibung |
|-------|-------|----------|-------------|
| Kino | Alle AUS oder 10% | Geschlossen, Lamellen zu | Verdunkelung fuer Filmgenuss |
| Dinner | Esstisch 60%, Rest AUS | Halb offen | Stimmungsbeleuchtung |
| Lesen | Stehleuchte 80%, Rest 30% | Offen | Lesebeleuchtung |
| Abwesenheit | Alle AUS | Geschlossen | Haus verlassen |
| Panik | Alle 100% | Alle offen | Notbeleuchtung |
| Guten Morgen | Decke 50%, Bad 100% | Offen | Sanftes Aufwachen |
| Gute Nacht | Alle AUS | Geschlossen | Schlafenszeit |
| Beschattung | Unveraendert | Automatik nach Sonnenstand | Sonnenschutz |

| ID | Anforderung |
|----|-------------|
| FA-1804 | Der Benutzer muss die Szenen-Vorlagen anpassen und eigene Szenen erstellen koennen. Pro Szene muessen beliebig viele Aktionen (Gewerk + Wert) definiert werden koennen. |
| FA-1805 | Das System muss die Szenen-Definitionen in die Gruppenadress-Struktur integrieren: Fuer jede Szene werden die entsprechenden Szenen-Gruppenadressen in der Zentralgruppe (HG 0) oder im jeweiligen Stockwerk automatisch erzeugt. |
| FA-1806 | Das System muss eine Szenen-Uebersicht pro Raum generieren koennen, die in die Projektdokumentation und die Bauherr-Bedienungsanleitung (FA-1900) einfliesst. |
| FA-1807 | Die Szenen-Definitionen muessen in das Bauherr-Funktionsdefinitions-Formular (FA-1501) integriert werden: Der Bauherr kann angeben, welche Szenen er in welchem Raum wuenscht und welche Werte (z.B. Lichtstimmung) er bevorzugt. |
| FA-1808 | Das System muss in importierten Projekten bestehende Szenen automatisch erkennen und in die Szenen-Uebersicht uebernehmen. Erkannt werden: (1) Gruppenadressen mit Datenpunkttyp 17.x (Szenennummer) oder 18.x (Szenensteuerung), unabhaengig vom Ordner und sowohl als ETS-Rohcode (KNXPROJ) als auch als Klartext (XLSX-Report); (2) Gruppenadressen in einer Mittelgruppe, deren Name "Szene" enthaelt, sofern auch die GA-Bezeichnung "Szene" enthaelt; (3) Namensmuster fuer Taster-Lichtstimmungen (z.B. "Raum1_Szene High/Middle/Low/Off" mit optionaler LED-Rueckmeldung). Datenpunkttyp 1.017 (Szene A/B) wird ausserhalb eines Szenen-Ordners bewusst nicht als Szene gewertet, da er haeufig fuer andere Zwecke verwendet wird. Erkannte Szenen werden als solche gekennzeichnet und bei der GA-Neugenerierung nicht doppelt angelegt; sie koennen in der Uebersicht bearbeitet oder geloescht werden. Aendert sich die Bezeichnung ihrer GA (Raum umbenannt oder zusammengefuehrt), fuehrt die GA-Neugenerierung den Text der Aktion nach, ebenso den Szenennamen, wenn er der GA-Bezeichnung entsprach. |
| FA-1809 | Das System muss aus dem Geraeteparameter-Abschnitt des ETS6-Topologie-Reports die Szenen-Schaltwerte der Aktorkanaele einlesen (z.B. "Kanal A schaltet bei Szene 2 auf AUS") und daraus die Aktionen der erkannten Szenen ableiten. Traegt ein zentraler Szenen-Kanal mehrere Szenennummern, muss pro konfigurierter Szenennummer eine eigene Szene entstehen. Nicht aufloesbare Kanaele werden uebersprungen. |
| FA-1810 | Das System muss aus der Tastenkonfiguration der Geraeteparameter einlesen, welche Taste welche Szenennummer sendet (z.B. "Taste 1, links sendet Szene 1"), und diese Tasten als Ausloeser der zugehoerigen Szene hinterlegen. |
| FA-1810a | Das System muss den ETS-Kommentar einer Gruppenadresse als Klartext uebernehmen (knxproj: RTF-Kommentar, GA-Report XLSX: Zeile unter der Adresse) und daraus Szenennamen einer Szenen-Adresse ableiten ("#1: Anwesend", eine Zeile je Szenennummer). Fehlende Szenennummern werden angelegt, selbst vergebene Namen bleiben erhalten. Beim Re-Import des GA-Reports bleiben DPT-Nummern und Kommentare des bisherigen Stands erhalten, wenn der Report nur Anzeigetexte ("Szenensteuerung") bzw. keinen Kommentar liefert. |
| FA-1812 | Die Szenen-Verwaltung muss wie der Szenenreport nach der Szenen-Gruppenadresse gegliedert sein (gemeinsame Einteilung): Baum mit der Adresse zuoberst und ihren Szenennummern darunter; geplante Szenen ohne generierte Adresse als kuenftige Adresse je Geltungsbereich ("wird in Schritt 10 erzeugt"); Szenen der Visualisierung und nicht eindeutige Erkennungen in eigenen, zugeklappten Abschnitten. Bei Auswahl einer Adresse: Adresse, DPT, Kommentar, verknuepfte Geraete und Geltungsbereich, der fuer alle Szenen der Adresse gilt. Bei Auswahl einer Szene: Name, Nummer (eindeutig je Adresse), Ausloeser, Aktionen und - bei selbst angelegten Szenen - die Szenen-Adresse zum Verschieben. Neue Szenen-Adressen werden ueber den Geltungsbereich angelegt, weitere Szenen mit der naechsten freien Nummer. |
| FA-1812a | Geltungsbereich einer Szenen-Adresse: ein Auswahlfeld "Gilt fuer" (Zentral, jede Zone einmal - bei Nebengebaeuden mit Gebaeudename -, Raeume). Eine Zone ueber mehrere Stockwerke ist ein Geltungsbereich mit einer gemeinsamen Szenen-GA. Bei einer bestehenden Szenen-GA eines geplanten Projekts fragt das System, ob sie in Schritt 10 als Szenen-GA des neuen Geltungsbereichs neu erzeugt werden soll (Szenen werden geloest, die bisherige GA entfaellt) oder der Geltungsbereich nur Beschriftung ist; bei importierten Projekten bleibt die GA. Feste Zentraladressen (Alle Lichter, Jalousien, Szene Abwesenheit) behalten beim Neuerzeugen eine vom Integrator vergebene Bezeichnung. |
| FA-1811 | Das System muss einen Szenenreport erzeugen, gegliedert nach der Szenen-Gruppenadresse (sie uebertraegt die Szenennummer, die Aktoren sind mit ihr verknuepft): Uebersicht der Szenen-Adressen mit ihren Szenen und Seitenzahl; je Adresse Geltungsbereich, DPT (Hinweis, wenn nicht 17.001/18.001), verknuepfte Geraete mit ihren Objekten - Sender (Taster, Sensoren, Visualisierung) und Empfaenger (Aktoren, Gateways), unterschieden ueber die Flags Uebertragen/Schreiben - und bestaetigte Gewerke, darunter eine Zeile je Szenennummer mit Name, ausloesenden Tastern und Aktionen. Szenennummern werden durchgehend 1-64 angezeigt (auf dem Bus Bytewert 0-63). Hinweis, wenn Aktionen hinterlegt, aber kein Aktor mit der Adresse verknuepft ist. Eigene Abschnitte: Szenen der Visualisierung ueber einzelne Schalt-Adressen (z.B. UniPro H/M/L/0, keine KNX-Szenenadressen), "Nicht eindeutig" fuer erkannte Adressen ohne Szenen-DPT und ohne Szenennummern (zur Fehlersuche), geplante Szenen ohne generierte Adresse. |

### 3.20 Abnahmeprotokoll und Inbetriebnahme (FA-1900)

#### 3.20.1 Inbetriebnahme-Checkliste

| ID | Anforderung |
|----|-------------|
| FA-1901 | Das System muss eine automatisch generierte Inbetriebnahme-Checkliste pro Raum erstellen koennen. Die Checkliste basiert auf den definierten Gewerken, Sensoren, Aktoren und Szenen des jeweiligen Raums. |
| FA-1902 | Pro Gewerk-Element/Funktion muss die Checkliste folgende Pruefpunkte enthalten: |

**Pruefpunkte der Inbetriebnahme-Checkliste:**

| Pruefpunkt | Beschreibung | Ergebnis |
|------------|-------------|----------|
| Montage geprueft | Geraet korrekt montiert und beschriftet | OK / Mangel |
| Busverbindung | KNX-Busteilnehmer erreichbar, physikalische Adresse korrekt | OK / Mangel |
| Funktion Schalten | Ein/Aus-Funktion des Gewerks getestet | OK / Mangel |
| Funktion Dimmen/Positionieren | Dimmen/Jalousieposition getestet (wo zutreffend) | OK / Mangel |
| Rueckmeldung | Statusrueckmeldung korrekt (wo zutreffend) | OK / Mangel |
| Szenen | Szenenabruf getestet (wo zutreffend) | OK / Mangel |
| Sensorzuordnung | Taster/Sensor steuert korrekte Funktion | OK / Mangel |
| Beschattungsautomatik | Automatische Beschattung getestet (wo zutreffend) | OK / Mangel |

| ID | Anforderung |
|----|-------------|
| FA-1903 | Die Checkliste muss als druckbares Dokument (PDF) exportiert werden koennen, damit sie waehrend der Inbetriebnahme vor Ort auf Papier ausgefuellt werden kann. |
| FA-1904 | Die Checkliste muss alternativ als Excel-Datei exportiert werden koennen, damit sie digital auf einem Tablet ausgefuellt werden kann. |
| FA-1905 | Die ausgefuellte Checkliste (Excel) muss wieder eingelesen werden koennen, um die Ergebnisse im Projekt zu dokumentieren. |

#### 3.20.2 Abnahmeprotokoll

| ID | Anforderung |
|----|-------------|
| FA-1911 | Das System muss basierend auf der ausgefuellten Inbetriebnahme-Checkliste ein formelles Abnahmeprotokoll generieren koennen. Das Protokoll muss folgende Bereiche enthalten: |

**Aufbau des Abnahmeprotokolls:**

| Bereich | Inhalt |
|---------|--------|
| Kopfbereich | Firmenlogo, Projektname, Projektnummer, Projektadresse, Datum der Abnahme |
| Beteiligte | Name und Funktion des Systemintegrators, Name des Bauherrn/Vertreters |
| Anlagenbeschreibung | Kurzuebersicht: Anzahl Bereiche, Linien, Geraete, Gruppenadressen, installierte Gewerke |
| Pruefergebnis pro Raum | Zusammenfassung der Checklisten-Ergebnisse: Alle OK / Anzahl Maengel |
| Maengelliste | Detaillierte Auflistung aller festgestellten Maengel mit: Raum, Gewerk, Beschreibung, Prioritaet (kritisch/unkritisch), vereinbarter Behebungstermin |
| Gesamtergebnis | Abnahme erfolgt / Abnahme unter Vorbehalt (mit Maengelliste) / Abnahme verweigert |
| Unterschriften | Unterschriftsfelder fuer Systemintegrator und Bauherr mit Datum |
| Anhang | Referenz auf Inbetriebnahme-Checklisten, Prinzipschema, Funktionsuebersicht |

| ID | Anforderung |
|----|-------------|
| FA-1912 | Das Abnahmeprotokoll muss als PDF exportiert werden koennen (druckfertig, professionelles Layout mit Firmenlogo und Unterschriftsfeldern). |
| FA-1913 | Das System muss eine Maengelliste fuehren koennen: Jeder Mangel erhaelt eine Nummer, einen Status (offen / in Bearbeitung / behoben) und ein Behebungsdatum. |
| FA-1914 | Bei Abnahme unter Vorbehalt muss das System eine Nachkontrolle ermoeglichen: Die behobenen Maengel werden nachgeprueft und ein Nachtrags-Abnahmeprotokoll generiert. |

### 3.21 Bauherr-Bedienungsanleitung (FA-2000)

| ID | Anforderung |
|----|-------------|
| FA-2001 | Das System muss eine projektspezifische Bedienungsanleitung fuer den Bauherrn automatisch generieren koennen. Die Anleitung beschreibt in einfacher, nicht-technischer Sprache, welche Funktionen in jedem Raum verfuegbar sind und wie sie bedient werden. |
| FA-2002 | Die Bedienungsanleitung muss pro Raum folgende Informationen enthalten: |

**Inhalt der Bedienungsanleitung pro Raum:**

| Bereich | Inhalt | Beispiel |
|---------|--------|---------|
| Raumbezeichnung | Name und Nummer des Raums | "Wohnzimmer (E01)" |
| Uebersichtsgrafik | Schematische Darstellung der Bedienstellen im Raum (optional) | Grundriss mit markierten Tastern |
| Taster/Sensoren | Liste aller Bedienstellen mit Beschreibung jeder Taste | "Taster Eingang, Taste 1: Deckenlicht ein/aus" |
| Lichtszenen | Verfuegbare Szenen mit Kurzbeschreibung | "Taste 4 lang: Szene Kino (gedimmtes Licht, Jalousien zu)" |
| Jalousie/Beschattung | Bedienung und automatische Funktionen | "Taste 2: Jalousie auf/ab, Automatik bei Sonneneinstrahlung" |
| Heizung/Klima | Thermostat-Bedienung, Betriebsarten | "Raumthermostat: Drehrad fuer Sollwert, Komfort/Eco-Umschaltung" |
| Besonderheiten | Spezielle Funktionen im Raum | "Praesenzmelder schaltet Licht nach 15 Min. aus" |

| ID | Anforderung |
|----|-------------|
| FA-2003 | Die Bedienungsanleitung muss einen allgemeinen Teil enthalten: a) Kurzerklaerung des KNX-Systems (was ist KNX, wie funktioniert es -- in Laiensprache), b) Zentrale Funktionen (Alles AUS, Panik, Abwesenheit), c) Hinweise bei Stoerungen (z.B. "Licht reagiert nicht" -> Sicherung pruefen, Systemintegrator kontaktieren), d) Kontaktdaten des Systemintegrators (aus Firmenprofil FA-851). |
| FA-2004 | Die Bedienungsanleitung muss als professionelles PDF-Dokument exportiert werden koennen, mit Firmenlogo, Inhaltsverzeichnis und Seitennummerierung. |
| FA-2005 | Der Benutzer muss die generierten Texte vor dem Export pruefen und anpassen koennen: Formulierungen aendern, Abschnitte hinzufuegen/entfernen, Bilder/Fotos einfuegen (z.B. Fotos der installierten Taster). Umsetzung: Berichte -> "Anleitung anpassen..." je Projekt: eigene Texte fuer Einleitung, "Ihr Haus in Kuerze", Bedientipps und "Wenn etwas nicht funktioniert" (leer = Standardtext); Abschnitte ein-/ausblenden (Ihr Haus in Kuerze, Bedientipps, Zentrale Funktionen, Stoerungen, Ansprechpartner, Szenen je Taster, Automatische Funktionen je Raum); eigene Abschnitte mit Titel und Text im Teil Allgemeines; Zusatztext je Raum (Raumschluessel Stockwerk|Raumnummer, uebersteht Neuaufbau); Foto je Taster rechts neben dem Tastenplan (Schluessel physikalische Adresse bzw. Raum + Nummer der Tastereinheit; das Foto wird in den Projektordner "Fotos" kopiert). |
| FA-2006 | Das System muss Textbausteine fuer die Bedienungsanleitung in den Sprachdateien (NFA-152) fuehren, sodass die Anleitung in der Sprache des Bauherrn generiert werden kann. Umsetzung: Deutsch, Franzoesisch, Italienisch und Englisch. Textbausteine in i18n/manual_<sprache>.json: feste Texte mit Schluessel (Ueberschriften, Einleitung, Tipps, Stoerungen, Tabellenkoepfe, Kopf/Fuss) und eine Phrasenliste fuer die automatisch erzeugten Bedienungstexte (z.B. "kurz druecken: Ein"). Sprache je Projekt in "Anleitung anpassen..."; Datum nach Sprachregion (NFA-156). Projektdaten (Raumnamen, Bezeichnungen und Szenennamen aus der ETS) bleiben, wie sie erfasst sind. |

### 3.22 Revisionsunterlagen / As-Built-Dokumentation (FA-2100)

| ID | Anforderung |
|----|-------------|
| FA-2101 | Das System muss ein vollstaendiges Revisionsunterlagen-Paket (As-Built-Dokumentation) als zusammenhaengendes Dokument oder als strukturierte Dokumentensammlung generieren koennen. Dieses Paket dient als Abschlussdokumentation des KNX-Projekts fuer den Bauherrn. |
| FA-2102 | Die Revisionsunterlagen muessen folgende Bestandteile enthalten (einzeln oder als Gesamtdokument): |

**Bestandteile der Revisionsunterlagen:**

| Nr. | Dokument | Quelle | Beschreibung |
|-----|----------|--------|-------------|
| 1 | Deckblatt | FA-855 | Projekt- und Firmenangaben |
| 2 | Inhaltsverzeichnis | Automatisch | Uebersicht aller enthaltenen Dokumente |
| 3 | Anlagenbeschreibung | FA-903 | Projektzusammenfassung, Statistik, Systemuebersicht |
| 4 | Topologie-Prinzipschema | FA-904 | Grafische Darstellung der KNX-Topologie |
| 5 | Gruppenadress-Liste | FA-801 | Vollstaendige GA-Struktur mit Bezeichnungen und DPTs |
| 6 | Geraete-Liste | FA-1306, FA-1405 | Alle Aktoren und Sensoren mit Hersteller, Bestellnummer, Einbauort |
| 7 | Funktionszuordnung | FA-1506 | Welcher Sensor steuert welche Funktion |
| 8 | Szenen-Uebersicht | FA-1806 | Alle definierten Szenen pro Raum |
| 9 | Produktdatenblaetter | FA-1204 | Datenblaetter aller verbauten Geraete |
| 10 | Abnahmeprotokoll | FA-1912 | Formelles Abnahmeprotokoll mit Ergebnis |
| 11 | Bauherr-Bedienungsanleitung | FA-2004 | Projektspezifische Bedienungsanleitung |
| 12 | Materialliste | FA-1406 | Vollstaendige Stueckliste aller Komponenten |
| 13 | Kundenofferte (akzeptiert) | FA-1724 | Die akzeptierte Offerte als Auftragsreferenz |

| ID | Anforderung |
|----|-------------|
| FA-2103 | Das Revisionsunterlagen-Paket muss als einzelnes PDF-Dokument (mit Inhaltsverzeichnis und durchgehender Seitennummerierung) oder als ZIP-Archiv mit einzelnen PDF-Dateien exportiert werden koennen. |
| FA-2104 | Das System muss die Vollstaendigkeit der Revisionsunterlagen pruefen und fehlende Bestandteile anzeigen (z.B. "Abnahmeprotokoll fehlt noch", "Produktdatenblatt fuer Geraet X fehlt"). Umsetzung: Vor dem Erstellen des Revisionspakets Rueckfrage mit den offenen Punkten (Firmenprofil, Topologie, Gruppenadressen, Geraete ohne Produkt, fehlende Produktdatenblaetter je Produkt, Bedienelemente ohne Funktion, Abnahmeentscheid, offene Maengel, offene Pruefpunkte, Materialliste); dieselben Punkte stehen im Inhaltsverzeichnis. Die Materialliste (Excel) ist Teil des Pakets. |
| FA-2105 | Der Benutzer muss einzelne Bestandteile ein-/ausschliessen koennen (z.B. Kundenofferte aus Vertraulichkeitsgruenden weglassen). Umsetzung: Dialog "Revisionspaket erstellen" mit allen Bestandteilen zum An-/Abwaehlen; Bestandteile ohne Daten entfallen automatisch. Die akzeptierte Kundenofferte (Offert-Brief) ist waehlbar, sobald eine Offerte den Status "Akzeptiert" hat. |
| FA-2106 | Die Revisionsunterlagen muessen mit einem Revisionsdatum und einer Versionsnummer versehen werden. Bei nachtraeglichen Aenderungen (z.B. Erweiterung der Anlage) muss eine neue Revision erstellt werden koennen. Umsetzung: Revisionsbezeichnung (Vorschlag A, B, C ...), Revisionsdatum und Anlass; jede Revision in eigenem Ordner Revisionen/Rev_X mit der Revision im Dateinamen. Die Revisionen werden im Projekt gefuehrt und im Inhaltsverzeichnis als fruehere Revisionen aufgefuehrt; dieselbe Bezeichnung erneut erstellt ersetzt den Stand (nach Rueckfrage). |

### 3.23 Nachkalkulation (FA-2200)

| ID | Anforderung |
|----|-------------|
| FA-2201 | Das System muss eine Nachkalkulation ermoeglichen, die den Vergleich zwischen Offerte (Soll) und tatsaechlichen Kosten (Ist) nach Projektabschluss darstellt. |
| FA-2202 | Das System muss die Erfassung der tatsaechlichen Kosten pro Kategorie ermoeglichen: |

**Nachkalkulations-Kategorien:**

| Kategorie | Soll (aus Offerte) | Ist (tatsaechlich) | Abweichung |
|-----------|-------------------|--------------------|-----------|
| Material gesamt | CHF aus FA-1706 | Tatsaechliche Einkaufskosten | +/- CHF und % |
| Montage (Stunden) | h aus FA-1704 | Tatsaechlich geleistete h | +/- h und % |
| Programmierung (Stunden) | h aus FA-1704 | Tatsaechlich geleistete h | +/- h und % |
| Inbetriebnahme (Stunden) | h aus FA-1704 | Tatsaechlich geleistete h | +/- h und % |
| Nebenkosten | CHF aus FA-1706 | Tatsaechliche Nebenkosten | +/- CHF und % |
| **Gesamtkosten** | **CHF Offertbetrag** | **CHF Ist-Kosten** | **+/- CHF und %** |
| **Marge** | Geplante Marge | Tatsaechliche Marge | +/- CHF und % |

| ID | Anforderung |
|----|-------------|
| FA-2203 | Das System muss die Ist-Stunden komfortabel erfassen koennen: a) Manuelle Eingabe pro Kategorie (Montage, Programmierung, Inbetriebnahme), b) Optional: Tagesrapport-Erfassung (Datum, Mitarbeiter, Stunden, Taetigkeit). |
| FA-2204 | Das System muss den Nachkalkulationsbericht als druckbares Dokument (PDF) generieren koennen mit: Soll-Ist-Vergleich pro Kategorie, grafischer Darstellung (Balkendiagramm Soll vs. Ist), Abweichungsanalyse (groesste Abweichungen hervorgehoben), Erkenntnisse/Bemerkungen (Freitextfeld). |
| FA-2205 | Das System muss die Richtwerte fuer den Zeitaufwand (FA-1704) auf Basis der Nachkalkulation optimieren koennen: Das System schlaegt angepasste Richtwerte vor, basierend auf den tatsaechlichen Durchschnittswerten abgeschlossener Projekte. Umsetzung: In der Auswertung aller Projekte Vorschlaege fuer die Minuten je Geraet (Programmierung, Inbetriebnahme, Dokumentation): (Ist-Stunden - Sockel) x 60 / Busgeraete, gemittelt ueber mindestens zwei Projekte; "Vorschlaege uebernehmen" schreibt sie nach Rueckfrage ins Firmenprofil. Montage hat keinen Richtwert je Geraet und bleibt ausgenommen. |
| FA-2206 | Das System muss eine projektuebergreifende Nachkalkulationsauswertung ermoeglichen: Durchschnittliche Marge ueber alle Projekte, haeufigste Kalkulationsabweichungen, Trend-Entwicklung ueber die Zeit. Umsetzung: Kundenofferte -> Nachkalkulation -> "Auswertung aller Projekte...": akzeptierte Offerten mit Ist-Werten im geoeffneten Projekt, im Arbeitsverzeichnis und in den zuletzt geoeffneten Projekten. Marge geplant und Ist (umsatzgewichtet; Offertbetrag netto minus Material zum Einkauf und Stunden zu den Offertsaetzen), Abweichungen je Kategorie (mittlere Abweichung, Anzahl Projekte ueber +/-10 %), Verlauf: Projekte nach Datum und Vergleich aeltere/neuere Haelfte. |

---

### 3.24 Materialliste (FA-2300)

Die Materialliste erfasst alle KNX-Geraete des Projekts -- Aktoren, Sensoren und
Infrastruktur-Komponenten -- mit Hersteller, Bestellnummer und Menge. Sie dient
als Grundlage fuer Offertanfragen und Revisionsunterlagen.

**Datenquelle fuer die Produktauswahl:**
- Nur zertifizierte KNX-Geraete duerfen ausgewaehlt werden (Produktkatalog-Eintraege)
- Lokaler Basiskatalog mit gaengigen Geraeten (JSON, wird mit der Software mitgeliefert)
- Erweiterbar durch Import offizieller Hersteller-Produktdatenbankdateien (.knxprod)
- Keine freie Texteingabe fuer Produktdaten -- nur Katalogprodukte sind auswaehlbar

**Kategorien in der Materialliste:**
Aktor | Sensor | Linienkoppler | Bereichskoppler | IP-Router | Netzteil | DALI-Gateway | Sonstiges

#### FA-2301 -- Datenmodell Materialliste **(M)**

| ID | Anforderung |
|----|-------------|
| FA-2301 | Das System muss eine persistente Materialliste pro Projekt fuhren, die folgende Felder pro Position enthaelt: Menge, Kategorie, Geraetetyp, Hersteller, Bestellnummer, Produktname, Einheitspreis (optional), Quelle (Wizard-automatisch oder manuell), Bemerkung. Die Materialliste wird im Projektformat (.knxarr) gespeichert und geladen. |

#### FA-2302 -- Materiallisten-Ansicht **(M)**

| ID | Anforderung |
|----|-------------|
| FA-2302 | Das System muss eine dedizierte Materiallisten-Ansicht bereitstellen (Sidebar-Eintrag "Materialliste"), die alle Positionen in einer Tabelle darstellt. Die Ansicht muss enthalten: Spalten Menge, Kategorie, Typ, Hersteller, Bestellnummer, Produktname, Quelle; Filter nach Kategorie; Gesamtanzahl Positionen und Geraete; visuelle Unterscheidung von automatisch (Wizard) und manuell erfassten Positionen. |
| FA-2306 | Der Benutzer muss Positionen aus der Materialliste entfernen koennen (mit Rueckfrage). Die Menge einer Position muss per Doppelklick direkt in der Tabelle aenderbar sein. |

#### FA-2303 -- Produktauswahl aus Katalog **(M)**

| ID | Anforderung |
|----|-------------|
| FA-2303 | Das System muss einen Produktauswahl-Dialog bereitstellen, der alle Geraete im lokalen Katalog anzeigt und filterbar macht (Kategorie, Hersteller, Freitextsuche ueber Produktname und Bestellnummer). Bevorzugte Hersteller (gemaess Projektkonfiguration) werden fett hervorgehoben und an den Anfang sortiert. Nur Produkte aus dem Katalog koennen ausgewaehlt werden -- keine Freitext-Erfassung. |
| FA-2305 | Das System muss in den Wizard-Schritten 6 (Aktoren) und 8 (Sensoren) einen Button "In Projekt-Materialliste uebernehmen" bereitstellen, der die berechneten Geraete automatisch als Positionen in die Materialliste eintraegt (Quelle: "wizard_auto"). Bei erneutem Aufruf werden bestehende Wizard-Eintraege derselben Kategorie ersetzt. |

#### FA-2304 -- KNXPROD-Import **(S)**

| ID | Anforderung |
|----|-------------|
| FA-2304 | Das System muss .knxprod-Dateien (Hersteller-Produktdatenbankdateien im KNX-Standard) importieren koennen. Eine .knxprod-Datei ist ein ZIP-Archiv mit XML-Struktur (Hardware.xml, Catalog.xml). Das System liest Hersteller, Bestellnummer, Produktname und Kanalanzahl aus und nimmt diese als neue Produkte in den lokalen Katalog auf. Die importierten Produkte stehen sofort in der Produktauswahl zur Verfuegung. Der Import ist erreichbar ueber: Menuepunkt "Datei -> Produktkatalog KNXPROD importieren..." sowie direkt im Produktauswahl-Dialog. |
| FA-2304a | Die Kommunikationsobjekte eines Produkts muessen ueber die Zuordnung Produkt -> Applikationsprogramm aufgeloest werden. Fehlt die Zuordnung in Catalog.xml (z.B. bei aus einem .knxproj extrahierten Herstellerdateien), muss die Zuordnung aus Hardware.xml verwendet werden, sofern sie eindeutig ist. Liefern weder Hardware.xml noch der Katalogbaum eine Kategorie, wird sie aus dem Produktnamen abgeleitet (z.B. Gateway/Schnittstelle -> Infrastruktur, Taster-/Fensterschnittstelle -> Sensor). Dasselbe Produkt muss unabhaengig von der Importquelle dieselben Kommunikationsobjekte erhalten. |
| FA-2304b | Per Parameter umschaltbare Varianten desselben Kommunikationsobjekts, die sich nur in der Objektgroesse unterscheiden, muessen als ein Objekt gefuehrt werden, damit der GA-Bedarf nicht vervielfacht wird. |
| FA-2304c | Der Anwender muss den GA-Bedarf einer Materiallisten-Position von Hand festlegen und wieder auf den Wert aus der KNXPROD-Datei zuruecksetzen koennen (z.B. fuer frei belegbare Gateways, deren KNXPROD nur generische Objektplaetze enthaelt). Der manuelle Wert wird im Projekt gespeichert, als solcher gekennzeichnet und bleibt beim Neuaufbau der Materialliste aus der Topologie erhalten; bei Zuweisung eines anderen Produkts wird er verworfen. |
| FA-2304d | Hersteller werden ueber die KNX-Hersteller-ID (M-XXXX) identifiziert. Das System fuehrt die offizielle KNX-Herstellerliste (aus knx_master.xml, aktualisierbar) und zeigt fuer jeden Hersteller einen einheitlichen Namen an, unabhaengig von der Schreibweise der Quelle (ETS-Import, KNXPROD-Datei, Online-Katalog, aeltere Projekte). Hersteller mit eigener ID (z.B. ABB und Busch-Jaeger) bleiben getrennt. Bestehende Projekte und Kataloge werden beim Laden vereinheitlicht. |
| FA-2304e | Produkte werden ueber Hersteller-ID und Bestellnummer abgeglichen; Leerzeichen, Punkte und Gross-/Kleinschreibung der Bestellnummer sind dabei unerheblich. Bei Platzhalter-Bestellnummern (leer oder "Dummy") gehoert der Produktname zum Schluessel, damit verschiedene Platzhalterprodukte (z.B. Hilfsgeraete fuer die GA-Filter der Linienkoppler) erhalten bleiben. Aus ETS importierte Geraete finden so ihren Katalogeintrag. |
| FA-2304f | Katalog und Geraete fuehren die ETS-Kennungen des Produkts (ProductRefId, Hardware2ProgramRefId, Applikationsprogramm-ID) aus KNXPROD- und ETS-Import. Vorhandene Katalogeintraege koennen aus KNXPROD-Dateien um die Kennungen ergaenzt werden, ohne andere Angaben zu veraendern. |

#### FA-2307 -- Materialliste Export **(S)**

| ID | Anforderung |
|----|-------------|
| FA-2307 | Das System muss die Materialliste als Excel-Datei (.xlsx) exportieren koennen mit: Projektbezeichnung, Tabelle aller Positionen (Menge, Kategorie, Typ, Hersteller, Bestellnummer, Produktname, Gesamtanzahl, Preis falls vorhanden). |
| FA-2308 | Die Materialliste muss als Bestandteil der Revisionsunterlagen (FA-2100) und der Kundenofferte (FA-1700) eingebunden werden koennen. |

### 3.25 KNXPROJ-Export (FA-2400)

> **Entfallen (25.09.2026).** ETS6 importiert nur Projektdateien mit gueltiger Projektsignatur (P-XXXX.signature/.certificate), die ausschliesslich ETS selbst mit dem Schluessel seiner Lizenz erzeugt. Mit ETS6 getestet und jeweils mit "Projektdatei hat keine gueltige Signatur" abgelehnt: Export im ETS6-Format (mit und ohne eingebettete, signierte Herstellerdaten), Export im ETS5-Format und Basis-Projekt-Modus (Signatur, Zertifikat und Herstellerdaten eines echten ETS6-Projekts unveraendert uebernommen, nur Projektinhalt neu). Der Export wurde deshalb aus der Anwendung entfernt. Weg nach ETS6: CSV-Gruppenadress-Export (FA-801); Geraete und Topologie werden in ETS angelegt. Eine Geraeteuebergabe waere nur ueber eine ETS-App (vgl. FA-3101 bis FA-3104) moeglich. Die Anforderungen bleiben zur Nachvollziehbarkeit stehen.

| ID | Anforderung |
|----|-------------|
| FA-2401 | **Entfallen (25.09.2026, siehe 3.25).** Das System muss die vollstaendige Projektstruktur als natives ETS-Projektformat (.knxproj) exportieren koennen. Das .knxproj-Format ist ein ZIP-Archiv mit XML-Dateien gemaess KNX-Standard (ETS6-Formatversion). **(S)** |
| FA-2402 | **Entfallen (25.09.2026, siehe 3.25).** Der KNXPROJ-Export muss folgende Projektbestandteile enthalten: Projektmetadaten (Name, Beschreibung, Datum), Gebaeudestruktur (Gebaeude, Fluegel, Stockwerke, Raeume), vollstaendige Gruppenadress-Hierarchie (Hauptgruppen, Mittelgruppen, Untergruppen mit Bezeichnung, DPT, Flags: Central, Unfiltered, Security), KNX-Topologie (Bereiche, Linien, Koppler mit physikalischen Adressen B.L.0). **(S)** |
| FA-2403 | **Entfallen (25.09.2026, siehe 3.25).** Fuer Geraete, die im Projekt aus dem lokalen Katalog (FA-2303) oder per KNXPROD-Import (FA-2304) bekannt sind, muss der Export die Geraete-Definitionen (Hersteller, Bestellnummer, physikalische Adresse, Einbauort) in die Topologie-Struktur der .knxproj-Datei einbetten. Applikationsprogramme koennen nicht automatisch generiert werden und muessen weiterhin in ETS geladen werden. **(S)** |
| FA-2404 | **Entfallen (25.09.2026, siehe 3.25).** CO-zu-GA-Verknuepfungen (FA-3000) muessen, sofern vorhanden, in den KNXPROJ-Export eingebunden werden, so dass in ETS die Kommunikationsobjekte bereits mit den korrekten Gruppenadressen verknuepft sind und keine manuelle Verlinkung mehr notwendig ist. **(S)** |
| FA-2405 | **Entfallen (25.09.2026, siehe 3.25).** Das System muss dem Benutzer vor dem Export eine Vollstaendigkeitsanzeige praesentieren: Welche Bestandteile sind im Export enthalten, welche fehlen (z.B. "Applikationsprogramme: nicht enthalten -- Geraete muessen in ETS programmiert werden", "CO-Verknuepfungen: 47 von 52 verknuepft"). **(S)** |
| FA-2406 | **Entfallen (25.09.2026, siehe 3.25).** Das System muss vor dem Export pruefen, ob alle zwingenden Felder vorhanden sind (Projektname, mindestens eine Gruppenadresse, mindestens eine Linie), und bei fehlenden Daten eine Warnung mit konkretem Hinweis ausgeben. Der Export muss trotz Warnungen nach Benutzerbestaetigung durchgefuehrt werden koennen. **(S)** |
| FA-2407 | Das System muss die Projektdaten (0.xml) einer .knxproj-Datei fuer Partnerprogramme als XML-Datei speichern koennen (Datei → "ETS-Projektdaten als XML speichern"), auch aus passwortgeschuetzten ETS6-Projekten (Passwortabfrage wie beim Import, FA-525c). Die XML bleibt unveraendert bis auf die entfernten Schluessel und Passwoerter: Attribute, deren Name auf "Key" endet oder "Password" bzw. "AuthenticationCode" enthaelt, sowie "FDSK" (z.B. BCUKey, ToolKey, LoadedToolKey, Gruppenschluessel Key). Die Statusleiste nennt die entfernten Attribute. Es ist das Original aus der ETS, ohne Aenderungen aus KNiX. **(S)** |

---

### 3.26 Sensor-Aktor-Verknuepfungsmatrix (FA-2500)

| ID | Anforderung |
|----|-------------|
| FA-2501 | Das System muss eine visuelle Sensor-Aktor-Verknuepfungsmatrix bereitstellen. Die Matrix zeigt fuer jeden Sensor (Taster, Praesenzmelder etc.) und jeden seiner Tasten/Kanaele, welche Gruppenadresse/Funktion ausgeloest wird. Die Matrix ist wahlweise pro Raum, pro Stockwerk oder fuer das gesamte Projekt anzeigbar. **(S)** |
| FA-2502 | Die Matrix muss folgende Dimensionen abbilden: Zeilen = Sensor-Bedienstellen (Geraet + Taste/Kanal, z.B. "Taster EG01 -- Taste 1 oben"), Spalten = ausloesbarer Funktion/Gruppenadresse (Schaltadresse, Dimmadresse, Jalousie-Adresse, Szene). Pro Zelle wird der zugewiesene Wert angezeigt (z.B. "EIN", "AUS", "Szene 3"). Nicht belegte Zellen bleiben leer. **(S)** |
| FA-2503 | Die Verknuepfungsmatrix ist die Uebersicht; bearbeitet wird in der Bauherren-Beratung (FA-1500). Ein Doppelklick auf eine Bedienstelle oeffnet deren Taster in der Bauherren-Beratung. Dort muessen je Taste Gewerk, Szene, freier Wunsch oder eine Gruppenadresse gewaehlt, zusaetzliche Gruppenadressen ergaenzt und ein langer Tastendruck ergaenzt werden koennen (Mehrfachbelegung, z.B. kurz = Einzelfunktion, lang = Szene). Ein langer Tastendruck gehoert zu seiner Taste, zaehlt nicht als eigene Taste und heisst wie in der ETS "<Taste> (langer Tastendruck)"; aus der ETS importierte lange Tastendruecke erscheinen unter ihrer Taste. Eine Taste ohne Gruppenadresse bleibt als offene Taste an ihrem Platz. **(S)** |
| FA-2504 | Die Verknuepfungsmatrix muss mit den Funktionsdefinitionen aus dem Bauherr-Formular (FA-1500) bidirektional synchronisiert sein: Importierte Bauherr-Antworten werden automatisch in die Matrix uebertragen; Aenderungen in der Matrix werden in das Bauherr-Formular rueckgeschrieben. **(S)** |
| FA-2505 | Die Verknuepfungsmatrix muss als druckbares Dokument (PDF) und als Excel-Datei exportiert werden koennen. Sie fliesst automatisch in die Funktionsdefinitions-Dokumentation (FA-1506) und die Revisionsunterlagen (FA-2100) ein. **(S)** |

---

### 3.27 Leitungslaengenberechnung (FA-2600)

| ID | Anforderung |
|----|-------------|
| FA-2601 | Das System muss die Erfassung von Leitungslaengen pro KNX-Linie ermoeglichen. Pro Linie koennen folgende Angaben erfasst werden: Laenge der Hauptleitung (Stamm in Meter), Anzahl und Laenge der Abzweigleitungen (Stichleitungen je Abzweigpunkt in Meter), Topologieform (Linie, Stern, Baum). **(S)** |
| FA-2602 | Das System muss die erfassten Leitungslaengen gegen die KNX-TP-Grenzwerte pruefen: |

**KNX TP Leitungslaengen-Grenzwerte (gemaess KNX TP-Topologie Kap. 5):**

| Parameter | Grenzwert (Fehler) | Warnung ab |
|-----------|-------------------|------------|
| Gesamtlaenge pro Linie | max. 1000 m | > 800 m |
| Hauptleitung (Stamm) | max. 700 m | > 560 m |
| Einzelne Stichleitung | max. 10 m | > 8 m |
| Abstand zwischen zwei Geraeten | mind. 200 mm | < 200 mm |

| ID | Anforderung |
|----|-------------|
| FA-2603 | Das System muss bei Ueberschreitung der Grenzwerte farblich hervorgehobene Warnungen (Gelb) und Fehlermeldungen (Rot) anzeigen -- analog zur Geraeteanzahl-Validierung (FA-609). Die Meldungen werden im Validierungsbericht (FA-901) und im Topologie-Prinzipschema (FA-904) aufgefuehrt. **(S)** |
| FA-2604 | Das System muss eine Zusammenfassung der Leitungslaengen pro Linie anzeigen: Topologieform, Gesamtlaenge, Anzahl Abzweigpunkte, Status (OK / Warnung / Fehler). Diese Uebersicht fliesst in die Revisionsunterlagen (FA-2100) ein. **(S)** |

---

### 3.28 KNX Secure (FA-2700)

| ID | Anforderung |
|----|-------------|
| FA-2701 | Das System muss KNX Secure-Projekte unterstuetzen (TP Secure und IP Secure gemaess KNX-Standard ISO 22510). Die Secure-Konfiguration wird pro Projekt aktivierbar sein und betrifft Gruppenadress-Sicherheit und physikalische Adressvergabe. **(C)** |
| FA-2702 | Das System muss pro Projekt folgende KNX Secure-Schluessel verwalten koennen: |

**KNX Secure -- Schluesseltypen:**

| Schluesseltyp | Beschreibung | Scope |
|--------------|-------------|-------|
| Backbone Key | Schluessel fuer die Bereichs-/Backbone-Linie | Gesamtprojekt |
| Line Key | Schluessel pro KNX-TP-Linie | Pro Linie |
| Device Authentication Code (DAC) | Geraete-Authentifizierungscode, ab Werk gesetzt | Pro Geraet |
| Tool Key | Schluessel fuer ETS-Programmierzugriff | Pro Geraet |
| Individual Address Write Key | Schluessel fuer physikalische Adressvergabe | Pro Geraet |

| ID | Anforderung |
|----|-------------|
| FA-2703 | Das System muss fuer jede Gruppenadresse die Secure-Konfiguration (Feld "Security" gemaess FA-802) mit den Werten Auto / Ein / Aus verwalten koennen. Bei aktiviertem KNX Secure muss das System automatisch alle sicherheitsrelevanten Gruppenadressen (Schalten, Szenen, Zentralfunktionen) als "Ein" vorschlagen. **(C)** |
| FA-2704 | Das System muss eine Secure-Geraetekompatibilitaetsliste fuehren: Fuer jedes Geraet im Projekt wird auf Basis der KNXPROD-Daten (FA-2304) angezeigt, ob es KNX Secure unterstuetzt. Nicht-Secure-faehige Geraete werden in der Topologie-Ansicht farblich markiert. **(C)** |
| FA-2705 | Das System muss eine Secure-Kompatibilitaetspruefung durchfuehren und warnen, wenn eine Linie gemischte Geraete enthaelt (Secure und Non-Secure), da dies die Sicherheit der gesamten Linie kompromittiert. Die Warnung benennt die betroffenen Geraete konkret. **(C)** |
| FA-2706 | Schluesselinformationen muessen im Projektformat (.knxarr) verschluesselt gespeichert werden (AES-128 oder gleichwertig). Die Einbettung in den KNXPROJ-Export (FA-2400) ist mit diesem entfallen. Bringt ein ETS-Import Geraete-Zertifikate (FDSK) oder das Projektpasswort mit und ist kein Master-Passwort gesetzt, muss das System eines verlangen, sonst werden sie nicht uebernommen. Enthaelt ein geoeffnetes Projekt solche Werte unverschluesselt, muss es darauf hinweisen. Beim Speichern muessen ueberschriebene Staende aus der Projektdatei entfernt werden (kein Klartext im freien Speicher der Datei). **(C)** |

---

### 3.29 DALI-Detailkonfiguration (FA-2800)

| ID | Anforderung |
|----|-------------|
| FA-2801 | Das System muss fuer Projekte mit DALI-Gewerken (Gewerk LDA, FA-302) eine dedizierte DALI-Konfigurationsansicht bereitstellen. Pro DALI-Gateway koennen bis zu 64 DALI-Betriebsgeraete (EVG/Leuchten) und bis zu 16 DALI-Gruppen konfiguriert werden. **(C)** |
| FA-2802 | Das System muss das DALI-Adressierungsschema unterstuetzen: |

**DALI-Adressierungsschema (gemaess IEC 62386):**

| Element | Bereich | Beschreibung |
|---------|---------|-------------|
| DALI-Kurzadresse (Short Address) | 0 -- 63 | Eindeutige Adresse pro EVG/Leuchte im Segment |
| DALI-Gruppe | 0 -- 15 | Logische Zusammenfassung von EVGs (z.B. Reihe 1, Reihe 2) |
| DALI-Szene | 0 -- 15 | Gespeicherte Lichtstimmung pro Gruppe oder Segment |
| Broadcast | 255 | Ansteuerung aller EVGs gleichzeitig |

| ID | Anforderung |
|----|-------------|
| FA-2803 | Das System muss pro DALI-Gateway die zugeordneten KNX-Gruppenadressen fuer die DALI-Steuerung abbilden: GA fuer Schalten (Broadcast und pro Gruppe), GA fuer Dimmen, GA fuer Szenenabruf, GA fuer Statusrueckmeldung (Ist-Wert, Stoerung). Diese GAs werden aus der automatisch generierten GA-Struktur (FA-400) uebernommen und dem DALI-Gateway zugeordnet. **(C)** Umsetzung geplante Projekte: je LDA-Element eine DALI-Gruppe mit allen GAs dieses Elements (Schalten, Dimmen, Wert, Status RM WERT bzw. RM, Szene, Stoerung), ermittelt aus Gewerk, Raum, Element und Funktion der GA; nur Raeume der Linie des Gateways, je Gateway hoechstens 16 Gruppen (weitere Gateways derselben Linie der Reihe nach). Gruppenname aus Raum und Bezeichnung des Elements (FA-403), z.B. "Wohnen Decke". KNiX erzeugt in geplanten Projekten keine Broadcast-GAs; Gruppen-GAs werden nicht als Broadcast eingetragen (bereinigt frueher falsch gesetzte). Die Konfiguration entsteht beim Oeffnen der DALI-Ansicht automatisch, sofern noch keine Gruppen erfasst sind. Die DALI-Geraeteliste enthaelt die Gruppen mit ihren GAs. |
| FA-2804 | Das System muss DALI-Notbeleuchtung (Emergency Lighting, DALI Part 202/203) unterstuetzen: Kennzeichnung von EVGs als Notlicht-EVGs, Konfiguration des Betriebsmodus (Dauerlicht, Bereitschaft, Automatik), automatische Aufnahme in die Inbetriebnahme-Checkliste (FA-1901) mit spezifischen DALI-Notlicht-Pruefpunkten (Funktionstest, Dauerbetriebstest). **(C)** |
| FA-2805 | Das System muss eine DALI-Geraete- und Gruppenliste pro Gateway generieren: DALI-Adresse, EVG-Typ, zugehoerige Gruppe(n), Einbauort/Raum, zugeordnete KNX-GAs. Diese Liste fliesst in die Revisionsunterlagen (FA-2100) ein. **(C)** Im Revisionspaket mit EVGs oder Gruppen; bei geplanten Projekten werden die Gruppen dafuer bei Bedarf eingerichtet (wie beim Oeffnen der DALI-Ansicht). |
| FA-2806 | **Entfallen (25.09.2026, siehe 3.25).** Das System muss die DALI-Konfiguration in den KNXPROJ-Export (FA-2400) einbinden, sofern das Exportformat DALI-spezifische XML-Felder gemaess KNX-Standard unterstuetzt. **(C)** |

---

### 3.30 Zeitsteuerungsplanung (FA-2900)

| ID | Anforderung |
|----|-------------|
| FA-2901 | Das System muss die Definition von Zeitschaltprogrammen (Wochenprogramme) ermoeglichen. Pro Zeitschaltprogramm koennen bis zu 7 Tagesprofile (Montag bis Sonntag) mit beliebig vielen Schaltzeitpunkten definiert werden. **(C)** |
| FA-2902 | Das System muss fuer jeden Schaltzeitpunkt folgende Parameter erfassen: |

**Zeitschaltprogramm -- Parameter pro Schaltzeitpunkt:**

| Parameter | Beschreibung | Beispiel |
|-----------|-------------|---------|
| Zeitpunkt | Uhrzeit (HH:MM) oder Astro-Ereignis | 07:30 / Sonnenaufgang + 15 min |
| Ziel-GA | Betroffene Gruppenadresse | LD_E01_01 E/A |
| Aktion | Zu sendender Wert | EIN, AUS, 50%, Szene 3 |
| Gueltigkeit | Wochentag(e), optionaler Datumsbereich | Mo-Fr / 01.06.-31.08. |
| Prioritaet | Normal / Erhoet (uebersteuert andere Programme) | Normal |

| ID | Anforderung |
|----|-------------|
| FA-2903 | Das System muss einen astronomischen Kalender (Astro-Timer) unterstuetzen: Der Benutzer gibt den Projektstandort (Breitengrad/Laengengrad oder PLZ/Gemeinde) ein. Das System berechnet Sonnenauf- und -untergangszeiten und stellt diese als Bezugspunkte fuer Schaltzeitpunkte bereit (z.B. "Sonnenuntergang - 30 Minuten" fuer die Beschattungssteuerung). **(C)** |
| FA-2904 | Das System muss Feiertagskalender unterstuetzen: Auswahl des Kantons (Schweiz) oder Bundeslandes (Deutschland, Oesterreich), automatische Beruecksichtigung gesetzlicher Feiertage bei der Wochenprogramm-Ausfuehrung (z.B. Samstags-Programm gilt auch an Feiertagen). **(C)** |
| FA-2905 | Das System muss die Zeitschaltprogramme als Dokumentation exportieren: Pro Raum/Gewerk eine tabellarische Uebersicht aller aktiven Zeitprogramme. Diese fliesst in die Bauherr-Bedienungsanleitung (FA-2000) und die Revisionsunterlagen (FA-2100) ein. **(C)** |
| FA-2906 | Das System muss die benoetigen Gruppenadress-Zeitschaltungsfunktionen automatisch in der Zentralgruppe (HG 0) anlegen, sofern ein KNX-Zeitmodul (Gewerk U, FA-302) im Projekt vorhanden ist (z.B. Uhrengruppe fuer Datums-/Zeituebertragung, Astro-Gruppen fuer Sonnenauf-/-untergang). **(C)** |

---

### 3.31 CO-Auto-Linking (FA-3000)

| ID | Anforderung |
|----|-------------|
| FA-3001 | Das System muss Kommunikationsobjekte (COs) von Geraeten automatisch mit den passenden Gruppenadressen verknuepfen koennen, sofern die Geraetedaten (aus KNXPROD-Import FA-2304 oder XLSX-Topologie-Import FA-511) bekannt sind. Das CO-Auto-Linking kann fuer das gesamte Projekt oder einzelne Geraete ausgefuehrt werden. **(S)** |
| FA-3002 | Das System muss eine standardisierte CO-Funktionserkennung durchfuehren: Anhand von CO-Name, DPT und KNX-Flags wird die Funktion des COs erkannt und mit der entsprechenden GA-Funktion abgeglichen: |

**CO-Funktions-GA-Mapping (Standardregeln, erweiterbar):**

| CO-Funktion (erkannt via Name/DPT/Flags) | Zugeordnete GA-Funktion |
|------------------------------------------|------------------------|
| Schalten (DPT 1.x, Flags: KSUe) | E/A |
| Dimmen relativ (DPT 3.x) | DIM |
| Dimmen absolut / Helligkeitswert (DPT 5.x, Schreib-Flag) | WERT |
| Statusrueckmeldung Schalten (DPT 1.x, Flags: KLUe) | RM |
| Statusrueckmeldung Wert (DPT 5.x, Flags: KLUe) | RM WERT |
| Jalousie Auf/Ab (DPT 1.8) | AUF/AB |
| Jalousie Stopp/Lamellen (DPT 1.7) | STOPP |
| Position Hoehe (DPT 5.x, Schreib-Flag) | POSITION HOEHE |
| Position Lamellen (DPT 5.x, Schreib-Flag) | POSITION LAMELLEN |
| Ist-Temperatur (DPT 9.1, Lese-Flag) | IST |
| Sollwert (DPT 9.1, Schreib-Flag) | BASIS-SOLL |
| Betriebsart (DPT 20.102) | UMSCHALTEN BETRIEBSART |
| Szenenabruf (DPT 17.1) | Szenen-GA |

| ID | Anforderung |
|----|-------------|
| FA-3003 | Das System muss dem Benutzer die vorgeschlagenen CO-GA-Verknuepfungen in einer Vorschau-Ansicht praesentieren, bevor sie uebernommen werden: Geraet, CO-Nummer, CO-Name, DPT, vorgeschlagene GA, Konfidenz (sicher / moegliche Uebereinstimmung / manuell pruefen). Der Benutzer muss einzelne Verknuepfungen korrigieren, entfernen oder manuell ergaenzen koennen. **(S)** |
| FA-3004 | Das System muss fuer CO-GA-Verknuepfungen eine Kompatibilitaetspruefung durchfuehren: DPT des COs und DPT der GA muessen uebereinstimmen. DPT-Abweichungen werden als Warnung markiert. Nicht verknuepfte COs (kein passendes GA-Angebot) werden als Information aufgelistet. **(S)** |
| FA-3005 | Die Einbindung der bestaetigten CO-GA-Verknuepfungen in den KNXPROJ-Export (FA-2400) ist mit diesem entfallen; sie dienen als Vorlage fuer die Programmierung in ETS. Die Verknuepfungen werden zusaetzlich in der Kreuzreferenz-Ansicht (FA-1011) und der Sensor-Aktor-Matrix (FA-2500) angezeigt. **(S)** |

---

### 3.32 ETS COM-Server-Anbindung (FA-3100)

| ID | Anforderung |
|----|-------------|
| FA-3101 | Das System kann eine direkte Verbindung zur ETS6 ueber den ETS-COM-Server (OLE-Automation-Schnittstelle) herstellen. Die Verbindung ermoeglicht die Fernsteuerung von ETS6-Funktionen aus dem KNX Arranger heraus. Die Funktion setzt eine installierte und geoeffnete ETS6-Instanz auf demselben Rechner voraus. **(W)** |
| FA-3102 | Ueber die ETS-COM-Verbindung muss das System folgende Funktionen anbieten: a) Gruppenadress-Monitor: Empfangene KNX-Telegramme in Echtzeit anzeigen (GA, Wert, Zeitstempel), b) Telegramm senden: Beliebigen Wert an eine GA senden (z.B. fuer Funktionstests), c) Projektdaten synchronisieren: Aktuelle GA-Struktur aus ETS einlesen und mit dem KNX Arranger-Projekt abgleichen. **(W)** |
| FA-3103 | Der Telegramm-Monitor muss filterbar sein: nach GA, nach Gewerk, nach Raum, nach Stockwerk. Empfangene Werte werden mit Zeitstempel, GA-Adresse, GA-Bezeichnung und dekodiertem Wert angezeigt. Eine Exportfunktion (CSV) der Telegrammaufzeichnung muss angeboten werden. **(W)** |
| FA-3104 | Das System muss Inbetriebnahme-Testsequenzen unterstuetzen: Pro Raum koennen automatisch alle Schalt-GAs nacheinander mit Testwerten beschickt werden (EIN -- 2 s Pause -- AUS), um die Verdrahtung und Programmierung sequenziell zu verifizieren. Die Testergebnisse (Reaktion erkannt / nicht erkannt) werden im Inbetriebnahme-Protokoll (FA-1903) gespeichert. **(W)** |

---

### 3.33 Eingabe-Effizienz und Workflow-Optimierung (FA-3200)

**Ziel:** Den Integrations-Workflow im Wizard beschleunigen – haeufige, repetitive Eingaben durch Schnelleingaben, Klonen, Massenerfassung und Tastaturkuerzel reduzieren.

#### FA-3201 Schnelleingabe Stockwerke

| ID | Anforderung |
|----|-------------|
| FA-3201a | In Wizard Schritt 1 muss ein Button "Schnelleingabe..." vorhanden sein, der einen Dialog oeffnet. **(S)** |
| FA-3201b | Im Dialog kann der Benutzer mehrere Stockwerk-Kuerzel kommagetrennt eingeben (z.B. "KG, EG, 1.OG, 2.OG, DG"). Die Kuerzel werden automatisch den Standard-Stockwerksnamen und Hauptgruppennummern aus `STANDARD_FLOOR_NAMES` / `FLOOR_TO_MAIN_GROUP` zugeordnet. Unbekannte Kuerzel erhalten einen generischen Namen. **(S)** |
| FA-3201c | Bestehende Stockwerke werden durch die Schnelleingabe nicht geloescht; neue Stockwerke werden angehaengt. **(S)** |

#### FA-3202 Auto-Zone pro Stockwerk

| ID | Anforderung |
|----|-------------|
| FA-3202a | In Wizard Schritt 2 muss ein Button "1 Zone pro Stockwerk anlegen" vorhanden sein. **(S)** |
| FA-3202b | Beim Klick wird fuer jedes Stockwerk, das noch keine Zone/Wohnung besitzt, automatisch eine Zone mit dem Namen des Stockwerks angelegt. Stockwerke mit bereits vorhandenen Zonen werden uebersprungen. **(S)** |

#### FA-3203 Raum klonen mit Auto-Inkrement

| ID | Anforderung |
|----|-------------|
| FA-3203a | In Wizard Schritt 3 muss ein Button "Klonen" vorhanden sein. **(S)** |
| FA-3203b | Der Button erstellt eine tiefe Kopie des aktuell gewaehlen Raums. Die Raumnummer wird automatisch inkrementiert (z.B. E01 -> E02, E09 -> E10). Der neue Raum wird direkt nach dem Originalraum in die Liste eingefuegt. **(S)** |
| FA-3203c | Button "Zusammenfuehren...": der gewaehlte Raum geht in einem anderen Raum auf und wird geloescht. Gewerke, Tastereinheiten samt Tastenbelegung, Verteiler und Bauherren-Notizen wandern mit; gleiche Gewerke werden zusammengezaehlt (Elemente des Quellraums hinten angehaengt), Tastereinheiten erhalten die naechsten freien Nummern, Tasten anderer Raeume zeigen auf die neuen Elemente. Alle Verweise auf den Raum (Topologie, DALI, Szenen, Checklisten) werden umgehaengt, DALI-Gruppen mit dem Raumnamen umbenannt. Gruppenadressen behalten ihre Adresse und werden bei der Neuberechnung auf den Zielraum umbenannt; nur ein durch gleiche Gewerke vergroesserter Block erhaelt neue Adressen. Nur geplante Projekte; gesperrt bei mehr als 20 Elementen je Gewerk oder verschiedenen Produkten/Sensortypen desselben Gewerks. **(C)** |

#### FA-3204 Inline-Bearbeitung Raeume per Doppelklick

| ID | Anforderung |
|----|-------------|
| FA-3204a | Ein Doppelklick auf einen Raum in Wizard Schritt 3 setzt den Fokus auf das Eingabefeld "Raumnummer" und markiert den gesamten Text, damit der Benutzer sofort tippen kann. **(C)** |

#### FA-3205 Massenerfassung Raeume aus Textblock

| ID | Anforderung |
|----|-------------|
| FA-3205a | In Wizard Schritt 3 muss ein Button "Massenerfassung..." vorhanden sein. **(C)** |
| FA-3205b | Ein Dialog zeigt ein mehrzeiliges Texteingabefeld. Jede Zeile im Format "NUMMER Name" (z.B. "E01 Wohnzimmer") erzeugt einen Raum. Leerzeilen werden ignoriert. **(C)** |
| FA-3205c | Die Raeume werden in die aktuell gewaehlt Wohnung/Zone eingefuegt (bestehende Raeume werden ersetzt, nach Benutzerbestaetigung). **(C)** |

#### FA-3206 Return-Taste bestaetigt Formulare

| ID | Anforderung |
|----|-------------|
| FA-3206a | In den Detailformularen der Wizard-Schritte 1, 2 und 3 loest die Return-Taste (Enter) den Button "Uebernehmen" aus, ohne dass der Benutzer die Maus benutzen muss. **(S)** |

#### FA-3207 Multi-Select in der Gewerk-Tabelle

| ID | Anforderung |
|----|-------------|
| FA-3207a | In Wizard Schritt 5 muss die Gewerk-Tabelle Mehrfachselektion (ExtendedSelection) unterstuetzen. **(S)** |
| FA-3207b | Aktionen "Vorlage anwenden" und "Gewerk hinzufuegen" wirken auf alle selektierten Zeilen gleichzeitig. **(S)** |

#### FA-3208 Gewerk-Zuweisung auf alle gleichen Raeume uebertragen

| ID | Anforderung |
|----|-------------|
| FA-3208a | In Wizard Schritt 5 muss ein Button "Auf alle gleichen Raeume anwenden" vorhanden sein. **(C)** |
| FA-3208b | Beim Klick werden die Gewerk-Zuweisungen aller aktuell selektierten Raeume auf alle Raeume mit demselben Namen (projektuebergreifend ueber alle Stockwerke und Wohnungen) uebertragen. Der Benutzer wird ueber die Anzahl der betroffenen Raeume informiert. **(C)** |

#### FA-3209 Schnell-Buttons fuer haeufige Gewerke

| ID | Anforderung |
|----|-------------|
| FA-3209a | In Wizard Schritt 5 muss eine Reihe von Schnell-Buttons fuer die haeufigsten Gewerke vorhanden sein: L (Licht), LD (Licht Dimmen), LDA (DALI), J (Jalousie), H (Heizung), S (Steckdose), V (Ventilator). **(S)** |
| FA-3209b | Ein Klick auf einen Schnell-Button fuegt das entsprechende Gewerk direkt in alle selektierten Zeilen ein, ohne zusaetzlichen Dialog. Bereits vorhandene Gewerke werden nicht dupliziert. **(S)** |

#### FA-3210 Erweiterte Gebaeudevorlagen

| ID | Anforderung |
|----|-------------|
| FA-3210a | Die Vorlagenliste in Wizard Schritt 1 muss mindestens die folgenden zusaetzlichen Vorlagen enthalten: "EFH Klein" (3 Stockwerke, Grundraeume), "Chalet / Ferienhaus" (2 Stockwerke, Ferienhausraeume), "Hotel klein" (Rezeption + 3 Zimmertypen). **(C)** |
| FA-3210b | Jede Vorlage beinhaltet vordefinierte Stockwerke, Zonen und Raeume gemaess Vorlage. **(C)** |

#### FA-3211 Wizard-Schritt-Statusanzeige

| ID | Anforderung |
|----|-------------|
| FA-3211a | Die Schritt-Buttons im Wizard-Navigator muessen dynamische Tooltips anzeigen, die den aktuellen Bearbeitungsstatus des jeweiligen Schritts zusammenfassen. **(C)** |
| FA-3211b | Beispielhafte Tooltip-Inhalte: Schritt 1: Anzahl Stockwerke; Schritt 2: Anzahl Zonen; Schritt 3: Anzahl Raeume; Schritt 5: Anzahl Gewerk-Zuweisungen; Schritt 7: Anzahl generierte GAs. **(C)** |

---

### 3.34 Zeitsteuerungsplanung -- Detaillierung (FA-3300)

**Ziel:** Die in FA-2901 bis FA-2906 spezifizierten Zeitsteuerungsfunktionen werden hier in implementierungsreife Teilanforderungen aufgeschluesselt. Der Integrator kann Wochenprogramme fuer beliebige Gruppenadressen erstellen, astronomische Schaltzeitpunkte nutzen, Feiertagsregeln hinterlegen und die Programme automatisch in die Projektdokumentation einbinden.

#### FA-3301 Datenmodell Zeitschaltprogramm

| ID | Anforderung |
|----|-------------|
| FA-3301a | Das Datenmodell muss folgende Klassen implementieren: `TimeProgram` (id, name, active, liste day_profiles), `DayProfile` (weekday_mask als int, liste switch_points), `SwitchPoint` (id, time_type, fixed_time, astro_event, astro_offset_min, target_ga_id, action_value, date_range_start, date_range_end, priority). **(C)** |
| FA-3301b | `KnxProject` erhaelt das Feld `time_programs: list[TimeProgram]`. Alle TimeProgram-Objekte werden in der `.knxarr`-Datei unter dem Schluessel `"time_programs"` serialisiert und beim Laden deserialisiert. **(C)** |
| FA-3301c | `SwitchPoint.time_type` nimmt die Werte `"FIXED"` (feste Uhrzeit HH:MM) oder `"ASTRO"` (astronomisches Ereignis + Offset) an. `astro_event` ist entweder `"SUNRISE"` oder `"SUNSET"`. `astro_offset_min` liegt im Bereich -120 bis +120 Minuten. **(C)** |
| FA-3301d | Wochentage werden in `DayProfile.weekday_mask` als Bitmaske gespeichert: Bit 0 = Montag, Bit 1 = Dienstag, ..., Bit 6 = Sonntag, Bit 7 = Feiertag. Convenience-Properties `.weekdays` (Liste der aktiven Tage als Strings) muessen vorhanden sein. **(C)** |
| FA-3301e | `SwitchPoint.action_value` wird als String gespeichert und beim Senden in den zum DPT der Ziel-GA passenden Typ konvertiert (z.B. "1" fuer DPT 1.x, "50" fuer DPT 5.x als Prozentwert 0-100, "Szene 3" fuer DPT 17.1). **(C)** |

#### FA-3302 Zeitprogramm-Editor-Ansicht

| ID | Anforderung |
|----|-------------|
| FA-3302a | Die Seitenleiste (Sidebar) muss einen neuen Eintrag "Zeitsteuerung" erhalten. Ein Klick oeffnet die Zeitprogramm-Editor-Ansicht im Hauptbereich des Fensters. **(C)** |
| FA-3302b | Die Ansicht ist zweigeteilt: Links eine Liste aller Zeitprogramme des Projekts (Name, aktiv/inaktiv, Anzahl SwitchPoints) mit Buttons "Neu", "Duplizieren" und "Loeschen". Rechts der Editor fuer das gewaehlt Zeitprogramm. **(C)** Umsetzung: Programmliste mit Name, Haken aktiv/inaktiv und Anzahl Schaltpunkte; Buttons Neu, Duplizieren, Loeschen, Aus Vorlage erstellen, Als Vorlage speichern. |
| FA-3302c | Der rechte Editorbereich zeigt das Wochenprogramm als Tabelle: Zeilen = Stunden (00:00-23:00), Spalten = Wochentage (Mo-So + Feiertag). SwitchPoints werden als farbige Eintraege in der zugehoerigen Zeile und Spalte dargestellt (Farbe nach Gewerk der Ziel-GA). **(C)** Umsetzung: Registerkarte "Wochenraster" (Stunden x Mo-So + Feiertag), Eintraege mit Zeit, Wert und Ziel, Farbe nach Gewerk-Kategorie; Astro-Zeitpunkte mit der Zeit von heute. |
| FA-3302d | Unterhalb der Wochenraster-Tabelle befindet sich eine editierbare Liste aller SwitchPoints des Zeitprogramms mit Spalten: Zeitpunkt, Ziel-GA, Aktion, Wochentage, Datumsbereich. Buttons "Hinzufuegen", "Bearbeiten" (Doppelklick) und "Entfernen" steuern die Liste. **(C)** |
| FA-3302e | Der SwitchPoint-Bearbeitungs-Dialog enthaelt folgende Felder: Zeitpunkt-Typ (Dropdown: Fest / Astro), Uhrzeit (HH:MM, nur bei Fest), Astro-Ereignis (Sonnenaufgang / Sonnenuntergang, nur bei Astro), Offset in Minuten (-120 bis +120, nur bei Astro), Ziel-GA (durchsuchbarer Dropdown aller Projekt-GAs mit Adresse + Bezeichnung), Aktionswert (Freitext mit DPT-Hinweis), Wochentage (Checkboxen Mo-So + Feiertag), optionaler Datumsbereich (Von-Datum, Bis-Datum). **(C)** Umsetzung mit Abweichung: Die Wochentage gelten je Tagesprofil (Registerkarte Wochentage), nicht je Schaltzeitpunkt. Datumsbereich optional ("Nur im Zeitraum"). |
| FA-3302f | Im GA-Dropdown des Bearbeitungs-Dialogs kann der Benutzer nach GA-Adresse, Bezeichnung, Gewerk oder Raum filtern. Die GAs werden nach Hauptgruppe/Mittelgruppe gruppiert angezeigt. **(C)** Umsetzung: Filterfeld ueber der GA-Auswahl (Adresse, Bezeichnung, Gewerk, Raumnummer), GAs nach HG/MG gruppiert. |
| FA-3302g | Jedes Zeitprogramm erhaelt einen frei waehlbaren Namen (Inline-Bearbeitung per Doppelklick in der Programmliste). Deaktivierte Programme (active=False) werden in der Liste ausgegraut dargestellt und durch ein Checkbox-Symbol als inaktiv kenntlich gemacht. **(C)** Umsetzung: Umbenennen per Doppelklick, Haken fuer aktiv, inaktive Programme grau. |

#### FA-3303 Astro-Timer-Konfiguration

| ID | Anforderung |
|----|-------------|
| FA-3303a | Der Projektstandort wird in den Projekteinstellungen (`KnxProject.location`) als Koordinatenpaar gespeichert: `latitude` (Breitengrad, Dezimalgrad, -90 bis +90) und `longitude` (Laengengrad, Dezimalgrad, -180 bis +180). Alternativ kann der Benutzer eine PLZ und ein Land (CH / DE / AT) eingeben; das System ermittelt dann die Koordinaten aus einer mitgelieferten PLZ-Lookup-Tabelle (JSON). **(C)** |
| FA-3303b | Das System berechnet aus den Koordinaten und dem Datum die Sonnenaufgangs- und Sonnenuntergangszeiten. Die Berechnung muss auf dem NOAA Solar Calculator-Algorithmus (oder gleichwertig) basieren und eine Genauigkeit von +/- 2 Minuten ueber das gesamte Jahr gewaehrleisten. Die Berechnung erfolgt lokal ohne Internetverbindung. **(C)** |
| FA-3303c | Im Zeitprogramm-Editor-Bearbeitungs-Dialog wird bei gewaaehltem Zeitpunkt-Typ "Astro" eine Vorschau des resultierenden Zeitpunkts fuer heute angezeigt (z.B. "Heute: Sonnenuntergang 20:14 + 0 min = 20:14 Uhr"). **(C)** Umsetzung: "Heute: Sonnenuntergang 19:02 + 15 min = 19:17 Uhr" im Dialog. |
| FA-3303d | Ist kein Standort im Projekt konfiguriert, ist der Zeitpunkt-Typ "Astro" im Bearbeitungs-Dialog deaktiviert. Ein gelbes Hinweisfeld zeigt: "Projektstandort nicht konfiguriert -- Astro-Timer nicht verfuegbar. Bitte in den Projekteinstellungen eintragen." **(C)** Abweichung: Der Projektstandort ist immer gesetzt (Standard Zuerich), daher bleibt Astro immer verfuegbar; der Standort wird ueber "Standort..." angepasst. |

#### FA-3304 Feiertagskalender

| ID | Anforderung |
|----|-------------|
| FA-3304a | Das System liefert Feiertagsdaten als JSON-Konfigurationsdatei `config/holidays.json` mit, welche die gesetzlichen Feiertage fuer mindestens folgende Regionen und einen Zeitraum von 5 Jahren (aktuelles Jahr + 4 Folgejahre) enthaelt: Schweiz (alle 26 Kantone), Deutschland (alle 16 Bundeslaender), Oesterreich (alle 9 Bundeslaender). **(C)** |
| FA-3304b | Der Benutzer waehlt in den Projekteinstellungen Land und Kanton/Bundesland. Alle `SwitchPoint`-Eintraege mit gesetztem Feiertag-Bit (Bit 7 in `weekday_mask`) werden an den konfigurierten Feiertagen aktiv. Das Standard-Verhalten (wie Samstag) ist konfigurierbar. **(C)** |
| FA-3304c | Im SwitchPoint-Bearbeitungs-Dialog wird neben der Wochentag-Checkbox "Feiertag" in Klammern die Anzahl der betroffenen Feiertage im laufenden Jahr angezeigt (z.B. "Feiertag (12 Tage in 2026)"). **(C)** Umsetzung: in der Registerkarte Wochentage, z.B. "Feiertag (10 Tage in 2026)" fuer das Land des Projektstandorts. |

#### FA-3305 Wochenprogramm-Vorlagen

| ID | Anforderung |
|----|-------------|
| FA-3305a | Das System stellt mindestens die folgenden vordefinierten Zeitprogramm-Vorlagen bereit, abrufbar ueber den Button "Aus Vorlage erstellen" in der Programmliste: **(C)** |

**Mitgelieferte Zeitprogramm-Vorlagen:**

| Vorlage-ID | Name | Typische SwitchPoints |
|------------|------|-----------------------|
| `beschattung_standard` | Beschattung Standard | Sonnenaufgang +30 min: Jalousie AUF; Sonnenuntergang -30 min: Jalousie AB |
| `licht_nacht` | Licht Nacht-Modus | 23:00 Mo-So: Alle Lichter AUS; 06:30 Mo-Fr: Treppenlicht EIN |
| `heizung_abwesenheit` | Heizung Abwesenheit | 08:00 Mo-Fr: Heizung ABSENK; 17:00 Mo-Fr: Heizung NORMAL; 23:00 Sa-So: Heizung ABSENK |
| `lueftung_zeitplan` | Lueftung Zeitprogramm | 07:00 Mo-So: Lueftung Stufe 2; 22:00 Mo-So: Lueftung Stufe 1 |

| ID | Anforderung |
|----|-------------|
| FA-3305b | Beim Laden einer Vorlage werden alle SwitchPoints mit Platzhalter-GAs (leer) angelegt. Der Benutzer muss die Ziel-GAs im Anschluss manuell zuweisen. Ein Banner weist darauf hin: "X Schaltzeitpunkte haben noch keine Ziel-GA -- bitte zuweisen." **(C)** Umsetzung: Hinweisbalken oben in der Ansicht. |
| FA-3305c | Vorlagen werden als JSON-Konfigurationsdatei `config/time_program_templates.json` mitgeliefert und sind durch den Benutzer erweiterbar (eigene Vorlagen speicherbar). **(C)** Umsetzung: "Als Vorlage speichern..." speichert ohne Ziel-GAs im Benutzerprofil (%APPDATA%/KNiX Arranger/time_program_templates.json); eigene Vorlagen erscheinen nach den mitgelieferten. |

#### FA-3306 GA-Verknuepfungs-Validierung

| ID | Anforderung |
|----|-------------|
| FA-3306a | Die Validierungsroutine (FA-600) muss Zeitprogramme pruefen: Jeder `SwitchPoint` mit einer `target_ga_id`, die nicht (mehr) im Projekt vorhanden ist, erzeugt einen Fehler (FA-601-Kategorie "Zeitsteuerung"): "Zeitprogramm '{name}': Ziel-GA '{adresse}' nicht gefunden." **(C)** Umsetzung: Regel FA-3306 in der Validierung. |
| FA-3306b | Jeder `SwitchPoint`, dessen `action_value` nicht mit dem DPT der Ziel-GA kompatibel ist, erzeugt eine Warnung: "Zeitprogramm '{name}': Wert '{wert}' moeglicherweise inkompatibel mit DPT {dpt} der GA '{adresse}'." **(C)** Umsetzung: DPT 1.x (0/1, Ein/Aus), 5.001 (0-100), 5.x (0-255), 17/18 (Szene 0-64), Zahlenwerte fuer 6-9, 12-14; unbekannte DPT gelten als passend. |
| FA-3306c | Im Zeitprogramm-Editor werden SwitchPoints mit Validierungsfehlern rot hinterlegt, SwitchPoints mit Warnungen gelb. Ein Fehler-Banner oben in der Ansicht listet die Gesamtanzahl der Probleme auf. **(C)** Umsetzung: Zeilen rot/gelb mit Tooltip, Hinweisbalken mit Anzahl Fehler und Warnungen. |
| FA-3306d | GAs, die in mindestens einem aktiven Zeitprogramm als Ziel referenziert werden, werden in den GA-Ansichten gekennzeichnet: in der GA-Tabelle in der Spalte "Notizen" mit "Zeitprogramm: <Name>" (mehrere Programme kommagetrennt), im GA-Baum mit einem Uhr-Symbol vor der Beschreibung und den Programmnamen im Tooltip. Ein Buchstabenkuerzel (urspruenglich "[T]") ist nicht zulaessig, da es mit Gewerk-Kuerzeln verwechselt wird (T = Tagesvorhang, in ETS-Projekten auch Tor). Aenderung 06.10.2026. **(C)** |

#### FA-3307 Dokumentationsexport

| ID | Anforderung |
|----|-------------|
| FA-3307a | Die Bauherr-Bedienungsanleitung (FA-2001) muss um einen Abschnitt "Automatische Zeitsteuerung" erweitert werden. Dieser enthaelt pro aktivem Zeitprogramm eine Tabelle: Name des Programms, Zeitpunkt, Ziel (GA-Bezeichnung, Raum, Gewerk), Aktion, Wochentage, Datumsbereich. **(C)** Umsetzung: Abschnitt im Teil Allgemeines in Alltagssprache (Zeitpunkt, Raum und Objekt, Aktion Ein/Aus/Auf/Ab/%, Tage, Zeitraum), ohne GA-Nummern; ausblendbar (FA-2005). |
| FA-3307b | Das Revisionspaket (FA-2101) muss eine separate Datei `{Projektkuerzel}_Zeitsteuerungsplan.pdf` enthalten, die alle aktiven Zeitprogramme vollstaendig auflistet (inkl. inaktiver SwitchPoints, die als "(inaktiv)" markiert sind). **(C)** Umsetzung: Datei {Projekt}_Zeitsteuerungsplan.pdf mit Spalte Zeitraum. Schaltzeitpunkte haben kein eigenes aktiv/inaktiv; inaktive Programme sind als "(inaktiv)" markiert. |
| FA-3307c | Der Reports-Dialog (FA-900) erhaelt einen neuen Eintrag "Zeitsteuerungsplan (PDF)" mit dem Beschreibungstext "Alle Wochenprogramme und Schaltzeitpunkte als druckbares Dokument". **(C)** Umgesetzt. |

#### FA-3308 Zentralgruppen-GA-Anlage fuer Astro-Funktionen

| ID | Anforderung |
|----|-------------|
| FA-3308a | Sobald mindestens ein aktives Zeitprogramm einen `SwitchPoint` mit `time_type = "ASTRO"` enthaelt, muss das System bei der GA-Generierung (FA-400) automatisch folgende GAs in HG 0 / MG 7 anlegen, sofern sie noch nicht vorhanden sind: `0/7/0 Uhrzeit und Datum` (DPT 19.001), `0/7/1 Sonnenaufgang` (DPT 1.001), `0/7/2 Sonnenuntergang` (DPT 1.001), `0/7/3 Daemmerung aktiv` (DPT 1.001). **(C)** |
| FA-3308b | Diese Astro-GAs werden bei der Validierung (FA-600) speziell behandelt: Fehlt eine dieser GAs trotz vorhandener Astro-SwitchPoints, wird eine Warnung ausgegeben: "Astro-GAs in HG 0 / MG 7 fehlen -- bitte GA-Generierung erneut ausfuehren." **(C)** |
| FA-3308c | Im CSV-Export (FA-801) werden die Astro-GAs wie alle anderen Zentraladressen mit exportiert. **(C)** |

### 3.35 Workspace- und Projektverwaltung (FA-3400)

Ab Version 1.1.0 legt das System neue Projekte verbindlich in einem zentralen Arbeitsverzeichnis (Workspace) mit einheitlicher Ordnerstruktur ab. Bestehende, frei abgelegte Projekte bleiben davon unberuehrt und koennen weiterhin von beliebigem Ort geoeffnet werden.

| ID | Anforderung |
|----|-------------|
| FA-3401 | Beim allerersten Start des Systems muss ein Ersteinrichtungs-Dialog erscheinen, der einen Vorschlag fuer das Arbeitsverzeichnis macht (Standard: Unterordner "KNX-Projekte" im Dokumente-Ordner des Betriebssystems) und dem Anwender erlaubt, einen abweichenden Ordner zu waehlen. |
| FA-3402 | Neue Projekte muessen zwingend in der Struktur `{Arbeitsverzeichnis}/{Projektname}/{Projektname}.knxarr` angelegt werden, wobei pro Projekt automatisch die Unterordner `Revisionen/` und `Berichte/` erstellt werden. |
| FA-3403 | Der Projektname muss beim Anlegen bereinigt werden (unzulaessige Dateisystemzeichen entfernt) und auf Kollisionen mit bestehenden Projektordnern sowie auf reservierte Windows-Namen (z.B. CON, NUL, PRN) geprueft werden; bei einer Kollision oder einem reservierten Namen muss eine verstaendliche Fehlermeldung erscheinen. |
| FA-3404 | Der Dialog "Neues Projekt erstellen" muss eine Live-Vorschau des resultierenden Projektordnerpfads anzeigen, die sich bei Eingabe des Projektnamens sofort aktualisiert. |
| FA-3405 | Berichte (FA-900) und Revisionspakete (FA-2101) muessen ohne erneute Ordnerauswahl automatisch in den Unterordnern `Berichte/` bzw. `Revisionen/` neben der `.knxarr`-Datei des aktuellen Projekts abgelegt werden. |
| FA-3406 | Das Arbeitsverzeichnis muss nachtraeglich in den Einstellungen (Allgemein-Tab) geaendert werden koennen; die Aenderung wirkt sich nur auf zukuenftig neu angelegte Projekte aus. |
| FA-3407 | Der Willkommens-Dialog muss eine Liste der zuletzt verwendeten Projekte als klickbare Eintraege anzeigen (Projektname als Beschriftung, vollstaendiger Pfad als Tooltip), ueber die ein Projekt direkt geoeffnet werden kann. |
| FA-3408 | Bestehende, ausserhalb des Arbeitsverzeichnisses abgelegte Projekte muessen weiterhin frei verschiebbar und oeffenbar sein; fuer sie werden Berichte/Revisionen ebenfalls automatisch neben der Projektdatei abgelegt (nicht im zentralen Workspace). |

---

## 4. Nicht-funktionale Anforderungen

### 4.1 Plattform und Technologie (NFA-010)

| ID | Anforderung |
|----|-------------|
| NFA-011 | Das System muss als eigenstaendige Desktop-Anwendung fuer Windows (10/11, 64-Bit) bereitgestellt werden. |
| NFA-012 | Das System wird in Python entwickelt und als eigenstaendige .exe-Datei ausgeliefert (bevorzugt via Nuitka fuer nativen C-Code, alternativ PyInstaller). |
| NFA-013 | Es darf keine separate Python-Installation auf dem Zielsystem erforderlich sein. |

### 4.2 Performance (NFA-020)

| ID | Anforderung |
|----|-------------|
| NFA-021 | Der Import einer CSV-Datei mit bis zu 5.000 Gruppenadressen muss in unter 5 Sekunden abgeschlossen sein. |
| NFA-022 | Die Validierung einer CSV-Datei mit bis zu 5.000 Gruppenadressen muss in unter 10 Sekunden abgeschlossen sein. |
| NFA-023 | Die Generierung eines vollstaendigen Gruppenadress-Satzes (bis 5.000 GA) muss in unter 15 Sekunden abgeschlossen sein. |
| NFA-023a | Stand 06.10.2026, gemessen mit 5.000 Gruppenadressen: CSV-Import 0,04 s, Validierung 0,01 s, CSV-Export 0,01 s. |

### 4.3 Benutzbarkeit (NFA-030)

| ID | Anforderung |
|----|-------------|
| NFA-031 | Die Benutzeroberflaeche muss in deutscher Sprache gestaltet sein. |
| NFA-032 | Die Software muss ohne Schulung von einem KNX-Systemintegrator bedienbar sein. |
| NFA-033 | Der Wizard fuer ein neues Projekt muss in 13 strukturierten Schritten (gemaess FA-1002) zu einem vollstaendigen Projektexport fuehren. Jeder Schritt muss einzeln abschliessbar und navigierbar sein (Vor/Zurueck). |
| NFA-034 | Alle Tabellen- und Baumansichten muessen ihre Spaltenbreiten automatisch an den laengsten Inhalt anpassen. Dies gilt fuer saemtliche Ansichten: Topologie, Gruppenadressen (Baum und Tabelle), Gebaeudestruktur, Gewerke-Uebersicht, Validierung sowie alle Wizard-Schritte mit Tabellen oder Baeumen. Ausnahme Gewerke-Uebersicht: kein horizontales Scrollen, der Gewerk-Name ist begrenzt (bei wenig Platz bis 120 px), die Bezeichnung fuellt die restliche Breite (mindestens 220 px), gekuerzte Texte stehen im Tooltip. |
| NFA-034a | Umsetzung: Spalten passen sich beim Fuellen an den Inhalt an (auch Inbetriebnahme-Checkliste); passen nicht alle in die Breite, werden sie bis zur Breite des Spaltenkopfs gestaucht, danach scrollt die Tabelle. Auswahldialoge (GA, KO, Produkt) dehnen die Bezeichnungsspalte. |

### 4.4 Zuverlaessigkeit (NFA-040)

| ID | Anforderung |
|----|-------------|
| NFA-041 | Das System darf bei fehlerhaften Eingaben nicht abstuerzen, sondern muss aussagekraeftige Fehlermeldungen anzeigen. |
| NFA-041a | Umsetzung: Ein unerwarteter Fehler im laufenden Betrieb (Knopf, Ansicht, Timer) wird abgefangen: Eintrag in der Logdatei, Crash-Report (NFA-143) und Meldung "Unerwarteter Fehler" mit dem Pfad des Berichts; das Programm bleibt offen, damit gespeichert werden kann. Fehler in Hintergrund-Threads werden nur protokolliert. |
| NFA-042 | Vor jeder Reorganisation, jedem Import und jedem Neuaufbau aus der ETS muss automatisch ein Backup der gespeicherten Projektdatei erstellt werden, im Unterordner "Sicherungen" des Projekts mit Zeitstempel und Anlass im Dateinamen; die letzten 10 Sicherungen bleiben erhalten. |
| NFA-043 | Das System muss Rueckgaengig und Wiederholen fuer Aenderungen bereitstellen, sichtbar in einer Werkzeugleiste in jeder Ansicht (zusaetzlich Menue Bearbeiten und Strg+Z/Strg+Y). Jede Bearbeitung in der Bauherren-Beratung setzt einen Rueckgaengig-Punkt. |
| NFA-044 | Projektdaten muessen in einem eigenen Projektformat gespeichert und wieder geladen werden koennen. |
| NFA-045 | Beim Beenden darf das System nur dann nach dem Speichern fragen, wenn der Projektinhalt vom zuletzt gespeicherten Stand abweicht. Schlaegt das Speichern fehl (auch beim automatischen Speichern), muss das angezeigt werden und das Fenster offen bleiben. |
| NFA-046 | Das Anzeigen einer Ansicht darf keine Projektdaten veraendern. Abgeleitete Daten (z.B. Bedienelemente aus der Topologie, Tastenbelegung aus den Sensorfunktionen) werden nach der Aenderung neu berechnet, die sie betrifft: Oeffnen, Import, Assistent, Aenderungen an Gebaeude, Gewerken, Gruppenadressen, Topologie und in der Verknuepfungsmatrix. Berichte und Exporte rechnen auf einer Kopie. |

### 4.5 Wartbarkeit und Erweiterbarkeit (NFA-050)

| ID | Anforderung |
|----|-------------|
| NFA-051 | Die Gewerke-Tabelle, Adressblock-Schemata und Validierungsregeln muessen ueber externe Konfigurationsdateien anpassbar sein. |
| NFA-052 | Neue Gewerke, Funktionsbezeichnungen und DPT-Zuordnungen muessen ohne Codeaenderung hinzugefuegt werden koennen. |
| NFA-053 | Die Topologie-Regeln (max. Teilnehmer, Empfehlungswerte) muessen konfigurierbar sein (Umschaltung TP-64/TP-256, Anpassung Planungswerte). |
| NFA-053a | Stand: Extern gepflegt werden Gewerke-Katalog mit Funktionen (gewerke_catalog.json), DPT-Vorschlaege (dpt_mapping.json), Aktor-Zuordnung, Gebaeude-, Szenen- und Zeitprogramm-Vorlagen, Feiertage und Produktkatalog. Adressblock-Schema, Validierungsregeln und die Planungswerte 85/100 Teilnehmer je Linie (KNX Swiss) stehen im Programm; TP-64/TP-256 ist je Projekt in den Projekteigenschaften waehlbar. Die frueher mitgelieferten, nie gelesenen Dateien topology_rules.json, default_settings.json, address_blocks.json, ga_rules.json und sensor_mapping.json entfallen. |

### 4.6 Lizenzierung und Softwareschutz (NFA-060)

#### 4.6.1 Lizenzsystem

| ID | Anforderung |
|----|-------------|
| NFA-060a | Stand 06.10.2026 (derzeit kein Verkauf): Umgesetzt sind die signierte Offline-Lizenz (NFA-098a-c), Test- und Jahreslizenz mit Ablaufdatum, Sperre ohne gueltige Lizenz und der Lizenz-Dialog. Zurueckgestellt bis Verkaufsstart: Online-Aktivierung und Lizenzserver (NFA-064, NFA-091 bis NFA-097), Code-Signatur (NFA-073, NFA-132), Integritaetspruefung beim Start (NFA-074), Datenschutz der Lizenzverwaltung und Datenschutzerklaerung (NFA-121 bis NFA-123, NFA-125). Die Hardware-Bindung (NFA-063) entfaellt bewusst. |
| NFA-061 | Die Software muss durch ein Lizenzsystem geschuetzt sein. Ohne gueltige Lizenz darf die Software nicht nutzbar sein. |
| NFA-062 | Das Lizenzsystem muss Lizenzschluessel im Format XXXX-XXXX-XXXX-XXXX unterstuetzen. Jeder Schluessel ist eindeutig einem Kunden zugeordnet. |
| NFA-062a | Umsetzung: Der Lizenzschluessel hat das Praefix "KNIX1-" und enthaelt die signierte Lizenz (NFA-098a); das kurze Format XXXX-XXXX-XXXX-XXXX setzt einen Lizenzserver voraus und ist mit diesem zurueckgestellt (NFA-060a). |
| NFA-063 | Die Lizenz muss an die Hardware des Zielsystems gebunden werden (Hardware-Bindung), um die Weitergabe und unberechtigte Nutzung auf anderen Rechnern zu verhindern. Bindungsmerkmale: CPU-ID, MAC-Adresse oder Festplatten-Seriennummer. |
| NFA-064 | Das System muss eine einmalige Online-Aktivierung ueber einen Lizenzserver unterstuetzen. Die Aktivierung verifiziert den Lizenzschluessel und registriert die Hardware-Kennung. |
| NFA-065 | Das System muss verschiedene Lizenzmodelle unterstuetzen: a) Einzelplatzlizenz (1 Rechner), b) zeitlich begrenzte Lizenz (Jahreslizenz mit Ablaufdatum), c) Testlizenz (zeitlich begrenzt, voller Funktionsumfang). |
| NFA-066 | Bei abgelaufener oder ungueltiger Lizenz muss das System eine klare Meldung anzeigen und den Zugang zum Funktionsumfang sperren. Bereits erstellte Projektdaten muessen weiterhin lesbar bleiben (Exportfunktion gesperrt). |
| NFA-066a | Umsetzung: Ohne gueltige Lizenz erscheint beim Start der Lizenzdialog; wird er ohne Lizenz geschlossen, startet KNiX im Lesemodus (Hinweis beim Start, "Lesemodus" im Fenstertitel). Projekte lassen sich oeffnen, ansehen und probehalber bearbeiten; Speichern (auch automatisch), neue Projekte und alle Exporte (Berichte, Revisionspaket, CSV, XML, PDF, Excel, Bilder, Datenblaetter, E-Mail-Entwuerfe) sind gesperrt. Jede gesperrte Aktion zeigt einen Hinweis mit Knopf "Lizenz..."; eine dort eingespielte Lizenz beendet den Lesemodus sofort. |
| NFA-067 | Das System muss eine Lizenzverwaltungsoberflaeche bieten: Lizenzstatus anzeigen (gueltig bis, Lizenztyp, gebundene Hardware), Lizenzschluessel eingeben/aendern, Online-Aktivierung/Deaktivierung durchfuehren. |

#### 4.6.2 Code-Schutz und Integritaet

| ID | Anforderung |
|----|-------------|
| NFA-071 | Die Auslieferung muss als nativ kompilierte Anwendung erfolgen (bevorzugt Nuitka statt PyInstaller), um Reverse Engineering wesentlich zu erschweren. |
| NFA-071a | Umsetzung: build.py baut mit Nuitka (--standalone) ein Bundle ohne .py/.pyc-Dateien des Programms; der Build bricht ab, wenn Quellcode im Bundle gefunden wird. Einzig die Fremdbibliothek PyMuPDF bleibt Bytecode (ihre generierte MuPDF-Anbindung sprengt den C-Compiler). Der Release-Workflow cached die Nuitka-Compiler-Ergebnisse und prueft das Bundle vor dem Installer mit `KNiX_Arranger.exe --selftest` (ohne Fenster und Lizenz: Datendateien, Firmenschrift, Qt-Uebersetzung, PDF-Erzeugung, Kryptografie, Excel; Exit-Code 0/1, Details im Log). |
| NFA-072 | Sicherheitskritische Module (Lizenzpruefung, Aktivierungslogik) muessen zusaetzlich geschuetzt werden (z.B. Cython-Kompilierung zu C-Extensions oder PyArmor-Verschluesselung). |
| NFA-072a | Umsetzung: Nuitka uebersetzt alle Programmmodule einschliesslich Lizenzpruefung in C (NFA-071a); eine zusaetzliche Verschluesselung (Cython/PyArmor) entfaellt. |
| NFA-073 | Die ausfuehrbare Datei (.exe) muss mit einem Code-Signing-Zertifikat signiert werden, um die Authentizitaet sicherzustellen und Windows-SmartScreen-Warnungen zu vermeiden. |
| NFA-074 | Das System muss beim Start eine Integritaetspruefung der eigenen Programmdateien durchfuehren (Checksummen/Hashes). Bei erkannter Manipulation muss der Start verweigert und eine Warnung angezeigt werden. |

#### 4.6.3 Rechtlicher Schutz

| ID | Anforderung |
|----|-------------|
| NFA-081 | Beim Erststart bzw. bei der Installation muss dem Benutzer ein Endbenutzer-Lizenzvertrag (EULA) angezeigt werden, der akzeptiert werden muss, bevor die Software genutzt werden kann. |
| NFA-081a | Umsetzung: Die EULA wird beim ersten Programmstart angezeigt und muss akzeptiert werden (gilt auch nach einer Silent-Installation); der Installer zeigt sie nicht. |
| NFA-082 | Die Software muss in der GUI (About-Dialog), im Splash-Screen und in allen generierten Berichten/Exporten einen Copyright-Hinweis anzeigen: "(c) Michael Mueller SmartHome&EnergieManagement. Alle Rechte vorbehalten." |
| NFA-082a | Umsetzung: Copyright im Info-Dialog, im Willkommensbildschirm (anstelle eines Splash-Screens, der Start ist kurz), im EULA-Dialog und in den Dokumenteigenschaften (Produzent) jedes PDF-Berichts. Auf den Berichtsseiten selbst steht er nicht: Sie gehoeren dem Integrator bzw. Bauherrn; die Fusszeile nennt den Lizenznehmer (NFA-098b). |
| NFA-083 | Die EULA muss als externe Textdatei mitgeliefert werden und ohne Codeaenderung aktualisierbar sein. |

#### 4.6.4 Lizenzserver und Verwaltungsinfrastruktur

| ID | Anforderung |
|----|-------------|
| NFA-091 | Es muss ein Lizenzserver (Backend) betrieben werden, der Lizenzschluessel verwaltet, Aktivierungen entgegennimmt und Hardware-Bindungen registriert. Der Server muss als REST-API (HTTPS) erreichbar sein. |
| NFA-092 | Der Lizenzserver muss eine Lizenzdatenbank fuehren mit folgenden Feldern pro Lizenz: |

**Lizenzdatenbank -- Pflichtfelder:**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Lizenzschluessel | Eindeutiger Key | KNiX-A3F2-B8C1-D4E5 |
| Kundenname | Name des Lizenznehmers | Elektro Muster AG |
| E-Mail | Kontakt-E-Mail des Kunden | info@muster-elektro.ch |
| Lizenztyp | Einzelplatz / Jahreslizenz / Testlizenz | Jahreslizenz |
| Erstellt am | Datum der Schluessel-Erstellung | 2026-02-13 |
| Gueltig bis | Ablaufdatum der Lizenz | 2027-02-13 |
| Hardware-ID | Gebundene Hardware-Kennung (nach Aktivierung) | CPU:AB12...MAC:00:1A:... |
| Status | Aktiv / Nicht aktiviert / Gesperrt / Abgelaufen | Aktiv |
| Aktiviert am | Datum der ersten Aktivierung | 2026-02-15 |
| Rechnungsnummer | Zuordnung zur Ausgangsrechnung | RE-2026-0042 |

**Lizenzdatenbank -- optionale Felder:**

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| Kundenadresse | Adresse des Lizenznehmers | Musterstrasse 1, 8000 Zuerich |
| Telefon | Kontakttelefon | +41 44 123 45 67 |
| Bemerkungen | Interne Notizen | Verlängerung besprochen am... |
| Aktivierungs-IP | IP-Adresse bei Aktivierung | 194.230.xx.xx |
| Letzte Pruefung | Datum des letzten Online-Checks | 2026-03-15 |

| ID | Anforderung |
|----|-------------|
| NFA-093 | Der Lizenzserver muss ein Admin-Verwaltungstool (Web-Oberflaeche oder Desktop-Tool) bereitstellen mit folgenden Funktionen: a) Lizenzschluessel generieren (einzeln oder als Batch), b) Schluessel mit Kundendaten verknuepfen, c) Status aller Lizenzen einsehen (aktiv, abgelaufen, nicht aktiviert, gesperrt), d) Lizenzen sperren (bei Missbrauch oder Zahlungsausfall), e) Lizenzen verlaengern (Ablaufdatum anpassen), f) Hardware-Reset durchfuehren (bei Rechnerwechsel des Kunden), g) Aktivierungslog einsehen (wer hat wann von welcher IP aktiviert). |
| NFA-094 | Der Lizenzschluessel-Generator muss kryptografisch sichere, eindeutige Schluessel im Format XXXX-XXXX-XXXX-XXXX erzeugen. Das Praefix "KNiX-" soll als Produktkennung im Schluessel enthalten sein. |
| NFA-095 | Der Lizenzserver muss bei der Aktivierung folgende Pruefungen durchfuehren: a) Ist der Lizenzschluessel gueltig und in der Datenbank vorhanden? b) Ist der Schluessel noch nicht aktiviert oder auf demselben Rechner aktiviert? c) Ist die Lizenz nicht abgelaufen? d) Ist die Lizenz nicht gesperrt? |
| NFA-096 | Die Kommunikation zwischen KNiX Arranger und Lizenzserver muss verschluesselt erfolgen (HTTPS/TLS). Lizenzschluessel und Hardware-IDs duerfen nie im Klartext uebertragen werden. |
| NFA-097 | Der Lizenzserver muss einen periodischen Online-Check unterstuetzen: Die Software prueft in konfigurierbaren Intervallen (z.B. alle 30 Tage) die Lizenzgueltigkeit beim Server. Bei fehlender Internetverbindung muss eine Karenzzeit (z.B. 60 Tage) gewaehrt werden, bevor die Software gesperrt wird. |
| NFA-098 | Fuer den Anfangsbetrieb mit wenigen Kunden muss alternativ ein Offline-Lizenzmodus unterstuetzt werden: Der Lizenzschluessel selbst enthaelt verschluesselt Lizenzinformationen (Typ, Ablaufdatum, Pruefsumme), die lokal validiert werden koennen -- ohne Serveranbindung. |
| NFA-098a | Umsetzung: Die Lizenz ist eine RSA-signierte Datei (.knxlic). Sie kann im Lizenz-Dialog als Datei ausgewaehlt oder als Lizenzschluessel (Praefix "KNIX1-", Base64url der signierten Datei) per Copy-Paste eingefuegt werden; Leerzeichen und Zeilenumbrueche aus der E-Mail werden ignoriert. In beiden Faellen gilt dieselbe Signaturpruefung. Die Lizenz-E-Mail enthaelt Datei und Schluessel. |
| NFA-098b | Der Lizenznehmer (Kunde aus der Lizenz) muss sichtbar sein, damit weitergegebene Kopien zuzuordnen sind: im Info-Dialog ("Lizenziert fuer ..."), in der Fusszeile jedes PDF-Berichts (Mitte) und in den PDF-Dokumenteigenschaften (Ersteller/Produzent) aller PDF-Exporte. |
| NFA-098c | Ein Zurueckstellen der Systemuhr darf eine abgelaufene Lizenz nicht verlaengern: Bei jeder gueltigen Pruefung wird das Datum gespeichert (Datei usage.dat in %APPDATA%\KNiX Arranger und Registry HKCU\Software\KNiX Arranger\LastSeen). Der Ablauf wird ab dem spaeteren Datum aus Systemuhr und gespeichertem Datum berechnet; eine Abweichung von 1 Tag wird toleriert. Ist die Lizenz deshalb abgelaufen, nennt die Meldung das zuletzt verwendete Datum und bittet, Datum und Uhrzeit zu pruefen. |

### 4.7 Systemvoraussetzungen (NFA-100)

| ID | Anforderung |
|----|-------------|
| NFA-101 | Das System muss auf folgender Mindest-Hardwarekonfiguration lauffaehig sein: |

**Minimale Systemvoraussetzungen:**

| Komponente | Mindestanforderung | Empfohlen |
|------------|---------------------|-----------|
| Betriebssystem | Windows 10 (64-Bit), Version 1903 oder neuer | Windows 11 (64-Bit) |
| Prozessor | Intel Core i3 / AMD Ryzen 3 (oder gleichwertig) | Intel Core i5 / AMD Ryzen 5 |
| Arbeitsspeicher (RAM) | 4 GB | 8 GB |
| Festplattenspeicher | 500 MB fuer Installation + 100 MB pro Projekt | 1 GB fuer Installation |
| Bildschirmaufloesung | 1366 x 768 Pixel | 1920 x 1080 Pixel (Full HD) |
| Netzwerk | Internetverbindung fuer Lizenzaktivierung (einmalig) | Breitbandverbindung fuer Online-Updates |
| Sonstiges | .NET Framework 4.7.2 oder neuer (fuer Installer) | -- |

| ID | Anforderung |
|----|-------------|
| NFA-102 | Die Software muss bei Unterschreitung der minimalen Bildschirmaufloesung eine Warnung anzeigen, aber weiterhin bedienbar bleiben (scrollbare Inhalte). |
| NFA-103 | Die Software muss bei Unterschreitung der minimalen RAM-Anforderung eine Warnung im Systemlog ausgeben. |
| NFA-103a | Umsetzung: Statt einer Warnung bleiben alle Inhalte bei kleiner Aufloesung bedienbar (Assistent-Schritte in Bildlaufbereichen, Fenster ab 1100 x 680). Eine RAM-Warnung entfaellt; Arbeitsspeicher und Bildschirm stehen im Crash-Report (NFA-143a). |

### 4.8 Update-Mechanismus (NFA-110)

| ID | Anforderung |
|----|-------------|
| NFA-111 | Die Software muss beim Start automatisch auf verfuegbare Updates pruefen (sofern eine Internetverbindung besteht). **(S)** |
| NFA-112 | Die Update-Pruefung muss den Benutzer ueber neue Versionen informieren: Versionsnummer, Aenderungen (Changelog), Download-Link. Die Pruefung darf den Programmstart nicht blockieren. |
| NFA-113 | Der Benutzer muss Updates manuell herunterladen und installieren koennen (kein erzwungenes Auto-Update). |
| NFA-114 | Der Benutzer muss die automatische Update-Pruefung in den Einstellungen deaktivieren koennen. |
| NFA-114a | Umsetzung: Einstellungen > Allgemein > "Automatisch beim Start pruefen" und gleichlautend im Update-Dialog; beide wirken auf dieselbe Einstellung. MG-Variante und Topologie-Modus werden je Projekt in den Projekteigenschaften gewaehlt, nicht in den Einstellungen. |
| NFA-115 | Das System muss eine manuelle Update-Pruefung ueber das Menue (z.B. "Hilfe > Nach Updates suchen") ermoeglichen. |
| NFA-116 | Fuer zukuenftige Versionen soll ein In-App-Update-Mechanismus vorgesehen werden: Download im Hintergrund, automatische Installation beim naechsten Programmstart. **(W)** |

### 4.9 Datenschutz (NFA-120)

| ID | Anforderung |
|----|-------------|
| NFA-121 | Die Lizenzverwaltung (Server und Admin-Tool) muss die Anforderungen des Schweizerischen Datenschutzgesetzes (DSG, revDSG 2023) einhalten. Bei EU-Kunden ist zusaetzlich die DSGVO zu beruecksichtigen. |
| NFA-122 | Personenbezogene Kundendaten in der Lizenzdatenbank (Name, E-Mail, Adresse, IP-Adresse) muessen verschluesselt gespeichert werden (Encryption at Rest). |
| NFA-123 | Es muss ein Loeschkonzept definiert werden: Kundendaten muessen auf Anfrage geloescht werden koennen (Recht auf Loeschung). Lizenzdaten, die fuer die Rechtsdurchsetzung erforderlich sind, duerfen gemaess gesetzlicher Aufbewahrungsfristen aufbewahrt werden. |
| NFA-124 | Die Software selbst (Desktop-Client) darf keine personenbezogenen Daten an den Hersteller uebermitteln, ausser: a) Lizenzschluessel und Hardware-ID fuer die Aktivierung, b) Versionsnummer fuer die Update-Pruefung. |
| NFA-124a | Umsetzung: Die Update-Pruefung uebermittelt nur die Versionsnummer (im User-Agent), der Online-Produktkatalog und die Datenblaetter werden nur abgerufen. Crash-Reports bleiben lokal (NFA-143a). |
| NFA-125 | Eine Datenschutzerklaerung muss dem Benutzer zugaenglich gemacht werden (im Installer, in der GUI und auf der Produkt-Webseite). |

### 4.10 Installation und Verteilung (NFA-130)

| ID | Anforderung |
|----|-------------|
| NFA-131 | Die Software muss ueber einen professionellen Installer (empfohlen: Inno Setup oder NSIS) installiert werden. Der Installer muss folgende Funktionen bieten: |

**Installer-Funktionen:**

| Funktion | Beschreibung |
|----------|-------------|
| Installationsverzeichnis | Waehlbarer Installationspfad (Standard: `C:\Program Files\KNiX Arranger`) |
| Startmenue-Eintrag | Automatische Erstellung eines Startmenue-Eintrags unter "KNiX Arranger" |
| Desktop-Verknuepfung | Optionale Desktop-Verknuepfung (vom Benutzer waehlbar) |
| Dateierweiterung | Registrierung der Dateierweiterung `.knxarr` mit dem Programm |
| EULA-Anzeige | Anzeige des Endbenutzer-Lizenzvertrags waehrend der Installation |
| Deinstallation | Eintrag in "Programme und Features" (Windows Systemsteuerung) fuer saubere Deinstallation |
| Silent-Install | Unterstuetzung einer Silent-Installation fuer Firmenverteilungen (`/SILENT`-Parameter) |

| ID | Anforderung |
|----|-------------|
| NFA-132 | Der Installer muss die Programmversion, das Code-Signing-Zertifikat und den Herausgeber "Michael Mueller SmartHome&EnergieManagement" anzeigen. |
| NFA-133 | Der Installer muss die Systemvoraussetzungen pruefen (Windows-Version, Bildschirmaufloesung) und bei Nichterfuellung eine Warnung anzeigen. |
| NFA-133a | Umsetzung: Windows 10 oder neuer (64 Bit) ist Voraussetzung (MinVersion); bei einer Aufloesung unter 1366 x 768 fragt der Installer, ob trotzdem installiert werden soll (nicht bei /SILENT). Herausgeber im Installer und in "Programme und Features": "Michael Mueller SmartHome&EnergieManagement" (NFA-132; Code-Signatur zurueckgestellt, NFA-060a). |
| NFA-134 | Benutzerspezifische Daten (Firmenprofil, Projektdateien, Konfiguration, Lizenz) muessen im Benutzerverzeichnis gespeichert werden (`%APPDATA%\KNiX Arranger\`) und bei einer Deinstallation optional beibehalten werden koennen. |
| NFA-134a | Umsetzung: Alle Benutzerdaten liegen in `%APPDATA%\KNiX Arranger\`, auch die Programmeinstellungen (app_settings.json; bis 1.1.31 in `%APPDATA%\KNiXArranger\`, wird beim ersten Start kopiert; die alte Datei bleibt, damit eine aeltere Version weiterhin ihr Arbeitsverzeichnis findet). Projekte liegen im gewaehlten Arbeitsverzeichnis. Die Deinstallation entfernt nur das Programm, Benutzerdaten bleiben immer erhalten. |
| NFA-135 | Die Installationsdatei (.exe) muss als einzelner Download bereitgestellt werden (Groesse < 100 MB). |
| NFA-135a | Stand 07.10.2026: Installer 1.1.31 rund 61 MB. |

### 4.11 Logging und Fehlerprotokollierung (NFA-140)

| ID | Anforderung |
|----|-------------|
| NFA-141 | Die Software muss ein Logfile fuehren, das alle relevanten Aktionen und Fehler protokolliert. Die Logdatei wird im Benutzerverzeichnis gespeichert (`%APPDATA%\KNiX Arranger\logs\`). |
| NFA-142 | Das Logging muss konfigurierbare Log-Level unterstuetzen: DEBUG, INFO, WARNING, ERROR, CRITICAL. Im Normalbetrieb ist das Level INFO aktiv. |
| NFA-142a | Umsetzung: Einstellungen > Allgemein > Protokollstufe (Standard INFO), wirkt sofort und beim naechsten Start. |
| NFA-143 | Bei einem unerwarteten Fehler (Crash) muss die Software einen Crash-Report erstellen, der folgende Informationen enthaelt: Fehlermeldung, Stack-Trace, Systemumgebung (OS-Version, RAM, Bildschirmaufloesung), Softwareversion, letzte Benutzeraktion. |
| NFA-143a | Umsetzung: Crash-Report als `crash_report_JJJJMMTT_hhmmss.txt` im Log-Ordner, bei Fehlern beim Start und im laufenden Betrieb (NFA-041a); letzte Benutzeraktion = zuletzt gewaehlter Menuepunkt, geoeffnete Ansicht oder Assistent-Schritt. Keine Uebermittlung an den Hersteller. |
| NFA-144 | Der Crash-Report muss lokal als Datei gespeichert werden. Eine optionale Uebermittlung an den Hersteller darf nur nach ausdruecklicher Zustimmung des Benutzers erfolgen. |
| NFA-145 | Logdateien muessen automatisch rotiert werden (z.B. max. 10 MB pro Datei, max. 5 Dateien), um den Speicherverbrauch zu begrenzen. |
| NFA-146 | Der Benutzer muss ueber das Menue (z.B. "Hilfe > Logdateien oeffnen") direkten Zugang zu den Logdateien fuer Support-Zwecke erhalten. Umsetzung: "Hilfe > Logdateien oeffnen..." oeffnet den Ordner mit Logdateien und Crash-Reports. |

### 4.12 Internationalisierung (NFA-150)

| ID | Anforderung |
|----|-------------|
| NFA-151 | Die primaere Benutzeroberflaeche muss in **Deutsch** bereitgestellt werden (Erstversion). |
| NFA-152 | Die Software-Architektur muss von Beginn an auf Mehrsprachigkeit ausgelegt sein: Alle Texte der Benutzeroberflaeche (Labels, Meldungen, Tooltips, Menuetexte) muessen in externen Sprachdateien (z.B. JSON oder .po/.mo) ausgelagert werden -- nicht hartcodiert im Quellcode. |
| NFA-153 | Die Software muss einen Sprachwechsel ueber die Einstellungen ermoeglichen. Der Sprachwechsel wird beim naechsten Programmstart wirksam. |
| NFA-154 | Folgende Sprachen sind fuer zukuenftige Versionen vorgesehen: Franzoesisch **(S)**, Englisch **(S)**, Italienisch **(C)**. |
| NFA-155 | Fachbegriffe (KNX-Terminologie wie Hauptgruppe, Mittelgruppe, Gewerk etc.) muessen in einer separaten Fachbegriff-Datei gepflegt werden, damit sie konsistent uebersetzt werden. |
| NFA-156 | Datum-, Zahlen- und Waehrungsformate muessen gemaess der gewaehlten Sprachregion (Locale) formatiert werden (z.B. Deutsch-CH: dd.MM.yyyy, Franzoesisch: dd/MM/yyyy). |
| NFA-156a | Stand 06.10.2026: Die Benutzeroberflaeche gibt es nur auf Deutsch (Formate Deutsch-CH); die Sprachdateien de/en/fr.json sind vorbereitet, aber noch nicht angebunden. Mehrsprachig ist die Bedienungsanleitung fuer den Bauherrn: Deutsch, Franzoesisch, Italienisch, Englisch mit Datumsformat der Sprache (FA-2006). Die Uebersetzung der Oberflaeche ist fuer eine spaetere Version vorgesehen. |

---

## 5. Datenmodell

### 5.1 Projektstruktur

```
KNX-Projekt
+-- Projektname, Projektnummer, Datum
+-- Konfiguration
|   +-- Mittelgruppen-Variante: A oder B
|   +-- Topologie-Modus: TP-64 oder TP-256
|   +-- Backbone-Typ: TP oder IP
|   +-- Bevorzugte Hersteller[]: z.B. ["ABB", "MDT", "Theben"]
|
+-- Gebaeudestruktur
|   +-- Areal (optional)
|       +-- Gebaeude
|           +-- Fluegel (optional)
|               +-- Stockwerk
|                   +-- Name: z.B. "UG", "EG", "1.OG", "DG"
|                   +-- Hauptgruppen-Nr.: z.B. 1, 2, 3, 4
|                   +-- Wohnung/Zone[]
|                       +-- Name: z.B. "Wohnung 1", "Zone Nord"
|                       +-- Raum[]
|                           +-- Raumnummer: z.B. "E01", "E02"
|                           +-- Klartext-Name: z.B. "Schlafzimmer", "Kueche"
|                           +-- Ist-HV/UV-Raum: ja/nein
|                           +-- Geplante Sensoren: z.B. 4 (Standard)
|                           +-- Geplante Aktoren: z.B. 2 (Standard)
|                           +-- Gewerk-Zuweisungen[]
|                           |   +-- Gewerk: z.B. "LD", "J", "H"
|                           |   +-- Anzahl Elemente: z.B. 2
|                           |   +-- Produktdatenblatt[]: PDF-Dateien
|                           +-- Sensor-Zuweisungen[]
|                           |   +-- Sensortyp: z.B. "Taster 4-fach"
|                           |   +-- Produkt: Hersteller, Bestellnummer, Name
|                           |   +-- Produktdatenblatt[]: PDF-Dateien
|                           |   +-- Funktionszuordnung[]
|                           |       +-- Taste/Kanal: z.B. "Taste 1 oben"
|                           |       +-- Funktion: z.B. "LD_E01_01 E/A"
|                           +-- Aktor-Zuweisungen[] (in HV/UV-Raeumen)
|                               +-- Aktortyp: z.B. "Schaltaktor 8-fach"
|                               +-- Produkt: Hersteller, Bestellnummer, Name
|                               +-- Produktdatenblatt[]: PDF-Dateien
|                               +-- Kanalzuordnung[]
|                                   +-- Kanal: z.B. "Ausgang A"
|                                   +-- Gewerk/Raum: z.B. "L_E01_01"
|
+-- KNX-Topologie
|   +-- Bereich[]
|       +-- Bereichs-Nr.: 1-15
|       +-- Name: z.B. "Westfluegel"
|       +-- Bereichskoppler: B.0.0
|       +-- Linie[]
|           +-- Linien-Nr.: 0-15
|           +-- Name: z.B. "Erdgeschoss"
|           +-- Linienkoppler: B.L.0
|           +-- Zugeordnete Stockwerke/Raeume
|           +-- Geraeteanzahl (berechnet: Sensoren + Aktoren)
|           +-- Spannungsversorgung (empfohlen)
|           +-- Zugeordnete UV: z.B. "UV2 (Steigzone)"
|           +-- Geraet[] (aus Topologie-Report oder Aktor-/Sensor-Ermittlung)
|               +-- Physikalische Adresse: z.B. "1.1.1"
|               +-- Hersteller: z.B. "ABB AG"
|               +-- Bestellnummer: z.B. "GH Q631 0047 R0111"
|               +-- Produkt: z.B. "AT/S8.16.5 Schaltaktor, 8fach"
|               +-- Applikationsprogramm: z.B. "Schalten Logik Status Zeit/5"
|               +-- Einbauort: z.B. "UV2 (Steigzone)"
|               +-- Produktdatenblatt[]: PDF-Dateien
|               +-- Kommunikationsobjekt[]
|                   +-- Objektnummer: z.B. 0
|                   +-- Name: z.B. "Ausgang A"
|                   +-- Objektfunktion: z.B. "Schalten"
|                   +-- Prioritaet: z.B. "Niedrig"
|                   +-- Flags: z.B. "K-SUEA-"
|                   +-- Datentyp: z.B. "1 bit"
|                   +-- Verbundene GA[]: z.B. ["3/0/65", "0/0/100"]
|
+-- Gruppenadressen
|   +-- Hauptgruppe (Main)
|       +-- Nummer: 0-31
|       +-- Name: z.B. "Zentral", "EG"
|       +-- Mittelgruppe (Middle)
|           +-- Nummer: 0-7
|           +-- Name: z.B. "Licht", "Jalousie"
|           +-- Untergruppe (Sub)
|               +-- Nummer: 0-255
|               +-- Bezeichnung: z.B. "LD_E05_01 E/A (Eingang Decke)"
|               +-- Volle GA: z.B. "2/0/0"
|               +-- Central: "" | "true"
|               +-- Unfiltered: ""
|               +-- Description: Freitext
|               +-- DatapointType: z.B. "DPST-1-1"
|               +-- Security: z.B. "Auto"
|
+-- Materialliste
    +-- Aktoren[]
    |   +-- Produkt, Hersteller, Bestellnummer, Anzahl, Einzelpreis (opt.)
    +-- Sensoren[]
    |   +-- Produkt, Hersteller, Bestellnummer, Anzahl, Einzelpreis (opt.)
    +-- Gesamtpreis (optional)
```

### 5.2 Bezeichnungskonvention (KNX Swiss Standard)

```
[Gewerk]_[Stockwerk+Raum]_[Nummer] [Funktion] ([Klartext])
```

**Aufbau:**
- **Gewerk**: Kuerzel gemaess Gewerke-Katalog (FA-302), z.B. LD, J, H
- **Stockwerk+Raum**: Raumnummer inkl. Stockwerkspraefix, z.B. E05, UG01, OG03
- **Nummer**: Fortlaufend pro Raum und Gewerk, beginnt bei 01
- **Funktion**: Standard-Funktionsbezeichnung (E/A, DIM, WERT, RM, AUF/AB, STOPP etc.)
- **Klartext**: Optionale Beschreibung in Klammern

**Beispiele:**
- `LD_E05_01 E/A (Eingang Decke)` -- Dimmbares Licht, Raum E05, Element 01, Ein/Aus
- `LD_E05_01 DIM` -- Dimmbares Licht, Raum E05, Element 01, Dimmen
- `LD_E05_01 WERT` -- Dimmbares Licht, Raum E05, Element 01, Wert
- `LD_E05_01 RM` -- Dimmbares Licht, Raum E05, Element 01, Rueckmeldung
- `J_E01_01 AUF/AB (Schlafzimmer Seite Eingang)` -- Jalousie, Raum E01, Element 01
- `H_E01_01 IST` -- Heizung, Raum E01, Element 01, Ist-Temperatur

---

## 6. Anwendungsfaelle

### 6.1 UC-01: Neues KNX-Projekt erstellen

| Feld | Beschreibung |
|------|-------------|
| **Akteur** | KNX-Systemintegrator |
| **Vorbedingung** | Grundrissplaene und Gewerkeliste des Gebaeudes liegen vor |
| **Ablauf** | 1. Benutzer startet den KNX Arranger und waehlt "Neues Projekt". 2. **(Schritt 1)** Benutzer erfasst die Gebaeudestruktur mit Stockwerken oder waehlt eine Vorlage. 3. **(Schritt 2)** Benutzer erstellt Wohnungen/Zonen pro Stockwerk. 4. **(Schritt 3)** Benutzer erstellt Raeume innerhalb der Wohnungen/Zonen. 5. **(Schritt 4)** Benutzer legt die Elektroverteilungen (HV/UV) pro Raum an. 6. **(Schritt 5)** Benutzer weist jedem Raum Gewerke und Elementanzahlen zu, hinterlegt optional Produktdatenblaetter. 7. **(Schritt 6)** Benutzer konfiguriert die physischen Bedienelemente (Tastereinheiten, Melder, Thermostate) pro Raum. 8. **(Schritt 7)** System errechnet anhand der Geraetekonfiguration eine topologisch sinnvolle Linienzuteilung; Benutzer passt die Topologie bei Bedarf an. 9. **(Schritt 8)** System errechnet benoetigte Aktorentypen und schlaegt Produkte vor. Benutzer waehlt Aktoren aus und speichert mit Datenblatt. 10. **(Schritt 9)** Benutzer definiert Szenen. 11. **(Schritt 10)** System generiert automatisch die vollstaendige Gruppenadress-Struktur. 12. **(Schritt 11)** Benutzer ordnet jedem Bedienelement die passenden Gruppenadressen zu; das System schlaegt passende Sensorprodukte vor. 13. **(Schritt 12)** Benutzer erstellt Funktionsdefinitions-Formular fuer den Bauherrn (oder nutzt die Bauherren-Beratungsansicht), liest ausgefuelltes Formular ein und uebernimmt die Zuordnungen. 14. **(Schritt 13)** Benutzer exportiert CSV-Datei fuer ETS6-Import und generiert Projektdokumentation. |
| **Nachbedingung** | Vollstaendige, richtlinienkonforme Gruppenadress-Struktur als CSV, Materialliste, Funktionszuordnungen und Projektdokumentation verfuegbar. |

### 6.2 UC-02: Bestehendes Projekt importieren und analysieren

| Feld | Beschreibung |
|------|-------------|
| **Akteur** | KNX-Systemintegrator |
| **Vorbedingung** | ETS6-Gruppenadress-Export (CSV) liegt vor |
| **Ablauf** | 1. Benutzer waehlt "Projekt importieren" und selektiert die CSV-Datei. 2. System liest die Datei ein und zeigt die Struktur in Baum- und Tabellenansicht an. 3. System leitet Gebaeudestruktur und Topologie rueckwaerts ab. 4. Benutzer klickt "Validieren". 5. System erzeugt den Validierungsbericht mit Fehlern, Warnungen und Empfehlungen. 6. Fehlerhafte Eintraege werden farblich markiert. |
| **Nachbedingung** | Validierungsbericht liegt vor, Abweichungen von den Richtlinien sind sichtbar. |

### 6.3 UC-03: Bestehendes Projekt reorganisieren

| Feld | Beschreibung |
|------|-------------|
| **Akteur** | KNX-Systemintegrator |
| **Vorbedingung** | Mit KNiX geplantes Projekt mit generierten Gruppenadressen (bei aus der ETS importierten Projekten ist die ETS massgebend, dort wird nicht reorganisiert) |
| **Ablauf** | 1. Benutzer waehlt Bearbeiten -> "Adressen neu ordnen...". 2. System baut die Stockwerk-Hauptgruppen lueckenlos neu auf (Adressblocking, Mittelgruppen-Zuordnung, Bezeichnungen). 3. System zeigt Vorher-/Nachher-Vergleich an. 4. Benutzer bestaetigt oder bricht ab. 5. Benutzer exportiert die Gruppenadressen (CSV) fuer die ETS. |
| **Nachbedingung** | Reorganisierte, richtlinienkonforme CSV-Datei verfuegbar. Backup der Originaldaten erstellt. |

### 6.4 UC-04: Topologie visualisieren und dokumentieren

| Feld | Beschreibung |
|------|-------------|
| **Akteur** | KNX-Systemintegrator |
| **Vorbedingung** | Projekt ist geladen (neu oder importiert) |
| **Ablauf** | 1. Benutzer navigiert zur Topologie-Ansicht. 2. System zeigt das Prinzipschema mit Bereichen, Linien, Kopplern und Geraeteanzahlen. 3. Benutzer kann das Schema als Grafik/PDF fuer die Projektdokumentation exportieren. |
| **Nachbedingung** | Prinzipschema ist als Dokumentation verfuegbar. |

---

## 7. Regelwerk (Zusammenfassung)

### 7.1 Topologie-Regeln (aus KNX TP-Topologie und KNX Swiss Richtlinien)

| Regel | Quelle | Beschreibung |
|-------|--------|-------------|
| T-01 | KNX Standard | Max. 256 Busteilnehmer pro Linie (TP-256) |
| T-02 | KNX Standard | Max. 64 Busteilnehmer pro Liniensegment (TP-64, Altanlagen) |
| T-03 | KNX Swiss 8.3.2 | Empfehlung: 85 Teilnehmer planen, max. 100 realisieren |
| T-04 | KNX Standard | Max. 15 Linien pro Bereich (Hauptlinie) |
| T-05 | KNX Standard | Max. 15 Bereiche (Bereichslinie/Backbone) |
| T-06 | KNX Standard | Jede Linie/Hauptlinie/Bereichslinie benoetigt eigene Spannungsversorgung. Umsetzung (geplante Projekte): Bereichslinie 0.0 eine SV (0.0.-) bei mehreren Bereichen und TP-Backbone; Hauptlinie B.0 eine SV (B.0.-) je Bereich mit Hauptlinie (mehrere Bereiche oder mehrere Linien) und TP-Medium; jede Linie B.L eine SV (B.L.-). Ueber IP gefuehrte Haupt- oder Bereichslinien brauchen keine TP-Speisung. Bis 1.1.31 hiess die SV auf B.0.- faelschlich "Bereichslinie" und die SV der Bereichslinie 0.0 fehlte; die Neuberechnung benennt sie um und ergaenzt sie, zugewiesene Produkte bleiben. |
| T-07 | KNX Standard | Max. Leitungslaenge 1.000 m pro Liniensegment |
| T-08 | KNX Standard | Erlaubte Strukturen: Stern, Linie, Baum (keine Ringe) |
| T-09 | KNX Standard | Physikalische Adresse: A.L.0 = Koppler, A.L.1-255 = Teilnehmer |
| T-10 | KNX Swiss 7.1 | Topologie soll Gebaeudestruktur widerspiegeln (Bereich=Fluegel, Linie=Stockwerk) |
| T-11 | KNX Standard | Keine Linienverstärker auf der Bereichslinie erlaubt |

### 7.2 Gruppenadress-Regeln (aus KNX Swiss Projektrichtlinien)

| Regel | Quelle | Beschreibung |
|-------|--------|-------------|
| GA-01 | KNX Swiss 13.1 | Hauptgruppe 0 = Zentraladressen, weitere HG = Stockwerke aufsteigend |
| GA-02 | KNX Swiss 13.2 | Mittelgruppe 0=Licht, 1=Jalousie, 2=Heizung/HLK, 3=Alarm, 4=Allgemein |
| GA-03 | KNX Swiss 13.2 | Variante B: MG 6=Rueckmeldung Licht, MG 7=Rueckmeldung Jalousie |
| GA-04 | KNX Swiss 13.4 | Licht: 5er-Bloecke (E/A, DIM, WERT, RM, RM WERT) |
| GA-05 | KNX Swiss 13.5 | Jalousie: 10er-Bloecke (AUF/AB, STOPP, POS HOEHE, POS LAM, BESCHATTUNG, SPERREN, STATUS HOEHE, STATUS LAM, Reserve, Reserve) |
| GA-06 | KNX Swiss 13.6 | Heizung: 10er-Bloecke (STELLGR, IST, BASIS-SOLL, RM SOLL, BETRIEBSART, STATUS BA, Reserve, Reserve, STOERUNG, SPERREN) |
| GA-07 | KNX Swiss 13.2 | Bei Variante B: Untergruppenadressen der Rueckmeldungen in MG 6/7 muessen identisch zu den Schaltadressen in MG 0/1 sein |
| GA-08 | KNX Standard | Adresse 0/0/0 ist Systemadresse und darf nicht vergeben werden. Das System muss sicherstellen, dass 0/0/0 weder automatisch generiert noch manuell zugewiesen werden kann. Zentraladressen in HG 0 beginnen daher bei 0/0/1. |
| GA-09 | KNX Swiss 10 | Bezeichnung: Gewerk_Raum_Nummer Funktion (Klartext) |

### 7.3 Bezeichnungs-Regeln (aus KNX Swiss Projektrichtlinien Kap. 10)

| Regel | Beschreibung |
|-------|-------------|
| BZ-01 | Label besteht aus: Gewerke-Kuerzel + "_" + Raumnummer + "_" + fortlaufende Nummer |
| BZ-02 | Gewerke-Kuerzel: gemaess Gewerke-Katalog (Kap. 10.1) |
| BZ-03 | Raumnummer: eindeutig pro Stockwerk, auf Grundrissplaenen ersichtlich |
| BZ-03a | Pruefrahmen Raumnummer: Grossbuchstaben A-Z, Ziffern 0-9, "-" und "." nur zwischen Buchstaben/Ziffern (z.B. E01, SEG02, S-EG02, S.EG.02). Kein Unterstrich (Trennzeichen der Bezeichnung), kein Leerzeichen (trennt die Funktion ab). |
| BZ-04 | Fortlaufende Nummer: beginnt pro Raum und Gewerk bei 01 |
| BZ-05 | Optionale Ergaenzung: Raumname und/oder Schaltgruppe in Klammern |
| BZ-06 | Dasselbe Label wird verwendet in: Installationsplan, Elektroschema, ETS |

---

## 8. Abnahmekriterien

| Nr. | Kriterium | Pruefmethode |
|-----|-----------|-------------|
| AK-01 | Ein neues Projekt (EFH mit UG, EG, OG, DG, je 5 Raeume) kann vom 13-Schritt-Wizard vollstaendig erstellt werden inkl. Gebaeudestruktur, Wohnungen/Zonen, Topologie, Gewerke, Aktoren, Gruppenadressen, Sensoren und Funktionsdefinition. | Durchlauf des Wizards mit Testdaten |
| AK-02 | Die generierte Gruppenadress-Struktur entspricht den KNX Swiss Richtlinien (korrekte Hauptgruppen-/Mittelgruppen-Zuordnung, 5er-/10er-Bloecke, Bezeichnungskonzept). | Vergleich mit Referenzstruktur |
| AK-03 | Sowohl Variante A als auch Variante B der Mittelgruppen-Zuordnung erzeugen korrekte Ergebnisse. | Export und manuelle Pruefung beider Varianten |
| AK-04 | Die Referenzdatei ETS6_Chalet.csv (1.082 Zeilen, 6 Hauptgruppen) wird fehlerfrei importiert und die Struktur korrekt dargestellt. | Test mit Referenzdatei |
| AK-04a | Die Referenzdatei Topologie.xlsx (7.901 Zeilen, 1 Bereich, 2 Linien, 70 Geraete) wird fehlerfrei importiert, Topologie und Kommunikationsobjekte korrekt dargestellt. | Test mit Referenzdatei |
| AK-04b | CSV- und XLSX-Import desselben Projekts koennen zusammengefuehrt werden und ergeben eine konsistente Gesamtansicht. | Zusammenfuehrungs-Test |
| AK-05 | Die Validierung der Referenzdatei erkennt mindestens: doppelte Adressen, fehlende DPTs, falsche Mittelgruppen-Zuordnung, inkonsistente Bezeichnungen. | Testdaten mit bekannten Fehlern |
| AK-06 | Der Topologievorschlag fuer ein EFH und einen Zweckbau liefert korrekte Ergebnisse (Geraeteanzahl pro Linie <= Empfehlung, korrekte physikalische Adressen). | Vergleich mit manueller Berechnung |
| AK-07 | Der CSV-Export kann in ETS6 erfolgreich reimportiert werden. | Reimport-Test in ETS6 |
| AK-08 | Die Software laeuft als eigenstaendige .exe ohne Python-Installation. | Test auf Clean-Windows-System |
| AK-09 | Import, Validierung und Generierung der Testdaten erfolgen innerhalb der definierten Zeitgrenzen. | Performance-Messung |
| AK-10 | Das Prinzipschema der Topologie wird korrekt visualisiert und kann exportiert werden. | Visuelle Pruefung und Export-Test |
| AK-11 | Die Software startet ohne gueltige Lizenz nicht (Funktionsumfang gesperrt, Fehlermeldung wird angezeigt). | Test ohne/mit abgelaufener Lizenz |
| AK-12 | Eine gueltige Lizenz kann online aktiviert, an die Hardware gebunden und erfolgreich verifiziert werden. | Aktivierungs-Test auf Testsystem |
| AK-13 | Die .exe-Datei ist mit einem gueltigen Code-Signing-Zertifikat signiert und loest keine SmartScreen-Warnung aus. | Signaturpruefung und Windows-Test |
| AK-14 | Der Copyright-Hinweis ist im About-Dialog, Splash-Screen und auf allen generierten Berichten sichtbar. | Visuelle Pruefung |
| AK-15 | Das Admin-Tool kann Lizenzschluessel generieren, einem Kunden zuordnen und den Status (aktiv/gesperrt/abgelaufen) korrekt anzeigen. | Funktionstest Admin-Tool |
| AK-16 | Ein Hardware-Reset im Admin-Tool ermoeglicht die erneute Aktivierung auf einem anderen Rechner. | Test: Aktivierung -> Reset -> Neuaktivierung |
| AK-17 | Die Offline-Lizenzvalidierung funktioniert korrekt ohne Serveranbindung (Schluessel mit eingebettetem Ablaufdatum). | Test ohne Netzwerkverbindung |
| AK-18 | Die Software laeuft auf einem System mit den minimalen Systemvoraussetzungen (Windows 10, 4 GB RAM, 1366x768) ohne Einschraenkungen. | Test auf Minimal-System |
| AK-19 | Die Update-Pruefung erkennt eine verfuegbare neue Version und zeigt Versionsnummer und Changelog korrekt an. | Test mit simuliertem Update-Server |
| AK-20 | Der Installer installiert die Software korrekt, erstellt Startmenue-/Desktop-Verknuepfungen, registriert die Dateierweiterung .knxarr und deinstalliert rueckstandsfrei. | Installations- und Deinstallationstest |
| AK-21 | Logdateien werden korrekt geschrieben, rotiert (max. 10 MB) und koennen ueber das Hilfemenue geoeffnet werden. | Log-Pruefung nach definiertem Testablauf |
| AK-22 | Die Sprachumschaltung (Deutsch -> Franzoesisch -> Englisch) funktioniert korrekt; alle GUI-Texte werden in der gewaehlten Sprache angezeigt. | Sprachwechsel-Test mit mindestens 2 Sprachen |
| AK-23 | Das kontextsensitive Hilfesystem zeigt fuer jeden Hauptbildschirm (Wizard-Schritte, Topologie, Validierung) die passende Hilfeseite an. | F1-Taste auf jedem Bildschirm pruefen |
| AK-24 | Bei einem simulierten Crash wird ein Crash-Report mit Stack-Trace und Systeminformationen korrekt erstellt und lokal gespeichert. | Provozierter Fehler, Report-Pruefung |
| AK-25 | Personenbezogene Kundendaten in der Lizenzdatenbank sind verschluesselt gespeichert und koennen auf Anfrage geloescht werden. | Datenbankinspektion und Loeschtest |
| AK-26 | Der 13-Schritt-Wizard fuehrt fuer ein EFH (4 Stockwerke, je 4 Raeume) vollstaendig durch alle Schritte inkl. Aktor-/Sensor-Ermittlung und Funktionsdefinition. | Vollstaendiger Wizard-Durchlauf mit Testdaten |
| AK-27 | Die Gebaeudestruktur-Hierarchie (Stockwerk > Wohnung/Zone > Raum) funktioniert korrekt fuer EFH (ohne Wohnungen) und MFH (mit Wohnungen). | Test EFH und MFH mit je 3 Stockwerken |
| AK-28 | Die automatische Linienzuteilung berechnet bei einem Testprojekt (20 Raeume, je 4 Sensoren + 2 Aktoren = 120 Geraete) eine korrekte Topologie mit max. 85 Geraeten pro Linie. | Berechnung pruefen, Vergleich mit manueller Planung |
| AK-29 | Produktdatenblaetter (PDF) koennen importiert, mit Gewerken/Aktoren/Sensoren verknuepft und in der Projektdokumentation ausgegeben werden. | Import-Test, Dokumentations-Export pruefen |
| AK-30 | Die Aktor-Ermittlung erkennt fuer ein Testprojekt (3x LD, 2x J, 2x L, 1x H) korrekt die benoetigten Aktorentypen (Dimmaktor, Jalousieaktor, Schaltaktor, Heizungsaktor). | Vergleich mit manueller Berechnung |
| AK-31 | Das Bauherr-Funktionsdefinitions-Formular kann als Excel exportiert, manuell ausgefuellt und wieder eingelesen werden. Die Zuordnungen erscheinen korrekt im Projekt. | Export -> Ausfuellen -> Reimport-Test |
| AK-32 | Die Materialliste listet alle ausgewaehlten Aktoren und Sensoren mit Hersteller, Bestellnummer und Stueckzahl korrekt auf. | Vergleich mit manuell erstellter Materialliste |
| AK-33 | Eine Offertanfrage wird aus der Materialliste korrekt generiert (PDF und Excel) und enthaelt alle Positionen, Firmenprofil und Projektangaben. | Generierung und visuelle Pruefung des Dokuments |
| AK-34 | Bei einer Sammel-Offertanfrage an 3 Lieferanten werden 3 separate, korrekt adressierte Dokumente mit den jeweils relevanten Positionen erstellt. | Test mit 3 Lieferanten und gemischter Materialliste |
| AK-35 | Der Preisvergleich stellt die Preise von mindestens 2 eingegangenen Offerten korrekt tabellarisch gegenueber und hebt den guenstigsten Anbieter hervor. | Test mit 2 Offerten, manuelle Pruefung der Berechnung |
| AK-36 | Die Kundenofferte berechnet den Gesamtpreis korrekt: Material (inkl. Aufschlag) + Montage + Programmierung + Inbetriebnahme + Nebenkosten - Rabatt + MwSt. | Kalkulation mit Testdaten, manuelle Gegenrechnung |
| AK-37 | Die Kundenofferte wird als professionelles PDF-Dokument mit Deckblatt, Positionsliste, Zusammenfassung und Konditionen korrekt generiert. Beide Detailstufen (detailliert/zusammenfassend) liefern korrekte Ergebnisse. | Visuelle Pruefung beider Varianten |
| AK-38 | Die Offertversionierung erstellt bei Ueberarbeitung eine neue Revision (Rev. A, Rev. B), wobei vorherige Versionen erhalten bleiben und abrufbar sind. | Ueberarbeitung einer Test-Offerte, Pruefung aller Versionen |
| AK-39 | Die Szenen-Definition erzeugt fuer ein Testprojekt (3 Raeume, je 2 Szenen) die korrekten Szenen-Gruppenadressen und eine vollstaendige Szenen-Uebersicht. | Szenen definieren, GA-Generierung pruefen |
| AK-40 | Die Inbetriebnahme-Checkliste wird pro Raum automatisch generiert und enthaelt alle Gewerke, Sensoren und Szenen des Raums als Pruefpunkte. | Generierung fuer Testprojekt, Vollstaendigkeitspruefung |
| AK-41 | Das Abnahmeprotokoll wird korrekt generiert mit Pruefergebnis, Maengelliste und Unterschriftsfeldern. Eine ausgefuellte Excel-Checkliste kann eingelesen werden. | Export -> Ausfuellen -> Import -> Protokoll-Generierung |
| AK-42 | Die Bauherr-Bedienungsanleitung beschreibt fuer ein Testprojekt (5 Raeume) alle Bedienstellen, Szenen und Funktionen in verstaendlicher Sprache. | Generierung und Lesepruefung durch Testperson |
| AK-43 | Die Revisionsunterlagen enthalten alle 13 Bestandteile. Die Vollstaendigkeitspruefung erkennt fehlende Elemente korrekt. | Export als Gesamt-PDF, Pruefung Inhaltsverzeichnis |
| AK-44 | Die Nachkalkulation zeigt den Soll-Ist-Vergleich korrekt an. Die Abweichungen (CHF und %) werden richtig berechnet. | Testdaten eingeben, manuelle Gegenrechnung |

---

## 9. Rahmenbedingungen

### 9.1 Technische Rahmenbedingungen
- Entwicklungssprache: Python 3.x
- GUI-Framework: nach Wahl (z.B. PyQt6, PySide6, wxPython)
- Kompilierung/Paketierung: Nuitka (bevorzugt, nativ kompiliert) oder PyInstaller (alternativ)
- Installer: Inno Setup oder NSIS fuer Windows-Installationspaket
- Unterstuetzte Betriebssysteme: Windows 10, Windows 11 (64-Bit)
- Internationalisierung: Sprachdateien in JSON- oder gettext-Format (.po/.mo)

### 9.2 Organisatorische Rahmenbedingungen
- Die Software wird als Installationspaket (.exe-Installer) ausgeliefert
- Installation in `C:\Program Files\KNiX Arranger\` (konfigurierbar)
- Benutzerdaten in `%APPDATA%\KNiX Arranger\` (Firmenprofil, Projekte, Lizenzdaten, Logs)
- Konfigurationsdateien (Gewerke-Katalog, Adressblock-Schemata, Topologie-Regeln, Sprachdateien) werden im Installationsverzeichnis mitgeliefert
- Projektdateien werden in einem eigenen Format gespeichert (.knxarr o.ae.)

### 9.3 Normative Grundlagen
- KNX-Standard (ISO/IEC 14543-3)
- KNX Swiss Projektrichtlinien 2024
- KNX TP-Topologie (04_Topology_DE0921a)
- EN 50090-3-4 (KNX Secure)

---

## 10. Abgrenzung

Folgende Funktionen sind **nicht** Bestandteil des KNX Arranger:

- Direkte Kommunikation mit dem KNX-Bus oder KNX-Geraeten
- Download/Upload von Applikationsprogrammen in KNX-Geraete
- Parametrierung individueller KNX-Geraete (dies erfolgt in der ETS6)
- Visualisierungserstellung oder Dashboard-Generierung
- Zuordnung von Kommunikationsobjekten zu Gruppenadressen (dies erfolgt in der ETS6)
- Erstellung von Elektrischeschemas oder Installationsplaenen
- KNX-Secure-Konfiguration (Schluesselmanagement, Zertifikate)
- Echtzeit-Busmonitoring oder Diagnose

---

## Anhang A: Beispiel -- Vollstaendige Gruppenadress-Generierung

Beispiel fuer Erdgeschoss (Hauptgruppe 2), Raum E01 (Schlafzimmer):
Gewerke im Raum: 1x LD, 2x J, 1x H

### Variante A (Rueckmeldung in derselben Mittelgruppe)

**Mittelgruppe 0 -- Licht:**
```
2/0/0   LD_E01_01 E/A (Schlafzimmer Decke)           DPST-1-1
2/0/1   LD_E01_01 DIM                                 DPST-3-7
2/0/2   LD_E01_01 WERT                                DPST-5-1
2/0/3   LD_E01_01 RM                                  DPST-1-1
2/0/4   LD_E01_01 RM WERT                             DPST-5-1
```

**Mittelgruppe 1 -- Jalousie:**
```
2/1/0   J_E01_01 AUF/AB (Schlafzimmer Seite Eingang)  DPST-1-8
2/1/1   J_E01_01 STOPP                                DPST-1-7
2/1/2   J_E01_01 POSITION HOEHE                       DPST-5-1
2/1/3   J_E01_01 POSITION LAMELLEN                    DPST-5-1
2/1/4   J_E01_01 BESCHATTUNG                          DPST-1-8
2/1/5   J_E01_01 SPERREN                              DPST-1-1
2/1/6   J_E01_01 STATUS POSITION HOEHE                DPST-5-1
2/1/7   J_E01_01 STATUS POSITION LAMELLEN             DPST-5-1
2/1/8   --
2/1/9   --
2/1/10  J_E01_02 AUF/AB (Schlafzimmer Seite Garten)   DPST-1-8
2/1/11  J_E01_02 STOPP                                DPST-1-7
2/1/12  J_E01_02 POSITION HOEHE                       DPST-5-1
2/1/13  J_E01_02 POSITION LAMELLEN                    DPST-5-1
2/1/14  J_E01_02 BESCHATTUNG                          DPST-1-8
2/1/15  J_E01_02 SPERREN                              DPST-1-1
2/1/16  J_E01_02 STATUS POSITION HOEHE                DPST-5-1
2/1/17  J_E01_02 STATUS POSITION LAMELLEN             DPST-5-1
2/1/18  --
2/1/19  --
```

**Mittelgruppe 2 -- Heizung:**
```
2/2/0   H_E01_01 STELLGROESSE                         DPST-5-1
2/2/1   H_E01_01 IST                                  DPST-9-1
2/2/2   H_E01_01 BASIS-SOLL                           DPST-9-1
2/2/3   H_E01_01 RM AKTUELLER SOLLWERT                DPST-9-1
2/2/4   H_E01_01 UMSCHALTEN BETRIEBSART               DPST-20-102
2/2/5   H_E01_01 STATUS BETRIEBSART                   DPST-20-102
2/2/6   --
2/2/7   --
2/2/8   H_E01_01 STOERUNG                             DPST-1-1
2/2/9   H_E01_01 SPERREN                              DPST-1-1
```

### Variante B (Separate Rueckmeldungs-Mittelgruppen)

**Mittelgruppe 0 -- Licht (ohne RM):**
```
2/0/0   LD_E01_01 E/A (Schlafzimmer Decke)            DPST-1-1
2/0/1   LD_E01_01 DIM                                 DPST-3-7
2/0/2   LD_E01_01 WERT                                DPST-5-1
2/0/3   --
2/0/4   --
```

**Mittelgruppe 6 -- Rueckmeldungen Licht:**
```
2/6/0   LD_E01_01 RM                                  DPST-1-1
2/6/1   --
2/6/2   LD_E01_01 RM WERT                             DPST-5-1
2/6/3   --
2/6/4   --
```

*Hinweis: Die Untergruppen-Adressen in MG 6 entsprechen den korrespondierenden Adressen in MG 0 (Adresse 0 = E/A-RM, Adresse 2 = WERT-RM).*
