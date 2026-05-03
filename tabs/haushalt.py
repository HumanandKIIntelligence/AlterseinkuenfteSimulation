"""Haushalt-Tab – Gemeinsame Einkommensübersicht für Ehepaare."""

from dataclasses import replace as _dc_replace

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from engine import (
    AKTUELLES_JAHR, Profil, RentenErgebnis,
    berechne_haushalt, berechne_rente, einkommensteuer_splitting,
    simuliere_szenarien, _netto_ueber_horizont,
)

try:
    from tabs.hypothek import get_hyp_schedule, get_anschluss_schedule
except ImportError:
    def get_hyp_schedule():
        return []
    def get_anschluss_schedule():
        return []


def _eink_label(profil: "Profil", sel_jahr: int) -> str:
    in_rente = profil.bereits_rentner or sel_jahr >= profil.eintritt_jahr
    if not in_rente:
        return "Brutto"
    return "Pension" if profil.ist_pensionaer else "Rente"


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _vorsorge_non_bav_monatlich(produkte: list[dict], jahr: int,
                                person: str | None = None) -> float:
    """Monatliche Vorsorge-Beiträge (ohne bAV) für das gegebene Jahr."""
    return sum(b for _, b in _vorsorge_non_bav_einzeln(produkte, jahr, person=person))


def _vorsorge_bav_monatlich(produkte: list[dict], jahr: int,
                             person: str | None = None) -> float:
    """Monatliche bAV-Beiträge (AN-Anteil) für das gegebene Jahr."""
    total = 0.0
    for vp in produkte:
        if vp.get("typ") != "bAV":
            continue
        if person is not None and vp.get("person", "Person 1") != person:
            continue
        je = float(vp.get("jaehrl_einzahlung", 0.0))
        if je <= 0.0:
            continue
        if int(vp.get("fruehestes_startjahr", AKTUELLES_JAHR)) <= jahr:
            continue
        bbj = int(vp.get("beitragsbefreiung_jahr", 0))
        if bbj > 0 and jahr >= bbj:
            continue
        dyn = float(vp.get("jaehrl_dynamik", 0.0))
        total += je * (1.0 + dyn) ** max(0, jahr - AKTUELLES_JAHR) / 12.0
    return total


def _vorsorge_non_bav_einzeln(produkte: list[dict], jahr: int,
                               person: str | None = None) -> list[tuple[str, float]]:
    """Liste von (Name, €/Mon.) für aktive nicht-bAV Vorsorge-Beiträge im Jahr.

    person: wenn gesetzt, nur Produkte dieser Person (None = alle Personen).
    LV-Produkte: fruehestes_startjahr gilt nur als Auszahlungszeitpunkt, nicht
    als Beitragsende – Beiträge laufen bis beitragsbefreiung_jahr weiter.
    """
    result: list[tuple[str, float]] = []
    for vp in produkte:
        if vp.get("typ") == "bAV":
            continue
        if person is not None and vp.get("person", "Person 1") != person:
            continue
        je = float(vp.get("jaehrl_einzahlung", 0.0))
        if je <= 0.0:
            continue
        # LV: Beiträge enden nicht am Auszahlungsjahr, sondern per Beitragsbefreiung
        if vp.get("typ") != "LV":
            if int(vp.get("fruehestes_startjahr", AKTUELLES_JAHR)) <= jahr:
                continue
        bbj = int(vp.get("beitragsbefreiung_jahr", 0))
        if bbj > 0 and jahr >= bbj:
            continue
        dyn = float(vp.get("jaehrl_dynamik", 0.0))
        monatlich = je * (1.0 + dyn) ** max(0, jahr - AKTUELLES_JAHR) / 12.0
        result.append((vp.get("name", "Vorsorge"), monatlich))
    return result


def render(
    T: dict,
    p1: Profil,
    p2: Profil,
    e1: RentenErgebnis,
    e2: RentenErgebnis,
    veranlagung: str,
    hh: dict,
    mieteinnahmen: float = 0.0,
    mietsteigerung: float = 0.0,
) -> None:
    _rc = st.session_state.get("_rc", 0)
    _vp_produkte = st.session_state.get("vp_produkte", [])
    _fixausgaben: list[dict] = list(st.session_state.get("hh_fixausgaben", []))
    with T["Haushalt"]:
        st.header("👥 Haushalts-Übersicht")

        veranlagung_label = "Zusammenveranlagung (Splitting)" if veranlagung == "Zusammen" \
            else "Getrennte Veranlagung"

        def _status(p: Profil) -> str:
            if p.bereits_rentner:
                return f"Im Ruhestand seit {p.rentenbeginn_jahr}"
            return f"Renteneintritt {p.eintritt_jahr}"

        st.info(
            f"**Steuerliche Veranlagung:** {veranlagung_label}  |  "
            f"**Person 1:** {_status(p1)}  |  "
            f"**Person 2:** {_status(p2)}"
        )

        # ── Jahres- und Personenfilter ─────────────────────────────────────────
        fil1, fil2 = st.columns([2, 3])
        with fil1:
            ansicht = st.radio(
                "Ansicht",
                ["Haushalt gesamt", "Person 1", "Person 2"],
                horizontal=True, key=f"rc{_rc}_hh_ansicht",
            )
        with fil2:
            # Arbeits- und Renteneinkommen pro Person
            _gehalt_p1 = 0.0 if p1.ist_pensionaer or p1.bereits_rentner else p1.aktuelles_brutto_monatlich
            _gehalt_p2 = 0.0 if p2.ist_pensionaer or p2.bereits_rentner else p2.aktuelles_brutto_monatlich

            # Simulationshorizont: frühester Renteneintritt bis +30 Jahre
            _start_p1 = p1.rentenbeginn_jahr if p1.bereits_rentner else p1.eintritt_jahr
            _start_p2 = p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr
            _start_j_ret = min(_start_p1, _start_p2)
            _end_j = _start_j_ret + 30

            # Slider beginnt ab AKTUELLES_JAHR wenn jemand noch berufstätig ist
            _start_j = AKTUELLES_JAHR if (_gehalt_p1 > 0 or _gehalt_p2 > 0) else _start_j_ret
            _default_j = min(_end_j, max(_start_j, AKTUELLES_JAHR))
            betrachtungsjahr = st.slider(
                "Betrachtungsjahr", _start_j, _end_j, _default_j,
                key=f"rc{_rc}_hh_jahr",
                help="Zeigt projizierte Einkommenswerte für das gewählte Jahr (mit Rentenanpassung).",
            )

        # Laufende Produkte für die Jahressimulation laden
        def _hh_laufende_entsch(person: str | None = None) -> list:
            try:
                from tabs.vorsorge import _aus_dict as _vd, _migriere as _vm
            except ImportError:
                return []
            _entsch = []
            for d in _vp_produkte:
                d = _vm(d)
                if d.get("als_kapitalanlage", False):
                    continue
                if float(d.get("max_monatsrente", 0.0)) <= 0:
                    continue
                if person is not None and d.get("person", "Person 1") != person:
                    continue
                try:
                    _entsch.append((_vd(d), int(d.get("fruehestes_startjahr", AKTUELLES_JAHR + 5)), 0.0))
                except Exception:
                    pass
            return _entsch

        _entsch_all = _hh_laufende_entsch(None)
        _entsch_p1  = _hh_laufende_entsch("Person 1")
        _entsch_p2  = _hh_laufende_entsch("Person 2")

        # Jahresverlauf berechnen (mit laufenden Produkten); individuelle Horizonte je Person
        _horizont_hh = _end_j - _start_j_ret + 1
        _horizont_p1 = max(1, _end_j - _start_p1 + 1)
        _horizont_p2 = max(1, _end_j - _start_p2 + 1)
        _, _jd_zus = _netto_ueber_horizont(
            p1, e1, _entsch_all, _horizont_hh, mieteinnahmen, mietsteigerung,
            profil2=p2, ergebnis2=e2, veranlagung="Zusammen",
        )
        _, _jd_get = _netto_ueber_horizont(
            p1, e1, _entsch_all, _horizont_hh, mieteinnahmen, mietsteigerung,
            profil2=p2, ergebnis2=e2, veranlagung="Getrennt",
        )
        _jd_hh = _jd_zus if veranlagung == "Zusammen" else _jd_get
        _miete_je = mieteinnahmen / 2  # 50/50 je Person bei Paar
        _, _jd_p1 = _netto_ueber_horizont(p1, e1, _entsch_p1, _horizont_p1,
                                           _miete_je, mietsteigerung,
                                           gehalt_monatlich=_gehalt_p1)
        _, _jd_p2 = _netto_ueber_horizont(p2, e2, _entsch_p2, _horizont_p2,
                                           _miete_je, mietsteigerung,
                                           gehalt_monatlich=_gehalt_p2)

        def _row_for_year(jd: list[dict], jahr: int) -> dict | None:
            for r in jd:
                if r["Jahr"] == jahr:
                    return r
            return None

        # _jd_hh startet erst ab P1's Renteneintritt – für frühere Jahre (z.B. wenn P2
        # früher in Rente geht) werden P1- und P2-Einzeldaten addiert.
        _hh_by_y = {r["Jahr"]: r for r in _jd_hh}
        _p1_by_y = {r["Jahr"]: r for r in _jd_p1}
        _p2_by_y = {r["Jahr"]: r for r in _jd_p2}
        _all_jahre = sorted(set(_hh_by_y) | set(_p1_by_y) | set(_p2_by_y))
        _jd_combined: list[dict] = []
        for _j in _all_jahre:
            if _j in _hh_by_y:
                _jd_combined.append(_hh_by_y[_j])
            else:
                _r1 = _p1_by_y.get(_j)
                _r2 = _p2_by_y.get(_j)
                _jd_combined.append({
                    "Jahr":   _j,
                    "Brutto": (_r1["Brutto"] if _r1 else 0) + (_r2["Brutto"] if _r2 else 0),
                    "Netto":  (_r1["Netto"]  if _r1 else 0) + (_r2["Netto"]  if _r2 else 0),
                    "Steuer": (_r1["Steuer"] if _r1 else 0) + (_r2["Steuer"] if _r2 else 0),
                    "KV_PV":  (_r1["KV_PV"]  if _r1 else 0) + (_r2["KV_PV"]  if _r2 else 0),
                    "Src_GesRente": (_r1.get("Src_GesRente", 0) if _r1 else 0),
                    "Src_Gehalt":   (_r1.get("Src_Gehalt", 0) if _r1 else 0),
                    "Src_P2_Rente": (_r2.get("Src_GesRente", 0) + _r2.get("Src_Gehalt", 0) if _r2 else 0),
                    "Src_bAV_P1":    (_r1.get("Src_bAV_P1", 0) if _r1 else 0),
                    "Src_Riester_P1":(_r1.get("Src_Riester_P1", 0) if _r1 else 0),
                    "Src_bAV_P2":    (_r2.get("Src_bAV_P1", 0) if _r2 else 0),
                    "Src_Riester_P2":(_r2.get("Src_Riester_P1", 0) if _r2 else 0),
                    "Src_Miete":     (_r1.get("Src_Miete", 0) if _r1 else 0),
                })

        _row_comb = _row_for_year(_jd_combined, betrachtungsjahr)
        _row_p1   = _row_for_year(_jd_p1,       betrachtungsjahr)
        _row_p2   = _row_for_year(_jd_p2,        betrachtungsjahr)

        # ── Kennzahlen für gewähltes Jahr ─────────────────────────────────────
        st.subheader(f"Monatseinkommen {betrachtungsjahr}")
        c1, c2, c3, c4 = st.columns(4)

        _no_data = False
        if ansicht == "Haushalt gesamt" and _row_comb:
            _b = _row_comb["Brutto"] / 12
            _n = _row_comb["Netto"] / 12
            _s = _row_comb["Steuer"] / 12
            _k = _row_comb["KV_PV"] / 12
            _label = "Haushalt gesamt"
        elif ansicht == "Haushalt gesamt":
            _b = hh["brutto_gesamt"]
            _n = hh["netto_gesamt"]
            _s = hh["steuer_gesamt"]
            _k = hh["kv_gesamt"]
            _label = "Haushalt (Eintrittsmonat)"
        elif ansicht == "Person 1" and _row_p1:
            _b = _row_p1["Brutto"] / 12
            _n = _row_p1["Netto"] / 12
            _s = _row_p1["Steuer"] / 12
            _k = _row_p1["KV_PV"] / 12
            _label = "Person 1"
        elif ansicht == "Person 2" and _row_p2:
            _b = _row_p2["Brutto"] / 12
            _n = _row_p2["Netto"] / 12
            _s = _row_p2["Steuer"] / 12
            _k = _row_p2["KV_PV"] / 12
            _label = "Person 2"
        else:
            _no_data = True
            _start_sel = _start_p1 if ansicht == "Person 1" else _start_p2
            st.info(
                f"Für **{ansicht}** liegen für {betrachtungsjahr} noch keine Daten vor "
                f"(Renteneintritt: {_start_sel}). "
                f"Bruttogehalt im Profil eingeben, um Berufsjahre zu simulieren."
            )

        if not _no_data:
            c1.metric("Brutto", f"{_de(_b)} €",
                      help=f"{_label}: Bruttoeinkommen inkl. Mieteinnahmen")
            c2.metric("Netto", f"{_de(_n)} €")
            c3.metric("Steuer", f"{_de(_s)} €/Mon.")
            c4.metric("KV / PV", f"{_de(_k)} €/Mon.")

        if ansicht == "Haushalt gesamt" and hh["steuerersparnis_splitting"] > 0:
            st.caption(
                f"Splitting-Vorteil (laufend): **{_de(hh['steuerersparnis_splitting'])} €/Mon.** "
                f"| **{_de(hh['steuerersparnis_splitting'] * 12)} €/Jahr**"
            )

        st.divider()

        # ── Mindesthaushaltsbetrag ────────────────────────────────────────────
        with st.expander("🏠 Mindesthaushaltsbetrag", expanded=False):
            st.caption("Monatlicher Mindestbetrag für die Haushaltsversorgung. Wird im Tab 💡 Entnahme-Optimierung als Zielgröße verwendet.")
            _mindest_mono_val = st.number_input(
                "Mindesthaushaltsbetrag (€/Monat)",
                min_value=0, max_value=20_000,
                value=int(st.session_state.get("mindest_haushalt_mono", 2_000)),
                step=100,
                key="mindest_haushalt_mono",
                help=f"Jahreswert: {int(st.session_state.get('mindest_haushalt_mono', 2000)) * 12:,} €/Jahr",
            )
            if _mindest_mono_val > 0:
                st.caption(f"**Jahresbetrag: {_mindest_mono_val * 12:,.0f} €/Jahr**")

        # ── Lebenshaltungskosten ───────────────────────────────────────────────
        with st.expander("💸 Lebenshaltungskosten"):
            lhk1, lhk2 = st.columns(2)
            with lhk1:
                st.number_input(
                    "Person 1 – Lebenshaltungskosten (€/Mon.)", 0.0, 15_000.0,
                    value=float(st.session_state.get(f"rc{_rc}_p1_lhk", 0.0)),
                    step=100.0, key=f"rc{_rc}_p1_lhk",
                    help=(
                        "Monatliche Fixausgaben (Miete, Lebensmittel, Versicherungen …). "
                        "Wird im Planungshorizont jährlich vom Nettoeinkommen abgezogen."
                    ),
                )
            with lhk2:
                st.number_input(
                    "Person 2 – Lebenshaltungskosten (€/Mon.)", 0.0, 15_000.0,
                    value=float(st.session_state.get(f"rc{_rc}_p2_lhk", 0.0)),
                    step=100.0, key=f"rc{_rc}_p2_lhk",
                    help=(
                        "Monatliche Fixausgaben (Miete, Lebensmittel, Versicherungen …). "
                        "Wird im Planungshorizont jährlich vom Nettoeinkommen abgezogen."
                    ),
                )

        # ── Fixe monatliche Ausgaben erfassen ─────────────────────────────────
        with st.expander("➕ Fixe monatliche Ausgaben erfassen"):
            st.caption(
                "Regelmäßige Fixausgaben mit Laufzeit (z.B. Pflegekosten, Abonnements, Mietausgaben). "
                "Werden im Brutto→Verfügbar-Diagramm und im Jahresverlauf berücksichtigt."
            )
            _fa_c1, _fa_c2, _fa_c3, _fa_c4 = st.columns([3, 2, 1, 1])
            with _fa_c1:
                _fa_name = st.text_input("Bezeichnung", key=f"rc{_rc}_hh_fa_name",
                                         placeholder="z.B. Pflegekosten")
            with _fa_c2:
                _fa_betrag = st.number_input("Betrag (€/Mon.)", 0.0, 100_000.0,
                                              value=0.0, step=50.0,
                                              key=f"rc{_rc}_hh_fa_betrag")
            with _fa_c3:
                _fa_start = st.number_input("Ab Jahr", AKTUELLES_JAHR - 10,
                                             AKTUELLES_JAHR + 60, AKTUELLES_JAHR,
                                             step=1, key=f"rc{_rc}_hh_fa_start")
            with _fa_c4:
                _fa_ende = st.number_input("Bis Jahr", AKTUELLES_JAHR,
                                            AKTUELLES_JAHR + 70, AKTUELLES_JAHR + 20,
                                            step=1, key=f"rc{_rc}_hh_fa_ende")
            if st.button("Hinzufügen", key=f"rc{_rc}_hh_fa_add"):
                if _fa_name and _fa_betrag > 0 and int(_fa_ende) >= int(_fa_start):
                    _fixausgaben.append({
                        "name": _fa_name,
                        "betrag_monatlich": float(_fa_betrag),
                        "startjahr": int(_fa_start),
                        "endjahr": int(_fa_ende),
                    })
                    st.session_state["hh_fixausgaben"] = _fixausgaben
                    st.rerun()
            if _fixausgaben:
                st.markdown("**Erfasste Fixausgaben:**")
                _fa_edit_idx = st.session_state.get("hh_fa_edit_idx", -1)
                for _i, _fa in enumerate(_fixausgaben):
                    if _fa_edit_idx == _i:
                        _fe1, _fe2, _fe3, _fe4 = st.columns([3, 2, 1, 1])
                        with _fe1:
                            _ed_name = st.text_input(
                                "Bezeichnung", value=_fa["name"],
                                key=f"rc{_rc}_hh_fa_ed_name_{_i}",
                            )
                        with _fe2:
                            _ed_betrag = st.number_input(
                                "€/Mon.", 0.0, 100_000.0,
                                value=float(_fa["betrag_monatlich"]), step=50.0,
                                key=f"rc{_rc}_hh_fa_ed_betrag_{_i}",
                            )
                        with _fe3:
                            _ed_start = st.number_input(
                                "Ab Jahr", AKTUELLES_JAHR - 10, AKTUELLES_JAHR + 60,
                                value=int(_fa["startjahr"]), step=1,
                                key=f"rc{_rc}_hh_fa_ed_start_{_i}",
                            )
                        with _fe4:
                            _ed_ende = st.number_input(
                                "Bis Jahr", AKTUELLES_JAHR, AKTUELLES_JAHR + 70,
                                value=int(_fa["endjahr"]), step=1,
                                key=f"rc{_rc}_hh_fa_ed_ende_{_i}",
                            )
                        _fs1, _fs2 = st.columns([1, 1])
                        with _fs1:
                            if st.button("✓ Speichern", key=f"rc{_rc}_hh_fa_save_{_i}"):
                                if _ed_name and _ed_betrag > 0 and _ed_ende >= _ed_start:
                                    _fixausgaben[_i] = {
                                        "name": _ed_name,
                                        "betrag_monatlich": float(_ed_betrag),
                                        "startjahr": int(_ed_start),
                                        "endjahr": int(_ed_ende),
                                    }
                                    st.session_state["hh_fixausgaben"] = _fixausgaben
                                    st.session_state["hh_fa_edit_idx"] = -1
                                    st.rerun()
                        with _fs2:
                            if st.button("✕ Abbrechen", key=f"rc{_rc}_hh_fa_cancel_{_i}"):
                                st.session_state["hh_fa_edit_idx"] = -1
                                st.rerun()
                    else:
                        _fl1, _fl2, _fl3 = st.columns([6, 1, 1])
                        with _fl1:
                            st.markdown(
                                f"- **{_fa['name']}**: {_de(_fa['betrag_monatlich'])} €/Mon."
                                f" ({_fa['startjahr']}–{_fa['endjahr']})"
                            )
                        with _fl2:
                            if st.button("✏️", key=f"rc{_rc}_hh_fa_edit_{_i}",
                                         help="Bearbeiten"):
                                st.session_state["hh_fa_edit_idx"] = _i
                                st.rerun()
                        with _fl3:
                            if st.button("🗑️", key=f"rc{_rc}_hh_fa_del_{_i}",
                                         help="Löschen"):
                                _fixausgaben.pop(_i)
                                st.session_state["hh_fixausgaben"] = _fixausgaben
                                st.session_state.pop("hh_fa_edit_idx", None)
                                st.rerun()

        # ── Ausgaben im Planungszeitraum ──────────────────────────────────────
        st.subheader("📤 Ausgaben im Planungszeitraum")

        _ansicht_person = ("Person 1" if ansicht == "Person 1"
                           else "Person 2" if ansicht == "Person 2"
                           else None)
        _ausgaben_rows = []

        # Vorsorgebeiträge: Produkte mit laufenden Beiträgen die noch nicht ausgezahlt werden
        for _vp in _vp_produkte:
            if _ansicht_person is not None and _vp.get("person", "Person 1") != _ansicht_person:
                continue
            _je = float(_vp.get("jaehrl_einzahlung", 0.0))
            if _je <= 0.0:
                continue
            _frueh = int(_vp.get("fruehestes_startjahr", AKTUELLES_JAHR))
            if _frueh <= betrachtungsjahr:
                continue
            _bbj = int(_vp.get("beitragsbefreiung_jahr", 0))
            if _bbj > 0 and betrachtungsjahr >= _bbj:
                continue
            _dyn = float(_vp.get("jaehrl_dynamik", 0.0))
            _jahre_gelaufen = max(0, betrachtungsjahr - AKTUELLES_JAHR)
            _beitrag_j = _je * (1.0 + _dyn) ** _jahre_gelaufen
            _name = _vp.get("bezeichnung") or _vp.get("typ", "Produkt")
            _ausgaben_rows.append({
                "Name / Beschreibung": f"{_name} ({_vp.get('typ', '')})",
                "_jaehrl": _beitrag_j,
            })

        # Fixe Ausgaben für Betrachtungsjahr
        for _fa in _fixausgaben:
            if _fa["startjahr"] <= betrachtungsjahr <= _fa["endjahr"]:
                _ausgaben_rows.append({
                    "Name / Beschreibung": f"{_fa['name']} (Fixausgabe)",
                    "_jaehrl": _fa["betrag_monatlich"] * 12,
                })

        # Hypothek: Jahresausgabe für Betrachtungsjahr
        _hyp_schedule = get_hyp_schedule()
        _hyp_row = next((r for r in _hyp_schedule if r["Jahr"] == betrachtungsjahr), None)
        if _hyp_row is not None:
            _ausgaben_rows.append({
                "Name / Beschreibung": "Hypothek (Annuität + Sondertilgung)",
                "_jaehrl": _hyp_row["Jahresausgabe"],
            })

        if _ausgaben_rows:
            _total_j = sum(r["_jaehrl"] for r in _ausgaben_rows)
            _total_m = _total_j / 12.0

            _df_aus = pd.DataFrame([{
                "Name / Beschreibung": r["Name / Beschreibung"],
                "Jährl. Betrag (€)": _de(r["_jaehrl"]),
                "Monatl. Betrag (€)": _de(r["_jaehrl"] / 12.0),
            } for r in _ausgaben_rows])
            st.dataframe(_df_aus.set_index("Name / Beschreibung"), use_container_width=True)

            out1, out2, out3 = st.columns(3)
            out1.metric("Gesamtausgaben/Jahr", f"{_de(_total_j)} €")
            out2.metric("Gesamtausgaben/Monat", f"{_de(_total_m)} €")

            # Verfügbares Netto nach Abzug der Ausgaben
            if ansicht == "Haushalt gesamt" and _row_comb:
                _netto_hh_m = _row_comb["Netto"] / 12.0
            elif ansicht == "Haushalt gesamt":
                _netto_hh_m = hh["netto_gesamt"]
            else:
                _netto_hh_m = 0.0

            if _netto_hh_m > 0:
                _verfuegbar = _netto_hh_m - _total_m
                out3.metric(
                    "Verfügbares Netto (nach Ausgaben)",
                    f"{_de(_verfuegbar)} €/Mon.",
                    help="Vereinfacht: Netto Haushalt minus monatliche Ausgaben. "
                         "Individuelle Steuerwirkung der Beiträge nicht berücksichtigt.",
                )
        else:
            st.caption(
                f"Für {betrachtungsjahr} liegen keine laufenden Vorsorgebeiträge oder "
                "Hypothekzahlungen vor."
            )

        st.divider()

        # ── Brutto → Netto / Verfügbar Wasserfall ────────────────────────────
        _ansicht_person = ("Person 1" if ansicht == "Person 1"
                           else "Person 2" if ansicht == "Person 2"
                           else None)
        if not _no_data:
            _vorsorge_nbav_einzeln = _vorsorge_non_bav_einzeln(
                _vp_produkte, betrachtungsjahr, person=_ansicht_person
            )
            _vorsorge_nbav_m = sum(b for _, b in _vorsorge_nbav_einzeln)
            _aktive_fix = [
                fa for fa in _fixausgaben
                if fa["startjahr"] <= betrachtungsjahr <= fa["endjahr"]
            ]
            _fix_m_wf = sum(fa["betrag_monatlich"] for fa in _aktive_fix)

            # bAV und Riester aus der aktuellen Zeile extrahieren
            if ansicht == "Haushalt gesamt" and _row_comb:
                _bav_m_wf     = (_row_comb.get("Src_bAV_P1", 0) + _row_comb.get("Src_bAV_P2", 0)) / 12
                _riester_m_wf = (_row_comb.get("Src_Riester_P1", 0) + _row_comb.get("Src_Riester_P2", 0)) / 12
            elif ansicht == "Person 1" and _row_p1:
                _bav_m_wf     = _row_p1.get("Src_bAV_P1", 0) / 12
                _riester_m_wf = _row_p1.get("Src_Riester_P1", 0) / 12
            elif ansicht == "Person 2" and _row_p2:
                _bav_m_wf     = _row_p2.get("Src_bAV_P1", 0) / 12
                _riester_m_wf = _row_p2.get("Src_Riester_P1", 0) / 12
            else:
                _bav_m_wf = _riester_m_wf = 0.0
            _b_basis = _b - _bav_m_wf - _riester_m_wf

            # Hover-Kontext je nach Ansicht
            if ansicht == "Person 1":
                _erg_wf   = e1
                _prof_wf  = p1
                _kv_txt   = f"PKV {_de(p1.pkv_beitrag, 0)} €/Mon. (Fixbetrag)" if p1.krankenversicherung == "PKV" else "GKV-Beitrag (AN-Anteil)"
                _ba_pct   = f"{e1.besteuerungsanteil:.0%}".replace(".", ",")
                _eff_pct  = f"{e1.effektiver_steuersatz:.1%}".replace(".", ",")
                _ver_txt  = ""
            elif ansicht == "Person 2":
                _erg_wf   = e2
                _prof_wf  = p2
                _kv_txt   = f"PKV {_de(p2.pkv_beitrag, 0)} €/Mon. (Fixbetrag)" if p2.krankenversicherung == "PKV" else "GKV-Beitrag (AN-Anteil)"
                _ba_pct   = f"{e2.besteuerungsanteil:.0%}".replace(".", ",")
                _eff_pct  = f"{e2.effektiver_steuersatz:.1%}".replace(".", ",")
                _ver_txt  = ""
            else:  # Haushalt gesamt
                _erg_wf   = e1
                _prof_wf  = p1
                _kv_txt   = "GKV/PKV je Person"
                _ba_pct   = (f"P1: {e1.besteuerungsanteil:.0%} / "
                             f"P2: {e2.besteuerungsanteil:.0%}".replace(".", ","))
                _eff_pct  = f"{e1.effektiver_steuersatz:.1%}".replace(".", ",")
                _ver_txt  = f"<br>{veranlagung_label}"

            _wf_x    = ["Rente/Pension", "− Einkommensteuer", "− KV / PV"]
            _wf_meas = ["absolute", "relative", "relative"]
            _wf_y    = [_b_basis, -_s, -_k]
            _wf_t    = [f"{_de(_b_basis)} €", f"−{_de(_s)} €", f"−{_de(_k)} €"]
            _wf_h    = [
                f"<b>Rente/Pension (brutto)</b><br>"
                f"{_de(_b_basis)} €/Mon.<br>"
                f"Gesetzliche Rente + Zusatzrente vor Steuer und KV.<br>"
                f"Besteuerungsanteil: {_ba_pct} (§ 22 EStG)",
                f"<b>Einkommensteuer + Solidaritätszuschlag</b><br>"
                f"−{_de(_s)} €/Mon.<br>"
                f"§ 32a EStG Grundtarif; eff. Steuersatz {_eff_pct}.{_ver_txt}<br>"
                f"Soli: 5,5 % ab 17.543 € ESt (§ 51a EStG).",
                f"<b>Kranken- + Pflegeversicherung</b><br>"
                f"−{_de(_k)} €/Mon.<br>"
                f"{_kv_txt}.<br>"
                f"PV-Kinderstaffelung: § 55 Abs. 3a SGB XI. BBG: 5.175 €/Mon.",
            ]
            # bAV / Riester als separate Schritte (vor Steuer, grün eingefärbt via increasing)
            if _bav_m_wf > 0:
                _wf_x.insert(1, "+ bAV")
                _wf_meas.insert(1, "relative")
                _wf_y.insert(1, _bav_m_wf)
                _wf_t.insert(1, f"+{_de(_bav_m_wf)} €")
                _wf_h.insert(1,
                    f"<b>Betriebliche Altersversorgung (bAV)</b><br>"
                    f"+{_de(_bav_m_wf)} €/Mon.<br>"
                    f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                    f"KV: abzgl. Freibetrag 187,25 €/Mon. (§ 226 Abs. 2 SGB V)."
                )
            if _riester_m_wf > 0:
                _ins = 2 if _bav_m_wf > 0 else 1
                _wf_x.insert(_ins, "+ Riester")
                _wf_meas.insert(_ins, "relative")
                _wf_y.insert(_ins, _riester_m_wf)
                _wf_t.insert(_ins, f"+{_de(_riester_m_wf)} €")
                _wf_h.insert(_ins,
                    f"<b>Riester-Rente</b><br>"
                    f"+{_de(_riester_m_wf)} €/Mon.<br>"
                    f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                    f"Nicht KVdR-pflichtig (private Rentenleistung)."
                )
            if _vorsorge_nbav_m > 0:
                _vb_detail = "; ".join(f"{n}: {_de(v)} €" for n, v in _vorsorge_nbav_einzeln)
                _wf_x.append("− Vorsorge\n(ohne bAV)")
                _wf_meas.append("relative")
                _wf_y.append(-_vorsorge_nbav_m)
                _wf_t.append(f"−{_de(_vorsorge_nbav_m)} €")
                _wf_h.append(
                    f"<b>Vorsorge-Beiträge (ohne bAV)</b><br>"
                    f"−{_de(_vorsorge_nbav_m)} €/Mon.<br>"
                    f"Laufende Beiträge: {_vb_detail}.<br>"
                    f"Reduzieren das verfügbare Netto während der Beitragsphase."
                )
            if _fix_m_wf > 0:
                _fix_detail = "; ".join(
                    f"{fa['name']}: {_de(fa['betrag_monatlich'])} €" for fa in _aktive_fix
                )
                _wf_x.append("− Fixe Ausgaben")
                _wf_meas.append("relative")
                _wf_y.append(-_fix_m_wf)
                _wf_t.append(f"−{_de(_fix_m_wf)} €")
                _wf_h.append(
                    f"<b>Fixe monatliche Ausgaben</b><br>"
                    f"−{_de(_fix_m_wf)} €/Mon.<br>"
                    f"Summe aktiver Fixausgaben {betrachtungsjahr}.<br>"
                    + (f"{_fix_detail}." if _fix_detail else "")
                )
            _hyp_schedule_wf = get_hyp_schedule()
            _hyp_row_wf = next((r for r in _hyp_schedule_wf if r["Jahr"] == betrachtungsjahr), None)
            _hyp_m_wf = _hyp_row_wf["Jahresausgabe"] / 12 if _hyp_row_wf else 0.0
            if _hyp_m_wf > 0:
                _wf_x.append("− Hypothek")
                _wf_meas.append("relative")
                _wf_y.append(-_hyp_m_wf)
                _wf_t.append(f"−{_de(_hyp_m_wf)} €")
                _wf_h.append(
                    f"<b>Hypothek-Jahresrate</b><br>"
                    f"−{_de(_hyp_m_wf)} €/Mon.<br>"
                    f"Annuität {betrachtungsjahr} (Zins + Tilgung).<br>"
                    f"Konfiguration im Tab Hypothek-Verwaltung."
                )
            _ak_schedule_wf = get_anschluss_schedule()
            _ak_row_wf = next((r for r in _ak_schedule_wf if r["Jahr"] == betrachtungsjahr), None)
            _ak_m_wf = _ak_row_wf["Jahresausgabe"] / 12 if _ak_row_wf else 0.0
            if _ak_m_wf > 0:
                _wf_x.append("− Anschlusskredit")
                _wf_meas.append("relative")
                _wf_y.append(-_ak_m_wf)
                _wf_t.append(f"−{_de(_ak_m_wf)} €")
                _wf_h.append(
                    f"<b>Anschlussfinanzierung</b><br>"
                    f"−{_de(_ak_m_wf)} €/Mon.<br>"
                    f"Annuität auf Restschuld nach Hypothek-Endjahr."
                )
            # Lebenshaltungskosten
            _lhk_p1 = float(st.session_state.get(f"rc{_rc}_p1_lhk", 0.0))
            _lhk_p2 = float(st.session_state.get(f"rc{_rc}_p2_lhk", 0.0))
            if ansicht == "Person 1":
                _lhk_m_wf = _lhk_p1
            elif ansicht == "Person 2":
                _lhk_m_wf = _lhk_p2
            else:
                _lhk_m_wf = _lhk_p1 + _lhk_p2
            if _lhk_m_wf > 0:
                _wf_x.append("− Lebenshalt.")
                _wf_meas.append("relative")
                _wf_y.append(-_lhk_m_wf)
                _wf_t.append(f"−{_de(_lhk_m_wf)} €")
                _wf_h.append(
                    f"<b>Lebenshaltungskosten</b><br>"
                    f"−{_de(_lhk_m_wf)} €/Mon.<br>"
                    f"Monatliche Fixkosten (Miete, Lebensmittel …).<br>"
                    f"Konfiguration im Expander 'Lebenshaltungskosten'."
                )

            _verfuegbar_m = _n - _vorsorge_nbav_m - _fix_m_wf - _hyp_m_wf - _ak_m_wf - _lhk_m_wf
            _wf_x.append("Verfügbar")
            _wf_meas.append("total")
            _wf_y.append(_verfuegbar_m)
            _wf_t.append(f"{_de(_verfuegbar_m)} €")
            _wf_h.append(
                f"<b>Verfügbares Einkommen</b><br>"
                f"{_de(_verfuegbar_m)} €/Mon.<br>"
                f"Nach Steuer, KV/PV, Vorsorge-Beiträgen, Lebenshaltungskosten und Fixausgaben."
            )
            st.subheader(f"Brutto → Verfügbar {betrachtungsjahr} ({_label})")
            fig_wf_hh = go.Figure(go.Waterfall(
                orientation="v", measure=_wf_meas, x=_wf_x, y=_wf_y, text=_wf_t,
                textposition="outside",
                customdata=_wf_h,
                hovertemplate="%{customdata}<extra></extra>",
                connector=dict(line=dict(color="#888")),
                increasing=dict(marker=dict(color="#4CAF50")),
                decreasing=dict(marker=dict(color="#F44336")),
                totals=dict(marker=dict(color="#2196F3")),
            ))
            fig_wf_hh.update_layout(
                template="plotly_white", height=380,
                yaxis=dict(title="€ / Monat", ticksuffix=" €"),
                margin=dict(l=10, r=10, t=10, b=10),
                separators=",.",
            )
            _mindest_m_wf = float(st.session_state.get("mindest_haushalt_mono", 2_000))
            fig_wf_hh.add_hline(
                y=_mindest_m_wf, line_dash="dot", line_color="orange", line_width=2,
                annotation_text=f"Mindest {_de(_mindest_m_wf)} €",
                annotation_position="top right",
            )
            st.plotly_chart(fig_wf_hh, use_container_width=True)
            # Infobox für bAV / Riester
            if _bav_m_wf > 0 or _riester_m_wf > 0:
                _info_parts = []
                if _bav_m_wf > 0:
                    _info_parts.append(
                        f"**+ bAV ({_de(_bav_m_wf)} €/Mon.):** Betriebliche Altersversorgung – "
                        f"laufende monatliche Auszahlungen aus Vorsorge-Bausteinen. "
                        f"100 % steuerpflichtig (§ 19/§ 22 Nr. 5 EStG), KVdR-pflichtig (§ 229 SGB V, Freibetrag {_de(187.25)} €/Mon.)."
                    )
                if _riester_m_wf > 0:
                    _info_parts.append(
                        f"**+ Riester ({_de(_riester_m_wf)} €/Mon.):** Riester-Rente – "
                        f"laufende monatliche Auszahlungen. "
                        f"100 % steuerpflichtig (§ 22 Nr. 5 EStG), nicht KVdR-pflichtig."
                    )
                st.info("  \n".join(_info_parts))
            if _vorsorge_nbav_einzeln:
                _vb_lines = "  \n".join(
                    f"**{_vn}:** {_de(_vm)} €/Mon."
                    for _vn, _vm in _vorsorge_nbav_einzeln
                )
                st.caption(f"Vorsorge-Abzüge (ohne bAV):  \n{_vb_lines}")

        st.divider()

        # ── Jahresverlauf (Haushalt) ──────────────────────────────────────────
        st.subheader("Jahresverlauf")
        if ansicht == "Haushalt gesamt":
            _jd_display = _jd_combined
            _label_netto = "Netto Haushalt"
        elif ansicht == "Person 1":
            _jd_display = _jd_p1
            _label_netto = "Netto Person 1"
        else:
            _jd_display = _jd_p2
            _label_netto = "Netto Person 2"

        if _jd_display:
            _df = pd.DataFrame(_jd_display).set_index("Jahr")

            # ── Blended Brutto für Renteneintritts-Jahr ───────────────────────
            # Für jede angezeigte Person: Brutto im Eintrittsjahr anteilig aus
            # Gehalt (Monate 1..m-1) + Rente (Monate m..12) berechnen.
            def _blend_brutto(prof, jd_single: list[dict]) -> None:
                if prof.bereits_rentner:
                    return
                ej = prof.eintritt_jahr
                m = prof.renteneintritt_monat   # 1–12; 1 = ganzes Jahr Rente
                if m <= 1 or ej not in _df.index:
                    return
                _by_y = {r["Jahr"]: r for r in jd_single}
                pension_mono = _by_y.get(ej, {}).get("Src_GesRente", 0.0) / 12
                # Gehalt des Vorjahres als Monatsgehalt (letztes Arbeitsjahr)
                prev = _by_y.get(ej - 1)
                if prev is None:
                    return
                salary_mono = prev.get("Src_Gehalt", 0.0) / 12
                m_before = m - 1
                m_after  = 12 - m_before
                blended  = m_before * salary_mono + m_after * pension_mono
                _df.loc[ej, "Brutto"] = blended * 12

            if ansicht == "Person 1":
                _blend_brutto(p1, _jd_p1)
            elif ansicht == "Person 2":
                _blend_brutto(p2, _jd_p2)
            else:
                # Haushalt gesamt: blend each person in their individual series,
                # then rebuild combined Brutto for the affected years
                _p1_by_y_orig = {r["Jahr"]: r for r in _jd_p1}
                _p2_by_y_orig = {r["Jahr"]: r for r in _jd_p2}
                for _prof, _jd_s in ((p1, _jd_p1), (p2, _jd_p2)):
                    if _prof.bereits_rentner or _prof.renteneintritt_monat <= 1:
                        continue
                    _ej = _prof.eintritt_jahr
                    if _ej not in _df.index:
                        continue
                    _by_y = {r["Jahr"]: r for r in _jd_s}
                    _pm = _by_y.get(_ej, {}).get("Src_GesRente", 0.0) / 12
                    _prev = _by_y.get(_ej - 1)
                    if _prev is None:
                        continue
                    _sm = _prev.get("Src_Gehalt", 0.0) / 12
                    _mb = _prof.renteneintritt_monat - 1
                    _ma = 12 - _mb
                    _bl = (_mb * _sm + _ma * _pm) * 12
                    # Difference to replace in combined df
                    _old = _by_y.get(_ej, {}).get("Brutto", 0.0)
                    _df.loc[_ej, "Brutto"] = _df.loc[_ej, "Brutto"] - _old + _bl

            # ── Jahresverlauf mit Abzügen ─────────────────────────────────────
            _alle_jahre = list(_df.index)
            _vbnbav_py = {j: _vorsorge_non_bav_monatlich(_vp_produkte, j,
                                                           person=_ansicht_person)
                         for j in _alle_jahre}
            _bav_beitrag_py = {j: _vorsorge_bav_monatlich(_vp_produkte, j,
                                                           person=_ansicht_person)
                               for j in _alle_jahre}
            _hyp_sched_jv  = get_hyp_schedule()
            _ak_sched_jv   = get_anschluss_schedule()
            _hyp_py = {
                j: (next((r["Jahresausgabe"] for r in _hyp_sched_jv if r["Jahr"] == j), 0.0)
                    + next((r["Jahresausgabe"] for r in _ak_sched_jv if r["Jahr"] == j), 0.0)) / 12
                for j in _alle_jahre
            }
            _fix_py    = {
                j: sum(fa["betrag_monatlich"] for fa in _fixausgaben
                       if fa["startjahr"] <= j <= fa["endjahr"])
                for j in _alle_jahre
            }
            _lhk_p1_jv = float(st.session_state.get(f"rc{_rc}_p1_lhk", 0.0))
            _lhk_p2_jv = float(st.session_state.get(f"rc{_rc}_p2_lhk", 0.0))
            if ansicht == "Person 1":
                _lhk_m_jv = _lhk_p1_jv
            elif ansicht == "Person 2":
                _lhk_m_jv = _lhk_p2_jv
            else:
                _lhk_m_jv = _lhk_p1_jv + _lhk_p2_jv
            _lhk_py = {j: _lhk_m_jv for j in _alle_jahre}
            _verfuegbar_py = {
                j: (_df.loc[j, "Netto"] / 12)
                   - _bav_beitrag_py[j] - _vbnbav_py[j]
                   - _fix_py[j] - _lhk_py[j] - _hyp_py[j]
                for j in _alle_jahre
            }
            # Hover-Breakdown: alle aktiven Abzüge je Jahr
            def _jv2_hover(j: int) -> str:
                parts = []
                if _bav_beitrag_py[j] > 0:
                    parts.append(f"bAV-Beitrag: −{_de(_bav_beitrag_py[j])} €/Mon.")
                if _vbnbav_py[j] > 0:
                    parts.append(f"Vorsorge: −{_de(_vbnbav_py[j])} €/Mon.")
                if _hyp_py[j] > 0:
                    parts.append(f"Hypothek: −{_de(_hyp_py[j])} €/Mon.")
                if _lhk_py[j] > 0:
                    parts.append(f"Lebenshalt.: −{_de(_lhk_py[j])} €/Mon.")
                if _fix_py[j] > 0:
                    parts.append(f"Fixausgaben: −{_de(_fix_py[j])} €/Mon.")
                return "<br>".join(parts)
            _cd_jv2 = [_jv2_hover(j) for j in _alle_jahre]
            fig_jv2 = go.Figure()
            fig_jv2.add_trace(go.Bar(
                name="Brutto", x=_alle_jahre,
                y=[_df.loc[j, "Brutto"] / 12 for j in _alle_jahre],
                marker_color="#90CAF9",
                hovertemplate="%{x}: %{y:,.0f} €/Mon.<extra>Brutto</extra>",
            ))
            if any(_bav_beitrag_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− bAV-Beiträge (AN)", x=_alle_jahre,
                    y=[-_bav_beitrag_py[j] for j in _alle_jahre],
                    marker_color="#F48FB1",
                    customdata=_cd_jv2,
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>bAV-Beitrag</extra>",
                ))
            if any(_vbnbav_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Vorsorge (ohne bAV)", x=_alle_jahre,
                    y=[-_vbnbav_py[j] for j in _alle_jahre],
                    marker_color="#EF9A9A",
                    customdata=_cd_jv2,
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>Vorsorge-Abzug</extra>",
                ))
            if any(_hyp_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Hypothek", x=_alle_jahre,
                    y=[-_hyp_py[j] for j in _alle_jahre],
                    marker_color="#B0BEC5",
                    customdata=_cd_jv2,
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>Hypothek</extra>",
                ))
            if _lhk_m_jv > 0:
                fig_jv2.add_trace(go.Bar(
                    name="− Lebenshaltungskosten", x=_alle_jahre,
                    y=[-_lhk_py[j] for j in _alle_jahre],
                    marker_color="#CE93D8",
                    customdata=_cd_jv2,
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>Lebenshaltungskosten</extra>",
                ))
            if any(_fix_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Fixausgaben", x=_alle_jahre,
                    y=[-_fix_py[j] for j in _alle_jahre],
                    marker_color="#FFCC80",
                    customdata=_cd_jv2,
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>Fixausgaben</extra>",
                ))
            fig_jv2.add_trace(go.Scatter(
                name=_label_netto, x=_alle_jahre,
                y=[_df.loc[j, "Netto"] / 12 for j in _alle_jahre],
                mode="lines+markers", line=dict(color="#4CAF50", width=2),
                customdata=_cd_jv2,
                hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>Netto</extra>",
            ))
            fig_jv2.add_trace(go.Scatter(
                name="Verfügbar (nach Abzügen)", x=_alle_jahre,
                y=[_verfuegbar_py[j] for j in _alle_jahre],
                mode="lines+markers",
                line=dict(color="#FF9800", width=2, dash="dash"),
                customdata=_cd_jv2,
                hovertemplate="%{x}: %{y:,.0f} €/Mon.<br>%{customdata}<extra>Verfügbar</extra>",
            ))
            fig_jv2.add_vline(
                x=betrachtungsjahr, line_width=1, line_dash="dash",
                line_color="#FF9800",
                annotation_text=str(betrachtungsjahr),
                annotation_position="top right",
            )
            _mindest_jv = float(st.session_state.get("mindest_haushalt_mono", 2_000))
            fig_jv2.add_hline(
                y=_mindest_jv, line_dash="dot", line_color="orange", line_width=2,
                annotation_text=f"Mindest {_de(_mindest_jv)} €",
                annotation_position="top right",
            )
            fig_jv2.update_layout(
                barmode="overlay", template="plotly_white", height=400,
                xaxis=dict(title="Jahr", dtick=2),
                yaxis=dict(title="€ / Monat", tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=10, r=10, t=40, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_jv2, use_container_width=True)

        st.divider()

        # ── Szenarien-Vergleich Haushalt ──────────────────────────────────────
        st.subheader(f"Haushalt-Szenarien {betrachtungsjahr} (pessimistisch / neutral / optimistisch)")

        sz1 = simuliere_szenarien(p1)
        sz2 = simuliere_szenarien(p2)
        _sz_params = {
            "Pessimistisch": (0.01, 0.03),
            "Neutral":       (p1.rentenanpassung_pa, p1.rendite_pa),
            "Optimistisch":  (0.03, 0.07),
        }
        # Genaue Jahressimulation je Szenario (korrekte Steuerprogression)
        _hh_sz_jd: dict[str, dict[int, dict]] = {}
        _p1_sz_jd: dict[str, dict[int, dict]] = {}
        _p2_sz_jd: dict[str, dict[int, dict]] = {}
        for _nm, (_rpa, _kpa) in _sz_params.items():
            _p1_n = _dc_replace(p1, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
            _e1_n = berechne_rente(_p1_n)
            _p2_n = _dc_replace(p2, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
            _e2_n = berechne_rente(_p2_n)
            _, _jd_hh = _netto_ueber_horizont(
                _p1_n, _e1_n, [], _horizont_hh, mieteinnahmen, mietsteigerung,
                profil2=_p2_n, ergebnis2=_e2_n, veranlagung=veranlagung,
            )
            _, _jd_p1 = _netto_ueber_horizont(_p1_n, _e1_n, [], _horizont_p1, _miete_je, mietsteigerung)
            _, _jd_p2 = _netto_ueber_horizont(_p2_n, _e2_n, [], _horizont_p2, _miete_je, mietsteigerung)
            _hh_sz_jd[_nm] = {r["Jahr"]: r for r in _jd_hh}
            _p1_sz_jd[_nm] = {r["Jahr"]: r for r in _jd_p1}
            _p2_sz_jd[_nm] = {r["Jahr"]: r for r in _jd_p2}

        rows = []
        for name in ["Pessimistisch", "Neutral", "Optimistisch"]:
            _row_hh = _hh_sz_jd[name].get(betrachtungsjahr)
            _row_p1 = _p1_sz_jd[name].get(betrachtungsjahr)
            _row_p2 = _p2_sz_jd[name].get(betrachtungsjahr)
            rows.append({
                "Szenario": name,
                "Brutto gesamt (€/Mon.)": _de(_row_hh["Brutto"] / 12 if _row_hh else (sz1[name].brutto_monatlich + sz2[name].brutto_monatlich)),
                "Netto gesamt (€/Mon.)":  _de(_row_hh["Netto"]  / 12 if _row_hh else (sz1[name].netto_monatlich  + sz2[name].netto_monatlich)),
                "Netto Person 1":         _de(_row_p1["Netto"]  / 12 if _row_p1 else sz1[name].netto_monatlich),
                "Netto Person 2":         _de(_row_p2["Netto"]  / 12 if _row_p2 else sz2[name].netto_monatlich),
            })
        st.dataframe(pd.DataFrame(rows).set_index("Szenario"), use_container_width=True)
        st.caption("Vollständige Jahressimulation mit korrekter Steuerprogression (keine Näherung).")

        st.divider()

        # ── Seite-an-Seite Vergleich ──────────────────────────────────────────
        if ansicht != "Haushalt gesamt":
            # Einzelpersonen-Ansicht – Slider-Jahr oder Eintrittsmonat als Fallback
            _e   = e1 if ansicht == "Person 1" else e2
            _p   = p1 if ansicht == "Person 1" else p2
            _row = _row_p1 if ansicht == "Person 1" else _row_p2
            _b_d = _row["Brutto"] / 12 if _row else _e.brutto_monatlich
            _n_d = _row["Netto"]  / 12 if _row else _e.netto_monatlich
            _s_d = _row["Steuer"] / 12 if _row else _e.steuer_monatlich
            _k_d = _row["KV_PV"]  / 12 if _row else _e.kv_monatlich
            _note = "" if _row else " (Eintrittsmonat)"
            st.subheader(f"{ansicht} – {betrachtungsjahr}{_note}")
            cv1, cv2 = st.columns(2)
            with cv1:
                for label, wert in [
                    ("Bruttoeinkommen", f"{_de(_b_d)} €"),
                    ("− Steuer", f"{_de(_s_d)} €"),
                    ("− KV / PV", f"{_de(_k_d)} €"),
                    ("**= Netto**", f"**{_de(_n_d)} €**"),
                    ("Rentenpunkte", f"{_e.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Renteneintritt",
                     str(_p.rentenbeginn_jahr if _p.bereits_rentner else _p.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)
        else:
            # Jahr-spezifische Werte aus Slider; Fallback auf Eintrittsmonat
            _p1_b = _row_p1["Brutto"] / 12 if _row_p1 else e1.brutto_monatlich
            _p1_n = _row_p1["Netto"]  / 12 if _row_p1 else e1.netto_monatlich
            _p1_s = _row_p1["Steuer"] / 12 if _row_p1 else e1.steuer_monatlich
            _p1_k = _row_p1["KV_PV"]  / 12 if _row_p1 else e1.kv_monatlich
            _p2_b = _row_p2["Brutto"] / 12 if _row_p2 else e2.brutto_monatlich
            _p2_n = _row_p2["Netto"]  / 12 if _row_p2 else e2.netto_monatlich
            _p2_s = _row_p2["Steuer"] / 12 if _row_p2 else e2.steuer_monatlich
            _p2_k = _row_p2["KV_PV"]  / 12 if _row_p2 else e2.kv_monatlich
            _note = "" if (_row_p1 and _row_p2) else " (Eintrittsmonat)"

            st.subheader(f"Person 1 vs. Person 2 – {betrachtungsjahr}{_note}")
            col1, col2, col3 = st.columns([2, 2, 3])

            with col1:
                st.markdown("**Person 1**")
                for label, wert in [
                    ("Bruttoeinkommen", f"{_de(_p1_b)} €"),
                    ("− Steuer", f"{_de(_p1_s)} €"),
                    ("− KV / PV", f"{_de(_p1_k)} €"),
                    ("**= Netto**", f"**{_de(_p1_n)} €**"),
                    ("Rentenpunkte", f"{e1.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Ruhestand seit" if p1.bereits_rentner else "Renteneintritt",
                     str(p1.rentenbeginn_jahr if p1.bereits_rentner else p1.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)

            with col2:
                st.markdown("**Person 2**")
                for label, wert in [
                    ("Bruttoeinkommen", f"{_de(_p2_b)} €"),
                    ("− Steuer", f"{_de(_p2_s)} €"),
                    ("− KV / PV", f"{_de(_p2_k)} €"),
                    ("**= Netto**", f"**{_de(_p2_n)} €**"),
                    ("Rentenpunkte", f"{e2.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Ruhestand seit" if p2.bereits_rentner else "Renteneintritt",
                     str(p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)

            with col3:
                # Stacked bar: Netto + Steuer + KV = Brutto (Total-Höhe)
                personen = ["Person 1", "Person 2"]
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="Netto", x=personen, y=[_p1_n, _p2_n],
                    marker_color="#A5D6A7",
                    text=[f"{_de(_p1_n)} €", f"{_de(_p2_n)} €"],
                    textposition="inside",
                ))
                fig.add_trace(go.Bar(
                    name="− Steuer", x=personen, y=[_p1_s, _p2_s],
                    marker_color="#EF9A9A",
                    text=[f"{_de(_p1_s)} €", f"{_de(_p2_s)} €"],
                    textposition="inside",
                ))
                fig.add_trace(go.Bar(
                    name="− KV/PV", x=personen, y=[_p1_k, _p2_k],
                    marker_color="#FFF176",
                    text=[f"{_de(_p1_k)} €", f"{_de(_p2_k)} €"],
                    textposition="inside",
                ))
                fig.update_layout(
                    barmode="stack",
                    template="plotly_white",
                    height=320,
                    yaxis=dict(title="€ / Monat (Brutto = Gesamthöhe)"),
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(l=0, r=0, t=30, b=0),
                    separators=",.",
                )
                st.plotly_chart(fig, use_container_width=True)

        if mieteinnahmen > 0:
            st.info(
                f"🏠 **Mieteinnahmen:** {_de(mieteinnahmen)} €/Monat "
                f"(+{mietsteigerung:.1%}".replace(".", ",") +
                " p.a.) – in Steuerberechnung enthalten, keine KV-Pflicht."
            )

        st.divider()

        # ── Steuervergleich: Zusammen vs. Getrennt ────────────────────────────
        st.subheader(f"Steuervergleich {betrachtungsjahr}: Zusammen- vs. Getrennte Veranlagung")

        _row_zus = _row_for_year(_jd_zus, betrachtungsjahr)
        _row_get = _row_for_year(_jd_get, betrachtungsjahr)

        # Fallback auf Eintrittsmonat wenn kein Jahreseintrag verfügbar
        hh_zusammen = berechne_haushalt(e1, e2, "Zusammen", mieteinnahmen, p1, p2)
        hh_getrennt  = berechne_haushalt(e1, e2, "Getrennt",  mieteinnahmen, p1, p2)
        _st_zus = _row_zus["Steuer"] / 12 if _row_zus else hh_zusammen["steuer_gesamt"]
        _st_get = _row_get["Steuer"] / 12 if _row_get else hh_getrennt["steuer_gesamt"]
        _nt_zus = _row_zus["Netto"]  / 12 if _row_zus else hh_zusammen["netto_gesamt"]
        _nt_get = _row_get["Netto"]  / 12 if _row_get else hh_getrennt["netto_gesamt"]
        _kv_zus = _row_zus["KV_PV"]  / 12 if _row_zus else hh_zusammen["kv_gesamt"]
        _kv_get = _row_get["KV_PV"]  / 12 if _row_get else hh_getrennt["kv_gesamt"]

        # Individuelle P1/P2 Werte (aus Einzelsimulationen)
        _st_p1 = _row_p1["Steuer"] / 12 if _row_p1 else e1.steuer_monatlich
        _nt_p1 = _row_p1["Netto"]  / 12 if _row_p1 else e1.netto_monatlich
        _kv_p1 = _row_p1["KV_PV"]  / 12 if _row_p1 else e1.kv_monatlich
        _st_p2 = _row_p2["Steuer"] / 12 if _row_p2 else e2.steuer_monatlich
        _nt_p2 = _row_p2["Netto"]  / 12 if _row_p2 else e2.netto_monatlich
        _kv_p2 = _row_p2["KV_PV"]  / 12 if _row_p2 else e2.kv_monatlich

        # Zeile 1: Steuer
        sv1, sv2, sv3, sv4 = st.columns(4)
        sv1.metric("Steuer Zusammen (Mon.)", f"{_de(_st_zus)} €")
        sv2.metric("Steuer Getrennt (Mon.)", f"{_de(_st_get)} €")
        sv3.metric("Steuer P1 (Mon.)", f"{_de(_st_p1)} €")
        sv4.metric("Steuer P2 (Mon.)", f"{_de(_st_p2)} €")

        # Zeile 2: Netto
        sv5, sv6, sv7, sv8 = st.columns(4)
        sv5.metric("Netto Zusammen (Mon.)", f"{_de(_nt_zus)} €")
        sv6.metric("Netto Getrennt (Mon.)", f"{_de(_nt_get)} €")
        sv7.metric("Netto P1 (Mon.)", f"{_de(_nt_p1)} €")
        sv8.metric("Netto P2 (Mon.)", f"{_de(_nt_p2)} €")

        ersparnis_monatlich = _nt_zus - _nt_get
        if ersparnis_monatlich > 1:
            st.success(
                f"**Zusammenveranlagung spart {_de(ersparnis_monatlich)} €/Monat "
                f"({_de(ersparnis_monatlich * 12)} €/Jahr)** gegenüber getrennter Veranlagung."
            )
        else:
            st.info("In diesem Fall ergibt sich kein Splitting-Vorteil "
                    "(ähnlich hohe Einkommen beider Partner).")

        # Stacked bar: Netto + Steuer + KV für Zusammen, Getrennt, P1, P2
        _szv_x = ["Zusammen\n(Splitting)", "Getrennt", "Person 1\n(allein)", "Person 2\n(allein)"]
        fig_st = go.Figure()
        fig_st.add_trace(go.Bar(
            name="Netto", x=_szv_x, y=[_nt_zus, _nt_get, _nt_p1, _nt_p2],
            marker_color="#A5D6A7",
            text=[f"{_de(v)} €" for v in [_nt_zus, _nt_get, _nt_p1, _nt_p2]],
            textposition="inside",
        ))
        fig_st.add_trace(go.Bar(
            name="− Steuer", x=_szv_x, y=[_st_zus, _st_get, _st_p1, _st_p2],
            marker_color="#EF9A9A",
            text=[f"{_de(v)} €" for v in [_st_zus, _st_get, _st_p1, _st_p2]],
            textposition="inside",
        ))
        fig_st.add_trace(go.Bar(
            name="− KV/PV", x=_szv_x, y=[_kv_zus, _kv_get, _kv_p1, _kv_p2],
            marker_color="#FFF176",
            text=[f"{_de(v)} €" for v in [_kv_zus, _kv_get, _kv_p1, _kv_p2]],
            textposition="inside",
        ))
        fig_st.update_layout(
            barmode="stack",
            template="plotly_white", height=340,
            yaxis=dict(title=f"€ / Monat {betrachtungsjahr} (Brutto = Gesamthöhe)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10, r=10, t=40, b=10),
            separators=",.",
        )
        st.caption("Zusammen/Getrennt = Haushalt gesamt (beide Personen); P1/P2 = Einzelwerte je Person.")
        st.plotly_chart(fig_st, use_container_width=True)

        st.divider()

        # ── Ruhestandsstatus und Übergangszeitraum ────────────────────────────
        st.subheader("Ruhestandsstatus und Übergangszeitraum")
        if p1.bereits_rentner and not p2.bereits_rentner:
            diff = p2.eintritt_jahr - AKTUELLES_JAHR
            diff_txt = f"in {diff} Jahren" if diff > 0 else "in diesem Jahr"
            st.info(
                f"**Person 1** befindet sich bereits im Ruhestand (seit {p1.rentenbeginn_jahr}). "
                f"**Person 2** tritt voraussichtlich **{p2.eintritt_jahr}** in Rente ({diff_txt}). "
                f"Bis dahin trägt Person 1 allein zum Renteneinkommen bei: "
                f"**{_de(e1.netto_monatlich)} €/Monat netto**."
            )
        elif p2.bereits_rentner and not p1.bereits_rentner:
            diff = p1.eintritt_jahr - AKTUELLES_JAHR
            diff_txt = f"in {diff} Jahren" if diff > 0 else "in diesem Jahr"
            st.info(
                f"**Person 2** befindet sich bereits im Ruhestand (seit {p2.rentenbeginn_jahr}). "
                f"**Person 1** tritt voraussichtlich **{p1.eintritt_jahr}** in Rente ({diff_txt}). "
                f"Bis dahin trägt Person 2 allein zum Renteneinkommen bei: "
                f"**{_de(e2.netto_monatlich)} €/Monat netto**."
            )
        elif p1.bereits_rentner and p2.bereits_rentner:
            st.info(
                f"Beide Partner befinden sich bereits im Ruhestand "
                f"(Person 1 seit {p1.rentenbeginn_jahr}, Person 2 seit {p2.rentenbeginn_jahr})."
            )
        else:
            years_diff = abs(p1.eintritt_jahr - p2.eintritt_jahr)
            if years_diff > 0:
                erster = "Person 1" if p1.eintritt_jahr <= p2.eintritt_jahr else "Person 2"
                zweiter = "Person 2" if erster == "Person 1" else "Person 1"
                e_erst = e1 if erster == "Person 1" else e2
                st.info(
                    f"**{erster}** geht {years_diff} Jahr(e) früher in Rente als **{zweiter}**. "
                    f"In dieser Zeit steht nur die Rente von {erster} zur Verfügung: "
                    f"**{_de(e_erst.netto_monatlich)} €/Monat netto**."
                )
            else:
                st.info("Beide Partner gehen voraussichtlich im gleichen Jahr in Rente.")

        st.divider()

        # ── Witwen-/Witwerrente-Schätzung ─────────────────────────────────────
        st.subheader("Witwen-/Witwerrente-Schätzung (§ 46 SGB VI)")
        _ww_grenze = 26_400.0  # Hinzuverdienstgrenze 2024 (§ 97 SGB VI), einfacher Freibetrag
        _ww_satz = 0.55        # großes Witwengeld (§ 46 Abs. 2 SGB VI)

        def _witwen_rente(verstorben_brutto: float, ueberlebend_netto: float,
                          label_verstorben: str, label_ueberlebend: str) -> None:
            _wwr_brutto = verstorben_brutto * _ww_satz
            # Anrechnung eigenes Einkommen: Freibetrag 26.400 €/Jahr; 40 % des darüber
            # liegenden Einkommens werden angerechnet (§ 97 SGB VI)
            _jahres_eigen = ueberlebend_netto * 12
            _anrechnung_basis = max(0.0, _jahres_eigen - _ww_grenze)
            _anrechnung_mono = _anrechnung_basis * 0.40 / 12
            _wwr_netto_mono = max(0.0, _wwr_brutto - _anrechnung_mono)
            ww1, ww2, ww3 = st.columns(3)
            ww1.metric(
                f"Witwen-/Witwerrente brutto",
                f"{_de(_wwr_brutto)} €/Mon.",
                help=f"55 % der gesetzl. Bruttorente von {label_verstorben}: "
                     f"{_de(verstorben_brutto)} €/Mon. × 0,55 (§ 46 Abs. 2 SGB VI).",
            )
            ww2.metric(
                "Anrechnung eigenes Einkommen",
                f"−{_de(_anrechnung_mono)} €/Mon.",
                help=f"40 % von max(0, Jahreseinkommen {label_ueberlebend} − {_de(_ww_grenze)} €) / 12 "
                     f"(§ 97 SGB VI, vereinfacht).",
            )
            ww3.metric(
                f"Witwen-/Witwerrente (geschätzt)",
                f"{_de(_wwr_netto_mono)} €/Mon.",
                help="Brutto-Witwerrente nach vereinfachter Einkommensanrechnung. "
                     "Steuerpflichtig nach § 22 Nr. 1 S. 3a aa EStG.",
            )
            if _anrechnung_mono > 0:
                st.caption(
                    f"Das eigene Jahreseinkommen von {label_ueberlebend} "
                    f"({_de(_jahres_eigen)} €/Jahr) übersteigt den Freibetrag "
                    f"({_de(_ww_grenze)} €/Jahr) um {_de(_anrechnung_basis)} €/Jahr → "
                    f"40 % = {_de(_anrechnung_mono)} €/Mon. werden angerechnet."
                )

        st.caption(
            "Schätzung: 55 % der gesetzlichen Bruttorente (großes Witwengeld nach "
            "§ 46 Abs. 2 SGB VI). Eigenes Einkommen wird nach § 97 SGB VI angerechnet "
            "(Freibetrag 2024: 26.400 €/Jahr; 40 % des übersteigenden Betrags). "
            "Keine Berücksichtigung von Bestandsschutz, kleinem Witwengeld oder Kinderzuschlägen."
        )

        with st.expander("Tod von Person 1 – Witwerrente für Person 2", expanded=False):
            _witwen_rente(
                e1.brutto_gesetzlich, e2.netto_monatlich,
                "Person 1", "Person 2",
            )
        with st.expander("Tod von Person 2 – Witwenrente für Person 1", expanded=False):
            _witwen_rente(
                e2.brutto_gesetzlich, e1.netto_monatlich,
                "Person 2", "Person 1",
            )

        st.caption(
            "⚠️ Vereinfachte Berechnung. Splitting-Vorteil basiert auf Renteneinnahmen. "
            "Weitere Einkünfte (Mieten, Kapitalerträge) können das Ergebnis erheblich verändern. "
            "Steuerberatung empfohlen."
        )
