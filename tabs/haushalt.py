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
    from tabs.hypothek import get_hyp_schedule, get_anschluss_schedule, get_ausgaben_plan
except ImportError:
    def get_hyp_schedule():
        return []
    def get_anschluss_schedule():
        return []
    def get_ausgaben_plan():
        return {}

from tabs import steuern
from tabs.analyse import render_analyse
from tabs.utils import (
    _de, _actual_startjahr, _actual_anteil, _blend_brutto_wf,
    _vorsorge_non_bav_einzeln, _vorsorge_non_bav_monatlich, _vorsorge_bav_monatlich,
    _eink_label, _vorsorge_ausz_breakdown, render_zeitstrahl,
)


def render(
    T: dict,
    p1: Profil,
    p2: "Profil | None",
    e1: RentenErgebnis,
    e2: "RentenErgebnis | None",
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
        if p2 is None:
            st.info(
                "Dieser Tab zeigt die gemeinsame Haushaltsübersicht für Paare. "
                "Bitte aktivieren Sie im **Profil-Tab** die Option **'Mit Partner/in'**, "
                "um Paarvergleich, Splitting-Vorteil und gemeinsamen Jahresverlauf zu sehen."
            )
            return

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

            betrachtungsjahr = render_zeitstrahl(
                _rc, _start_j, _end_j, _default_j, "_hh",
                help_text="Zeigt projizierte Einkommenswerte für das gewählte Jahr (mit Rentenanpassung).",
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
                if person is not None and d.get("person", "Person 1") != person:
                    continue
                if d.get("als_kapitalanlage", False):
                    if float(d.get("max_einmalzahlung", 0.0)) > 0:
                        try:
                            _entsch.append((_vd(d), _actual_startjahr(d), _actual_anteil(d)))
                        except Exception:
                            pass
                    continue
                if float(d.get("max_monatsrente", 0.0)) <= 0:
                    continue
                try:
                    _entsch.append((_vd(d), _actual_startjahr(d), _actual_anteil(d)))
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
        # Simulationsdaten in session_state ablegen (für konsistente Kennzahlen in anderen Tabs)
        st.session_state["_sb_hh_jd_p1"]  = _jd_p1
        st.session_state["_sb_hh_jd_p2"]  = _jd_p2
        st.session_state["_sb_hh_jd_zus"] = _jd_zus
        st.session_state["_sb_hh_jd_get"] = _jd_get

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
                    "Vorsorge_Beitraege": ((_r1.get("Vorsorge_Beitraege", 0) if _r1 else 0)
                                           + (_r2.get("Vorsorge_Beitraege", 0) if _r2 else 0)),
                    "LHK":    ((_r1.get("LHK", 0) if _r1 else 0)
                                + (_r2.get("LHK", 0) if _r2 else 0)),
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
            # Blend Brutto per person and patch combined value
            _bl1 = _blend_brutto_wf(p1, _jd_p1, betrachtungsjahr)
            _bl2 = _blend_brutto_wf(p2, _jd_p2, betrachtungsjahr)
            if _bl1 is not None or _bl2 is not None:
                _p1_by_y = {r["Jahr"]: r for r in _jd_p1}
                _p2_by_y = {r["Jahr"]: r for r in _jd_p2}
                _p1_orig = _p1_by_y.get(betrachtungsjahr, {}).get("Brutto", 0.0) / 12
                _p2_orig = _p2_by_y.get(betrachtungsjahr, {}).get("Brutto", 0.0) / 12
                _b = _b - _p1_orig + (_bl1 if _bl1 is not None else _p1_orig) \
                       - _p2_orig + (_bl2 if _bl2 is not None else _p2_orig)
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
            _bl = _blend_brutto_wf(p1, _jd_p1, betrachtungsjahr)
            if _bl is not None:
                _b = _bl
        elif ansicht == "Person 2" and _row_p2:
            _b = _row_p2["Brutto"] / 12
            _n = _row_p2["Netto"] / 12
            _s = _row_p2["Steuer"] / 12
            _k = _row_p2["KV_PV"] / 12
            _label = "Person 2"
            _bl = _blend_brutto_wf(p2, _jd_p2, betrachtungsjahr)
            if _bl is not None:
                _b = _bl
        else:
            _no_data = True
            _start_sel = _start_p1 if ansicht == "Person 1" else _start_p2
            st.info(
                f"Für **{ansicht}** liegen für {betrachtungsjahr} noch keine Daten vor "
                f"(Renteneintritt: {_start_sel}). "
                f"Bruttogehalt im Profil eingeben, um Berufsjahre zu simulieren."
            )

        # Vorab: LHK + Vorsorge-Beiträge für Netto-Basis (= nach Steuer+KV+bAV, vor VB/LHK)
        _ansicht_person = ("Person 1" if ansicht == "Person 1"
                           else "Person 2" if ansicht == "Person 2"
                           else None)
        if not _no_data:
            _lhk_p1_wf = float(st.session_state.get(f"rc{_rc}_p1_lhk", 0.0))
            _lhk_p2_wf = float(st.session_state.get(f"rc{_rc}_p2_lhk", 0.0))
            if ansicht == "Person 1":
                _lhk_m_wf = _lhk_p1_wf
            elif ansicht == "Person 2":
                _lhk_m_wf = _lhk_p2_wf
            else:
                _lhk_m_wf = _lhk_p1_wf + _lhk_p2_wf
            _bav_contrib_wf = _vorsorge_bav_monatlich(
                _vp_produkte, betrachtungsjahr, person=_ansicht_person
            )
            _vorsorge_nbav_einzeln = _vorsorge_non_bav_einzeln(
                _vp_produkte, betrachtungsjahr, person=_ansicht_person
            )
            _vorsorge_nbav_m = sum(b for _, b in _vorsorge_nbav_einzeln)
            _n_nach_kv = _n + _lhk_m_wf + _vorsorge_nbav_m

            c1.metric("Brutto", f"{_de(_b)} €",
                      help=f"{_label}: Bruttoeinkommen inkl. Mieteinnahmen")
            c2.metric("Netto", f"{_de(_n_nach_kv)} €",
                      help="Nach Einkommensteuer und KV/PV (vor Vorsorge-Beiträgen und Lebenshaltungskosten).")
            _is_zus = ansicht == "Haushalt gesamt" and veranlagung == "Zusammen"
            _steuer_help = (
                "Einkommensteuer (§ 32a EStG) + Solidaritätszuschlag (§ 51a EStG) "
                "beider Personen im Splitting-Verfahren (§ 32a Abs. 5 EStG): ESt = 2 × ESt(zvE/2). "
                "Plus Abgeltungsteuer (25 %) auf Kapitalerträge aus dem Kapitalanlage-Pool."
                if _is_zus else
                "Einkommensteuer (§ 32a EStG) + Solidaritätszuschlag (§ 51a EStG) "
                "auf das zu versteuernde Einkommen (gesetzliche Rente × Besteuerungsanteil, "
                "Pension nach VFB, Vorsorgeauszahlungen, Mieteinnahmen). "
                "Plus Abgeltungsteuer (25 %) auf Kapitalerträge aus dem Kapitalanlage-Pool."
            )
            _kv_help = (
                "Kranken- und Pflegeversicherungsbeiträge beider Personen. "
                "KVdR-Pflichtmitglieder (§ 5 Abs. 1 Nr. 11 SGB V): Beiträge nur auf §229-Einkünfte "
                "(gesetzliche Rente, bAV nach Freibetrag 187,25 €/Mon.). "
                "Freiwillig GKV (§ 240 SGB V): alle Einkünfte beitragspflichtig, "
                "Mindest-BMG 1.096,67 €/Mon. PKV: fixer Monatsbeitrag."
            )
            c3.metric("Steuer", f"{_de(_s)} €/Mon.", help=_steuer_help)
            c4.metric("KV / PV", f"{_de(_k)} €/Mon.", help=_kv_help)

            _vors_row_hh = (_row_comb if ansicht == "Haushalt gesamt"
                            else _row_p1 if ansicht == "Person 1"
                            else _row_p2)
            if _vors_row_hh:
                _vors_m_hh, _vors_help_hh = _vorsorge_ausz_breakdown(_vors_row_hh)
                if _vors_m_hh > 0:
                    vh1, vh2, vh3, vh4 = st.columns(4)
                    vh1.metric(
                        f"Vorsorgeauszahlungen {betrachtungsjahr}", f"{_de(_vors_m_hh)} €/Mon.",
                        help=_vors_help_hh,
                    )

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
            _aus_help = (
                "Summe aller laufenden Ausgaben im Betrachtungsjahr: "
                "Vorsorgebeiträge (bAV, Riester, PrivRV, LV u. a. – solange noch keine Auszahlung), "
                "fixe monatliche Ausgaben und Hypothek-Annuität (Zins + Tilgung + Sondertilgung). "
                "Nicht enthalten: Einkommensteuer und KV/PV (bereits in Netto verrechnet), "
                "Lebenshaltungskosten."
            )
            out1.metric("Gesamtausgaben/Jahr",  f"{_de(_total_j)} €", help=_aus_help)
            out2.metric("Gesamtausgaben/Monat", f"{_de(_total_m)} €", help=_aus_help)

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
        if not _no_data:
            _aktive_fix = [
                fa for fa in _fixausgaben
                if fa["startjahr"] <= betrachtungsjahr <= fa["endjahr"]
            ]
            _fix_faktor_wf = 0.5 if ansicht in ("Person 1", "Person 2") else 1.0
            _fix_m_wf = sum(fa["betrag_monatlich"] for fa in _aktive_fix) * _fix_faktor_wf

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

            # ── Wasserfall-Einkommensquellen (ansichtsabhängig) ──────────────
            if ansicht == "Haushalt gesamt":
                # Dashboard-Stil: P1 / P2 als getrennte Säulen + Mieteinnahmen + Sonstige
                _lbl_p1_wf = _eink_label(p1, betrachtungsjahr)
                _lbl_p2_wf = _eink_label(p2, betrachtungsjahr)
                _ba1_pct = f"{e1.besteuerungsanteil:.0%}".replace(".", ",")
                _ba2_pct = f"{e2.besteuerungsanteil:.0%}".replace(".", ",")
                _ver_label_wf = ("Zusammenveranlagung (Splitting)"
                                 if veranlagung == "Zusammen" else "Getrenntveranlagung")
                _hh_kv_p1_wf = (_row_comb["KV_P1"] / 12
                                 if _row_comb and "KV_P1" in _row_comb else None)
                _hh_kv_p2_wf = (_row_comb["KV_P2"] / 12
                                 if _row_comb and "KV_P2" in _row_comb else None)
                _p1_b_wf = (
                    (_row_comb.get("Src_GesRente", 0)
                     + _row_comb.get("Src_Gehalt", 0)
                     + _row_comb.get("Src_Zusatzentgelt", 0)) / 12
                ) if _row_comb else e1.brutto_monatlich
                _bl1_wf = _blend_brutto_wf(p1, _jd_p1, betrachtungsjahr)
                if _bl1_wf is not None:
                    _p1_b_wf = _bl1_wf
                _p2_b_wf = (
                    _row_comb.get("Src_P2_Rente", 0) / 12
                ) if _row_comb else e2.brutto_monatlich
                _bl2_wf = _blend_brutto_wf(p2, _jd_p2, betrachtungsjahr)
                if _bl2_wf is not None:
                    _p2_b_wf = _bl2_wf
                _miete_wf = _row_comb.get("Src_Miete", 0) / 12 if _row_comb else mieteinnahmen
                _sonst_wf = max(0.0, _b - _p1_b_wf - _p2_b_wf
                                - _bav_m_wf - _riester_m_wf - _miete_wf)
                _wf_x      = [f"P1 {_lbl_p1_wf}", f"P2 {_lbl_p2_wf}"]
                _wf_meas   = ["absolute", "relative"]
                _wf_y      = [_p1_b_wf, _p2_b_wf]
                _wf_t      = [f"{_de(_p1_b_wf)} €", f"+{_de(_p2_b_wf)} €"]
                _wf_colors = ["#2196F3", "#2196F3"]
                _wf_h      = [
                    f"<b>P1 {_lbl_p1_wf} (brutto)</b><br>"
                    f"{_de(_p1_b_wf)} €/Mon.<br>"
                    f"Gesetzliche Rente + Zusatzrente vor Steuer und KV.<br>"
                    f"Besteuerungsanteil: {_ba1_pct} (Renteneintritt {p1.eintritt_jahr})",
                    f"<b>P2 {_lbl_p2_wf} (brutto)</b><br>"
                    f"+{_de(_p2_b_wf)} €/Mon.<br>"
                    f"Gesetzliche Rente + Zusatzrente vor Steuer und KV.<br>"
                    f"Besteuerungsanteil: {_ba2_pct} (Renteneintritt {p2.eintritt_jahr})",
                ]
                if _bav_m_wf > 0:
                    _wf_x.append("+ bAV"); _wf_meas.append("relative")
                    _wf_y.append(_bav_m_wf); _wf_t.append(f"+{_de(_bav_m_wf)} €")
                    _wf_colors.append("#4CAF50")
                    _wf_h.append(
                        f"<b>Betriebliche Altersversorgung (P1+P2)</b><br>"
                        f"+{_de(_bav_m_wf)} €/Mon.<br>"
                        f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                        f"KV: abzgl. Freibetrag 187,25 €/Mon. (§ 226 Abs. 2 SGB V)."
                    )
                if _riester_m_wf > 0:
                    _wf_x.append("+ Riester"); _wf_meas.append("relative")
                    _wf_y.append(_riester_m_wf); _wf_t.append(f"+{_de(_riester_m_wf)} €")
                    _wf_colors.append("#4CAF50")
                    _wf_h.append(
                        f"<b>Riester-Rente (P1+P2)</b><br>"
                        f"+{_de(_riester_m_wf)} €/Mon.<br>"
                        f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                        f"Nicht KV-pflichtig (private Rentenleistung)."
                    )
                if _miete_wf > 0:
                    _wf_x.append("Mieteinnahmen"); _wf_meas.append("relative")
                    _wf_y.append(_miete_wf); _wf_t.append(f"+{_de(_miete_wf)} €")
                    _wf_colors.append("#4CAF50")
                    _wf_h.append(
                        f"<b>Mieteinnahmen (gesamt)</b><br>"
                        f"+{_de(_miete_wf)} €/Mon.<br>"
                        f"Netto nach abzugsfähigen Werbungskosten (§ 21 EStG).<br>"
                        f"Voll steuerpflichtig, keine KV-Pflicht. Steuerlich 50/50 aufgeteilt."
                    )
                if _sonst_wf > 0.5:
                    _wf_x.append("+ Sonstige"); _wf_meas.append("relative")
                    _wf_y.append(_sonst_wf); _wf_t.append(f"+{_de(_sonst_wf)} €")
                    _wf_colors.append("#4CAF50")
                    _wf_h.append(
                        f"<b>Sonstige Einnahmen</b><br>"
                        f"+{_de(_sonst_wf)} €/Mon.<br>"
                        f"Rürup, Private RV, Kapitalverzehr u.a.<br>"
                        f"Steuerlich nach jeweiliger Regelung."
                    )
                _n_nach_kv_hh = _n + _lhk_m_wf + _vorsorge_nbav_m
                _wf_x    += ["− Einkommensteuer", "− KV/PV"]
                _wf_meas += ["relative", "relative"]
                _wf_y    += [-_s, -_k]
                _wf_t    += [f"−{_de(_s)} €", f"−{_de(_k)} €"]
                _wf_colors += ["#F44336", "#F44336"]
                _wf_h    += [
                    f"<b>Einkommensteuer + Solidaritätszuschlag</b><br>"
                    f"−{_de(_s)} €/Mon.<br>"
                    f"{_ver_label_wf} (§ 32a EStG).<br>"
                    f"Soli: 5,5 % ab 17.543 € ESt (§ 51a EStG).",
                    f"<b>Kranken- + Pflegeversicherung (Haushalt)</b><br>"
                    f"−{_de(_k)} €/Mon."
                    + (f"<br>P1: {_de(_hh_kv_p1_wf)} €, P2: {_de(_hh_kv_p2_wf)} €"
                       if _hh_kv_p1_wf is not None else "")
                    + "<br>GKV/PKV je nach Versicherungsstatus.<br>"
                    "BBG: 5.175 €/Mon.",
                ]
                if _bav_contrib_wf > 0:
                    _wf_x.append("− bAV-Beiträge"); _wf_meas.append("relative")
                    _wf_y.append(-_bav_contrib_wf); _wf_t.append(f"−{_de(_bav_contrib_wf)} €")
                    _wf_colors.append("#F44336")
                    _wf_h.append(
                        f"<b>bAV-Beiträge (Entgeltumwandlung)</b><br>"
                        f"−{_de(_bav_contrib_wf)} €/Mon.<br>"
                        f"AN-Anteil laufender bAV-Einzahlungen.<br>"
                        f"Reduziert das disponible Bruttoeinkommen."
                    )
                _wf_x.append("Netto Haushalt"); _wf_meas.append("total")
                _wf_y.append(_n_nach_kv_hh); _wf_t.append(f"{_de(_n_nach_kv_hh)} €")
                _wf_colors.append("#2196F3")
                _wf_h.append(
                    f"<b>Netto Haushalt</b><br>"
                    f"{_de(_n_nach_kv_hh)} €/Mon.<br>"
                    f"Nach Steuer, KV/PV und bAV-Beiträgen."
                )
            else:
                # Person 1 / Person 2: einzelne Rente/Pension-Säule
                if ansicht == "Person 1":
                    _kv_txt  = (f"PKV {_de(p1.pkv_beitrag, 0)} €/Mon. (Fixbetrag)"
                                if p1.krankenversicherung == "PKV" else "GKV-Beitrag (AN-Anteil)")
                    _ba_pct  = f"{e1.besteuerungsanteil:.0%}".replace(".", ",")
                    _eff_pct = f"{e1.effektiver_steuersatz:.1%}".replace(".", ",")
                else:
                    _kv_txt  = (f"PKV {_de(p2.pkv_beitrag, 0)} €/Mon. (Fixbetrag)"
                                if p2.krankenversicherung == "PKV" else "GKV-Beitrag (AN-Anteil)")
                    _ba_pct  = f"{e2.besteuerungsanteil:.0%}".replace(".", ",")
                    _eff_pct = f"{e2.effektiver_steuersatz:.1%}".replace(".", ",")
                _wf_x      = ["Rente/Pension", "− Einkommensteuer", "− KV / PV"]
                _wf_meas   = ["absolute", "relative", "relative"]
                _wf_y      = [_b_basis, -_s, -_k]
                _wf_t      = [f"{_de(_b_basis)} €", f"−{_de(_s)} €", f"−{_de(_k)} €"]
                _wf_colors = ["#2196F3", "#F44336", "#F44336"]
                _wf_h      = [
                    f"<b>Rente/Pension (brutto)</b><br>"
                    f"{_de(_b_basis)} €/Mon.<br>"
                    f"Gesetzliche Rente + Zusatzrente vor Steuer und KV.<br>"
                    f"Besteuerungsanteil: {_ba_pct} (§ 22 EStG)",
                    f"<b>Einkommensteuer + Solidaritätszuschlag</b><br>"
                    f"−{_de(_s)} €/Mon.<br>"
                    f"§ 32a EStG Grundtarif; eff. Steuersatz {_eff_pct}.<br>"
                    f"Soli: 5,5 % ab 17.543 € ESt (§ 51a EStG).",
                    f"<b>Kranken- + Pflegeversicherung</b><br>"
                    f"−{_de(_k)} €/Mon.<br>"
                    f"{_kv_txt}.<br>"
                    f"PV-Kinderstaffelung: § 55 Abs. 3a SGB XI. BBG: 5.175 €/Mon.",
                ]
                if _bav_m_wf > 0:
                    _wf_x.insert(1, "+ bAV"); _wf_meas.insert(1, "relative")
                    _wf_y.insert(1, _bav_m_wf); _wf_t.insert(1, f"+{_de(_bav_m_wf)} €")
                    _wf_colors.insert(1, "#4CAF50")
                    _wf_h.insert(1,
                        f"<b>Betriebliche Altersversorgung (bAV)</b><br>"
                        f"+{_de(_bav_m_wf)} €/Mon.<br>"
                        f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                        f"KV: abzgl. Freibetrag 187,25 €/Mon. (§ 226 Abs. 2 SGB V)."
                    )
                if _riester_m_wf > 0:
                    _ins = 2 if _bav_m_wf > 0 else 1
                    _wf_x.insert(_ins, "+ Riester"); _wf_meas.insert(_ins, "relative")
                    _wf_y.insert(_ins, _riester_m_wf); _wf_t.insert(_ins, f"+{_de(_riester_m_wf)} €")
                    _wf_colors.insert(_ins, "#4CAF50")
                    _wf_h.insert(_ins,
                        f"<b>Riester-Rente</b><br>"
                        f"+{_de(_riester_m_wf)} €/Mon.<br>"
                        f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                        f"Nicht KVdR-pflichtig (private Rentenleistung)."
                    )
                _n_nach_kv_p = _n + _lhk_m_wf + _vorsorge_nbav_m
                if _bav_contrib_wf > 0:
                    _wf_x.append("− bAV-Beiträge"); _wf_meas.append("relative")
                    _wf_y.append(-_bav_contrib_wf); _wf_t.append(f"−{_de(_bav_contrib_wf)} €")
                    _wf_colors.append("#F44336")
                    _wf_h.append(
                        f"<b>bAV-Beiträge (Entgeltumwandlung)</b><br>"
                        f"−{_de(_bav_contrib_wf)} €/Mon.<br>"
                        f"AN-Anteil laufender bAV-Einzahlungen.<br>"
                        f"Reduziert das disponible Bruttoeinkommen."
                    )
                _wf_x.append("Netto"); _wf_meas.append("total")
                _wf_y.append(_n_nach_kv_p); _wf_t.append(f"{_de(_n_nach_kv_p)} €")
                _wf_colors.append("#2196F3")
                _wf_h.append(
                    f"<b>Nettoeinkommen</b><br>"
                    f"{_de(_n_nach_kv_p)} €/Mon.<br>"
                    f"Nach Einkommensteuer, KV, PV und bAV-Beiträgen."
                )

            # ── Gemeinsame Abzüge (Vorsorge, Hypothek, Lebenshaltung, Fixe) ──
            if _vorsorge_nbav_m > 0:
                _vb_detail = "; ".join(f"{n}: {_de(v)} €" for n, v in _vorsorge_nbav_einzeln)
                _wf_x.append("− Vorsorge\n(ohne bAV)")
                _wf_meas.append("relative")
                _wf_y.append(-_vorsorge_nbav_m)
                _wf_t.append(f"−{_de(_vorsorge_nbav_m)} €")
                _wf_colors.append("#F44336")
                _wf_h.append(
                    f"<b>Vorsorge-Beiträge (ohne bAV)</b><br>"
                    f"−{_de(_vorsorge_nbav_m)} €/Mon.<br>"
                    f"Laufende Beiträge: {_vb_detail}.<br>"
                    f"Reduzieren das verfügbare Netto während der Beitragsphase."
                )
            _hyp_schedule_wf = get_hyp_schedule()
            _hyp_row_wf = next((r for r in _hyp_schedule_wf if r["Jahr"] == betrachtungsjahr), None)
            _hyp_faktor_wf = 0.5 if ansicht in ("Person 1", "Person 2") else 1.0
            _hyp_hint = " (½ Haushalt)" if _hyp_faktor_wf < 1.0 else ""
            _hyp_m_wf = (_hyp_row_wf["Jahresausgabe"] / 12 if _hyp_row_wf else 0.0) * _hyp_faktor_wf
            if _hyp_m_wf > 0:
                _wf_x.append("− Hypothek")
                _wf_meas.append("relative")
                _wf_y.append(-_hyp_m_wf)
                _wf_t.append(f"−{_de(_hyp_m_wf)} €")
                _wf_colors.append("#F44336")
                _wf_h.append(
                    f"<b>Hypothek-Jahresrate{_hyp_hint}</b><br>"
                    f"−{_de(_hyp_m_wf)} €/Mon.<br>"
                    f"Annuität {betrachtungsjahr} (Zins + Tilgung).<br>"
                    f"Konfiguration im Tab Hypothek-Verwaltung."
                )
            _ak_schedule_wf = get_anschluss_schedule()
            _ak_row_wf = next((r for r in _ak_schedule_wf if r["Jahr"] == betrachtungsjahr), None)
            _ak_m_wf = (_ak_row_wf["Jahresausgabe"] / 12 if _ak_row_wf else 0.0) * _hyp_faktor_wf
            if _ak_m_wf > 0:
                _wf_x.append("− Anschlusskredit")
                _wf_meas.append("relative")
                _wf_y.append(-_ak_m_wf)
                _wf_t.append(f"−{_de(_ak_m_wf)} €")
                _wf_colors.append("#F44336")
                _wf_h.append(
                    f"<b>Anschlussfinanzierung{_hyp_hint}</b><br>"
                    f"−{_de(_ak_m_wf)} €/Mon.<br>"
                    f"Annuität auf Restschuld nach Hypothek-Endjahr."
                )
            if _lhk_m_wf > 0:
                _wf_x.append("− Lebenshalt.")
                _wf_meas.append("relative")
                _wf_y.append(-_lhk_m_wf)
                _wf_t.append(f"−{_de(_lhk_m_wf)} €")
                _wf_colors.append("#F44336")
                _wf_h.append(
                    f"<b>Lebenshaltungskosten</b><br>"
                    f"−{_de(_lhk_m_wf)} €/Mon.<br>"
                    f"Monatliche Fixkosten (Miete, Lebensmittel …).<br>"
                    f"Konfiguration im Expander 'Lebenshaltungskosten'."
                )
            if _fix_m_wf > 0:
                _fix_detail = "; ".join(
                    f"{fa['name']}: {_de(fa['betrag_monatlich'])} €" for fa in _aktive_fix
                )
                _wf_x.append("− Fixe Ausgaben")
                _wf_meas.append("relative")
                _wf_y.append(-_fix_m_wf)
                _wf_t.append(f"−{_de(_fix_m_wf)} €")
                _wf_colors.append("#F44336")
                _wf_h.append(
                    f"<b>Fixe monatliche Ausgaben</b><br>"
                    f"−{_de(_fix_m_wf)} €/Mon.<br>"
                    f"Summe aktiver Fixausgaben {betrachtungsjahr}.<br>"
                    + (f"{_fix_detail}." if _fix_detail else "")
                )
            # Einmaltilgung (Sondertilgung aus Ausgabenplan, exkl. laufende Raten)
            _ausgaben_plan_wf = get_ausgaben_plan()
            _sonder_j_wf = _ausgaben_plan_wf.get(betrachtungsjahr, 0.0)
            _hyp_j_wf = (_hyp_row_wf["Jahresausgabe"] if _hyp_row_wf else 0.0)
            _ak_j_wf  = (_ak_row_wf["Jahresausgabe"]  if _ak_row_wf  else 0.0)
            _einmaltilgung_j_wf = max(0.0, _sonder_j_wf - _hyp_j_wf - _ak_j_wf)
            _einmaltilgung_m_wf = _einmaltilgung_j_wf * _hyp_faktor_wf / 12
            if _einmaltilgung_m_wf > 0:
                _wf_x.append("− Einmaltilgung")
                _wf_meas.append("relative")
                _wf_y.append(-_einmaltilgung_m_wf)
                _wf_t.append(f"−{_de(_einmaltilgung_m_wf)} €")
                _wf_colors.append("#F44336")
                _wf_h.append(
                    f"<b>Einmaltilgung{_hyp_hint}</b><br>"
                    f"−{_de(_einmaltilgung_m_wf)} €/Mon.<br>"
                    f"Einmalige Sondertilgung {betrachtungsjahr}: "
                    f"{_de(_einmaltilgung_j_wf * _hyp_faktor_wf)} € gesamt<br>"
                    f"(÷ 12 zur monatlichen Darstellung)."
                )
            _verfuegbar_m = _n - _fix_m_wf - _hyp_m_wf - _ak_m_wf - _einmaltilgung_m_wf
            _wf_x.append("Verfügbar")
            _wf_meas.append("total")
            _wf_y.append(_verfuegbar_m)
            _wf_t.append(f"{_de(abs(_verfuegbar_m))} €")
            _wf_colors.append("#2196F3")
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
                _df.loc[ej, "Brutto"] = blended

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
                    _bl = _mb * _sm + _ma * _pm
                    # Difference to replace in combined df
                    _old = _by_y.get(_ej, {}).get("Brutto", 0.0)
                    _df.loc[_ej, "Brutto"] = _df.loc[_ej, "Brutto"] - _old + _bl

            # ── Jahresverlauf mit Abzügen ─────────────────────────────────────
            _alle_jahre = list(_df.index)
            # Vorsorge-Beiträge aus Engine-Daten (korrekte Beitragsphase je Produkt)
            _has_vb_col = "Vorsorge_Beitraege" in _df.columns
            if _has_vb_col:
                _vbtotal_py = {j: float(_df.loc[j, "Vorsorge_Beitraege"]) / 12.0
                               for j in _alle_jahre}
                _bav_raw_py = {j: _vorsorge_bav_monatlich(_vp_produkte, j,
                                                           person=_ansicht_person)
                               for j in _alle_jahre}
                _bav_beitrag_py = {j: min(_bav_raw_py[j], _vbtotal_py[j])
                                   for j in _alle_jahre}
                _vbnbav_py = {j: max(0.0, _vbtotal_py[j] - _bav_beitrag_py[j])
                              for j in _alle_jahre}
            else:
                _vbnbav_py = {j: _vorsorge_non_bav_monatlich(_vp_produkte, j,
                                                               person=_ansicht_person)
                              for j in _alle_jahre}
                _bav_beitrag_py = {j: _vorsorge_bav_monatlich(_vp_produkte, j,
                                                               person=_ansicht_person)
                                   for j in _alle_jahre}
            _hyp_sched_jv  = get_hyp_schedule()
            _ak_sched_jv   = get_anschluss_schedule()
            _hyp_faktor_jv = 0.5 if ansicht in ("Person 1", "Person 2") else 1.0
            _hyp_py = {
                j: (next((r["Jahresausgabe"] for r in _hyp_sched_jv if r["Jahr"] == j), 0.0)
                    + next((r["Jahresausgabe"] for r in _ak_sched_jv if r["Jahr"] == j), 0.0))
                   / 12 * _hyp_faktor_jv
                for j in _alle_jahre
            }
            _fix_jv_faktor = 0.5 if ansicht in ("Person 1", "Person 2") else 1.0
            _fix_py    = {
                j: sum(fa["betrag_monatlich"] for fa in _fixausgaben
                       if fa["startjahr"] <= j <= fa["endjahr"]) * _fix_jv_faktor
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
            # Korrigiertes Netto: nach Steuer+KV, vor Vorsorge-Beiträgen und LHK
            # _lhk_col_py = was die Simulation tatsächlich abgezogen hat (nur P1 bei _jd_zus)
            # _lhk_py     = Anzeigewert im Chart (P1+P2 bei "Haushalt gesamt")
            _lhk_col_py = {
                j: (_df.loc[j, "LHK"] / 12 if "LHK" in _df.columns else 0.0)
                for j in _alle_jahre
            }
            _netto_korr_py = {
                j: (_df.loc[j, "Netto"] / 12
                    + (_bav_beitrag_py[j] + _vbnbav_py[j])
                    + _lhk_col_py[j])
                for j in _alle_jahre
            }
            _verfuegbar_py = {
                j: _netto_korr_py[j]
                   - _bav_beitrag_py[j] - _vbnbav_py[j]
                   - _lhk_py[j]
                   - _fix_py[j] - _hyp_py[j]
                for j in _alle_jahre
            }
            # ── Steuer und KV pro Jahr (monatlich) ───────────────────────────
            _est_py = {
                j: float(_df.loc[j, "Steuer"]) / 12.0
                for j in _alle_jahre
            }
            _kv_py = {
                j: (float(_df.loc[j, "KV_PV"]) / 12.0 if "KV_PV" in _df.columns else 0.0)
                for j in _alle_jahre
            }

            # Y-Achsen-Bereich: oben = Brutto, unten = Summe aller Abzüge
            _max_brutto_jv = max(
                _df.loc[j, "Brutto"] / 12 for j in _alle_jahre
            ) if _alle_jahre else 1000.0
            _max_ded_jv = max(
                _est_py[j] + _kv_py[j] + _bav_beitrag_py[j] + _vbnbav_py[j]
                + _hyp_py[j] + _lhk_py[j] + _fix_py[j]
                for j in _alle_jahre
            ) if _alle_jahre else 0.0
            _y1_hi = max(_max_brutto_jv * 1.12, 100.0)
            _y1_lo = -_max_ded_jv * 1.15 if _max_ded_jv > 0 else -50.0

            # Hover-Texte
            _netto_hover_jv = [
                f"Netto (nach Steuer+KV): {_de(_netto_korr_py[j])} €/Mon."
                for j in _alle_jahre
            ]
            _verf_hover_jv = [
                f"Verfügbar: {_de(_verfuegbar_py[j])} €/Mon.<br>"
                f"(Netto − Vorsorge − LHK − Hyp. − Fix)"
                for j in _alle_jahre
            ]

            # Brutto-Hover mit Einkommens-Bestandteilen
            _src_cols = [
                ("Src_Gehalt",         "Gehalt"),
                ("Src_GesRente",       "Gesetzl. Rente"),
                ("Src_P2_Rente",       "P2 Rente/Pension"),
                ("Src_Versorgung",     "Vers.-Leistungen"),
                ("Src_Einmal",         "Einmalerträge"),
                ("Src_Kapitalverzehr", "Kapitalverzehr"),
                ("Src_DUV_P1",         "DUV"),
                ("Src_BUV_P1",         "BUV"),
                ("Src_Miete",          "Miete"),
            ]
            def _brutto_hover_str(j: int) -> str:
                lines = [f"<b>{j} – Brutto: {_de(_df.loc[j, 'Brutto'] / 12)} €/Mon.</b>"]
                for _col, _lbl in _src_cols:
                    if _col in _df.columns:
                        _v = float(_df.loc[j, _col]) / 12
                        if abs(_v) >= 1.0:
                            lines.append(f"  {_lbl}: {_de(_v)} €/Mon.")
                return "<br>".join(lines)

            _brutto_hover_jv = [_brutto_hover_str(j) for j in _alle_jahre]

            # Balken-Reihenfolge (gestapelt von 0 abwärts, wie im Wasserfall):
            # ESt → KV → bAV-Beiträge → Vorsorge → Hypothek → LHK → Fixausgaben
            fig_jv2 = go.Figure()
            fig_jv2.add_trace(go.Bar(
                name="Brutto", x=_alle_jahre,
                y=[_df.loc[j, "Brutto"] / 12 for j in _alle_jahre],
                marker_color="#90CAF9",
                customdata=_brutto_hover_jv,
                hovertemplate="%{customdata}<extra></extra>",
            ))
            if any(_est_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Einkommensteuer + Soli", x=_alle_jahre,
                    y=[-_est_py[j] for j in _alle_jahre],
                    marker_color="#EF5350",
                    customdata=[int(_est_py[j]) for j in _alle_jahre],
                    hovertemplate="<b>%{x} – Einkommensteuer + Soli</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            if any(_kv_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− KV / PV", x=_alle_jahre,
                    y=[-_kv_py[j] for j in _alle_jahre],
                    marker_color="#26A69A",
                    customdata=[int(_kv_py[j]) for j in _alle_jahre],
                    hovertemplate="<b>%{x} – Kranken- + Pflegeversicherung</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            if any(_bav_beitrag_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− bAV-Beiträge (AN)", x=_alle_jahre,
                    y=[-_bav_beitrag_py[j] for j in _alle_jahre],
                    marker_color="#C62828",
                    customdata=[_bav_beitrag_py[j] for j in _alle_jahre],
                    hovertemplate="<b>%{x} – bAV-Beiträge (AN)</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            if any(_vbnbav_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Vorsorge (ohne bAV)", x=_alle_jahre,
                    y=[-_vbnbav_py[j] for j in _alle_jahre],
                    marker_color="#E65100",
                    customdata=[_vbnbav_py[j] for j in _alle_jahre],
                    hovertemplate="<b>%{x} – Vorsorge (ohne bAV)</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            if any(_hyp_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Hypothek", x=_alle_jahre,
                    y=[-_hyp_py[j] for j in _alle_jahre],
                    marker_color="#1565C0",
                    customdata=[_hyp_py[j] for j in _alle_jahre],
                    hovertemplate="<b>%{x} – Hypothek</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            if any(_lhk_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Lebenshaltungskosten", x=_alle_jahre,
                    y=[-_lhk_py[j] for j in _alle_jahre],
                    marker_color="#6A1B9A",
                    customdata=[_lhk_py[j] for j in _alle_jahre],
                    hovertemplate="<b>%{x} – Lebenshaltungskosten</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            if any(_fix_py[j] > 0 for j in _alle_jahre):
                fig_jv2.add_trace(go.Bar(
                    name="− Fixausgaben", x=_alle_jahre,
                    y=[-_fix_py[j] for j in _alle_jahre],
                    marker_color="#F9A825",
                    customdata=[_fix_py[j] for j in _alle_jahre],
                    hovertemplate="<b>%{x} – Fixausgaben</b><br>−%{customdata:,.0f} €/Mon.<extra></extra>",
                ))
            fig_jv2.add_trace(go.Scatter(
                name=_label_netto, x=_alle_jahre,
                y=[_netto_korr_py[j] for j in _alle_jahre],
                mode="lines+markers", line=dict(color="#4CAF50", width=2),
                customdata=_netto_hover_jv,
                hovertemplate="%{customdata}<extra></extra>",
            ))
            fig_jv2.add_trace(go.Scatter(
                name="Verfügbar (nach Abzügen)", x=_alle_jahre,
                y=[_verfuegbar_py[j] for j in _alle_jahre],
                mode="lines+markers",
                line=dict(color="#FF9800", width=2, dash="dash"),
                customdata=_verf_hover_jv,
                hovertemplate="%{customdata}<extra></extra>",
            ))
            fig_jv2.add_vline(
                x=betrachtungsjahr, line_width=1, line_dash="dash",
                line_color="#FF9800",
                annotation_text=str(betrachtungsjahr),
                annotation_position="top right",
            )
            # Renteneintritt-Markierungen
            _re_lines = []
            if ansicht == "Person 1" and not p1.bereits_rentner:
                _re_lines = [(p1.eintritt_jahr, f"Renteneintritt {p1.eintritt_jahr}")]
            elif ansicht == "Person 2" and not p2.bereits_rentner:
                _re_lines = [(p2.eintritt_jahr, f"Renteneintritt {p2.eintritt_jahr}")]
            else:  # Haushalt gesamt
                if not p1.bereits_rentner:
                    _re_lines.append((p1.eintritt_jahr, f"Rente P1 {p1.eintritt_jahr}"))
                if not p2.bereits_rentner:
                    _re_lines.append((p2.eintritt_jahr, f"Rente P2 {p2.eintritt_jahr}"))
            for _re_j, _re_lbl in _re_lines:
                fig_jv2.add_vline(
                    x=_re_j, line_width=1.5, line_dash="dot",
                    line_color="#9C27B0",
                    annotation_text=_re_lbl,
                    annotation_position="top",
                    annotation_font_color="#9C27B0",
                )
            _mindest_jv = float(st.session_state.get("mindest_haushalt_mono", 2_000))
            fig_jv2.add_hline(
                y=_mindest_jv, line_dash="dot", line_color="orange", line_width=2,
                annotation_text=f"Mindest {_de(_mindest_jv)} €",
                annotation_position="top right",
            )
            fig_jv2.update_layout(
                barmode="relative", template="plotly_white", height=520,
                xaxis=dict(title="Jahr", dtick=2),
                yaxis=dict(
                    title="€ / Monat",
                    tickformat=",.0f",
                    range=[_y1_lo, _y1_hi],
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                margin=dict(l=10, r=10, t=80, b=10),
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
        def _brutto_help(row: "dict | None", profil: "Profil", ergebnis_obj: "RentenErgebnis") -> str:
            """Baut eine dynamische Aufschlüsselung des Bruttoeinkommens für den Tooltip."""
            if row is None:
                src = [
                    ("Rente/Pension", ergebnis_obj.brutto_monatlich),
                ]
            else:
                def _m(key: str) -> float:
                    return row.get(key, 0) / 12
                src = [
                    ("Gehalt",            _m("Src_Gehalt")),
                    ("Rente/Pension",     _m("Src_GesRente")),
                    ("bAV",               _m("Src_bAV_P1")),
                    ("Riester",           _m("Src_Riester_P1")),
                    ("Versorgungsbezüge", _m("Src_Versorgung")),
                    ("DUV",               _m("Src_DUV_P1")),
                    ("BUV",               _m("Src_BUV_P1")),
                    ("Mieteinnahmen",     _m("Src_Miete")),
                    ("Einmalausz. (÷12)", _m("Src_Einmal")),
                    ("Kapitalverzehr",    _m("Src_Kapitalverzehr")),
                ]
            parts = [f"{lbl}: {_de(v)} €/Mon." for lbl, v in src if v > 0.5]
            base = "Monatliche Bruttoeinnahmen: " + " | ".join(parts) if parts else "Alle Einkommensquellen."
            return (
                base + "\n\n"
                "Enthält: gesetzliche Rente (× Besteuerungsanteil § 22 EStG) bzw. Pension (nach VFB § 19 Abs. 2 EStG), "
                "Vorsorgeauszahlungen (bAV, Riester, PrivRV), Mieteinnahmen (§ 21 EStG, bei Paar je 50 %), "
                "Einmalauszahlungen (Jahresbetrag ÷ 12), Kapitalverzehr aus dem Pool. Vor Steuern und KV/PV."
            )

        def _steuer_help_person(profil: "Profil", veranlagung_typ: str = "einzel") -> str:
            if veranlagung_typ == "splitting":
                return (
                    "Einkommensteuer (§ 32a EStG) + Solidaritätszuschlag (§ 51a EStG) beider Personen "
                    "im Splitting-Verfahren (§ 32a Abs. 5 EStG): ESt = 2 × ESt(zvE / 2). "
                    "Basis: zvE = Bruttoeinkünfte − Grundfreibetrag − Altersentlastungsbetrag (§ 24a) − VFB (§ 19 Abs. 2)."
                )
            if veranlagung_typ == "getrennt":
                return (
                    "Summe der Einkommensteuer (§ 32a EStG) + Soli beider Personen bei Getrenntveranlagung "
                    "(§ 25 EStG). Jede Person wird einzeln veranlagt. Keine Splitting-Wirkung."
                )
            return (
                "Einkommensteuer (§ 32a EStG) + Solidaritätszuschlag (§ 51a EStG) "
                "auf das zu versteuernde Einkommen dieser Person (Einzelveranlagung). "
                "Basis: zvE = Bruttoeinkünfte − Grundfreibetrag (§ 32a) − Altersentlastungsbetrag (§ 24a EStG)."
            )

        def _kv_help_person(profil: "Profil") -> str:
            kv_typ = profil.krankenversicherung
            if kv_typ == "PKV":
                return f"Privat krankenversichert (PKV): fixer Monatsbeitrag {_de(profil.pkv_beitrag)} €."
            if profil.ist_pensionaer or not profil.kvdr_pflicht:
                return (
                    "Freiwillige GKV (§ 240 SGB V): alle Einkünfte beitragspflichtig "
                    "(Rente, bAV ohne Freibetrag, PrivRV, Mieteinnahmen, Kapitalerträge). "
                    f"Mindest-BMG 1.096,67 €/Mon., Deckel BBG 5.175 €/Mon."
                )
            return (
                "KVdR-Pflichtmitglied (§ 5 Abs. 1 Nr. 11 SGB V): Beiträge nur auf §229-Einkünfte "
                "(gesetzliche Rente, bAV nach Freibetrag 187,25 €/Mon.). "
                "Private RV, Riester, Mieteinnahmen: nicht beitragspflichtig. "
                f"Deckel BBG 5.175 €/Mon."
            )

        def _src_person(row, ergebnis_obj):
            """Gibt (rente_gehalt, vorsorge, miete) in €/Mon. für eine Person zurück."""
            if row is None:
                return ergebnis_obj.brutto_monatlich, 0.0, 0.0
            rente = (row.get("Src_GesRente", 0) + row.get("Src_Gehalt", 0)) / 12
            vors, _ = _vorsorge_ausz_breakdown(row)
            miete = row.get("Src_Miete", 0) / 12
            return rente, vors, miete

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
                st.metric("Bruttoeinkommen", f"{_de(_b_d)} €",
                          help=_brutto_help(_row, _p, _e))
                st.metric("− Steuer", f"{_de(_s_d)} €",
                          help=_steuer_help_person(_p))
                st.metric("− KV / PV", f"{_de(_k_d)} €",
                          help=_kv_help_person(_p))
                st.metric("= Netto", f"{_de(_n_d)} €",
                          help="Bruttoeinkommen − Einkommensteuer − KV/PV.")
                st.caption(
                    f"Rentenpunkte: {_e.gesamtpunkte:.1f}".replace(".", ",") +
                    f" | {'Ruhestand seit' if _p.bereits_rentner else 'Renteneintritt'}: "
                    f"{_p.rentenbeginn_jahr if _p.bereits_rentner else _p.eintritt_jahr}"
                )
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
                st.metric("Bruttoeinkommen", f"{_de(_p1_b)} €",
                          help=_brutto_help(_row_p1, p1, e1))
                st.metric("− Steuer", f"{_de(_p1_s)} €",
                          help=_steuer_help_person(p1))
                st.metric("− KV / PV", f"{_de(_p1_k)} €",
                          help=_kv_help_person(p1))
                st.metric("= Netto", f"{_de(_p1_n)} €",
                          help="Bruttoeinkommen − Einkommensteuer − KV/PV.")
                st.caption(
                    f"Rentenpunkte: {e1.gesamtpunkte:.1f}".replace(".", ",") +
                    f" | {'Ruhestand seit' if p1.bereits_rentner else 'Renteneintritt'}: "
                    f"{p1.rentenbeginn_jahr if p1.bereits_rentner else p1.eintritt_jahr}"
                )

            with col2:
                st.markdown("**Person 2**")
                st.metric("Bruttoeinkommen", f"{_de(_p2_b)} €",
                          help=_brutto_help(_row_p2, p2, e2))
                st.metric("− Steuer", f"{_de(_p2_s)} €",
                          help=_steuer_help_person(p2))
                st.metric("− KV / PV", f"{_de(_p2_k)} €",
                          help=_kv_help_person(p2))
                st.metric("= Netto", f"{_de(_p2_n)} €",
                          help="Bruttoeinkommen − Einkommensteuer − KV/PV.")
                st.caption(
                    f"Rentenpunkte: {e2.gesamtpunkte:.1f}".replace(".", ",") +
                    f" | {'Ruhestand seit' if p2.bereits_rentner else 'Renteneintritt'}: "
                    f"{p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr}"
                )

            with col3:
                # Stacked bar: Einkommensquellen (Rente/Gehalt + Vorsorge + Miete)
                _p1_rente, _p1_vors, _p1_miete = _src_person(_row_p1, e1)
                _p2_rente, _p2_vors, _p2_miete = _src_person(_row_p2, e2)
                personen = ["Person 1", "Person 2"]
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="Rente / Pension / Gehalt", x=personen,
                    y=[_p1_rente, _p2_rente],
                    marker_color="#A5D6A7",
                    text=[f"{_de(v)} €" if v > 0.5 else "" for v in [_p1_rente, _p2_rente]],
                    textposition="inside",
                ))
                if max(_p1_vors, _p2_vors) > 0.5:
                    fig.add_trace(go.Bar(
                        name="Vorsorgeauszahlungen", x=personen,
                        y=[_p1_vors, _p2_vors],
                        marker_color="#42A5F5",
                        text=[f"{_de(v)} €" if v > 0.5 else "" for v in [_p1_vors, _p2_vors]],
                        textposition="inside",
                    ))
                if max(_p1_miete, _p2_miete) > 0.5:
                    fig.add_trace(go.Bar(
                        name="Mieteinnahmen", x=personen,
                        y=[_p1_miete, _p2_miete],
                        marker_color="#CE93D8",
                        text=[f"{_de(v)} €" if v > 0.5 else "" for v in [_p1_miete, _p2_miete]],
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
        sv1.metric("Steuer Zusammen (Mon.)", f"{_de(_st_zus)} €",
                   help=_steuer_help_person(p1, "splitting"))
        sv2.metric("Steuer Getrennt (Mon.)", f"{_de(_st_get)} €",
                   help=_steuer_help_person(p1, "getrennt"))
        sv3.metric("Steuer P1 (Mon.)", f"{_de(_st_p1)} €",
                   help=_steuer_help_person(p1) +
                        " Mieteinnahmen je 50 % bei Paar.")
        sv4.metric("Steuer P2 (Mon.)", f"{_de(_st_p2)} €",
                   help=_steuer_help_person(p2) +
                        " Mieteinnahmen je 50 % bei Paar.")

        # Zeile 2: Netto
        sv5, sv6, sv7, sv8 = st.columns(4)
        sv5.metric("Netto Zusammen (Mon.)", f"{_de(_nt_zus)} €",
                   help="Haushaltsnetto beider Personen nach Splitting-Steuer und KV/PV.")
        sv6.metric("Netto Getrennt (Mon.)", f"{_de(_nt_get)} €",
                   help="Haushaltsnetto beider Personen nach Getrenntveranlagungs-Steuer und KV/PV.")
        sv7.metric("Netto P1 (Mon.)", f"{_de(_nt_p1)} €",
                   help="Netto von Person 1 bei Einzelveranlagung (halbe Mieteinnahmen).")
        sv8.metric("Netto P2 (Mon.)", f"{_de(_nt_p2)} €",
                   help="Netto von Person 2 bei Einzelveranlagung (halbe Mieteinnahmen).")

        ersparnis_monatlich = _nt_zus - _nt_get
        if ersparnis_monatlich > 1:
            st.success(
                f"**Zusammenveranlagung spart {_de(ersparnis_monatlich)} €/Monat "
                f"({_de(ersparnis_monatlich * 12)} €/Jahr)** gegenüber getrennter Veranlagung."
            )
        else:
            st.info("In diesem Fall ergibt sich kein Splitting-Vorteil "
                    "(ähnlich hohe Einkommen beider Partner).")

        # Stacked bar: Einkommensquellen für Zusammen, Getrennt, P1, P2
        def _src_hh(row, fallback_b1, fallback_b2=0.0):
            if row is None:
                return fallback_b1 + fallback_b2, 0.0, 0.0
            rente = (row.get("Src_GesRente", 0) + row.get("Src_P2_Rente", 0) + row.get("Src_Gehalt", 0)) / 12
            vors, _ = _vorsorge_ausz_breakdown(row)
            miete = row.get("Src_Miete", 0) / 12
            return rente, vors, miete

        _rente_zus, _vors_zus, _miete_zus = _src_hh(_row_zus, e1.brutto_monatlich, e2.brutto_monatlich)
        _rente_get, _vors_get, _miete_get = _src_hh(_row_get, e1.brutto_monatlich, e2.brutto_monatlich)
        _rente_p1,  _vors_p1,  _miete_p1  = _src_person(_row_p1, e1)
        _rente_p2,  _vors_p2,  _miete_p2  = _src_person(_row_p2, e2)

        _szv_x = ["Zusammen\n(Splitting)", "Getrennt", "Person 1\n(allein)", "Person 2\n(allein)"]
        _rente_vals = [_rente_zus, _rente_get, _rente_p1, _rente_p2]
        _vors_vals  = [_vors_zus,  _vors_get,  _vors_p1,  _vors_p2]
        _miete_vals = [_miete_zus, _miete_get, _miete_p1, _miete_p2]

        fig_st = go.Figure()
        fig_st.add_trace(go.Bar(
            name="Rente / Pension / Gehalt", x=_szv_x, y=_rente_vals,
            marker_color="#A5D6A7",
            text=[f"{_de(v)} €" if v > 0.5 else "" for v in _rente_vals],
            textposition="inside",
        ))
        if max(_vors_vals) > 0.5:
            fig_st.add_trace(go.Bar(
                name="Vorsorgeauszahlungen", x=_szv_x, y=_vors_vals,
                marker_color="#42A5F5",
                text=[f"{_de(v)} €" if v > 0.5 else "" for v in _vors_vals],
                textposition="inside",
            ))
        if max(_miete_vals) > 0.5:
            fig_st.add_trace(go.Bar(
                name="Mieteinnahmen", x=_szv_x, y=_miete_vals,
                marker_color="#CE93D8",
                text=[f"{_de(v)} €" if v > 0.5 else "" for v in _miete_vals],
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

        with st.expander("🧾 Steuer- & KV-Details Person 1", expanded=False):
            steuern.render_section(p1, e1, mieteinnahmen / 2 if mieteinnahmen > 0 else 0.0,
                                   key_prefix="hh_p1")
        with st.expander("🧾 Steuer- & KV-Details Person 2", expanded=False):
            steuern.render_section(p2, e2, mieteinnahmen / 2 if mieteinnahmen > 0 else 0.0,
                                   key_prefix="hh_p2")

        render_analyse(
            p1, e1, label="Person 1",
            profil2=p2, ergebnis2=e2,
            veranlagung=veranlagung,
            mieteinnahmen=mieteinnahmen / 2,
            hh=hh,
            rc=_rc,
        )

        st.caption(
            "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
            "Keine Steuer- oder Anlageberatung."
        )

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
