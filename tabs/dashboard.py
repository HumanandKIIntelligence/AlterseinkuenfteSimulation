"""Dashboard-Tab – Rentenübersicht auf einen Blick."""

import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, GRUNDFREIBETRAG_2024, AKTUELLES_JAHR,
    GRUNDSICHERUNG_SCHWELLE,
    berechne_haushalt, _netto_ueber_horizont,
    einkommensteuer, einkommensteuer_splitting, solidaritaetszuschlag,
)
from tabs import steuern
from tabs.analyse import render_analyse

try:
    from tabs.hypothek import get_hyp_schedule, get_anschluss_schedule
except ImportError:
    def get_hyp_schedule():
        return []
    def get_anschluss_schedule():
        return []


def _actual_startjahr(vp: dict) -> int:
    """Tatsächlich gewähltes Auszahlungs-Startjahr aus dem Vorsorge-Tab.

    Liest rc{_rc}_vp_sels (vom Vorsorge-Tab gespeichert); Fallback: fruehestes_startjahr.
    """
    _rc = st.session_state.get("_rc", 0)
    _sels = st.session_state.get(f"rc{_rc}_vp_sels", {})
    _pid = vp.get("id")
    _sel = _sels.get(_pid) if _pid else None
    if _sel is not None:
        try:
            return int(str(_sel).rsplit("_", 1)[0])
        except (ValueError, IndexError):
            pass
    return int(vp.get("fruehestes_startjahr", AKTUELLES_JAHR))


def _vorsorge_non_bav_einzeln(produkte: list[dict], jahr: int,
                               person: str | None = None) -> list[tuple[str, float]]:
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
            if _actual_startjahr(vp) <= jahr:
                continue
        bbj = int(vp.get("beitragsbefreiung_jahr", 0))
        if bbj > 0 and jahr >= bbj:
            continue
        dyn = float(vp.get("jaehrl_dynamik", 0.0))
        monatlich = je * (1.0 + dyn) ** max(0, jahr - AKTUELLES_JAHR) / 12.0
        result.append((vp.get("name", "Vorsorge"), monatlich))
    return result


def _vorsorge_non_bav_monatlich(produkte: list[dict], jahr: int,
                                 person: str | None = None) -> float:
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
        if _actual_startjahr(vp) <= jahr:
            continue
        bbj = int(vp.get("beitragsbefreiung_jahr", 0))
        if bbj > 0 and jahr >= bbj:
            continue
        dyn = float(vp.get("jaehrl_dynamik", 0.0))
        total += je * (1.0 + dyn) ** max(0, jahr - AKTUELLES_JAHR) / 12.0
    return total


def _eink_label(profil: "Profil", sel_jahr: int) -> str:
    """Einkommens-Label abhängig vom Zustand der Person im gewählten Jahr."""
    in_rente = profil.bereits_rentner or sel_jahr >= profil.eintritt_jahr
    if not in_rente:
        return "Brutto"
    return "Pension" if profil.ist_pensionaer else "Rente"


def _netto_label(eink_lbl: str) -> str:
    """Netto-Label für das Ende des Wasserfalls."""
    return {"Rente": "Nettorente", "Pension": "Nettopension"}.get(eink_lbl, "Nettoeinkommen")


def _de(v: float, dec: int = 0) -> str:
    """Zahl im deutschen Format: 1.234,56"""
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _load_laufende_entsch(person: str | None = None) -> list:
    """VorsorgeProdukt-Entscheidungen für laufende (nicht als_kapitalanlage) Produkte."""
    try:
        from tabs.vorsorge import _aus_dict as _vd, _migriere as _vm
    except ImportError:
        return []
    entsch = []
    for d in st.session_state.get("vp_produkte", []):
        d = _vm(d)
        if d.get("als_kapitalanlage", False):
            continue
        if float(d.get("max_monatsrente", 0.0)) <= 0:
            continue
        if person is not None and d.get("person", "Person 1") != person:
            continue
        try:
            prod = _vd(d)
            entsch.append((prod, _actual_startjahr(d), 0.0))
        except Exception:
            pass
    return entsch


def _grenzsteuersatz(zvE: float) -> float:
    if zvE <= 11_604:
        return 0.0
    if zvE <= 17_005:
        y = (zvE - 11_604) / 10_000
        return (1_856.74 * y + 1_400) / 10_000
    if zvE <= 66_760:
        z = (zvE - 17_005) / 10_000
        return (353.28 * z + 2_397) / 10_000
    if zvE <= 277_825:
        return 0.42
    return 0.45


def _kv_pv_split(profil: Profil, kv_gesamt: float,
                  ergebnis: RentenErgebnis | None = None) -> tuple[float, float]:
    """Gibt (GKV-Anteil, PV-Anteil) des monatlichen KV-Beitrags zurück."""
    if ergebnis is not None and (ergebnis.kv_gkv_monatlich + ergebnis.kv_pv_monatlich) > 0:
        return ergebnis.kv_gkv_monatlich, ergebnis.kv_pv_monatlich
    if profil.krankenversicherung == "PKV":
        return kv_gesamt, 0.0
    _freiwillig = profil.ist_pensionaer or not profil.kvdr_pflicht
    if _freiwillig:
        _kv_rate = 0.146 + profil.gkv_zusatzbeitrag
        _pv_rate = 0.034 if profil.kinder else 0.040
    else:
        _kv_rate = 0.073 + profil.gkv_zusatzbeitrag / 2
        _pv_rate = 0.017 if profil.kinder else 0.023
    _total = _kv_rate + _pv_rate
    if _total == 0:
        return 0.0, 0.0
    return kv_gesamt * _kv_rate / _total, kv_gesamt * _pv_rate / _total


def _steuerampel(zvE: float, titel: str = "", splitting: bool = False) -> None:
    """zvE: bei splitting=True das kombinierte Haushalts-zvE; sonst individuelles zvE."""
    if zvE <= 0:
        zvE = 0.0
    f = 2 if splitting else 1              # Grenzen × 2 für Splitting-Haushalt
    zvE_ind = zvE / f                      # individuelles zvE für Grenzsteuersatz

    _GFB = GRUNDFREIBETRAG_2024 * f
    _Z1  = 17_005 * f
    _Z2  = 66_760 * f
    _Z42 = 277_825 * f

    if zvE <= _GFB:
        zone = "Steuerfrei"
        farbe = "✅"
        gst = 0.0
        freiraum = _GFB - zvE
        naechste = f"Grundfreibetrag ({_de(_GFB)} €)"
        tipp = "Optimale Zone – Einkommen vollständig unter Grundfreibetrag."
    elif zvE <= _Z1:
        zone = "Progressionszone 1 (14–24 %)"
        farbe = "🟢"
        gst = _grenzsteuersatz(zvE_ind)
        freiraum = _Z1 - zvE
        naechste = f"Zone 2 ({_de(_Z1)} €)"
        tipp = "Geringe Progression – Einnahmen vorziehen oder strecken prüfen."
    elif zvE <= _Z2:
        zone = "Progressionszone 2 (24–42 %)"
        farbe = "🟡"
        gst = _grenzsteuersatz(zvE_ind)
        freiraum = _Z2 - zvE
        naechste = f"42%-Zone ({_de(_Z2)} €)"
        tipp = "Wachsende Progression – Aufschub oder Einmalentnahme-Streckung sinnvoll."
    elif zvE <= _Z42:
        zone = "Proportionalzone 42 %"
        farbe = "🟠"
        gst = 0.42
        freiraum = _Z42 - zvE
        naechste = f"Spitzensteuersatz ({_de(_Z42)} €)"
        tipp = "42 % Grenzsteuersatz – Einnahmen auf mehrere Jahre verteilen."
    else:
        zone = "Spitzensteuersatz 45 %"
        farbe = "🔴"
        gst = 0.45
        freiraum = 0.0
        naechste = "–"
        tipp = "Maximale Steuerbelastung – intensive Steuerplanung und -beratung empfohlen."

    _header = f"{farbe} Steuerzone: {zone}"
    if titel:
        _header = f"{farbe} {titel} – {zone}"
    st.subheader(_header)
    zc1, zc2, zc3, zc4 = st.columns(4)
    zc1.metric("Grenzsteuersatz", f"{gst:.1%}".replace(".", ","),
               help="Steuersatz auf jeden zusätzlichen Euro Einkommen.")
    _zvE_label = "zvE Haushalt" if splitting else "zvE aktuell"
    zc2.metric(_zvE_label, f"{_de(zvE)} €/Jahr")
    if splitting:
        _est  = einkommensteuer_splitting(zvE)
        _soli = 2 * solidaritaetszuschlag(einkommensteuer(zvE_ind))
    else:
        _est  = einkommensteuer(zvE)
        _soli = solidaritaetszuschlag(_est)
    zc3.metric("Jahressteuer (ESt + Soli)",
               f"{_de(_est + _soli)} €",
               help=f"ESt: {_de(_est)} € + Soli: {_de(_soli, 2)} € (5,5 % ab 17.543 € ESt)")
    if freiraum > 0:
        zc4.metric(f"Freiraum bis {naechste}", f"{_de(freiraum)} €",
                   help="Um diesen Betrag kann das zvE noch steigen, bevor der nächste Steuersatz greift.")
    else:
        zc4.metric("Nächste Zone", "–")
    st.info(f"💡 **Handlungshinweis:** {tipp}")


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis,
           mieteinnahmen: float = 0.0,
           mietsteigerung: float = 0.0,
           profil2: Profil | None = None,
           ergebnis2: RentenErgebnis | None = None,
           veranlagung: str = "Getrennt") -> None:
    _rc = st.session_state.get("_rc", 0)
    with T["Dashboard"]:
        st.header("📊 Rentenübersicht")

        hat_partner = profil2 is not None and ergebnis2 is not None
        wahl = "Person 1"
        if hat_partner:
            wahl = st.radio("Ansicht", ["Person 1", "Person 2", "Zusammen"],
                            horizontal=True, key=f"rc{_rc}_dash_person")

        zusammen_modus = wahl == "Zusammen"
        # P1-Ergebnis vor dem Swap aufbewahren (Kapital ist Haushaltsvermögen unter P1)
        _ergebnis_p1_kapital = ergebnis

        if wahl == "Person 2":
            profil, ergebnis = profil2, ergebnis2

        # ══════════════════════════════════════════════════════════════════════
        # ZUSAMMEN-ANSICHT
        # ══════════════════════════════════════════════════════════════════════
        if zusammen_modus:
            hh = berechne_haushalt(ergebnis, ergebnis2, veranlagung, mieteinnahmen, profil, profil2)

            # Jahressimulationen für Slider (HH kombiniert + Einzelpersonen)
            _g_p1 = 0.0 if profil.ist_pensionaer  or profil.bereits_rentner  else profil.aktuelles_brutto_monatlich
            _g_p2 = 0.0 if profil2.ist_pensionaer or profil2.bereits_rentner else profil2.aktuelles_brutto_monatlich
            _start_p1_ret = profil.rentenbeginn_jahr  if profil.bereits_rentner  else profil.eintritt_jahr
            _start_p2_ret = profil2.rentenbeginn_jahr if profil2.bereits_rentner else profil2.eintritt_jahr
            _start_hh     = min(_start_p1_ret, _start_p2_ret)
            _end_hh       = _start_hh + 30
            _start_slider_hh = AKTUELLES_JAHR if (_g_p1 > 0 or _g_p2 > 0) else _start_hh
            _hz_p1 = _end_hh - _start_p1_ret + 1
            _hz_p2 = _end_hh - _start_p2_ret + 1
            _entsch_all = _load_laufende_entsch(None)
            _entsch_p1  = _load_laufende_entsch("Person 1")
            _entsch_p2  = _load_laufende_entsch("Person 2")
            _, _jd_dash    = _netto_ueber_horizont(
                profil, ergebnis, _entsch_all, _hz_p1, mieteinnahmen, mietsteigerung,
                profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung,
                gehalt_monatlich=_g_p1,
            )
            _miete_je_dash = mieteinnahmen / 2  # 50/50 je Person bei Paar
            _, _jd_dash_p1 = _netto_ueber_horizont(profil,  ergebnis,  _entsch_p1, _hz_p1,
                                                    _miete_je_dash, mietsteigerung, gehalt_monatlich=_g_p1)
            _, _jd_dash_p2 = _netto_ueber_horizont(profil2, ergebnis2, _entsch_p2, _hz_p2,
                                                    _miete_je_dash, mietsteigerung, gehalt_monatlich=_g_p2)
            _sel_j_dash = st.slider(
                "Betrachtungsjahr", _start_slider_hh, _end_hh,
                min(_end_hh, max(_start_slider_hh, _start_hh)), key=f"rc{_rc}_dash_jahr",
                help="Zeigt projizierte Haushaltswerte mit Rentenanpassung für das gewählte Jahr.",
            )
            _row_dash    = next((r for r in _jd_dash    if r["Jahr"] == _sel_j_dash), None)
            _row_dash_p1 = next((r for r in _jd_dash_p1 if r["Jahr"] == _sel_j_dash), None)
            _row_dash_p2 = next((r for r in _jd_dash_p2 if r["Jahr"] == _sel_j_dash), None)
            # Einzelnetto für P1 vs P2 Chart (inkl. Produkteinkommen)
            _p1_n_y = _row_dash_p1["Netto"]  / 12 if _row_dash_p1 else ergebnis.netto_monatlich
            _p2_n_y = _row_dash_p2["Netto"]  / 12 if _row_dash_p2 else ergebnis2.netto_monatlich
            # P1/P2 Basis-Brutto (Rente/Pension/Gehalt + Zusatzentgelt, ohne bAV/Riester)
            _p1_b_y = (
                _row_dash.get("Src_GesRente", 0)
                + _row_dash.get("Src_Gehalt", 0)
                + _row_dash.get("Src_Zusatzentgelt", 0)
            ) / 12 if _row_dash else ergebnis.brutto_monatlich
            _p2_b_y = _row_dash.get("Src_P2_Rente", 0) / 12 if _row_dash else ergebnis2.brutto_monatlich
            # bAV und Riester (P1 + P2 zusammen, aus HH-Simulation)
            _zus_bav = (_row_dash.get("Src_bAV_P1", 0) + _row_dash.get("Src_bAV_P2", 0)) / 12 \
                       if _row_dash else 0.0
            _zus_riester = (_row_dash.get("Src_Riester_P1", 0) + _row_dash.get("Src_Riester_P2", 0)) / 12 \
                           if _row_dash else 0.0
            _miete_y = _row_dash.get("Src_Miete", 0) / 12 if _row_dash else mieteinnahmen
            # zvE für Steuerampel
            _miet_r_y = max(0, _sel_j_dash - _start_hh)
            _miete_zvE_half = mieteinnahmen * (1 + mietsteigerung) ** _miet_r_y * 6  # halbes Jahresmiete je Person (Fallback)
            _zvE_dash = _row_dash["zvE"] if _row_dash else (ergebnis.zvE_jahres + ergebnis2.zvE_jahres + mieteinnahmen * 12)
            # Individuelle zvE: Simulation enthält bereits halbe Miete; Fallback ergänzt sie manuell
            _zvE_p1_y = _row_dash_p1["zvE"] if _row_dash_p1 else ergebnis.zvE_jahres + _miete_zvE_half
            _zvE_p2_y = _row_dash_p2["zvE"] if _row_dash_p2 else ergebnis2.zvE_jahres + _miete_zvE_half

            # Header: beide Personen
            hi1, hi2 = st.columns(2)
            with hi1:
                _ab1 = (
                    f"  |  Abschlag: {ergebnis.rentenabschlag:.1%}".replace(".", ",")
                    if ergebnis.rentenabschlag > 0 else ""
                )
                st.info(
                    f"**P1:** {profil.aktuelles_alter} Jahre  |  "
                    f"Renteneintritt {profil.renteneintritt_alter} ({profil.eintritt_jahr})  |  "
                    f"Noch {profil.jahre_bis_rente} Jahre" + _ab1
                )
            with hi2:
                _ab2 = (
                    f"  |  Abschlag: {ergebnis2.rentenabschlag:.1%}".replace(".", ",")
                    if ergebnis2.rentenabschlag > 0 else ""
                )
                st.info(
                    f"**P2:** {profil2.aktuelles_alter} Jahre  |  "
                    f"Renteneintritt {profil2.renteneintritt_alter} ({profil2.eintritt_jahr})  |  "
                    f"Noch {profil2.jahre_bis_rente} Jahre" + _ab2
                )

            # ── Top-Kennzahlen (Jahr-spezifisch) ─────────────────────────────
            _hh_brutto = _row_dash["Brutto"] / 12 if _row_dash else hh["brutto_gesamt"]
            _hh_netto  = _row_dash["Netto"]  / 12 if _row_dash else hh["netto_gesamt"]
            _hh_steuer = _row_dash["Steuer"] / 12 if _row_dash else hh["steuer_gesamt"]
            _hh_kv     = _row_dash["KV_PV"]  / 12 if _row_dash else hh["kv_gesamt"]
            _hh_kv_p1  = _row_dash["KV_P1"]  / 12 if _row_dash and "KV_P1" in _row_dash else None
            _hh_kv_p2  = _row_dash["KV_P2"]  / 12 if _row_dash and "KV_P2" in _row_dash else None

            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                f"Brutto Haushalt {_sel_j_dash}", f"{_de(_hh_brutto)} €/Mon.",
                help="Gesetzliche Renten + Zusatzrenten beider Personen + Mieteinnahmen.",
            )
            c2.metric(
                f"Netto Haushalt {_sel_j_dash}", f"{_de(_hh_netto)} €/Mon.",
                help="Nach Einkommensteuer und KV/PV beider Personen.",
            )
            kapital_gesamt = ergebnis.kapital_bei_renteneintritt  # P1 = geteiltes Haushaltsvermögen
            c3.metric(
                "Kapital gesamt (Eintritt)", f"{_de(kapital_gesamt)} €",
                help="Angewachsenes gemeinsames Spar- und Depotkapital zum früheren Renteneintritt.",
            )
            if hh["steuerersparnis_splitting"] > 0:
                c4.metric(
                    "Splitting-Ersparnis / Mon.", f"{_de(hh['steuerersparnis_splitting'])} €",
                    help="Steuerersparnis durch Zusammenveranlagung (§ 32a Abs. 5 EStG) gegenüber getrennter Veranlagung.",
                )
            else:
                c4.metric(f"Steuer {_sel_j_dash} / Mon.", f"{_de(_hh_steuer)} €")

            # ── Zeile 2: P1/P2 Netto + Steuer / KV ──────────────────────────
            c5, c6, c7, c8, c9 = st.columns(5)
            c5.metric(f"P1 Netto {_sel_j_dash}", f"{_de(_p1_n_y)} €/Mon.")
            c6.metric(f"P2 Netto {_sel_j_dash}", f"{_de(_p2_n_y)} €/Mon.")
            c7.metric(f"Steuer {_sel_j_dash} / Mon.", f"{_de(_hh_steuer)} €")
            c8.metric(f"KV/PV {_sel_j_dash} / Mon.", f"{_de(_hh_kv)} €")
            if mieteinnahmen > 0:
                c9.metric(
                    "Mieteinnahmen", f"{_de(mieteinnahmen)} €/Mon.",
                    help="Gemeinsame Nettomieteinnahmen (§ 21 EStG).",
                )
            else:
                c9.metric(
                    "Veranlagung", veranlagung,
                    help="Getrennte oder gemeinsame Einkommensteuerveranlagung.",
                )

            st.divider()

            # ── Wasserfall Haushalt Brutto → Verfügbar ───────────────────────
            st.subheader(f"Haushalt Brutto → Verfügbar {_sel_j_dash} (monatlich)")
            _ba1_pct = f"{ergebnis.besteuerungsanteil:.0%}".replace(".", ",")
            _ba2_pct = f"{ergebnis2.besteuerungsanteil:.0%}".replace(".", ",")
            _ver_label = "Zusammenveranlagung (Splitting)" if veranlagung == "Zusammen" else "Getrenntveranlagung"
            _lbl_p1 = _eink_label(profil,  _sel_j_dash)
            _lbl_p2 = _eink_label(profil2, _sel_j_dash)
            _wf_x = [f"P1 {_lbl_p1}", f"P2 {_lbl_p2}"]
            _wf_m = ["absolute", "relative"]
            _wf_y = [_p1_b_y, _p2_b_y]
            _wf_t = [
                f"{_de(_p1_b_y)} €",
                f"+{_de(_p2_b_y)} €",
            ]
            _wf_h = [
                f"<b>P1 {_lbl_p1} (brutto)</b><br>"
                f"{_de(_p1_b_y)} €/Mon.<br>"
                f"Gesetzliche Rente + Zusatzrente vor Steuer und KV.<br>"
                f"Besteuerungsanteil: {_ba1_pct} (Renteneintritt {profil.eintritt_jahr})",
                f"<b>P2 {_lbl_p2} (brutto)</b><br>"
                f"+{_de(_p2_b_y)} €/Mon.<br>"
                f"Gesetzliche Rente + Zusatzrente vor Steuer und KV.<br>"
                f"Besteuerungsanteil: {_ba2_pct} (Renteneintritt {profil2.eintritt_jahr})",
            ]
            if _zus_bav > 0:
                _wf_x.append("+ bAV")
                _wf_m.append("relative")
                _wf_y.append(_zus_bav)
                _wf_t.append(f"+{_de(_zus_bav)} €")
                _wf_h.append(
                    f"<b>Betriebliche Altersversorgung (P1+P2)</b><br>"
                    f"+{_de(_zus_bav)} €/Mon.<br>"
                    f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                    f"KV: abzgl. Freibetrag 187,25 €/Mon. (§ 226 Abs. 2 SGB V)."
                )
            if _zus_riester > 0:
                _wf_x.append("+ Riester")
                _wf_m.append("relative")
                _wf_y.append(_zus_riester)
                _wf_t.append(f"+{_de(_zus_riester)} €")
                _wf_h.append(
                    f"<b>Riester-Rente (P1+P2)</b><br>"
                    f"+{_de(_zus_riester)} €/Mon.<br>"
                    f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                    f"Nicht KV-pflichtig (private Rentenleistung)."
                )
            if _miete_y > 0:
                _wf_x.append("Mieteinnahmen")
                _wf_m.append("relative")
                _wf_y.append(_miete_y)
                _wf_t.append(f"+{_de(_miete_y)} €")
                _wf_h.append(
                    f"<b>Mieteinnahmen (gesamt)</b><br>"
                    f"+{_de(_miete_y)} €/Mon.<br>"
                    f"Netto nach abzugsfähigen Werbungskosten (§ 21 EStG).<br>"
                    f"Voll steuerpflichtig, keine KV-Pflicht. Steuerlich 50/50 aufgeteilt."
                )
            # Sonstige Einnahmen (Rürup, PrivRV, Kapitalverzehr etc.)
            _sonst_zus = _hh_brutto - _p1_b_y - _p2_b_y - _zus_bav - _zus_riester - _miete_y
            if _sonst_zus > 0.5:
                _wf_x.append("+ Sonstige")
                _wf_m.append("relative")
                _wf_y.append(_sonst_zus)
                _wf_t.append(f"+{_de(_sonst_zus)} €")
                _wf_h.append(
                    f"<b>Sonstige Einnahmen</b><br>"
                    f"+{_de(_sonst_zus)} €/Mon.<br>"
                    f"Rürup, Private RV, Kapitalverzehr u.a.<br>"
                    f"Steuerlich nach jeweiliger Regelung."
                )
            _wf_x += ["− Einkommensteuer", "− KV/PV", "Netto Haushalt"]
            _wf_m += ["relative", "relative", "total"]
            _wf_y += [-_hh_steuer, -_hh_kv, _hh_netto]
            _wf_t += [
                f"−{_de(_hh_steuer)} €",
                f"−{_de(_hh_kv)} €",
                f"{_de(_hh_netto)} €",
            ]
            _wf_h += [
                f"<b>Einkommensteuer + Solidaritätszuschlag</b><br>"
                f"−{_de(_hh_steuer)} €/Mon.<br>"
                f"{_ver_label} (§ 32a EStG).<br>"
                f"Soli: 5,5 % ab 17.543 € ESt (§ 51a EStG).",
                f"<b>Kranken- + Pflegeversicherung (Haushalt)</b><br>"
                f"−{_de(_hh_kv)} €/Mon."
                + (f"<br>P1: {_de(_hh_kv_p1)} €, P2: {_de(_hh_kv_p2)} €" if _hh_kv_p1 is not None else "")
                + "<br>GKV/PKV je nach Versicherungsstatus.<br>"
                "BBG: 5.175 €/Mon.",
                f"<b>Netto Haushalt</b><br>"
                f"{_de(_hh_netto)} €/Mon.<br>"
                f"Nach Steuer und KV/PV-Abzügen.",
            ]
            # Vorsorgebeiträge: bAV-Beiträge (AN-Anteil) + sonstige Vorsorge
            _vp_produkte_hh = st.session_state.get("vp_produkte", [])
            _bav_m_hh = _vorsorge_bav_monatlich(_vp_produkte_hh, _sel_j_dash)
            if _bav_m_hh > 0:
                _wf_x.append("− bAV-Beiträge")
                _wf_m.append("relative")
                _wf_y.append(-_bav_m_hh)
                _wf_t.append(f"−{_de(_bav_m_hh)} €")
                _wf_h.append(
                    f"<b>bAV-Beiträge (AN-Anteil)</b><br>"
                    f"−{_de(_bav_m_hh)} €/Mon.<br>"
                    f"Eigenbeitrag zur betrieblichen Altersversorgung.<br>"
                    f"Reduziert verfügbares Netto in der Ansparphase."
                )
            _vb_einzeln_hh = _vorsorge_non_bav_einzeln(_vp_produkte_hh, _sel_j_dash)
            _vb_m_hh = sum(b for _, b in _vb_einzeln_hh)
            if _vb_m_hh > 0:
                _vb_detail_hh = "; ".join(f"{n}: {_de(v)} €" for n, v in _vb_einzeln_hh)
                _wf_x.append("− Vorsorge\n(ohne bAV)")
                _wf_m.append("relative")
                _wf_y.append(-_vb_m_hh)
                _wf_t.append(f"−{_de(_vb_m_hh)} €")
                _wf_h.append(
                    f"<b>Vorsorge-Beiträge (ohne bAV)</b><br>"
                    f"−{_de(_vb_m_hh)} €/Mon.<br>"
                    f"Laufende Beiträge: {_vb_detail_hh}.<br>"
                    f"Reduzieren das verfügbare Netto während der Beitragsphase."
                )
            # Fixe monatliche Ausgaben
            _hh_fix_aktiv = [
                fa for fa in st.session_state.get("hh_fixausgaben", [])
                if fa["startjahr"] <= _sel_j_dash <= fa["endjahr"]
            ]
            _hh_fix_m = sum(fa["betrag_monatlich"] for fa in _hh_fix_aktiv)
            if _hh_fix_m > 0:
                _hh_fix_detail = "; ".join(
                    f"{fa['name']}: {_de(fa['betrag_monatlich'])} €" for fa in _hh_fix_aktiv
                )
                _wf_x.append("− Fixe Ausgaben")
                _wf_m.append("relative")
                _wf_y.append(-_hh_fix_m)
                _wf_t.append(f"−{_de(_hh_fix_m)} €")
                _wf_h.append(
                    f"<b>Fixe monatliche Ausgaben</b><br>"
                    f"−{_de(_hh_fix_m)} €/Mon.<br>"
                    f"Summe aktiver Fixausgaben {_sel_j_dash}.<br>"
                    + (f"{_hh_fix_detail}." if _hh_fix_detail else "")
                )
            # Hypothek
            _hyp_sched_hh = get_hyp_schedule()
            _hyp_row_hh = next((r for r in _hyp_sched_hh if r["Jahr"] == _sel_j_dash), None)
            _hyp_m_hh = _hyp_row_hh["Jahresausgabe"] / 12 if _hyp_row_hh else 0.0
            if _hyp_m_hh > 0:
                _wf_x.append("− Hypothek")
                _wf_m.append("relative")
                _wf_y.append(-_hyp_m_hh)
                _wf_t.append(f"−{_de(_hyp_m_hh)} €")
                _wf_h.append(
                    f"<b>Hypothek-Jahresrate</b><br>"
                    f"−{_de(_hyp_m_hh)} €/Mon.<br>"
                    f"Annuität {_sel_j_dash} (Zins + Tilgung).<br>"
                    f"Konfiguration im Tab Hypothek-Verwaltung."
                )
            _ak_sched_hh = get_anschluss_schedule()
            _ak_row_hh = next((r for r in _ak_sched_hh if r["Jahr"] == _sel_j_dash), None)
            _ak_m_hh = _ak_row_hh["Jahresausgabe"] / 12 if _ak_row_hh else 0.0
            if _ak_m_hh > 0:
                _wf_x.append("− Anschlusskredit")
                _wf_m.append("relative")
                _wf_y.append(-_ak_m_hh)
                _wf_t.append(f"−{_de(_ak_m_hh)} €")
                _wf_h.append(
                    f"<b>Anschlussfinanzierung</b><br>"
                    f"−{_de(_ak_m_hh)} €/Mon.<br>"
                    f"Annuität auf Restschuld nach Hypothek-Endjahr."
                )
            # Lebenshaltungskosten (beide Personen)
            _hh_lhk = (
                float(st.session_state.get(f"rc{_rc}_p1_lhk", 0.0))
                + float(st.session_state.get(f"rc{_rc}_p2_lhk", 0.0))
            )
            if _hh_lhk > 0:
                _wf_x.append("− Lebenshalt.")
                _wf_m.append("relative")
                _wf_y.append(-_hh_lhk)
                _wf_t.append(f"−{_de(_hh_lhk)} €")
                _wf_h.append(
                    f"<b>Lebenshaltungskosten (Haushalt)</b><br>"
                    f"−{_de(_hh_lhk)} €/Mon.<br>"
                    f"P1 + P2, Miete, Lebensmittel u.a.<br>"
                    f"Konfiguration im Tab Haushalt."
                )
            _hh_verfuegbar = _hh_netto - _bav_m_hh - _vb_m_hh - _hh_fix_m - _hyp_m_hh - _ak_m_hh - _hh_lhk
            _wf_x.append("Verfügbar")
            _wf_m.append("total")
            _wf_y.append(_hh_verfuegbar)
            _wf_t.append(f"{_de(_hh_verfuegbar)} €")
            _wf_h.append(
                f"<b>Verfügbares Einkommen (Haushalt)</b><br>"
                f"{_de(_hh_verfuegbar)} €/Mon.<br>"
                f"Nach Steuer, KV/PV, Vorsorge, Hypothek, Lebenshaltung und Fixausgaben."
            )
            fig_wf = go.Figure(go.Waterfall(
                orientation="v",
                measure=_wf_m,
                x=_wf_x,
                y=_wf_y,
                text=_wf_t,
                textposition="outside",
                customdata=_wf_h,
                hovertemplate="%{customdata}<extra></extra>",
                connector=dict(line=dict(color="#888")),
                increasing=dict(marker=dict(color="#4CAF50")),
                decreasing=dict(marker=dict(color="#F44336")),
                totals=dict(marker=dict(color="#2196F3")),
            ))
            _mindest_mono_hh = float(st.session_state.get("mindest_haushalt_mono", 2_000))
            fig_wf.add_hline(
                y=_mindest_mono_hh, line_dash="dot", line_color="orange", line_width=2,
                annotation_text=f"Mindest {_de(_mindest_mono_hh)} €",
                annotation_position="top right",
            )
            fig_wf.update_layout(
                template="plotly_white",
                height=380,
                yaxis=dict(title="€ / Monat", ticksuffix=" €"),
                margin=dict(l=10, r=10, t=10, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_wf, use_container_width=True)

            st.divider()

            # ── Vergleich P1 / P2 + Kaufkraft ────────────────────────────────
            left, right = st.columns(2)

            with left:
                st.subheader(f"Nettorente P1 vs. P2 – {_sel_j_dash}")
                fig_bar = go.Figure(go.Bar(
                    x=["Person 1", "Person 2"],
                    y=[_p1_n_y, _p2_n_y],
                    marker_color=["#2196F3", "#4CAF50"],
                    text=[f"{_de(_p1_n_y)} €", f"{_de(_p2_n_y)} €"],
                    textposition="outside",
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<extra></extra>",
                ))
                fig_bar.update_layout(
                    template="plotly_white", height=300,
                    yaxis=dict(title="Nettorente (€/Mon.)", ticksuffix=" €"),
                    margin=dict(l=10, r=10, t=10, b=10),
                    separators=",.",
                )
                st.plotly_chart(fig_bar, use_container_width=True)

            with right:
                st.subheader(f"Kaufkraft Haushalt heute vs. {_sel_j_dash}")
                _inf_pct_hh = st.number_input(
                    "Inflation p.a. (%)", 0.0, 5.0, 2.0, 0.1,
                    key=f"rc{_rc}_dash_inflation_hh",
                    help="Angenommene jährliche Inflationsrate für die Kaufkraftberechnung.",
                )
                inflation = _inf_pct_hh / 100
                jahre_max = _sel_j_dash - _start_hh + max(profil.jahre_bis_rente, profil2.jahre_bis_rente)
                kaufkraft = _hh_netto / (1 + inflation) ** max(0, jahre_max)
                verlust = _hh_netto - kaufkraft
                st.metric(
                    f"Haushaltsnetto {_sel_j_dash} in heutiger Kaufkraft ({_inf_pct_hh:.1f} % Inflation)".replace(".", ","),
                    f"{_de(kaufkraft)} €",
                    delta=f"−{_de(verlust)} € Kaufkraftverlust",
                    delta_color="inverse",
                )
                st.caption(
                    f"Das Haushaltsnetto von **{_de(_hh_netto)} €** im Jahr {_sel_j_dash} "
                    f"entspricht bei {_inf_pct_hh:.1f} % Inflation".replace(".", ",") +
                    f" der heutigen Kaufkraft von nur **{_de(kaufkraft)} €**."
                )

            st.divider()

            # ── Steuerampel ───────────────────────────────────────────────────
            if veranlagung == "Zusammen":
                st.caption(
                    f"Steuerampel auf Basis des gemeinsamen Haushalts-zvE bei Splitting "
                    f"(§ 32a Abs. 5 EStG). Grenzen = 2 × Einzelperson."
                )
                _steuerampel(_zvE_dash, splitting=True)
            else:
                ac1, ac2 = st.columns(2)
                with ac1:
                    _steuerampel(_zvE_p1_y, titel="Person 1")
                with ac2:
                    _steuerampel(_zvE_p2_y, titel="Person 2")

            st.divider()

            with st.expander("🧾 Steuer- & KV-Details Person 1", expanded=False):
                steuern.render_section(profil, ergebnis, mieteinnahmen / 2 if mieteinnahmen > 0 else 0.0)
            with st.expander("🧾 Steuer- & KV-Details Person 2", expanded=False):
                steuern.render_section(profil2, ergebnis2, mieteinnahmen / 2 if mieteinnahmen > 0 else 0.0)

            render_analyse(
                profil, ergebnis, label="Person 1",
                profil2=profil2, ergebnis2=ergebnis2,
                veranlagung=veranlagung,
                mieteinnahmen=mieteinnahmen / 2,
                hh=hh,
                rc=_rc,
            )

            # Grundsicherungs-Hinweis für beide Personen
            for _gs_label, _gs_netto in [("Person 1", _p1_n_y), ("Person 2", _p2_n_y)]:
                if 0 < _gs_netto < GRUNDSICHERUNG_SCHWELLE:
                    st.warning(
                        f"⚠️ **Grundsicherungsrisiko {_gs_label}:** Nettorente "
                        f"**{_de(_gs_netto)} €/Mon.** im Jahr {_sel_j_dash} "
                        f"unter Grundsicherungsschwelle ca. {_de(GRUNDSICHERUNG_SCHWELLE)} €/Mon. "
                        f"(§ 41 SGB XII)."
                    )

            st.caption(
                "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
                "Keine Steuer- oder Anlageberatung."
            )
            return

        # ══════════════════════════════════════════════════════════════════════
        # EINZELPERSON-ANSICHT (Person 1 oder Person 2)
        # ══════════════════════════════════════════════════════════════════════

        # Jahressimulation für Slider (mit laufenden Produkten)
        _start_einzel = profil.rentenbeginn_jahr if profil.bereits_rentner else profil.eintritt_jahr
        _g_einzel = 0.0 if profil.ist_pensionaer or profil.bereits_rentner else profil.aktuelles_brutto_monatlich
        _start_slider_einzel = AKTUELLES_JAHR if _g_einzel > 0 else _start_einzel
        _end_einzel = _start_einzel + 30
        _person_label_einzel = "Person 2" if wahl == "Person 2" else "Person 1"
        _entsch_einzel = _load_laufende_entsch(_person_label_einzel)
        # Beim Paar: Mieteinnahmen 50/50 für Einzelperson-Sicht
        _miete_einzel = mieteinnahmen / 2 if hat_partner else mieteinnahmen
        _, _jd_dash = _netto_ueber_horizont(profil, ergebnis, _entsch_einzel, 31, _miete_einzel, mietsteigerung, gehalt_monatlich=_g_einzel)
        _sel_j_dash = st.slider(
            "Betrachtungsjahr", _start_slider_einzel, _end_einzel,
            min(_end_einzel, max(_start_slider_einzel, _start_einzel)), key=f"rc{_rc}_dash_jahr",
            help="Zeigt projizierte Jahreswerte mit Rentenanpassung für das gewählte Jahr.",
        )
        _row_dash = next((r for r in _jd_dash if r["Jahr"] == _sel_j_dash), None)
        _d_miete  = _row_dash.get("Src_Miete", 0) / 12 if _row_dash else 0.0
        # Bruttorente = Rente/Pension + Produkte, OHNE Mieteinnahmen (eigene Kategorie)
        _d_brutto = (_row_dash["Brutto"] - _row_dash.get("Src_Miete", 0)) / 12 \
                    if _row_dash else ergebnis.brutto_monatlich
        _d_netto  = _row_dash["Netto"]  / 12 if _row_dash else ergebnis.netto_monatlich
        _d_steuer = _row_dash["Steuer"] / 12 if _row_dash else ergebnis.steuer_monatlich
        _d_kv     = _row_dash["KV_PV"]  / 12 if _row_dash else ergebnis.kv_monatlich
        _d_zvE    = _row_dash["zvE"]         if _row_dash else ergebnis.zvE_jahres
        _d_bav    = _row_dash.get("Src_bAV_P1", 0) / 12 if _row_dash else 0.0
        _d_riester= _row_dash.get("Src_Riester_P1", 0) / 12 if _row_dash else 0.0
        _d_duv    = _row_dash.get("Src_DUV_P1", 0) / 12 if _row_dash else 0.0
        _d_buv    = _row_dash.get("Src_BUV_P1", 0) / 12 if _row_dash else 0.0
        # Basis = Rente/Pension ohne bAV/Riester/DUV/BUV/Mieteinnahmen
        _d_basis  = _d_brutto - _d_bav - _d_riester - _d_duv - _d_buv

        abschlag_info = (
            f"  |  **Rentenabschlag:** {ergebnis.rentenabschlag:.1%}".replace(".", ",") +
            f" ({(67 - profil.renteneintritt_alter) * 12} Monate × 0,3 % § 77 SGB VI)"
            if ergebnis.rentenabschlag > 0 else ""
        )
        st.info(
            f"**Alter heute:** {profil.aktuelles_alter} Jahre  |  "
            f"**Renteneintritt:** {profil.renteneintritt_alter} Jahre ({profil.eintritt_jahr})  |  "
            f"**Noch {profil.jahre_bis_rente} Jahre bis zur Rente**"
            + abschlag_info
        )

        # ── Kennzahlen (Jahr-spezifisch via Slider) ───────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            f"Bruttorente {_sel_j_dash}", f"{_de(_d_brutto)} €/Mon.",
            help="Gesetzliche Rente + Zusatzrente vor Steuer und KV-Abzügen.",
        )
        c2.metric(
            f"Nettorente {_sel_j_dash}", f"{_de(_d_netto)} €/Mon.",
            help="Nach Einkommensteuer und Kranken-/Pflegeversicherungsbeitrag.",
        )
        _kapital_einzel = (_ergebnis_p1_kapital.kapital_bei_renteneintritt / 2
                          if hat_partner
                          else ergebnis.kapital_bei_renteneintritt)
        _kap_label = "Kapital (½ Haushalt, Eintritt)" if hat_partner else "Kapital bei Renteneintritt"
        c3.metric(
            _kap_label,
            f"{_de(_kapital_einzel)} €",
            help=("Anteil am gemeinsamen Haushaltsvermögen zum Renteneintritt (50/50)."
                  if hat_partner else
                  "Angewachsenes Spar- und Depotkapital zum Renteneintritt."),
        )
        c4.metric(
            "Rentenpunkte gesamt", f"{ergebnis.gesamtpunkte:.1f}".replace(".", ","),
            help=f"Aktuell {ergebnis.gesamtpunkte - profil.punkte_pro_jahr * profil.jahre_bis_rente:.1f} "
                 f"+ {profil.punkte_pro_jahr:.2f} Punkte/Jahr × {profil.jahre_bis_rente} Jahre.".replace(".", ","),
        )

        # KV/PV-Split berechnen (Eintrittsmonat-Verhältnis auf Jahr-KV anwenden)
        _kv_ratio = _kv_pv_split(profil, ergebnis.kv_monatlich, ergebnis)
        _kv_total_ratio = ergebnis.kv_monatlich if ergebnis.kv_monatlich > 0 else 1.0
        _kv_share_gkv = _kv_ratio[0] / _kv_total_ratio
        _kv_share_pv  = _kv_ratio[1] / _kv_total_ratio
        gkv_mono = _d_kv * _kv_share_gkv
        pv_mono  = _d_kv * _kv_share_pv
        _kv_label = "PKV / Monat" if profil.krankenversicherung == "PKV" else "KV / Monat"

        c5, c6, c7, c8, c9 = st.columns(5)
        c5.metric(
            "Gesetzl. Rente (brutto, Eintritt)", f"{_de(ergebnis.brutto_gesetzlich)} €/Mon.",
            help=f"Rentenabschlag: {ergebnis.rentenabschlag:.1%}".replace(".", ",") + " (§ 77 SGB VI)"
                 if ergebnis.rentenabschlag > 0 else None,
        )
        c6.metric(f"Steuer {_sel_j_dash} / Mon.", f"{_de(_d_steuer)} €")
        c7.metric(
            f"{_kv_label} {_sel_j_dash}", f"{_de(gkv_mono)} €",
            help="Krankenversicherungsbeitrag (eigener Anteil).",
        )
        if profil.krankenversicherung == "GKV":
            _freiwillig = profil.ist_pensionaer or not profil.kvdr_pflicht
            _pv_info = (
                "Freiwillig GKV: voller PV-Satz (kein DRV-Trägeranteil)"
                if _freiwillig else
                "KVdR: DRV trägt die Hälfte des PV-Beitrags"
            )
            c8.metric("PV / Monat", f"{_de(pv_mono)} €", help=_pv_info)
        else:
            c8.metric("PV / Monat", "–")
        if _miete_einzel > 0:
            _miete_label = "Mieteinnahmen (je 50 %)" if hat_partner else "Mieteinnahmen"
            c9.metric(
                _miete_label, f"{_de(_miete_einzel)} €/Mon.",
                help="Nettomieteinnahmen (§ 21 EStG). Steuerlich wirksam, keine KV-Pflicht."
                     + (" Gesamt 50/50 aufgeteilt." if hat_partner else ""),
            )
        else:
            c9.metric(
                "Eff. Steuersatz", f"{ergebnis.effektiver_steuersatz:.1%}".replace(".", ","),
                help=f"Besteuerungsanteil: {ergebnis.besteuerungsanteil:.1%}".replace(".", ",") +
                     f" (Renteneintritt {profil.eintritt_jahr})",
            )

        # ── Grundsicherungs-Hinweis ───────────────────────────────────────────
        if _d_netto < GRUNDSICHERUNG_SCHWELLE and _d_netto > 0:
            st.warning(
                f"⚠️ **Grundsicherungsrisiko:** Die projizierte Nettorente von "
                f"**{_de(_d_netto)} €/Mon.** im Jahr {_sel_j_dash} liegt unter der "
                f"Grundsicherungsschwelle von ca. {_de(GRUNDSICHERUNG_SCHWELLE)} €/Mon. "
                f"(§ 41 SGB XII). Ein ergänzender Anspruch auf Grundsicherung im Alter "
                f"könnte bestehen. Bitte prüfen Sie zusätzliche Vorsorgemöglichkeiten "
                f"(Riester, bAV, Rürup) und ggf. einen späteren Renteneintritt."
            )

        st.divider()

        # ── Wasserfall Brutto → Verfügbar ────────────────────────────────────
        st.subheader(f"Brutto → Verfügbar {_sel_j_dash} (monatlich)")
        _ba_pct = f"{ergebnis.besteuerungsanteil:.0%}".replace(".", ",")
        _eff_pct = f"{ergebnis.effektiver_steuersatz:.1%}".replace(".", ",")
        _kv_satz = f"{profil.pkv_beitrag:.0f} € (Fixbetrag PKV)" if profil.krankenversicherung == "PKV" else "GKV-Beitrag (AN-Anteil)"
        _lbl_e      = _eink_label(profil, _sel_j_dash)
        _netto_lbl_e = _netto_label(_lbl_e)
        _wf_x_e = [_lbl_e]
        _wf_m_e = ["absolute"]
        _wf_y_e = [_d_basis]
        _wf_t_e = [f"{_de(_d_basis)} €"]
        _wf_h_e = [
            f"<b>{_lbl_e} (brutto)</b><br>"
            f"{_de(_d_basis)} €/Mon.<br>"
            f"Bruttorente inkl. Zusatzrente vor Steuer und KV.<br>"
            f"Besteuerungsanteil: {_ba_pct} (§ 22 EStG, Renteneintritt {profil.eintritt_jahr})"
        ]
        if _d_bav > 0:
            _wf_x_e.append("+ bAV")
            _wf_m_e.append("relative")
            _wf_y_e.append(_d_bav)
            _wf_t_e.append(f"+{_de(_d_bav)} €")
            _wf_h_e.append(
                f"<b>Betriebliche Altersversorgung (bAV)</b><br>"
                f"+{_de(_d_bav)} €/Mon.<br>"
                f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                f"KV: abzgl. Freibetrag 187,25 €/Mon. (§ 226 Abs. 2 SGB V)."
            )
        if _d_riester > 0:
            _wf_x_e.append("+ Riester")
            _wf_m_e.append("relative")
            _wf_y_e.append(_d_riester)
            _wf_t_e.append(f"+{_de(_d_riester)} €")
            _wf_h_e.append(
                f"<b>Riester-Rente</b><br>"
                f"+{_de(_d_riester)} €/Mon.<br>"
                f"§ 22 Nr. 5 EStG – voll steuerpflichtig.<br>"
                f"Nicht KV-pflichtig (private Rentenleistung)."
            )
        if _d_duv > 0:
            _wf_x_e.append("+ DUV")
            _wf_m_e.append("relative")
            _wf_y_e.append(_d_duv)
            _wf_t_e.append(f"+{_de(_d_duv)} €")
            _wf_h_e.append(
                f"<b>Dienstunfähigkeitsversicherung (DUV)</b><br>"
                f"+{_de(_d_duv)} €/Mon.<br>"
                f"Ertragsanteil § 22 Nr. 1 S. 3a bb EStG.<br>"
                f"Nicht KV-pflichtig (private Versicherungsleistung)."
            )
        if _d_buv > 0:
            _wf_x_e.append("+ BUV")
            _wf_m_e.append("relative")
            _wf_y_e.append(_d_buv)
            _wf_t_e.append(f"+{_de(_d_buv)} €")
            _wf_h_e.append(
                f"<b>Berufsunfähigkeitsversicherung (BUV)</b><br>"
                f"+{_de(_d_buv)} €/Mon.<br>"
                f"Ertragsanteil § 22 Nr. 1 S. 3a bb EStG.<br>"
                f"Nicht KV-pflichtig (private Versicherungsleistung)."
            )
        if _d_miete > 0:
            _wf_x_e.append("+ Mieteinnahmen")
            _wf_m_e.append("relative")
            _wf_y_e.append(_d_miete)
            _wf_t_e.append(f"+{_de(_d_miete)} €")
            _wf_h_e.append(
                f"<b>Mieteinnahmen</b><br>"
                f"+{_de(_d_miete)} €/Mon.<br>"
                f"Netto nach abzugsfähigen Werbungskosten (§ 21 EStG).<br>"
                f"Voll steuerpflichtig, keine KV-Pflicht."
                + (" (50 % Anteil bei Paar)" if hat_partner else "")
            )
        _wf_x_e += ["− Einkommensteuer", "− KV", "− PV"]
        _wf_m_e += ["relative", "relative", "relative"]
        _wf_y_e += [-_d_steuer, -gkv_mono, -pv_mono]
        _wf_t_e += [f"−{_de(_d_steuer)} €", f"−{_de(gkv_mono)} €", f"−{_de(pv_mono)} €"]
        _wf_h_e += [
            f"<b>Einkommensteuer + Solidaritätszuschlag</b><br>"
            f"−{_de(_d_steuer)} €/Mon.<br>"
            f"§ 32a EStG Grundtarif; eff. Steuersatz {_eff_pct}.<br>"
            f"Soli: 5,5 % ab 17.543 € ESt (§ 51a EStG).",
            f"<b>Krankenversicherung</b><br>"
            f"−{_de(gkv_mono)} €/Mon.<br>"
            f"{_kv_satz}.<br>"
            f"Beitragsbemessungsgrenze: 5.175 €/Mon.",
            f"<b>Pflegeversicherung</b><br>"
            f"−{_de(pv_mono)} €/Mon.<br>"
            f"§ 55 SGB XI; Kinderstaffelung § 55 Abs. 3a SGB XI.<br>"
            f"Kinderlosenzuschlag: +0,6 % (trägt Versicherter allein).",
        ]
        # Vorsorgebeiträge: bAV-Beiträge + sonstige (inkl. LV)
        _d_person_vb = "Person 2" if wahl == "Person 2" else "Person 1"
        _vp_produkte_e = st.session_state.get("vp_produkte", [])
        _bav_m_e = _vorsorge_bav_monatlich(_vp_produkte_e, _sel_j_dash, person=_d_person_vb)
        if _bav_m_e > 0:
            _wf_x_e.append("− bAV-Beiträge")
            _wf_m_e.append("relative")
            _wf_y_e.append(-_bav_m_e)
            _wf_t_e.append(f"−{_de(_bav_m_e)} €")
            _wf_h_e.append(
                f"<b>bAV-Beiträge (AN-Anteil)</b><br>"
                f"−{_de(_bav_m_e)} €/Mon.<br>"
                f"Eigenbeitrag zur betrieblichen Altersversorgung.<br>"
                f"Reduziert verfügbares Netto in der Ansparphase."
            )
        _vb_einzeln_e = _vorsorge_non_bav_einzeln(_vp_produkte_e, _sel_j_dash, person=_d_person_vb)
        _vb_m_e = sum(b for _, b in _vb_einzeln_e)
        if _vb_m_e > 0:
            _vb_detail_e = "; ".join(f"{n}: {_de(v)} €" for n, v in _vb_einzeln_e)
            _wf_x_e.append("− Vorsorge\n(ohne bAV)")
            _wf_m_e.append("relative")
            _wf_y_e.append(-_vb_m_e)
            _wf_t_e.append(f"−{_de(_vb_m_e)} €")
            _wf_h_e.append(
                f"<b>Vorsorge-Beiträge (ohne bAV)</b><br>"
                f"−{_de(_vb_m_e)} €/Mon.<br>"
                f"Laufende Beiträge: {_vb_detail_e}.<br>"
                f"Reduzieren das verfügbare Netto während der Beitragsphase."
            )
        # Fixe monatliche Ausgaben
        _lhk_key_d = "p2_lhk" if wahl == "Person 2" else "p1_lhk"
        _d_lhk = float(st.session_state.get(f"rc{_rc}_{_lhk_key_d}", 0.0))
        _d_fix_aktiv = [
            fa for fa in st.session_state.get("hh_fixausgaben", [])
            if fa["startjahr"] <= _sel_j_dash <= fa["endjahr"]
        ]
        _d_fix_m = sum(fa["betrag_monatlich"] for fa in _d_fix_aktiv)
        if _d_fix_m > 0:
            _d_fix_detail_e = "; ".join(
                f"{fa['name']}: {_de(fa['betrag_monatlich'])} €" for fa in _d_fix_aktiv
            )
            _wf_x_e.append("− Fixe Ausgaben")
            _wf_m_e.append("relative")
            _wf_y_e.append(-_d_fix_m)
            _wf_t_e.append(f"−{_de(_d_fix_m)} €")
            _wf_h_e.append(
                f"<b>Fixe monatliche Ausgaben</b><br>"
                f"−{_de(_d_fix_m)} €/Mon.<br>"
                f"Summe aktiver Fixausgaben {_sel_j_dash}.<br>"
                + (f"{_d_fix_detail_e}." if _d_fix_detail_e else "")
            )
        # Hypothek (bei Paar: 50/50 je Person)
        _hyp_faktor_e = 0.5 if hat_partner else 1.0
        _hyp_sched_e = get_hyp_schedule()
        _hyp_row_e = next((r for r in _hyp_sched_e if r["Jahr"] == _sel_j_dash), None)
        _hyp_m_e_val = (_hyp_row_e["Jahresausgabe"] / 12 if _hyp_row_e else 0.0) * _hyp_faktor_e
        if _hyp_m_e_val > 0:
            _hyp_hint_e = " (½ Haushalt)" if hat_partner else ""
            _wf_x_e.append("− Hypothek")
            _wf_m_e.append("relative")
            _wf_y_e.append(-_hyp_m_e_val)
            _wf_t_e.append(f"−{_de(_hyp_m_e_val)} €")
            _wf_h_e.append(
                f"<b>Hypothek-Jahresrate{_hyp_hint_e}</b><br>"
                f"−{_de(_hyp_m_e_val)} €/Mon.<br>"
                f"Annuität {_sel_j_dash} (Zins + Tilgung).<br>"
                f"Konfiguration im Tab Hypothek-Verwaltung."
            )
        _ak_sched_e = get_anschluss_schedule()
        _ak_row_e = next((r for r in _ak_sched_e if r["Jahr"] == _sel_j_dash), None)
        _ak_m_e_val = (_ak_row_e["Jahresausgabe"] / 12 if _ak_row_e else 0.0) * _hyp_faktor_e
        if _ak_m_e_val > 0:
            _wf_x_e.append("− Anschlusskredit")
            _wf_m_e.append("relative")
            _wf_y_e.append(-_ak_m_e_val)
            _wf_t_e.append(f"−{_de(_ak_m_e_val)} €")
            _wf_h_e.append(
                f"<b>Anschlussfinanzierung{_hyp_hint_e}</b><br>"
                f"−{_de(_ak_m_e_val)} €/Mon.<br>"
                f"Annuität auf Restschuld nach Hypothek-Endjahr."
            )
        # Lebenshaltungskosten
        if _d_lhk > 0:
            _wf_x_e.append("− Lebenshalt.")
            _wf_m_e.append("relative")
            _wf_y_e.append(-_d_lhk)
            _wf_t_e.append(f"−{_de(_d_lhk)} €")
            _wf_h_e.append(
                f"<b>Lebenshaltungskosten</b><br>"
                f"−{_de(_d_lhk)} €/Mon.<br>"
                f"Monatliche Fixkosten (Miete, Lebensmittel …).<br>"
                f"Konfiguration im Tab Haushalt."
            )
        _d_verfuegbar = _d_netto - _bav_m_e - _vb_m_e - _d_fix_m - _hyp_m_e_val - _ak_m_e_val - _d_lhk
        _wf_x_e.append("Verfügbar")
        _wf_m_e.append("total")
        _wf_y_e.append(_d_verfuegbar)
        _wf_t_e.append(f"{_de(_d_verfuegbar)} €")
        _wf_h_e.append(
            f"<b>Verfügbares Einkommen</b><br>"
            f"{_de(_d_verfuegbar)} €/Mon.<br>"
            f"Nach Steuer, KV/PV, Vorsorge, Hypothek, Lebenshaltung und Fixausgaben."
        )
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=_wf_m_e,
            x=_wf_x_e,
            y=_wf_y_e,
            text=_wf_t_e,
            textposition="outside",
            customdata=_wf_h_e,
            hovertemplate="%{customdata}<extra></extra>",
            connector=dict(line=dict(color="#888")),
            increasing=dict(marker=dict(color="#4CAF50")),
            decreasing=dict(marker=dict(color="#F44336")),
            totals=dict(marker=dict(color="#2196F3")),
        ))
        _mindest_mono_d = float(st.session_state.get("mindest_haushalt_mono", 2_000))
        fig_wf.add_hline(
            y=_mindest_mono_d, line_dash="dot", line_color="orange", line_width=2,
            annotation_text=f"Mindest {_de(_mindest_mono_d)} €",
            annotation_position="top right",
        )
        fig_wf.update_layout(
            template="plotly_white",
            height=380,
            yaxis=dict(title="€ / Monat", ticksuffix=" €"),
            margin=dict(l=10, r=10, t=10, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_wf, use_container_width=True)

        st.divider()

        # ── Zusammensetzung + Kaufkraft ───────────────────────────────────────
        left, right = st.columns(2)

        with left:
            st.subheader("Rentenbausteine")
            # Basis: gesetzl. Rente/Pension + sonstige (Rürup, PrivRV etc.) – ohne bAV/Riester/Miete
            _pie_basis = max(0.0, _d_basis)
            _pie_bav = max(0.0, _d_bav)
            _pie_riester = max(0.0, _d_riester)
            _pie_miete = max(0.0, _d_miete)
            labels = []
            values = []
            if _pie_basis > 0:
                labels.append(f"Gesetzl. {_lbl_e}")
                values.append(_pie_basis)
            if _pie_bav > 0:
                labels.append("bAV")
                values.append(_pie_bav)
            if _pie_riester > 0:
                labels.append("Riester")
                values.append(_pie_riester)
            if _pie_miete > 0:
                labels.append("Mieteinnahmen")
                values.append(_pie_miete)
            if not labels:
                labels = [f"Gesetzl. {_lbl_e}", "Zusatzrente"]
                values = [ergebnis.brutto_gesetzlich, profil.zusatz_monatlich]
            if any(v > 0 for v in values):
                fig_pie = go.Figure(go.Pie(
                    labels=labels,
                    values=[max(0.0, v) for v in values],
                    hole=0.45,
                    textinfo="percent+label",
                    hovertemplate="%{label}<br>%{value:,.0f} €/Mon.<extra></extra>",
                ))
                fig_pie.update_layout(
                    height=300,
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=False,
                    separators=",.",
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with right:
            st.subheader(f"Kaufkraft heute vs. {_sel_j_dash}")
            _inf_pct = st.number_input(
                "Inflation p.a. (%)", 0.0, 5.0, 2.0, 0.1,
                key=f"rc{_rc}_dash_inflation",
                help="Angenommene jährliche Inflationsrate für die Kaufkraftberechnung.",
            )
            inflation = _inf_pct / 100
            jahre_inflation = _sel_j_dash - profil.eintritt_jahr + profil.jahre_bis_rente
            kaufkraft = _d_netto / (1 + inflation) ** max(0, jahre_inflation)
            verlust = _d_netto - kaufkraft
            st.metric(
                f"Nettorente {_sel_j_dash} in heutiger Kaufkraft ({_inf_pct:.1f} % Inflation)".replace(".", ","),
                f"{_de(kaufkraft)} €",
                delta=f"−{_de(verlust)} € Kaufkraftverlust",
                delta_color="inverse",
            )
            st.caption(
                f"Die Nettorente von **{_de(_d_netto)} €** im Jahr {_sel_j_dash} "
                f"entspricht bei {_inf_pct:.1f} % Inflation".replace(".", ",") +
                f" der heutigen Kaufkraft von nur **{_de(kaufkraft)} €**. "
                f"Die eigene Rentenanpassungs-Annahme von "
                f"{profil.rentenanpassung_pa:.0%}".replace(".", ",") + " p.a. "
                f"{'federt dies ab' if profil.rentenanpassung_pa >= inflation else 'deckt dies nicht vollständig ab'}."
            )

        st.divider()

        # Simulation enthält Miete bereits im zvE; Fallback addiert sie manuell
        _zvE_ampel = _d_zvE if _row_dash else _d_zvE + _miete_einzel * 12
        _steuerampel(_zvE_ampel)

        st.divider()

        with st.expander("🔎 Was-wäre-wenn: Steuerzone", expanded=False):
            st.caption(
                "Verschieben Sie den Slider, um zu sehen, wie sich ein "
                "zusätzliches Einkommen (z.B. Einmalentnahme, Mieterhöhung, "
                "Nebenverdienst) auf Ihren Grenzsteuersatz auswirkt."
            )
            _ww_extra = st.slider(
                "Zusätzliches Jahreseinkommen (€)", 0, 50_000,
                value=0, step=500, key=f"rc{_rc}_dash_ww_extra",
            )
            _zvE_ww = _zvE_ampel + _ww_extra
            _est_vorher = einkommensteuer(_zvE_ampel)
            _soli_vorher = solidaritaetszuschlag(_est_vorher)
            _est_nachher = einkommensteuer(_zvE_ww)
            _soli_nachher = solidaritaetszuschlag(_est_nachher)
            _mehrsteuer = (_est_nachher + _soli_nachher) - (_est_vorher + _soli_vorher)
            if _ww_extra > 0:
                ww1, ww2, ww3, ww4 = st.columns(4)
                ww1.metric("zvE vorher", f"{_de(_zvE_ampel)} €")
                ww2.metric("zvE nachher", f"{_de(_zvE_ww)} €", delta=f"+{_de(_ww_extra)} €")
                ww3.metric("Jahressteuer vorher", f"{_de(_est_vorher + _soli_vorher)} €")
                ww4.metric(
                    "Mehrsteuer (ESt + Soli)", f"{_de(_mehrsteuer)} €",
                    delta=f"{_mehrsteuer / _ww_extra:.1%} Grenzbelastung".replace(".", ","),
                    delta_color="inverse",
                )
                _steuerampel(_zvE_ww, titel="Mit Zusatzeinkommen")

        st.divider()

        with st.expander("🧾 Steuer- & KV-Details", expanded=False):
            steuern.render_section(profil, ergebnis, _miete_einzel)

        # ── HTML-Export ───────────────────────────────────────────────────────
        with st.expander("📄 Zusammenfassung exportieren", expanded=False):
            _html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>Rentenübersicht – {_sel_j_dash}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:2em auto}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:.4em .8em}}th{{background:#f0f0f0}}
h2{{color:#1976d2}}</style></head><body>
<h1>Rentenübersicht {_sel_j_dash}</h1>
<p><em>Erstellt: {__import__('datetime').date.today()}</em></p>
<h2>Kennzahlen</h2>
<table>
<tr><th>Kennzahl</th><th>Wert</th></tr>
<tr><td>Bruttorente</td><td>{_de(_d_brutto)} €/Mon.</td></tr>
<tr><td>Nettorente</td><td>{_de(_d_netto)} €/Mon.</td></tr>
<tr><td>Einkommensteuer</td><td>{_de(_d_steuer)} €/Mon.</td></tr>
<tr><td>KV/PV</td><td>{_de(_d_kv)} €/Mon.</td></tr>
<tr><td>zvE (Jahr)</td><td>{_de(_d_zvE)} €/Jahr</td></tr>
<tr><td>Kapital bei Renteneintritt</td><td>{_de(ergebnis.kapital_bei_renteneintritt)} €</td></tr>
<tr><td>Rentenpunkte gesamt</td><td>{ergebnis.gesamtpunkte:.1f}</td></tr>
</table>
<h2>Profil</h2>
<table>
<tr><th>Feld</th><th>Wert</th></tr>
<tr><td>Geburtsjahr</td><td>{profil.geburtsjahr}</td></tr>
<tr><td>Renteneintrittsalter</td><td>{profil.renteneintritt_alter}</td></tr>
<tr><td>Renteneintrittsjahr</td><td>{profil.eintritt_jahr}</td></tr>
<tr><td>Krankenversicherung</td><td>{profil.krankenversicherung}</td></tr>
</table>
<p style="color:#888;font-size:.9em">⚠️ Simulationswerte – keine Steuer- oder Anlageberatung.</p>
</body></html>"""
            st.download_button(
                "⬇️ HTML herunterladen",
                data=_html.encode("utf-8"),
                file_name=f"rente_{_sel_j_dash}.html",
                mime="text/html",
            )
            st.caption("Die HTML-Datei kann im Browser geöffnet und als PDF gedruckt werden (Strg+P).")

        render_analyse(
            profil, ergebnis,
            label=wahl,
            profil2=profil2 if hat_partner else None,
            ergebnis2=ergebnis2 if hat_partner else None,
            veranlagung=veranlagung,
            mieteinnahmen=_miete_einzel,
            rc=_rc,
        )

        st.caption(
            "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
            "Keine Steuer- oder Anlageberatung."
        )
