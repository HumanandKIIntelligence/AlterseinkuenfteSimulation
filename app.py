"""Alterseinkünfte Simulation – Hauptdatei."""

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Alterseinkünfte Simulation",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

from engine import (
    Profil, berechne_rente, berechne_haushalt, AKTUELLES_JAHR, einkommensteuer,
    BBG_KV_MONATLICH, _pv_satz, DURCHSCHNITTSENTGELT_2024, BBG_RV_MONATLICH,
    _berechne_pension_beamte, _VERSORGUNGSSATZ_PRO_JAHR, _VERSORGUNGSSATZ_MAX,
)
from session_io import save_session, load_session, list_saves
from tabs import dashboard, simulation, vorsorge, haushalt, dokumentation, entnahme_opt, hypothek

# Reset-Counter: erzwingt neue Widget-Keys nach "Neu anfangen"
_RC = st.session_state.get("_rc", 0)


# ── Gemeinsame Helpers ────────────────────────────────────────────────────────

def _gkey(key: str) -> str:
    """Globaler Widget-Key mit Reset-Counter."""
    return f"rc{_RC}_{key}"


def _get(pfx: str, key: str, default):
    """Liest einen Wert aus session_state; einheitlicher Zugriffspunkt für beide Funktionen."""
    return st.session_state.get(f"rc{_RC}_{pfx}_{key}", default)


# ── Profil aus session_state lesen (kein Rendering) ──────────────────────────

def _profil_from_session(pfx: str, geb_default: int) -> Profil:
    """Baut ein Profil aus session_state (keine Widgets)."""
    bereits_rentner  = bool(_get(pfx, "rentner", False))
    ist_pensionaer   = bool(_get(pfx, "pensionaer", False))
    geburtsjahr      = int(_get(pfx, "geb", geb_default))

    # Kapital ist ein geteiltes Haushaltsvermögen – nur für P1 erfasst; P2 bekommt 0
    _hat_kapital = (pfx == "p1")
    if bereits_rentner:
        rentenbeginn_jahr    = int(_get(pfx, "rbj", AKTUELLES_JAHR - 3))
        aktuelles_brutto     = float(_get(pfx, "akt_brutto", 2_000.0))
        renteneintritt_alter = max(60, rentenbeginn_jahr - geburtsjahr)
        aktuelle_punkte      = 0.0
        punkte_pro_jahr      = 0.0
        rentenanpassung      = 0.02
        sparrate             = float(_get(pfx, "sprate", 0.0)) if _hat_kapital else 0.0
        sparkapital          = float(_get(pfx, "spkap", 50_000.0)) if _hat_kapital else 0.0
        rendite              = float(_get(pfx, "rendite", 3.0)) / 100
    else:
        rentenbeginn_jahr    = AKTUELLES_JAHR
        aktuelles_brutto     = float(_get(pfx, "akt_brutto", 3_000.0)) if ist_pensionaer else float(_get(pfx, "gehalt", 0.0))
        renteneintritt_alter = int(_get(pfx, "re_alter", 67))
        sparkapital          = float(_get(pfx, "spkap", 50_000.0)) if _hat_kapital else 0.0
        sparrate             = float(_get(pfx, "sprate", 500.0)) if _hat_kapital else 0.0
        rendite              = float(_get(pfx, "rendite", 5.0)) / 100
        if ist_pensionaer:
            aktuelle_punkte  = 0.0
            punkte_pro_jahr  = 0.0
            rentenanpassung  = float(_get(pfx, "ren_anp", 0.0)) / 100
        else:
            aktuelle_punkte  = float(_get(pfx, "punkte", 25.0 if pfx == "p1" else 15.0))
            _gehalt_j        = float(_get(pfx, "gehalt", 0.0)) * 12
            _aufstock_j      = float(_get(pfx, "zusatzentgelt", 0.0))
            punkte_pro_jahr  = min(_gehalt_j + _aufstock_j, BBG_RV_MONATLICH * 12) / DURCHSCHNITTSENTGELT_2024
            rentenanpassung  = float(_get(pfx, "ren_anp", 2.0)) / 100

    kv_raw      = str(_get(pfx, "kv_radio", "Gesetzlich (GKV)"))
    kv_typ      = "PKV" if "PKV" in kv_raw else "GKV"
    pkv_beitrag = float(_get(pfx, "pkv", 250.0 if ist_pensionaer else 600.0))
    gkv_zusatz  = float(_get(pfx, "gkv_zus", 1.7)) / 100
    kinder        = bool(_get(pfx, "kinder", True))
    kinder_anzahl = int(_get(pfx, "kinder_anz", 1)) if kinder else 0
    kvdr_pflicht  = bool(_get(pfx, "kvdr", True))

    duv_monatlich = float(_get(pfx, "duv", 0.0))
    duv_endjahr   = int(_get(pfx, "duv_end", AKTUELLES_JAHR + 10))
    buv_monatlich = float(_get(pfx, "buv", 0.0))
    buv_endjahr   = int(_get(pfx, "buv_end", AKTUELLES_JAHR + 10))

    kirchensteuer      = bool(_get(pfx, "kist", False))
    kirchensteuer_satz = float(_get(pfx, "kist_satz", 9.0)) / 100

    grundfreibetrag_wachstum_pa = float(_get(pfx, "gfb_wachstum", 0.0)) / 100
    kap_pool_rendite_pa = -1.0  # Pool immer mit Profil-Rendite (keine separate Pool-Rendite)
    lebenshaltungskosten_monatlich = float(_get(pfx, "lhk", 0.0))
    zusatzentgelt_jaehrlich = (float(_get(pfx, "zusatzentgelt", 0.0))
                               if not ist_pensionaer and not bereits_rentner else 0.0)

    # Gehalts-/Dienstbezüge-Perioden: stabiler Key (nicht rc-gepräfixt) damit Werte Reruns überstehen
    gehalt_perioden = st.session_state.get(f"{pfx}_gehalt_perioden", [])
    if not isinstance(gehalt_perioden, list):
        gehalt_perioden = []

    # Beamtenpension-Felder (§ 14 BeamtVG)
    ruhegehalt_bezuege_mono = float(_get(pfx, "rhg_bezuege", 0.0)) if ist_pensionaer and not bereits_rentner else 0.0
    bisherige_dienstjahre   = int(_get(pfx, "dienstjahre", 0))     if ist_pensionaer and not bereits_rentner else 0

    return Profil(
        geburtsjahr=geburtsjahr,
        renteneintritt_alter=renteneintritt_alter,
        aktuelle_punkte=aktuelle_punkte,
        punkte_pro_jahr=punkte_pro_jahr,
        zusatz_monatlich=0.0,   # O2: Zusatzrente nur noch via Vorsorge-Bausteine
        zusatz_typ="bAV",
        sparkapital=sparkapital,
        sparrate=sparrate,
        rendite_pa=rendite,
        rentenanpassung_pa=rentenanpassung,
        krankenversicherung=kv_typ,
        pkv_beitrag=pkv_beitrag,
        gkv_zusatzbeitrag=gkv_zusatz,
        kinder=kinder,
        kinder_anzahl=kinder_anzahl,
        ist_pensionaer=ist_pensionaer,
        bereits_rentner=bereits_rentner,
        rentenbeginn_jahr=rentenbeginn_jahr,
        aktuelles_brutto_monatlich=aktuelles_brutto,
        duv_monatlich=duv_monatlich,
        duv_endjahr=duv_endjahr,
        buv_monatlich=buv_monatlich,
        buv_endjahr=buv_endjahr,
        kvdr_pflicht=kvdr_pflicht,
        kirchensteuer=kirchensteuer,
        kirchensteuer_satz=kirchensteuer_satz,
        grundfreibetrag_wachstum_pa=grundfreibetrag_wachstum_pa,
        kap_pool_rendite_pa=kap_pool_rendite_pa,
        lebenshaltungskosten_monatlich=lebenshaltungskosten_monatlich,
        zusatzentgelt_jaehrlich=zusatzentgelt_jaehrlich,
        gehalt_perioden=gehalt_perioden,
        ruhegehalt_bezuege_mono=ruhegehalt_bezuege_mono,
        bisherige_dienstjahre=bisherige_dienstjahre,
    )


# ── Profilwerte in session_state schreiben ────────────────────────────────────

def _write_profil_to_state(p: Profil, pfx: str) -> None:
    """Schreibt ein Profil-Objekt in session_state (für Laden)."""
    if p.krankenversicherung == "PKV" and p.ist_pensionaer:
        kv_label = "Beihilfe + PKV (70 % / 30 %)"
    elif p.krankenversicherung == "PKV":
        kv_label = "Privat (PKV)"
    elif p.ist_pensionaer:
        kv_label = "GKV (freiwillig versichert)"
    else:
        kv_label = "Gesetzlich (GKV)"

    updates = {
        f"rc{_RC}_{pfx}_geb":        p.geburtsjahr,
        f"rc{_RC}_{pfx}_re_alter":   p.renteneintritt_alter,
        f"rc{_RC}_{pfx}_punkte":     p.aktuelle_punkte,
        f"rc{_RC}_{pfx}_ren_anp":    p.rentenanpassung_pa * 100,
        f"rc{_RC}_{pfx}_spkap":      p.sparkapital,
        f"rc{_RC}_{pfx}_sprate":     p.sparrate,
        f"rc{_RC}_{pfx}_rendite":    p.rendite_pa * 100,
        f"rc{_RC}_{pfx}_zusatz":     p.zusatz_monatlich,
        f"rc{_RC}_{pfx}_pkv":        p.pkv_beitrag,
        f"rc{_RC}_{pfx}_gkv_zus":    p.gkv_zusatzbeitrag * 100,
        f"rc{_RC}_{pfx}_kinder":     p.kinder,
        f"rc{_RC}_{pfx}_kinder_anz": p.kinder_anzahl,
        f"rc{_RC}_{pfx}_kv_radio":   kv_label,
        f"rc{_RC}_{pfx}_rentner":    p.bereits_rentner,
        f"rc{_RC}_{pfx}_pensionaer": p.ist_pensionaer,
        f"rc{_RC}_{pfx}_rbj":        p.rentenbeginn_jahr,
        f"rc{_RC}_{pfx}_akt_brutto": p.aktuelles_brutto_monatlich,
        f"rc{_RC}_{pfx}_gehalt":     (0.0 if p.ist_pensionaer else p.aktuelles_brutto_monatlich),
        f"rc{_RC}_{pfx}_duv":        p.duv_monatlich,
        f"rc{_RC}_{pfx}_duv_end":    p.duv_endjahr,
        f"rc{_RC}_{pfx}_buv":        p.buv_monatlich,
        f"rc{_RC}_{pfx}_buv_end":    p.buv_endjahr,
        f"rc{_RC}_{pfx}_kvdr":       p.kvdr_pflicht,
        f"rc{_RC}_{pfx}_kist":            p.kirchensteuer,
        f"rc{_RC}_{pfx}_kist_satz":       p.kirchensteuer_satz * 100,
        f"rc{_RC}_{pfx}_gfb_wachstum":    p.grundfreibetrag_wachstum_pa * 100,
        f"rc{_RC}_{pfx}_lhk":             p.lebenshaltungskosten_monatlich,
        f"rc{_RC}_{pfx}_zusatzentgelt":   p.zusatzentgelt_jaehrlich,
        f"rc{_RC}_{pfx}_rhg_bezuege":     p.ruhegehalt_bezuege_mono,
        f"rc{_RC}_{pfx}_dienstjahre":     p.bisherige_dienstjahre,
    }
    st.session_state.update(updates)
    # Gehaltsperioden: stabiler Key (nicht rc-gepräfixt)
    st.session_state[f"{pfx}_gehalt_perioden"] = p.gehalt_perioden


# ── Profil-Widgets rendern (im Profil-Tab) ────────────────────────────────────

def _render_profil_inputs(label: str, pfx: str, geb_default: int,
                          show_kapital: bool = True) -> None:
    """Rendert Eingabe-Widgets für eine Person in den aktuellen Container."""
    st.subheader(label)

    bereits_rentner = st.checkbox(
        "Bereits in Rente / Pension",
        value=_get(pfx, "rentner", False),
        key=f"rc{_RC}_{pfx}_rentner",
    )
    ist_pensionaer = st.checkbox(
        "Beamter / Pensionär",
        value=_get(pfx, "pensionaer", False),
        key=f"rc{_RC}_{pfx}_pensionaer",
        help="Beamtenpension: Versorgungsfreibetrag § 19 Abs. 2 EStG; KV § 229 Abs. 1 Nr. 1 SGB V.",
    )

    st.number_input(
        "Geburtsjahr", 1945, 1995,
        value=int(_get(pfx, "geb", geb_default)),
        step=1, key=f"rc{_RC}_{pfx}_geb",
    )

    if bereits_rentner:
        ca, cb = st.columns(2)
        with ca:
            st.number_input(
                "Rentenbeginn (Jahr)", 1980, AKTUELLES_JAHR,
                value=int(_get(pfx, "rbj", AKTUELLES_JAHR - 3)),
                step=1, key=f"rc{_RC}_{pfx}_rbj",
                help="Entscheidend für Besteuerungsanteil (GRV) bzw. Versorgungsfreibetrag (Pension).",
            )
        with cb:
            st.number_input(
                "Bruttorente / -pension (€/Mon.)", 0.0, 20_000.0,
                value=float(_get(pfx, "akt_brutto", 2_000.0)),
                step=50.0, key=f"rc{_RC}_{pfx}_akt_brutto",
            )
    else:
        _re_alter_val = int(_get(pfx, "re_alter", 67))
        st.slider(
            "Pensionierungsalter" if ist_pensionaer else "Renteneintrittsalter",
            60, 70,
            value=_re_alter_val,
            key=f"rc{_RC}_{pfx}_re_alter",
            help="Regelaltersgrenze 2025: 67 Jahre." if not ist_pensionaer
                 else "Pensionierungsalter Bund/Länder: i.d.R. 65–67 J.",
        )
        if not ist_pensionaer and _re_alter_val < 63:
            st.warning(
                f"⚠️ Renteneintrittsalter {_re_alter_val}: Das frühestmögliche GRV-Eintrittsalter "
                "beträgt 63 Jahre (mit 35 Versicherungsjahren, § 36 SGB VI). "
                "Abschlag: 0,3 % je Monat vor Regelaltersgrenze 67."
            )
        if ist_pensionaer:
            st.markdown("**Beamtenversorgung (§ 14 BeamtVG)**")
            ca_p0, cb_p0 = st.columns(2)
            with ca_p0:
                st.number_input(
                    "Ruhegehaltfähige Dienstbezüge (€/Mon.)", 0.0, 20_000.0,
                    value=float(_get(pfx, "rhg_bezuege", 0.0)),
                    step=50.0, key=f"rc{_RC}_{pfx}_rhg_bezuege",
                    help="Erwartetes Bruttogehalt (Grundgehalt + Familienzuschlag) zum Pensionierungszeitpunkt. "
                         "Basis für Ruhegehalt nach § 14 Abs. 1 BeamtVG.",
                )
            with cb_p0:
                st.number_input(
                    "Bisherige Dienstjahre", 0, 50,
                    value=int(_get(pfx, "dienstjahre", 0)),
                    step=1, key=f"rc{_RC}_{pfx}_dienstjahre",
                    help="Bisher abgeleistete ruhegehaltfähige Dienstjahre. "
                         "Gesamtdienstjahre = Bisherige + Jahre bis Pensionierung.",
                )
            # Berechnete Pension anzeigen
            _rhg_bez  = float(_get(pfx, "rhg_bezuege", 0.0))
            _dj_bish  = int(_get(pfx, "dienstjahre", 0))
            _re_alt_p = int(_get(pfx, "re_alter", 67))
            _geb_p    = int(_get(pfx, "geb", AKTUELLES_JAHR - 40))
            _dj_rest  = max(0, _re_alt_p - (AKTUELLES_JAHR - _geb_p))
            _dj_ges   = _dj_bish + _dj_rest
            _vs       = min(_dj_ges * _VERSORGUNGSSATZ_PRO_JAHR, _VERSORGUNGSSATZ_MAX)
            _pens_calc = _rhg_bez * _vs if _rhg_bez > 0 else 0.0
            _cp1, _cp2, _cp3 = st.columns(3)
            with _cp1:
                st.metric("Dienstjahre gesamt", f"{_dj_ges} J.",
                          help=f"Bisherige {_dj_bish} J. + {_dj_rest} J. bis Pensionierung")
            with _cp2:
                st.metric("Versorgungssatz", f"{_vs*100:.2f} %",
                          help=f"§ 14 BeamtVG: min({_dj_ges} × 1,79375 %, 71,75 %)")
            with _cp3:
                st.metric("Erwartete Bruttopension", f"{_pens_calc:,.0f} €/Mon." if _pens_calc > 0 else "–",
                          help="Ruhegehaltfähige Dienstbezüge × Versorgungssatz. "
                               "0 = bitte Dienstbezüge eingeben.")
            if _pens_calc == 0:
                st.info("Bitte Ruhegehaltfähige Dienstbezüge eingeben, um die Pension zu berechnen.")
            # Fallback-Feld für direkte Eingabe (falls keine Bezüge angegeben)
            with st.expander("Alternativ: Bruttopension direkt eingeben (Fallback)", expanded=(_rhg_bez == 0)):
                st.number_input(
                    "Erwartete Bruttopension (€/Mon.)", 0.0, 20_000.0,
                    value=float(_get(pfx, "akt_brutto", 0.0)),
                    step=50.0, key=f"rc{_RC}_{pfx}_akt_brutto",
                    help="Wird nur genutzt, wenn keine Ruhegehaltfähigen Dienstbezüge angegeben. "
                         "Besteuerung nach § 19 Abs. 2 EStG (Versorgungsfreibetrag).",
                )
            ca_p, cb_p = st.columns(2)
            with ca_p:
                st.slider(
                    "Pensionsanpassung p.a. (%)", 0.0, 3.0,
                    value=float(_get(pfx, "ren_anp", 0.0)),
                    step=0.1, key=f"rc{_RC}_{pfx}_ren_anp",
                    help="Jährliche Anpassung der Bruttopension (Besoldungserhöhung). 0 = konstant.",
                )
        else:
            st.markdown("**Gesetzliche Rente (DRV)**")
            ca, cb = st.columns(2)
            with ca:
                st.number_input(
                    "Aktuelle Rentenpunkte", 0.0, 80.0,
                    value=float(_get(pfx, "punkte", 25.0 if pfx == "p1" else 15.0)),
                    step=0.5, key=f"rc{_RC}_{pfx}_punkte",
                    help="Entgeltpunkte lt. letzter Renteninformation der DRV.",
                )
            with cb:
                _gehalt_hint  = float(_get(pfx, "gehalt", 0.0))
                _aufstock_hint = float(_get(pfx, "zusatzentgelt", 0.0))
                _ep_basis     = _gehalt_hint * 12 + _aufstock_hint
                _ep_auto      = min(_ep_basis, BBG_RV_MONATLICH * 12) / DURCHSCHNITTSENTGELT_2024
                _ep_help_parts = []
                if _gehalt_hint > 0:
                    _ep_help_parts.append(f"Gehalt {_gehalt_hint:,.0f} €/Mon. × 12 = {_gehalt_hint*12:,.0f} €")
                if _aufstock_hint > 0:
                    _ep_help_parts.append(f"Aufstockungsbetrag {_aufstock_hint:,.0f} €/Jahr")
                if _ep_help_parts:
                    _ep_help = (
                        " + ".join(_ep_help_parts)
                        + f" → {_ep_basis:,.0f} € (Basis) / {DURCHSCHNITTSENTGELT_2024:,.0f} € (Ø-Entgelt); "
                        f"Kappung bei BBG-RV {BBG_RV_MONATLICH * 12:,.0f} €/Jahr."
                    )
                else:
                    _ep_help = "Kein Bruttogehalt angegeben → 0 EP/Jahr. Bitte Bruttogehalt unten eingeben."
                st.metric(
                    "Rentenpunkte pro Jahr",
                    f"{_ep_auto:.2f} EP".replace(".", ","),
                    help=_ep_help,
                )
            st.slider(
                "Rentenanpassung p.a. (%)", 0.0, 5.0,
                value=float(_get(pfx, "ren_anp", 2.0)),
                step=0.1, key=f"rc{_RC}_{pfx}_ren_anp",
            )

        st.markdown("**Aktuelles Bruttogehalt**")
        st.number_input(
            "Bruttogehalt heute (€/Mon.)", 0.0, 30_000.0,
            value=float(_get(pfx, "gehalt", 0.0)),
            step=100.0, key=f"rc{_RC}_{pfx}_gehalt",
            help="Aktuelles Bruttogehalt für die Steuer- und KV-Simulation in den Arbeitsjahren. "
                 "0 = Simulation startet erst ab Renteneintritt (kein Arbeitsphasen-Verlauf).",
        )

        # ── Gehalts-/Dienstbezüge-Perioden ───────────────────────────────────
        _gp_label = "📅 Dienstbezüge-Perioden (Besoldungsänderungen)" if ist_pensionaer \
                    else "📅 Gehaltsänderungen (Perioden)"
        _gp_help  = ("Zeiträume, in denen sich die Dienstbezüge ändern (z.B. Beförderung, "
                     "Besoldungsgruppe). Beeinflussen das Simulations-Einkommen in den Arbeitsjahren."
                     ) if ist_pensionaer else (
                     "Zeiträume, in denen sich das Bruttogehalt vorübergehend ändert "
                     "(z.B. Teilzeit, Elternzeit, Sabbatjahr). Beeinflussen Rentenentgeltpunkte "
                     "und Simulations-Einkommen.")
        with st.expander(_gp_label, expanded=False):
            st.caption(_gp_help)
            _gp_key   = f"{pfx}_gehalt_perioden"
            _gp_raw   = st.session_state.get(_gp_key, [])
            if not isinstance(_gp_raw, list):
                _gp_raw = []
            _re_alt_gp = int(_get(pfx, "re_alter", 67))
            _geb_gp    = int(_get(pfx, "geb", AKTUELLES_JAHR - 40))
            _ein_j_gp  = _geb_gp + _re_alt_gp
            _gp_df = pd.DataFrame(
                _gp_raw if _gp_raw else [],
                columns=["start_jahr", "end_jahr", "gehalt_monatlich"],
            )
            _gp_edited = st.data_editor(
                _gp_df,
                num_rows="dynamic",
                use_container_width=True,
                key=f"rc{_RC}_{pfx}_gp_editor",
                column_config={
                    "start_jahr": st.column_config.NumberColumn(
                        "Start-Jahr", min_value=AKTUELLES_JAHR - 30,
                        max_value=_ein_j_gp, step=1, format="%d",
                        help="Jahr, ab dem das geänderte Gehalt gilt.",
                    ),
                    "end_jahr": st.column_config.NumberColumn(
                        "End-Jahr", min_value=AKTUELLES_JAHR,
                        max_value=_ein_j_gp, step=1, format="%d",
                        help="Letztes Jahr mit diesem Gehalt (inkl.).",
                    ),
                    "gehalt_monatlich": st.column_config.NumberColumn(
                        "Bruttogehalt (€/Mon.)" if not ist_pensionaer else "Dienstbezüge (€/Mon.)",
                        min_value=0.0, max_value=30_000.0, step=100.0, format="%.0f",
                    ),
                },
            )
            # Gültige Zeilen speichern (beide Jahresfelder und Gehalt gesetzt)
            _gp_new = []
            for _, _gpr in _gp_edited.iterrows():
                try:
                    _sj = int(_gpr["start_jahr"]) if pd.notna(_gpr["start_jahr"]) else 0
                    _ej = int(_gpr["end_jahr"])   if pd.notna(_gpr["end_jahr"])   else 0
                    _gm = float(_gpr["gehalt_monatlich"]) if pd.notna(_gpr["gehalt_monatlich"]) else -1.0
                except (TypeError, ValueError):
                    continue
                if _sj > 0 and _ej >= _sj and _gm >= 0:
                    _gp_new.append({"start_jahr": _sj, "end_jahr": _ej, "gehalt_monatlich": _gm})
            if _gp_new != _gp_raw:
                st.session_state[_gp_key] = _gp_new
                st.rerun()

    if show_kapital:
        st.markdown("**Kapital**")
        st.caption("💡 Zusatzrenten (bAV, Riester, Rürup …) bitte im Tab **Vorsorge-Bausteine** erfassen.")
        _kap_ca, _kap_cb, _kap_cc = st.columns(3)
        with _kap_ca:
            st.number_input(
                "Kapital heute (€)", 0.0, 5_000_000.0,
                value=float(_get(pfx, "spkap", 50_000.0)),
                step=1_000.0, key=f"rc{_RC}_{pfx}_spkap",
            )
        with _kap_cb:
            st.number_input(
                "Monatliche Sparrate (€)", 0.0, 10_000.0,
                value=float(_get(pfx, "sprate", 0.0 if bereits_rentner else 500.0)),
                step=50.0, key=f"rc{_RC}_{pfx}_sprate",
            )
        with _kap_cc:
            st.slider(
                "Rendite p.a. (%)", 0.0, 12.0,
                value=float(_get(pfx, "rendite", 3.0 if bereits_rentner else 5.0)),
                step=0.5, key=f"rc{_RC}_{pfx}_rendite",
            )

    st.markdown("**Krankenversicherung**")
    if ist_pensionaer:
        kv_opts = ["Beihilfe + PKV (70 % / 30 %)", "GKV (freiwillig versichert)"]
        kv_def  = 0 if "PKV" in str(_get(pfx, "kv_radio", "Beihilfe + PKV (70 % / 30 %)")) else 1
        kv_raw  = st.radio("Versicherungsart", kv_opts,
                           index=kv_def, horizontal=True, key=f"rc{_RC}_{pfx}_kv_radio")
        if "PKV" in kv_raw:
            st.number_input(
                "PKV-Eigenanteil nach Beihilfe (€/Mon.)", 50.0, 2_000.0,
                value=float(_get(pfx, "pkv", 250.0)),
                step=10.0, key=f"rc{_RC}_{pfx}_pkv",
                help="Beihilfe übernimmt 70 % der beihilfefähigen Krankheitskosten.",
            )
        else:
            ca, cb = st.columns(2)
            with ca:
                st.slider("GKV Zusatzbeitrag (%)", 0.5, 4.0,
                          value=float(_get(pfx, "gkv_zus", 1.7)),
                          step=0.1, key=f"rc{_RC}_{pfx}_gkv_zus")
            with cb:
                _kinder_val = st.checkbox("Hat Kinder",
                                          value=bool(_get(pfx, "kinder", True)),
                                          key=f"rc{_RC}_{pfx}_kinder")
            if _kinder_val:
                st.number_input(
                    "Anzahl Kinder (PV-Staffelung § 55 Abs. 3a SGB XI)", 1, 5,
                    value=int(_get(pfx, "kinder_anz", 1)),
                    step=1, key=f"rc{_RC}_{pfx}_kinder_anz",
                    help="Ab 2. Kind: je −0,25 % PV-Eigenbeitrag (max. 5 Kinder → −1,0 %).",
                )
            st.checkbox(
                "KVdR-Pflichtmitglied (§ 5 Abs. 1 Nr. 11 SGB V)",
                value=bool(_get(pfx, "kvdr", True)),
                key=f"rc{_RC}_{pfx}_kvdr",
                help=(
                    "✅ Angehakt = KVdR-Pflichtmitglied (§ 5 Abs. 1 Nr. 11 SGB V): "
                    "Nur §229-Einkünfte (gesetzliche Rente + bAV) beitragspflichtig. "
                    "Kapitalerträge, Mieteinnahmen und private Renten bleiben beitragsfrei.\n\n"
                    "☐ Nicht angehakt = Freiwillig versichert (§ 240 SGB V): "
                    "ALLE Einnahmen beitragspflichtig (inkl. Kapitalerträge, Mieten, private Renten).\n\n"
                    "📋 9/10-Regel (Voraussetzung für KVdR): "
                    "In der zweiten Hälfte des Erwerbslebens müssen mindestens 9/10 der Zeit "
                    "eine GKV-Mitgliedschaft (Pflicht oder freiwillig) bestanden haben. "
                    "Wer längere Zeit in der PKV oder als Beamter tätig war, erfüllt diese "
                    "Bedingung meist nicht → dann freiwillig versichert. "
                    "Im Zweifel bei der eigenen Krankenkasse oder der DRV nachfragen."
                ),
            )
    else:
        kv_idx = 0 if "PKV" not in str(_get(pfx, "kv_radio", "Gesetzlich (GKV)")) else 1
        kv_raw = st.radio("Versicherungsart", ["Gesetzlich (GKV)", "Privat (PKV)"],
                          index=kv_idx, horizontal=True, key=f"rc{_RC}_{pfx}_kv_radio")
        if "PKV" in kv_raw:
            st.number_input(
                "PKV-Beitrag (€/Mon.)", 200.0, 3_000.0,
                value=float(_get(pfx, "pkv", 600.0)),
                step=10.0, key=f"rc{_RC}_{pfx}_pkv",
            )
        else:
            ca, cb = st.columns(2)
            with ca:
                st.slider("GKV Zusatzbeitrag (%)", 0.5, 4.0,
                          value=float(_get(pfx, "gkv_zus", 1.7)),
                          step=0.1, key=f"rc{_RC}_{pfx}_gkv_zus")
            with cb:
                _kinder_val2 = st.checkbox("Hat Kinder",
                                           value=bool(_get(pfx, "kinder", True)),
                                           key=f"rc{_RC}_{pfx}_kinder")
            if _kinder_val2:
                st.number_input(
                    "Anzahl Kinder (PV-Staffelung § 55 Abs. 3a SGB XI)", 1, 5,
                    value=int(_get(pfx, "kinder_anz", 1)),
                    step=1, key=f"rc{_RC}_{pfx}_kinder_anz",
                    help="Ab 2. Kind: je −0,25 % PV-Eigenbeitrag (max. 5 Kinder → −1,0 %).",
                )
            st.checkbox(
                "KVdR-Pflichtmitglied (§ 5 Abs. 1 Nr. 11 SGB V)",
                value=bool(_get(pfx, "kvdr", True)),
                key=f"rc{_RC}_{pfx}_kvdr",
                help=(
                    "✅ Angehakt = KVdR-Pflichtmitglied (§ 5 Abs. 1 Nr. 11 SGB V): "
                    "Nur §229-Einkünfte (gesetzliche Rente + bAV) beitragspflichtig. "
                    "Kapitalerträge, Mieteinnahmen und private Renten bleiben beitragsfrei.\n\n"
                    "☐ Nicht angehakt = Freiwillig versichert (§ 240 SGB V): "
                    "ALLE Einnahmen beitragspflichtig (inkl. Kapitalerträge, Mieten, private Renten).\n\n"
                    "📋 9/10-Regel (Voraussetzung für KVdR): "
                    "In der zweiten Hälfte des Erwerbslebens müssen mindestens 9/10 der Zeit "
                    "eine GKV-Mitgliedschaft (Pflicht oder freiwillig) bestanden haben. "
                    "Wer längere Zeit in der PKV oder als Beamter tätig war, erfüllt diese "
                    "Bedingung meist nicht → dann freiwillig versichert. "
                    "Im Zweifel bei der eigenen Krankenkasse oder der DRV nachfragen."
                ),
            )

    st.markdown("**Kirchensteuer**")
    kist_col1, kist_col2 = st.columns([1, 2])
    with kist_col1:
        kirchensteuer_cb = st.checkbox(
            "Kirchensteuerpflichtig",
            value=bool(_get(pfx, "kist", False)),
            key=f"rc{_RC}_{pfx}_kist",
            help="Kirchensteuer (§ 51a EStG): 8 % der ESt in Bayern und Baden-Württemberg, "
                 "9 % in allen anderen Bundesländern.",
        )
    with kist_col2:
        if kirchensteuer_cb:
            _kist_opts = ["9 % (alle anderen Bundesländer)", "8 % (Bayern, Baden-Württemberg)"]
            _kist_def  = 0 if float(_get(pfx, "kist_satz", 9.0)) >= 9.0 else 1
            _kist_sel  = st.radio(
                "Kirchensteuersatz", _kist_opts,
                index=_kist_def, horizontal=True,
                key=f"rc{_RC}_{pfx}_kist_radio",
            )
            _kist_val = 8.0 if "8 %" in _kist_sel else 9.0
            st.session_state[f"rc{_RC}_{pfx}_kist_satz"] = _kist_val

    with st.expander("⚙️ Erweiterte Einstellungen"):
        st.slider(
            "GFB-Wachstum p.a. (%)", 0.0, 3.0,
            value=float(_get(pfx, "gfb_wachstum", 0.0)),
            step=0.1, key=f"rc{_RC}_{pfx}_gfb_wachstum",
            help=(
                "Jährliche Steigerung des Grundfreibetrags (§ 32a EStG) im Planungshorizont. "
                "Historisch ca. 1–2 % p.a. Wirkt nur in der Jahressimulation "
                "(Entnahme-Optimierung), nicht im Basisdashboard."
            ),
        )
        if not ist_pensionaer and not bereits_rentner:
            st.number_input(
                "Zusatzentgelt / Aufstockungsbetrag (§ 32b EStG, €/Jahr)", 0.0, 200_000.0,
                value=float(_get(pfx, "zusatzentgelt", 0.0)),
                step=500.0, key=f"rc{_RC}_{pfx}_zusatzentgelt",
                help=(
                    "Steuerfreies Zusatzentgelt mit Progressionsvorbehalt (§ 32b EStG), "
                    "z.B. Altersteilzeit-Aufstockungsbetrag oder Transferkurzarbeitergeld. "
                    "Steuerfrei und kein KV/PV-Beitrag auf diesen Betrag, erhöht aber den "
                    "Steuersatz auf das übrige Bruttoeinkommen. "
                    "Fließt zusätzlich in die Rentenpunkt-Berechnung ein "
                    "(Gehalt × 12 + Aufstockung, gedeckelt bei BBG-RV). "
                    "Gilt nur in der Simulation bis zum Renteneintritt."
                ),
            )

    if ist_pensionaer:
        with st.expander("🛡 Dienstunfähigkeitsversicherung (DUV)"):
            ca, cb = st.columns(2)
            with ca:
                st.number_input(
                    "DUV-Monatsrente (€/Mon.)", 0.0, 5_000.0,
                    value=float(_get(pfx, "duv", 0.0)),
                    step=50.0, key=f"rc{_RC}_{pfx}_duv",
                    help="Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; nicht KVdR-pflichtig.",
                )
            with cb:
                st.number_input(
                    "DUV endet (Jahr)", AKTUELLES_JAHR, AKTUELLES_JAHR + 45,
                    value=int(_get(pfx, "duv_end", AKTUELLES_JAHR + 10)),
                    step=1, key=f"rc{_RC}_{pfx}_duv_end",
                    help="Laufzeitende der DUV, z.B. das reguläre Pensionierungsalter.",
                )
    else:
        with st.expander("🛡 Berufsunfähigkeitsversicherung (BUV)"):
            ca, cb = st.columns(2)
            with ca:
                st.number_input(
                    "BUV-Monatsrente (€/Mon.)", 0.0, 5_000.0,
                    value=float(_get(pfx, "buv", 0.0)),
                    step=50.0, key=f"rc{_RC}_{pfx}_buv",
                    help="Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; nicht KVdR-pflichtig. "
                         "Gesetzliche Erwerbsminderungsrente stattdessen als 'Bereits in Rente' erfassen.",
                )
            with cb:
                st.number_input(
                    "BUV endet (Jahr)", AKTUELLES_JAHR, AKTUELLES_JAHR + 45,
                    value=int(_get(pfx, "buv_end", AKTUELLES_JAHR + 10)),
                    step=1, key=f"rc{_RC}_{pfx}_buv_end",
                    help="Laufzeitende der BUV, z.B. das reguläre Renteneintrittsalter.",
                )


# ── Profil-Tab rendern ────────────────────────────────────────────────────────

def render_profil_tab(T: dict) -> None:
    with T["Profil"]:
        st.header("⚙️ Profil")
        st.caption(
            "Persönliche Angaben für alle Berechnungen. "
            "Alle anderen Tabs aktualisieren sich automatisch nach jeder Änderung."
        )

        # Partner-Toggle und Veranlagung
        pc1, pc2 = st.columns([1, 2])
        with pc1:
            st.checkbox(
                "👥 Ehepartner / Partnerin",
                value=st.session_state.get(_gkey("hat_partner"), False),
                key=_gkey("hat_partner"),
            )
        hat_partner = bool(st.session_state.get(_gkey("hat_partner"), False))
        if hat_partner:
            with pc2:
                ver_saved = str(st.session_state.get(_gkey("veranlagung_radio"),
                                                      "Zusammenveranlagung (Splitting)"))
                ver_idx = 0 if "Splitting" in ver_saved else 1
                st.radio(
                    "Steuerliche Veranlagung",
                    ["Zusammenveranlagung (Splitting)", "Getrennte Veranlagung"],
                    index=ver_idx, horizontal=True, key=_gkey("veranlagung_radio"),
                    help="Splitting: Einkommen wird halbiert, Steuer berechnet und verdoppelt → "
                         "Vorteil bei ungleichen Einkommen.",
                )

        st.divider()

        # Personen-Eingaben
        if hat_partner:
            col1, col2 = st.columns(2)
            with col1:
                _render_profil_inputs("👤 Person 1", "p1", 1970)
            with col2:
                _render_profil_inputs("👤 Person 2", "p2", 1972, show_kapital=False)
        else:
            _render_profil_inputs("👤 Person 1", "p1", 1970)

        st.divider()

        # Mieteinnahmen
        st.subheader("🏠 Mieteinnahmen")
        mc1, mc2 = st.columns(2)
        with mc1:
            st.number_input(
                "Netto-Mieteinnahmen (€/Mon.)", 0.0, 50_000.0,
                value=float(st.session_state.get(_gkey("hh_miet"), 0.0)),
                step=50.0, key=_gkey("hh_miet"),
                help=(
                    "Nettomieteinnahmen nach abzugsfähigen Werbungskosten (§ 21 EStG). "
                    "Voll steuerpflichtig, keine KV-Pflicht.\n\n"
                    "**Abzugsfähige Werbungskosten:** Abschreibung (AfA), Schuldzinsen, "
                    "Reparaturen/Instandhaltung, Hausverwaltung, Grundsteuer, Versicherungen, "
                    "Werbungskosten-Pauschale. Bitte den Nettobetrag nach eigener Berechnung eintragen."
                ),
            )
        with mc2:
            st.slider(
                "Jährl. Mietsteigerung (%)", 0.0, 5.0,
                value=float(st.session_state.get(_gkey("hh_miet_stg"), 1.5)),
                step=0.1, key=_gkey("hh_miet_stg"),
            )


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _sidebar_top() -> None:
    """Titel, Reset und Laden – muss vor den Berechnungen laufen."""
    st.sidebar.title("🏦 Alterseinkünfte")
    st.sidebar.caption("Simulation | Keine Anlageberatung")

    if st.sidebar.button("🔄 Neu anfangen",
                         help="Alle Eingaben zurücksetzen und für eine neue Person von vorne beginnen.",
                         use_container_width=True):
        new_rc = st.session_state.get("_rc", 0) + 1
        st.session_state.clear()
        st.session_state["_rc"] = new_rc
        st.rerun()

    st.sidebar.markdown("---")

    saves = list_saves()
    if saves:
        with st.sidebar.expander("📂 Gespeicherte Profile", expanded=False):
            namen = [n for n, _ in saves]
            auswahl = st.selectbox("Profil wählen", namen, key="load_select")
            if st.button("📥 Laden", key="load_btn", use_container_width=True):
                data = load_session(dict(saves)[auswahl])
                _apply_loaded_session(data)
                st.session_state["save_name"] = auswahl
                st.rerun()


def _apply_loaded_session(data: dict) -> None:
    _write_profil_to_state(data["profil1"], "p1")
    if data.get("profil2"):
        st.session_state[_gkey("hat_partner")] = True
        _write_profil_to_state(data["profil2"], "p2")
    else:
        st.session_state[_gkey("hat_partner")] = False

    veranlagung = data.get("veranlagung", "Zusammen")
    st.session_state[_gkey("veranlagung_radio")] = (
        "Zusammenveranlagung (Splitting)" if veranlagung == "Zusammen"
        else "Getrennte Veranlagung"
    )
    st.session_state["vp_produkte"] = data.get("produkte", [])
    st.session_state[_gkey("hh_miet")]     = data.get("mieteinnahmen", 0.0)
    st.session_state[_gkey("hh_miet_stg")] = data.get("mietsteigerung", 0.015) * 100
    if data.get("hyp_daten"):
        st.session_state["hyp_daten"] = data["hyp_daten"]


def _sidebar_save(profil1: Profil, profil2, veranlagung: str,
                  mieteinnahmen: float, mietsteigerung: float) -> None:
    """Speichern-Bereich – läuft nach den Berechnungen, da Profil-Objekte benötigt werden."""
    with st.sidebar.expander("💾 Profil speichern", expanded=False):
        save_name = st.text_input("Name der Sicherung", value="MeinProfil", key="save_name")
        if st.button("💾 Jetzt speichern", key="save_btn", use_container_width=True):
            pfad = save_session(
                name=save_name,
                profil1=profil1,
                profil2=profil2,
                veranlagung=veranlagung,
                produkte=st.session_state.get("vp_produkte", []),
                mieteinnahmen=mieteinnahmen,
                mietsteigerung=mietsteigerung,
                hyp_daten=st.session_state.get("hyp_daten"),
            )
            st.sidebar.success(f"Gespeichert: {pfad}")


# ── App ───────────────────────────────────────────────────────────────────────

# Sidebar oben: Reset + Laden (können rerun auslösen)
_sidebar_top()

# Profile aus session_state aufbauen
hat_partner   = bool(st.session_state.get(_gkey("hat_partner"), False))
_ver_raw      = str(st.session_state.get(_gkey("veranlagung_radio"), "Zusammenveranlagung (Splitting)"))
veranlagung   = "Zusammen" if "Splitting" in _ver_raw else "Getrennt"
mieteinnahmen  = float(st.session_state.get(_gkey("hh_miet"), 0.0))
mietsteigerung = float(st.session_state.get(_gkey("hh_miet_stg"), 1.5)) / 100

profil1 = _profil_from_session("p1", 1970)
profil2 = _profil_from_session("p2", 1972) if hat_partner else None

# Bruttogehalt P1 → globaler Key für Vorsorge-/Entnahme-Optimierung
# aktuelles_brutto_monatlich hält bei Nicht-Pensionären das Gehalt (bei Pensionären die erwartete Pension)
st.session_state["opt_gehalt_mono"] = 0.0 if profil1.ist_pensionaer else profil1.aktuelles_brutto_monatlich

ergebnis1      = berechne_rente(profil1)
ergebnis2      = berechne_rente(profil2) if profil2 else None
haushalt_daten = berechne_haushalt(ergebnis1, ergebnis2, veranlagung, mieteinnahmen, profil1, profil2)

# Sidebar unten: Speichern (braucht Profil-Objekte)
_sidebar_save(profil1, profil2, veranlagung, mieteinnahmen, mietsteigerung)

# M4: Schnell-Übersicht Einkommen in Sidebar
st.sidebar.divider()

def _de_sidebar(v: float) -> str:
    s = f"{v:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def _approx_netto_gehalt(p: Profil) -> float:
    """Approximate net salary (AN-KV + simplified ESt) for sidebar."""
    if p.aktuelles_brutto_monatlich <= 0 or p.bereits_rentner or p.ist_pensionaer:
        return 0.0
    brutto = p.aktuelles_brutto_monatlich
    if p.krankenversicherung == "GKV":
        basis = min(brutto, BBG_KV_MONATLICH)
        an_kv = basis * (0.073 + p.gkv_zusatzbeitrag / 2)
        an_pv = basis * _pv_satz(p.kinder_anzahl if p.kinder else 0)[1]
    else:
        an_kv = an_pv = 0.0
    zvE_j = max(0.0, brutto * 12 - (an_kv + an_pv) * 12)
    return max(0.0, brutto - einkommensteuer(zvE_j) / 12 - an_kv - an_pv)

def _aktive_zusatzrenten(person_label: str) -> float:
    """Sum of monthly payouts from currently active contracts for this person."""
    total = 0.0
    for vp in st.session_state.get("vp_produkte", []):
        if vp.get("person", "Person 1") != person_label:
            continue
        startjahr = int(vp.get("fruehestes_startjahr", AKTUELLES_JAHR + 5))
        laufzeit = int(vp.get("laufzeit_jahre", 0))
        mono = float(vp.get("max_monatsrente", 0.0))
        if mono > 0 and startjahr <= AKTUELLES_JAHR:
            if laufzeit == 0 or startjahr + laufzeit > AKTUELLES_JAHR:
                total += mono
    return total

def _sidebar_person_metrics(label: str, p: Profil, erg, miete_anteil: float) -> None:
    st.sidebar.markdown(f"**{label}**")
    netto_g = _approx_netto_gehalt(p)
    zusatz = _aktive_zusatzrenten(label)
    if netto_g > 0:
        st.sidebar.metric("Nettogehalt (ca.)", f"{_de_sidebar(netto_g)} €/Mon.",
                          help="Geschätztes Nettogehalt (AN-KV + vereinfachte ESt).")
    st.sidebar.metric("Nettorente (Eintritt)", f"{_de_sidebar(erg.netto_monatlich)} €/Mon.",
                      help="Projizierte Nettorente zum Renteneintritt nach Steuer und KV.")
    if zusatz > 0:
        st.sidebar.metric("Zusatzrenten (laufend)", f"{_de_sidebar(zusatz)} €/Mon.",
                          help="Monatliche Vertragsauszahlungen, die bereits aktiv sind.")
    if miete_anteil > 0:
        st.sidebar.metric("Mieteinnahmen", f"{_de_sidebar(miete_anteil)} €/Mon.",
                          help="Netto-Mieteinnahmen zu gleichen Teilen je Person.")

_miete_pp = mieteinnahmen / (2 if ergebnis2 else 1)
_sidebar_person_metrics("Person 1", profil1, ergebnis1, _miete_pp)
if ergebnis2:
    _sidebar_person_metrics("Person 2", profil2, ergebnis2, _miete_pp)

# Vertragsauszahlungen aus Entnahme-Optimierung für ausgewähltes Slider-Jahr
_eo_jd = st.session_state.get("_sb_eo_jd", [])
if _eo_jd:
    _slider_jahre = [
        st.session_state.get(f"rc{_RC}_dash_jahr"),
        st.session_state.get(f"rc{_RC}_hh_jahr"),
        st.session_state.get(f"rc{_RC}_sim_jahr"),
        st.session_state.get(f"rc{_RC}_eo_sel_jahr"),
    ]
    _sel_sb_j = next((j for j in _slider_jahre if j is not None), None)
    if _sel_sb_j:
        _jrow_sb = next((r for r in _eo_jd if r["Jahr"] == _sel_sb_j), None)
        if _jrow_sb:
            _vers_p1 = _jrow_sb.get("Src_Versorgung", 0) / 12
            _einm_p1 = _jrow_sb.get("Src_Einmal", 0) / 12
            if _vers_p1 + _einm_p1 > 0:
                st.sidebar.divider()
                st.sidebar.caption(f"Vertragsauszahlungen {_sel_sb_j}")
                if _vers_p1 > 0:
                    st.sidebar.metric("Versorgungsrenten", f"{_de_sidebar(_vers_p1)} €/Mon.")
                if _einm_p1 > 0:
                    st.sidebar.metric("Einmalerträge", f"{_de_sidebar(_einm_p1)} €/Mon.")

# O3d: 6 Tabs (Steuern → Dashboard-Expander; Auszahlung → Entnahme-Expander)
tab_labels = ["⚙️ Profil", "📊 Dashboard", "🔮 Simulation",
              "🏦 Vorsorge-Bausteine", "🏠 Hypothek", "💡 Entnahme-Optimierung",
              "📖 Dokumentation"]
if profil2:
    tab_labels.insert(2, "👥 Haushalt")

tabs = st.tabs(tab_labels)

idx = 0
T: dict = {}
T["Profil"]        = tabs[idx]; idx += 1
T["Dashboard"]     = tabs[idx]; idx += 1
if profil2:
    T["Haushalt"]  = tabs[idx]; idx += 1
T["Simulation"]    = tabs[idx]; idx += 1
T["Vorsorge"]      = tabs[idx]; idx += 1
T["Hypothek"]      = tabs[idx]; idx += 1
T["Entnahme"]      = tabs[idx]; idx += 1
T["Dokumentation"] = tabs[idx]; idx += 1

render_profil_tab(T)
dashboard.render(T, profil1, ergebnis1, mieteinnahmen=mieteinnahmen,
                 mietsteigerung=mietsteigerung,
                 profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung)
if profil2:
    haushalt.render(T, profil1, profil2, ergebnis1, ergebnis2, veranlagung, haushalt_daten,
                    mieteinnahmen=mieteinnahmen, mietsteigerung=mietsteigerung)
simulation.render(T, profil1, ergebnis1, profil2=profil2, ergebnis2=ergebnis2,
                  veranlagung=veranlagung, mieteinnahmen=mieteinnahmen)
vorsorge.render(T, profil1, ergebnis1, profil2=profil2,
                mieteinnahmen=mieteinnahmen, mietsteigerung=mietsteigerung,
                ergebnis2=ergebnis2, veranlagung=veranlagung)
hypothek.render(T, _RC)
entnahme_opt.render(T, profil1, ergebnis1, profil2=profil2,
                    mieteinnahmen=mieteinnahmen, mietsteigerung=mietsteigerung,
                    ergebnis2=ergebnis2, veranlagung=veranlagung)
dokumentation.render(T)
