"""Entnahme-Optimierung – steueroptimierte Auszahlungsstrategie für bekannte Verträge.

Zeigt den Steuer-Steckbrief je Produkt und ermittelt die optimale Kombination
aus Startjahr und Auszahlungsart (Einmal/Rente) unter Berücksichtigung von
Einkommensteuer, Abgeltungsteuer und KVdR-Beiträgen.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, VorsorgeProdukt,
    optimiere_auszahlungen, besteuerungsanteil, ertragsanteil,
    BAV_FREIBETRAG_MONATLICH, BBG_KV_MONATLICH, _pv_satz, AKTUELLES_JAHR,
    _netto_ueber_horizont,
)
from tabs import auszahlung
from tabs.vorsorge import _run_optimierung
try:
    from tabs.hypothek import (
        get_ausgaben_plan, get_restschuld_end,
        get_hyp_info, get_ausgaben_plan_optimierung,
    )
except ImportError:
    def get_ausgaben_plan() -> dict:
        return {}
    def get_restschuld_end() -> float:
        return 0.0
    def get_hyp_info():
        return None
    def get_ausgaben_plan_optimierung(markt_zins_pa: float, anschluss_laufzeit: int,
                                      als_einmaltilgung: bool = False) -> dict:
        return {}


def _aus_dict(d: dict) -> VorsorgeProdukt:
    """Importiert _aus_dict aus vorsorge ohne zirkulären Import."""
    from tabs.vorsorge import _aus_dict as _vp_aus_dict
    return _vp_aus_dict(d)


def _kv_label_und_wert(typ: str, vbeg: int, tf: float, profil_p: Profil) -> tuple[str, str]:
    """Gibt (Spaltentitel, Zellwert) für die KV-Spalte zurück, abhängig vom KV-Status der Person."""
    is_pkv  = profil_p.krankenversicherung == "PKV"
    is_kvdr = profil_p.kvdr_pflicht  # nur relevant wenn GKV

    if is_pkv:
        return "KV", "–"

    if is_kvdr:
        col = "KVdR-pflichtig"
        kv_map = {
            "bAV":         "Ja – FB 187 €/Mon. (§ 226 SGB V)",
            "Riester":     "Nein",
            "Rürup":       "Nein",
            "LV":          "–",
            "PrivateRente":"Nein",
            "ETF":         "Nein",
        }
    else:
        col = "KV-pflichtig (§240)"
        kv_map = {
            "bAV":         "Ja – ohne Freibetrag (§ 240 SGB V)",
            "Riester":     "Ja (§ 240 SGB V)",
            "Rürup":       "Ja (§ 240 SGB V)",
            "LV":          "Ja – Einmalauszahlung (§ 240 SGB V)",
            "PrivateRente":"Ja (§ 240 SGB V)",
            "ETF":         "Ja – laufende Erträge (§ 240 SGB V)",
        }
    return col, kv_map.get(typ, "–")


def _steuer_steckbrief(prod_dicts: list[dict], profil: Profil,
                       profil2: Profil | None = None) -> pd.DataFrame:
    rows = []
    kv_cols_seen: set[str] = set()

    for p in prod_dicts:
        typ  = p.get("typ", "bAV")
        vbeg = p.get("vertragsbeginn", 2010)
        tf   = p.get("teilfreistellung", 0.30)
        person_label = p.get("person", "Person 1")
        profil_p = profil2 if (person_label == "Person 2" and profil2 is not None) else profil

        if typ == "bAV":
            einmal_regel = "100 % progressiv (§ 19 EStG)"
            mono_regel   = "100 % progressiv (§ 19 EStG)"
        elif typ == "Riester":
            einmal_regel = "100 % progressiv (§ 22 Nr. 5 EStG)"
            mono_regel   = "100 % progressiv (§ 22 Nr. 5 EStG)"
        elif typ == "Rürup":
            einmal_regel = "Nicht möglich (Basisrente)"
            ba = besteuerungsanteil(profil_p.eintritt_jahr)
            mono_regel   = f"Besteuerungsanteil {ba:.0%} (§ 22 Nr. 1 EStG)"
        elif typ == "LV":
            if vbeg < 2005:
                einmal_regel = "Steuerfrei (Altvertrag vor 2005)"
            else:
                einmal_regel = "Halbeinkünfte (≥ 12 J. + ≥ 60/62 J.) oder 25 % Abgeltungsteuer"
            mono_regel = "–"
        elif typ == "PrivateRente":
            if vbeg < 2005:
                einmal_regel = "Steuerfrei (Altvertrag vor 2005)"
            else:
                einmal_regel = "Halbeinkünfte (≥ 12 J. + ≥ 60/62 J.) oder 25 % Abgeltungsteuer"
            ea = ertragsanteil(profil_p.renteneintritt_alter)
            mono_regel = f"Ertragsanteil {ea:.0%} (§ 22 Nr. 1 S. 3a bb EStG)"
        elif typ == "ETF":
            einmal_regel = f"25 % Abgelt. auf {(1 - tf):.0%} des Gewinns (TF {tf:.0%}, § 20 InvStG)"
            mono_regel   = "–"
        else:
            einmal_regel = "–"
            mono_regel   = "–"

        kv_col, kv_val = _kv_label_und_wert(typ, vbeg, tf, profil_p)
        kv_cols_seen.add(kv_col)

        rows.append({
            "Produkt":          p["name"],
            "Typ":              p["typ_label"],
            "Person":           person_label,
            "Einmalauszahlung": einmal_regel,
            "Monatsrente":      mono_regel,
            "_kv_col":          kv_col,
            "_kv_val":          kv_val,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Wenn alle Produkte dieselbe KV-Spalte haben, einfache Spalte; sonst "KV-Status"
    if len(kv_cols_seen) == 1:
        col_name = kv_cols_seen.pop()
        df = df.rename(columns={"_kv_val": col_name}).drop(columns=["_kv_col"])
    else:
        df["KV-Status"] = df.apply(
            lambda r: f"{r['_kv_col']}: {r['_kv_val']}", axis=1)
        df = df.drop(columns=["_kv_col", "_kv_val"])

    return df


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _analyse_schenkungspotenzial(
    produkte: list[dict],
    profil: Profil,
    profil2: Profil | None,
    ergebnis: "RentenErgebnis | None" = None,
    ergebnis2: "RentenErgebnis | None" = None,
    mieteinnahmen_monatlich: float = 0.0,
) -> dict | None:
    """Analysiert Schenkungspotenzial zwischen GKV- und PKV-Person.

    Gibt None zurück wenn keine gemischte GKV/PKV-Konstellation vorliegt.
    Sonst ein Dict mit Empfehlungen, KV-Ersparnis und nicht übertragbaren Verträgen.
    """
    if profil2 is None:
        return None

    p1_gkv = profil.krankenversicherung == "GKV"
    p2_gkv = profil2.krankenversicherung == "GKV"
    if p1_gkv == p2_gkv:
        return None

    if p1_gkv:
        gkv_label, pkv_label, gkv_profil = "Person 1", "Person 2", profil
        gkv_ergebnis = ergebnis
    else:
        gkv_label, pkv_label, gkv_profil = "Person 2", "Person 1", profil2
        gkv_ergebnis = ergebnis2

    gkv_ist_freiwillig = not gkv_profil.kvdr_pflicht
    pv_voll, pv_halb = _pv_satz(gkv_profil.kinder_anzahl if gkv_profil.kinder else 0)
    kv_rate_voll = 0.146 + gkv_profil.gkv_zusatzbeitrag + pv_voll
    kv_rate_halb = 0.073 + gkv_profil.gkv_zusatzbeitrag / 2 + pv_halb

    gkv_prods = [p for p in produkte if p.get("person") == gkv_label]
    bav_mono_sum = sum(p.get("max_monatsrente", 0.0) for p in gkv_prods if p.get("typ") == "bAV")
    verbleibender_freibetrag = (
        max(0.0, BAV_FREIBETRAG_MONATLICH - bav_mono_sum)
        if not gkv_ist_freiwillig else 0.0
    )

    # Verbleibendes BBG-Kontingent für übertragbare Produkte (freiwillig GKV)
    # Basis: Festeinkommen das bereits KV-pflichtig ist und nicht übertragbar ist
    if gkv_ist_freiwillig and gkv_ergebnis is not None:
        ruerup_mono_sum = sum(
            p.get("max_monatsrente", 0.0) for p in gkv_prods if p.get("typ") == "Rürup"
        )
        _base_mono = (
            gkv_ergebnis.brutto_monatlich   # GRV/Pension + Profil.zusatz_monatlich
            + bav_mono_sum                   # bAV (nicht übertragbar)
            + ruerup_mono_sum                # Rürup (nicht übertragbar)
            + mieteinnahmen_monatlich / 2    # Mietanteil (50 %, konservativ)
        )
        _bbg_rest_mono = max(0.0, BBG_KV_MONATLICH - _base_mono)
    else:
        _bbg_rest_mono = BBG_KV_MONATLICH

    zu_verschieben: list[dict] = []
    nicht_verschiebbar: list[dict] = []
    gesamt_ersparnis_pa = 0.0
    gesamt_einmal_ersparnis = 0.0

    for p in gkv_prods:
        typ = p.get("typ", "")
        name = p.get("name", typ)
        mono = p.get("max_monatsrente", 0.0)
        einmal = p.get("max_einmalzahlung", 0.0)
        lfd_kap = p.get("laufende_kapitalertraege_mono", 0.0)

        if typ == "bAV":
            kv_j = (
                mono * 12 * kv_rate_voll if gkv_ist_freiwillig
                else max(0.0, mono - BAV_FREIBETRAG_MONATLICH) * 12 * kv_rate_halb
            )
            nicht_verschiebbar.append({
                "Vertrag": name, "Typ": typ,
                "KV-Kosten p.a. (ca.)": round(kv_j),
                "Grund": "Betriebsrente: nicht übertragbar (§ 1 BetrAVG)",
            })

        elif typ == "Rürup":
            kv_j = mono * 12 * kv_rate_voll if gkv_ist_freiwillig else 0.0
            nicht_verschiebbar.append({
                "Vertrag": name, "Typ": typ,
                "KV-Kosten p.a. (ca.)": round(kv_j),
                "Grund": "Rürup/Basisrente: nicht abtretbar (§ 97 EStG i.V.m. § 10 Abs. 1 Nr. 2b EStG)",
            })

        elif typ == "Riester":
            if gkv_ist_freiwillig:
                kv_relevant = min(mono, _bbg_rest_mono)
                kv_j = kv_relevant * 12 * kv_rate_voll
                _bbg_rest_mono = max(0.0, _bbg_rest_mono - kv_relevant)
            else:
                kv_j = 0.0
            gesamt_ersparnis_pa += kv_j
            zu_verschieben.append({
                "Vertrag": name, "Typ": typ, "Von": gkv_label, "An": pkv_label,
                "KV-Ersparnis p.a. (ca.)": round(kv_j),
                "Hinweis": "Nur zwischen Riester-berechtigten Eheleuten (§ 6 AltZertG)",
            })

        elif typ in ("PrivateRente", "LV"):
            _ist_einmal = False
            if gkv_ist_freiwillig:
                if mono > 0:
                    kv_relevant = min(mono, _bbg_rest_mono)
                    kv_j = kv_relevant * 12 * kv_rate_voll
                    _bbg_rest_mono = max(0.0, _bbg_rest_mono - kv_relevant)
                    hinweis = ""
                else:
                    einmal_relevant = min(einmal, _bbg_rest_mono * 12)
                    kv_j = einmal_relevant * kv_rate_voll
                    _ist_einmal = True
                    hinweis = "Einmalauszahlung – einmalige KV-Ersparnis (nicht p.a.)"
            else:
                kv_j = 0.0
                hinweis = "Unter KVdR nicht KV-pflichtig – kein KV-Vorteil durch Schenkung"
            if _ist_einmal:
                gesamt_einmal_ersparnis += kv_j
            else:
                gesamt_ersparnis_pa += kv_j
            zu_verschieben.append({
                "Vertrag": name, "Typ": typ, "Von": gkv_label, "An": pkv_label,
                "KV-Ersparnis p.a. (ca.)": round(kv_j),
                "Hinweis": hinweis,
            })

        elif typ == "ETF":
            if gkv_ist_freiwillig and lfd_kap > 0:
                kv_relevant = min(lfd_kap, _bbg_rest_mono)
                kv_j = kv_relevant * 12 * kv_rate_voll
                _bbg_rest_mono = max(0.0, _bbg_rest_mono - kv_relevant)
            else:
                kv_j = 0.0
            hinweis = (
                "" if kv_j > 0
                else "Keine lfd. Kapitalerträge erfasst – KV-Ersparnis nicht berechenbar"
            )
            gesamt_ersparnis_pa += kv_j
            zu_verschieben.append({
                "Vertrag": name, "Typ": typ, "Von": gkv_label, "An": pkv_label,
                "KV-Ersparnis p.a. (ca.)": round(kv_j),
                "Hinweis": hinweis,
            })

    return {
        "hat_empfehlung": (gesamt_ersparnis_pa + gesamt_einmal_ersparnis) > 0,
        "gkv_label": gkv_label,
        "pkv_label": pkv_label,
        "gkv_ist_freiwillig": gkv_ist_freiwillig,
        "zu_verschieben": zu_verschieben,
        "nicht_verschiebbar": nicht_verschiebbar,
        "gesamt_ersparnis_pa": gesamt_ersparnis_pa,
        "gesamt_einmal_ersparnis": gesamt_einmal_ersparnis,
        "verbleibender_freibetrag_bav_mono": verbleibender_freibetrag,
        "kv_rate_voll": kv_rate_voll,
        "kv_rate_halb": kv_rate_halb,
    }


def _render_schenkungsanalyse(analyse: dict) -> None:
    """Rendert den Schenkungsanalyse-Abschnitt."""
    st.subheader("🎁 Schenkungspotenzial – Vertragsübertragung zur KV-Optimierung")
    gkv_kv_typ = (
        "freiwillig GKV (§ 240 SGB V)" if analyse["gkv_ist_freiwillig"]
        else "KVdR-Pflichtmitglied (§ 229 SGB V)"
    )
    st.caption(
        f"**{analyse['gkv_label']}** ist {gkv_kv_typ}. "
        f"**{analyse['pkv_label']}** ist PKV-versichert (fixer Beitrag). "
        "Eine Übertragung von Vorsorgeverträgen auf die PKV-Person kann KV-Beiträge dauerhaft reduzieren."
    )

    if not analyse["hat_empfehlung"]:
        if not analyse["gkv_ist_freiwillig"]:
            st.info(
                f"**{analyse['gkv_label']} ist KVdR-Pflichtmitglied.** "
                "Unter KVdR (§ 229 SGB V) sind nur betriebliche Versorgungsbezüge (bAV) KV-pflichtig – "
                "diese sind arbeitsrechtlich nicht übertragbar (§ 1 BetrAVG). "
                "Private Renten, Riester und ETF-Erträge sind unter KVdR nicht KV-pflichtig. "
                "Eine Vertragsschenkung bringt daher **keinen KV-Vorteil**."
            )
        elif not analyse["zu_verschieben"]:
            st.info(
                "Keine Verträge der GKV-Person erfasst. "
                "Im Tab **Vorsorge-Bausteine** Produkte anlegen."
            )
        else:
            st.info(
                "Die erfassten Verträge der GKV-Person haben kein berechenbares KV-Einsparpotenzial "
                "(keine monatliche Rente oder laufende Kapitalerträge erfasst)."
            )
        if analyse["nicht_verschiebbar"]:
            with st.expander(
                f"Nicht übertragbare Verträge ({len(analyse['nicht_verschiebbar'])})",
                expanded=False,
            ):
                df_nv = pd.DataFrame(analyse["nicht_verschiebbar"])[
                    ["Vertrag", "Typ", "KV-Kosten p.a. (ca.)", "Grund"]
                ]
                st.dataframe(df_nv.set_index("Vertrag"), use_container_width=True)
        return

    _kv_rate_str = f"{analyse['kv_rate_voll']:.1%}".replace(".", ",")
    _metrics: list[tuple[str, str, str]] = []
    if analyse["gesamt_ersparnis_pa"] > 0:
        _metrics.append((
            "KV-Ersparnis p.a. (ca.)",
            f"{_de(analyse['gesamt_ersparnis_pa'])} €",
            f"Jährliche KV-Ersparnis für laufende Renten bei Übertragung auf die PKV-Person. "
            f"KV-Gesamtsatz: {_kv_rate_str}",
        ))
    if analyse["gesamt_einmal_ersparnis"] > 0:
        _metrics.append((
            "KV-Ersparnis einmalig (ca.)",
            f"{_de(analyse['gesamt_einmal_ersparnis'])} €",
            f"Einmalige KV-Ersparnis aus Einmalauszahlungen bei Übertragung auf die PKV-Person. "
            f"KV-Gesamtsatz: {_kv_rate_str}",
        ))
    if not analyse["gkv_ist_freiwillig"] and analyse["verbleibender_freibetrag_bav_mono"] > 0:
        _metrics.append((
            "Verbleibender bAV-Freibetrag",
            f"{_de(analyse['verbleibender_freibetrag_bav_mono'])} €/Mon.",
            f"Ungenutzter bAV-Freibetrag (§ 226 Abs. 2 SGB V): {_de(BAV_FREIBETRAG_MONATLICH)} €/Mon. gesamt.",
        ))
    if _metrics:
        _m_cols = st.columns(max(len(_metrics), 2))
        for _i, (_lbl, _val, _hlp) in enumerate(_metrics):
            _m_cols[_i].metric(_lbl, _val, help=_hlp)

    if analyse["zu_verschieben"]:
        st.markdown(
            f"**Empfohlen – von {analyse['gkv_label']} auf {analyse['pkv_label']} übertragen:**"
        )
        df_v = pd.DataFrame(analyse["zu_verschieben"])[
            ["Vertrag", "Typ", "Von", "An", "KV-Ersparnis p.a. (ca.)", "Hinweis"]
        ]
        st.dataframe(df_v.set_index("Vertrag"), use_container_width=True)

    if analyse["nicht_verschiebbar"]:
        with st.expander(
            f"Nicht übertragbare Verträge ({len(analyse['nicht_verschiebbar'])})",
            expanded=False,
        ):
            df_nv = pd.DataFrame(analyse["nicht_verschiebbar"])[
                ["Vertrag", "Typ", "KV-Kosten p.a. (ca.)", "Grund"]
            ]
            st.dataframe(df_nv.set_index("Vertrag"), use_container_width=True)

    st.caption(
        "⚠️ **Rechtlicher Hinweis:** Schenkungen zwischen Eheleuten können den Freibetrag "
        "von 500.000 € (alle 10 Jahre, § 16 Abs. 1 Nr. 1 ErbStG) nutzen. "
        "Riester-Übertragungen nur zwischen förderberechtigten Eheleuten (§ 6 AltZertG). "
        "Die individuelle Umsetzung sollte mit einem Steuerberater abgestimmt werden."
    )


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis, profil2=None,
           mieteinnahmen: float = 0.0, mietsteigerung: float = 0.0,
           ergebnis2=None, veranlagung: str = "Getrennt") -> None:
    with T["Entnahme"]:
        st.header("💡 Entnahme-Optimierung")
        st.caption(
            "Steueroptimale Auszahlungsstrategie für alle erfassten Verträge unter "
            "Berücksichtigung von Einkommensteuer (progressiv + Abgeltungsteuer), "
            "KVdR-Beiträgen und Sparerpauschbetrag. "
            "Produkte werden im Tab **Vorsorge-Bausteine** erfasst."
        )

        # ── Personenfilter ────────────────────────────────────────────────────
        _rc = st.session_state.get("_rc", 0)
        hat_partner = profil2 is not None and ergebnis2 is not None
        eo_person = "Zusammen"
        if hat_partner:
            eo_person = st.radio(
                "Optimierung für", ["Person 1", "Person 2", "Zusammen"],
                horizontal=True, key=f"rc{_rc}_eo_person", index=2,
                help="Person 1/2: nur deren Produkte + einzelne Steuerberechnung. "
                     "Zusammen: alle Produkte, gemeinsame Steuer (Splitting falls aktiv).",
            )

        # Richtiges Profil + Ergebnis je Auswahl
        if eo_person == "Person 2" and hat_partner:
            _profil_eo  = profil2
            _ergebnis_eo = ergebnis2
            _profil2_eo  = None
            _ergebnis2_eo = None
            _ver_eo = "Getrennt"
        elif eo_person == "Zusammen" and hat_partner:
            _profil_eo   = profil
            _ergebnis_eo = ergebnis
            _profil2_eo  = profil2
            _ergebnis2_eo = ergebnis2
            _ver_eo = veranlagung
        else:
            _profil_eo   = profil
            _ergebnis_eo = ergebnis
            _profil2_eo  = None
            _ergebnis2_eo = None
            _ver_eo = "Getrennt"

        produkte_dicts = [
            p for p in st.session_state.get("vp_produkte", [])
        ]
        from tabs.vorsorge import _migriere
        produkte_dicts = [_migriere(p) for p in produkte_dicts]

        # Produkte nach Personenfilter einschränken
        if eo_person == "Person 1":
            produkte_dicts = [p for p in produkte_dicts
                              if p.get("person", "Person 1") == "Person 1"]
        elif eo_person == "Person 2":
            produkte_dicts = [p for p in produkte_dicts
                              if p.get("person") == "Person 2"]

        if not produkte_dicts:
            st.info("Noch keine Verträge erfasst. Bitte zuerst im Tab **Vorsorge-Bausteine** Produkte anlegen.")
            return

        # ── Steuer-Steckbrief ─────────────────────────────────────────────────
        st.subheader("📋 Steuer-Steckbrief")
        _kv_hint = (
            "KVdR-Pflichtmitglied (§229 SGB V)" if _profil_eo.krankenversicherung == "GKV" and _profil_eo.kvdr_pflicht
            else "freiwillig GKV (§240 SGB V)" if _profil_eo.krankenversicherung == "GKV"
            else "PKV"
        )
        st.caption(f"Steuerliche und KV-Behandlung je Produkt auf einen Blick. KV-Status: {_kv_hint}.")
        df_stb = _steuer_steckbrief(produkte_dicts, _profil_eo,
                                    profil2=_profil2_eo if eo_person == "Zusammen" else None)
        st.dataframe(df_stb.set_index("Produkt"), use_container_width=True)

        st.divider()

        # ── Schenkungsanalyse (nur bei gemischter GKV/PKV-Konstellation) ────────
        if eo_person == "Zusammen" and hat_partner:
            _analyse = _analyse_schenkungspotenzial(
                produkte_dicts, profil, profil2, ergebnis, ergebnis2, mieteinnahmen)
            if _analyse is not None:
                _render_schenkungsanalyse(_analyse)
                st.divider()

        # ── Optimierungsparameter ─────────────────────────────────────────────
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            horizon = st.slider("Planungshorizont ab Renteneintritt (Jahre)",
                                10, 40, 25, key=f"rc{_rc}_eo_horizon")
            from engine import AKTUELLES_JAHR as _AJ_EO
            _pre_eo = max(0, _profil_eo.eintritt_jahr - _AJ_EO) if not _profil_eo.bereits_rentner else 0
            if _pre_eo > 0:
                st.caption(f"Gesamt: {horizon + _pre_eo} Jahre ({_pre_eo} Arbeits- + {horizon} Rentenjahre)")
        with oc2:
            if mieteinnahmen > 0:
                st.metric("Mieteinnahmen (Basis)",
                          f"{_de(mieteinnahmen)} €/Mon.",
                          help=f"Steigen um {mietsteigerung:.1%}".replace(".", ",") +
                               " p.a. und erhöhen die Steuerprogression.")
        with oc3:
            if not _profil_eo.bereits_rentner:
                gehalt = float(st.session_state.get("opt_gehalt_mono", 0.0))
                if eo_person == "Person 2":
                    gehalt = 0.0
                st.metric("Bruttogehalt (aktiv)",
                          f"{_de(gehalt)} €/Mon." if gehalt > 0 else "–",
                          help="Im Tab ⚙️ Profil einstellbar. "
                               "Wird für Steuerprogression in Arbeitsjahren verwendet.")
            else:
                gehalt = 0.0

        # ── Hypothek ──────────────────────────────────────────────────────────
        _hyp_info = get_hyp_info()
        _ausgaben_plan: dict[int, float] = {}
        if _hyp_info:
            _hyp_checkbox = st.checkbox(
                "🏠 Hypothek in Optimierung berücksichtigen",
                value=True,
                key=f"rc{_rc}_eo_hyp_aktiv",
                help="Berücksichtigt laufende Hypothekraten und Restschuld-Behandlung "
                     "im Ausgaben-Plan der Optimierung.",
            )
            if _hyp_checkbox:
                _de_h = lambda v: f"{v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
                _rs = _hyp_info["restschuld_end"]
                st.caption(
                    f"Hypothek {_hyp_info['startjahr']}–{_hyp_info['endjahr']} · "
                    f"Rate {_de_h(_hyp_info['jaehrl_rate'])} €/Jahr · "
                    f"Nominalzins {_hyp_info['zins_pa']*100:.2f} % · "
                    f"Restschuld Endjahr: **{_de_h(_rs)} €**"
                )
                _markt_zins_pa = _hyp_info["anschluss_zins_pa"]
                _anschluss_lz  = _hyp_info["anschluss_laufzeit"]
                _vorsorge_tilgung = False
                if _rs > 0:
                    _vorsorge_tilgung = st.checkbox(
                        "💰 Restschuld aus Vorsorgevertrag tilgen (Einmalauszahlung)",
                        value=False,
                        key=f"rc{_rc}_eo_hyp_vorsorge_tilgung",
                        help="Der Optimizer prüft, ob eine Einmalauszahlung aus einem "
                             "Vorsorgevertrag im Endjahr der Hypothek die Restschuld deckt "
                             "und ob ein früherer Auszahlungszeitpunkt vorteilhafter ist.",
                    )
                    if not _vorsorge_tilgung:
                        hc1, hc2 = st.columns(2)
                        with hc1:
                            _markt_zins_pct = st.number_input(
                                "Marktaktueller Anschluss-Zinssatz (%)", 0.0, 20.0,
                                value=round(_hyp_info["anschluss_zins_pa"] * 100, 2),
                                step=0.05, format="%.2f",
                                key=f"rc{_rc}_eo_hyp_markt_zins",
                                help="Anschlussfinanzierung nach Ablauf der Zinsbindung. "
                                     "Default: in Hypothek-Tab eingestellter Anschlusszins.",
                            )
                            _markt_zins_pa = _markt_zins_pct / 100.0
                        with hc2:
                            _anschluss_lz = int(st.number_input(
                                "Laufzeit Anschlussfinanzierung (Jahre)", 1, 30,
                                value=_hyp_info["anschluss_laufzeit"], step=1,
                                key=f"rc{_rc}_eo_hyp_anschl_lz",
                            ))
                    else:
                        st.info(
                            f"Restschuld **{_de_h(_rs)} €** wird als Einmalbetrag im Jahr "
                            f"**{_hyp_info['endjahr']}** geplant. Der Optimizer bewertet, "
                            "ob eine frühere Einmalauszahlung aus einem Vorsorgevertrag "
                            "die Restschuld vorteilhafter deckt."
                        )
                _ausgaben_plan = get_ausgaben_plan_optimierung(
                    _markt_zins_pa, _anschluss_lz, als_einmaltilgung=_vorsorge_tilgung
                )

        # ── Optimierung ausführen ─────────────────────────────────────────────
        st.subheader("🔍 Optimale Auszahlungsstrategie")
        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        with st.spinner("Optimierung läuft …"):
            opt = _run_optimierung("eo", _profil_eo, _ergebnis_eo, produkte_obj, produkte_dicts,
                                   horizon, mieteinnahmen, mietsteigerung,
                                   profil2=_profil2_eo, ergebnis2=_ergebnis2_eo,
                                   veranlagung=_ver_eo, gehalt=gehalt,
                                   ausgaben_plan=_ausgaben_plan if _ausgaben_plan else None)

        if not opt:
            st.info("Keine Produkte für Optimierung vorhanden.")
            return

        # Jahresdaten für Sidebar-Vertragsanzeige speichern
        st.session_state["_sb_eo_jd"] = opt["jahresdaten"]

        # Kennzahlen
        _df_kc = pd.DataFrame(opt["jahresdaten"])
        _netto_arbeit = _df_kc.loc[_df_kc.get("Src_Gehalt", pd.Series(0, index=_df_kc.index)) > 0, "Netto"].sum() if "Src_Gehalt" in _df_kc.columns else 0
        _netto_rente  = _df_kc.loc[_df_kc.get("Src_Gehalt", pd.Series(0, index=_df_kc.index)) == 0, "Netto"].sum() if "Src_Gehalt" in _df_kc.columns else opt["bestes_netto"]

        if _netto_arbeit > 0:
            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Netto Arbeitsphase", f"{_de(_netto_arbeit)} €",
                       help="Summe Netto-Jahreseinkommen in aktiven Berufsjahren.")
            kc2.metric("Netto Rentenphase", f"{_de(_netto_rente)} €",
                       help=f"Summe Netto-Jahreseinkommen in {horizon} Rentenjahren.")
            delta_mono = opt["bestes_netto"] - opt["netto_alle_monatlich"]
            kc3.metric("Vorteil vs. alles monatlich",
                       f"{'+' if delta_mono >= 0 else ''}{_de(delta_mono)} €", delta_color="normal")
            delta_einmal = opt["bestes_netto"] - opt["netto_alle_einmal"]
            kc4.metric("Vorteil vs. alles Einmal",
                       f"{'+' if delta_einmal >= 0 else ''}{_de(delta_einmal)} €", delta_color="normal")
        else:
            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Netto optimal (gesamt)", f"{_de(opt['bestes_netto'])} €",
                       help=f"Summe aller Netto-Jahreseinkommen über {horizon} Jahre.")
            delta_mono = opt["bestes_netto"] - opt["netto_alle_monatlich"]
            kc2.metric("Vorteil vs. alles monatlich",
                       f"{'+' if delta_mono >= 0 else ''}{_de(delta_mono)} €", delta_color="normal")
            delta_einmal = opt["bestes_netto"] - opt["netto_alle_einmal"]
            kc3.metric("Vorteil vs. alles Einmal",
                       f"{'+' if delta_einmal >= 0 else ''}{_de(delta_einmal)} €", delta_color="normal")
            kc4.metric("Kombinationen geprüft", f"{opt['anzahl_kombinationen']:,}")
        st.caption(f"Kombinationen geprüft: {opt['anzahl_kombinationen']:,}")

        st.success("**Optimale Strategie:**")
        for prod, startjahr, anteil in opt["beste_entscheidungen"]:
            einmal_wert = prod.max_einmalzahlung * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr)
            mono_wert = prod.max_monatsrente * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr)
            if anteil == 1.0:
                modus = f"Einmalauszahlung **{_de(einmal_wert)} €**"
            elif anteil == 0.0:
                modus = f"Monatliche Rente **{_de(mono_wert)} €/Mon.**"
            else:
                modus = (f"Kombiniert: **{_de(einmal_wert * anteil)} €** Einmal + "
                         f"**{_de(mono_wert * (1 - anteil))} €/Mon.**")
            aufschub = startjahr - prod.fruehestes_startjahr
            note = f" (+{aufschub} J. Aufschub)" if aufschub > 0 else ""
            st.markdown(f"- **{prod.name}** ({prod.typ}): {modus} ab **{startjahr}**{note}")

        st.divider()

        # ── Strategievergleich ────────────────────────────────────────────────
        st.subheader("Strategievergleich")
        _vgl_labels = [
            "Optimal",
            "Alles Monatlich\n(frühest möglich)",
            "Alles Monatlich\n(spätestens)",
            "Alles Einmal\n(frühest möglich)",
            "Alles Einmal\n(spätestens)",
        ]
        _vgl_werte = [
            opt["bestes_netto"],
            opt["netto_alle_monatlich"],
            opt["netto_alle_monatlich_spaet"],
            opt["netto_alle_einmal"],
            opt["netto_alle_einmal_spaet"],
        ]
        _vgl_farben = ["#4CAF50", "#2196F3", "#64B5F6", "#FF9800", "#FFB74D"]
        fig_vgl = go.Figure(go.Bar(
            x=_vgl_labels,
            y=_vgl_werte,
            marker_color=_vgl_farben,
            text=[f"{_de(v)} €" for v in _vgl_werte],
            textposition="outside",
        ))
        fig_vgl.update_layout(
            template="plotly_white", height=380,
            yaxis=dict(title=f"Gesamt-Netto über {horizon} Jahre (€)", tickformat=",.0f"),
            margin=dict(l=10, r=10, t=20, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_vgl, use_container_width=True)

        st.divider()

        # ── Jahresverlauf nach Einkommensquelle ───────────────────────────────
        st.subheader("Jahresverlauf nach Einkommensquelle")
        _rl_col1, _rl_col2 = st.columns([2, 1])
        with _rl_col1:
            _real_toggle = st.checkbox(
                "Reale Werte (inflationsbereinigt)",
                value=False, key=f"rc{_rc}_eo_real",
                help="Deflationiert alle Jahreswerte auf die Kaufkraft des Renteneintritts-Jahres.",
            )
        with _rl_col2:
            _real_inf = st.number_input(
                "Inflation p.a. (%)", 0.0, 5.0, 2.0, 0.1,
                key=f"rc{_rc}_eo_inflation",
                disabled=not _real_toggle,
                help="Jährliche Inflationsrate für Kaufkraftkorrektur.",
            ) if _real_toggle else 2.0
        df_jd = pd.DataFrame(opt["jahresdaten"]).set_index("Jahr")

        # Reale Werte: alle numerischen Spalten mit Inflationsdeflaktor skalieren
        _start_j = int(df_jd.index[0]) if len(df_jd) > 0 else 0
        if _real_toggle and _real_inf > 0:
            _inf_r = _real_inf / 100
            _deflator = {j: 1.0 / (1 + _inf_r) ** (j - _start_j) for j in df_jd.index}
            _num_cols = [c for c in df_jd.columns if df_jd[c].dtype in ("float64", "int64")
                         and c not in ("LHK",)]
            for _col in _num_cols:
                df_jd[_col] = df_jd[_col] * df_jd.index.map(_deflator)

        # Vertragsnamen pro Jahr für Einmal- und Versorgungsbalken
        _jahre = list(df_jd.index)
        _VERSORGUNG_TYPEN = {"bAV", "Riester", "Rürup", "PrivateRente"}
        _einmal_info  = {j: [] for j in _jahre}
        _versorg_info = {j: [] for j in _jahre}
        for _prod, _startjahr, _anteil in opt["beste_entscheidungen"]:
            _aufschub = max(0, _startjahr - _prod.fruehestes_startjahr)
            _fak = (1 + _prod.aufschub_rendite) ** _aufschub
            # Einmalauszahlung: nur im Startjahr
            if _anteil > 0 and _startjahr in _einmal_info:
                _betrag = _prod.max_einmalzahlung * _fak * _anteil
                _einmal_info[_startjahr].append(f"{_prod.name}: {_de(_betrag)} €")
            # Laufende Versorgung: ab Startjahr für die Laufzeit
            if _anteil < 1.0 and _prod.typ in _VERSORGUNG_TYPEN:
                _mono = _prod.max_monatsrente * _fak * (1 - _anteil)
                _lz = _prod.laufzeit_jahre  # 0 = lebenslang
                for _j in _jahre:
                    if _j < _startjahr:
                        continue
                    if _lz > 0 and _j >= _startjahr + _lz:
                        break
                    _versorg_info[_j].append(f"{_prod.name}: {_de(_mono)} €/Mon.")

        def _hover_lines(info_dict: dict, jahre: list) -> list[str]:
            return [
                "<br>".join(info_dict[j]) if info_dict[j] else ""
                for j in jahre
            ]

        _cd_einmal  = _hover_lines(_einmal_info,  _jahre)
        _cd_versorg = _hover_lines(_versorg_info, _jahre)

        fig_src = go.Figure()
        src_cols = [
            ("Src_Gehalt",       "Bruttogehalt (aktiv)",    "#78909C", None),
            ("Src_GesRente",     "Gesetzl. Rente P1",       "#4CAF50", None),
            ("Src_P2_Rente",     "Gesetzl. Rente P2",       "#81C784", None),
            ("Src_Versorgung",   "Betriebliche Versorgung", "#2196F3", _cd_versorg),
            ("Src_Einmal",       "Einmalauszahlungen",      "#FF9800", _cd_einmal),
            ("Src_Miete",        "Mieteinnahmen",           "#9C27B0", None),
            ("Src_Kapitalverzehr", "Kapitalverzehr (Pool)", "#9E9D24", None),
        ]
        for col, label, color, customdata in src_cols:
            if col in df_jd.columns and df_jd[col].sum() > 0:
                if customdata is not None:
                    _non_empty = [s for s in customdata if s]
                    _has_detail = len(_non_empty) > 0
                else:
                    _has_detail = False
                if _has_detail:
                    fig_src.add_trace(go.Bar(
                        name=label, x=df_jd.index, y=df_jd[col],
                        marker_color=color,
                        customdata=customdata,
                        hovertemplate=(
                            "%{x}: %{y:,.0f} €"
                            "<br><i>%{customdata}</i>"
                            "<extra>" + label + "</extra>"
                        ),
                    ))
                else:
                    fig_src.add_trace(go.Bar(
                        name=label, x=df_jd.index, y=df_jd[col],
                        marker_color=color,
                        hovertemplate="%{x}: %{y:,.0f} €<extra>" + label + "</extra>",
                    ))
        fig_src.add_trace(go.Scatter(
            name="Netto", x=df_jd.index, y=df_jd["Netto"],
            mode="lines+markers",
            line=dict(color="black", width=2),
            hovertemplate="%{x}: %{y:,.0f} € Netto<extra></extra>",
        ))
        if not _profil_eo.bereits_rentner:
            _vline_label_src = "P1 Renteneintritt" if _profil2_eo else "Renteneintritt"
            fig_src.add_vline(
                x=_profil_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#5C6BC0",
                annotation_text=_vline_label_src, annotation_position="top right",
            )
        if _profil2_eo and not _profil2_eo.bereits_rentner:
            fig_src.add_vline(
                x=_profil2_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#E91E63",
                annotation_text="P2 Renteneintritt", annotation_position="top left",
            )
        # Sonderausgaben (Hypothek) als Annotationen im Chart
        if "Sonderausgabe" in df_jd.columns:
            _sonder_jahre = df_jd[df_jd["Sonderausgabe"] > 0].index
            for _sj in _sonder_jahre:
                _sa = df_jd.loc[_sj, "Sonderausgabe"]
                fig_src.add_annotation(
                    x=_sj, y=0,
                    text=f"Hyp. {_de(_sa / 1000, 0)}k€",
                    showarrow=True, arrowhead=2, arrowcolor="#D32F2F",
                    font=dict(color="#D32F2F", size=10),
                    ax=0, ay=30,
                )
        # Pool-Injektion-Annotationen (Produkt wird in Kapitalanlage-Pool überführt)
        if "Kap_Injektion" in df_jd.columns:
            for _ij in df_jd[df_jd["Kap_Injektion"] > 0].index:
                _inj = df_jd.loc[_ij, "Kap_Injektion"]
                fig_src.add_annotation(
                    x=_ij, y=_inj,
                    text=f"Pool +{_de(_inj / 1000, 0)}k€",
                    showarrow=True, arrowhead=2, arrowcolor="#0288D1",
                    font=dict(color="#0288D1", size=10),
                    ax=0, ay=-30,
                )

        fig_src.update_layout(
            barmode="stack", template="plotly_white", height=400,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr (brutto)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=50, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_src, use_container_width=True)

        # ── Hypothek-Fehlbetrag Warnungen ────────────────────────────────────
        if "Kap_Fehlbetrag" in df_jd.columns and df_jd["Kap_Fehlbetrag"].sum() > 0:
            _fehlbetrag_jahre = df_jd[df_jd["Kap_Fehlbetrag"] > 0]
            st.error(
                "**Kapitalanlage-Pool unzureichend für Restschuld-Tilgung!**\n\n"
                + "\n".join(
                    f"- {int(j)}: Fehlbetrag **{_de(row['Kap_Fehlbetrag'])} €** "
                    f"— verfügbares Netto um {_de(row['Kap_Fehlbetrag'] / 12)} €/Mon. reduziert"
                    for j, row in _fehlbetrag_jahre.iterrows()
                )
                + "\n\nEmpfehlung: Anschlussfinanzierung oder Sondertilgung erhöhen.",
            )
        elif "Sonderausgabe" in df_jd.columns and df_jd["Sonderausgabe"].sum() > 0:
            _sa_total = df_jd["Sonderausgabe"].sum()
            st.success(
                f"✅ Restschuld-Tilgung ({_de(_sa_total)} €) vollständig durch Kapitalanlage-Pool gedeckt."
            )

        # ── Zwei-Strategie-Vergleich Netto-Verlauf ────────────────────────────
        with st.expander("📊 Zwei-Strategie-Vergleich", expanded=False):
            st.caption(
                "Vergleicht den jährlichen Nettoverlauf der optimalen Strategie mit "
                "einer manuell gewählten Vergleichsstrategie."
            )
            _vgl_opts = [
                "Alles Monatlich (frühestmöglich)",
                "Alles Monatlich (spätestmöglich)",
                "Alles Einmal (frühestmöglich)",
                "Alles Einmal (spätestmöglich)",
            ]
            _sel_vgl = st.selectbox(
                "Vergleichsstrategie", _vgl_opts, key=f"rc{_rc}_eo_vgl_strat",
            )
            # Build the comparison scenario decisions
            _vgl_sj_frueh  = {p.id: p.fruehestes_startjahr for p in produkte_obj}
            _vgl_sj_spaet  = {p.id: p.spaetestes_startjahr for p in produkte_obj}
            if "frühestmöglich" in _sel_vgl:
                _vgl_sj_map = _vgl_sj_frueh
            else:
                _vgl_sj_map = _vgl_sj_spaet
            if "Monatlich" in _sel_vgl:
                _vgl_ents = [(p, _vgl_sj_map[p.id], 0.0) for p in produkte_obj]
            else:
                _vgl_ents = [(p, _vgl_sj_map[p.id], 1.0) for p in produkte_obj]
            _, _vgl_jd = _netto_ueber_horizont(
                _profil_eo, _ergebnis_eo, _vgl_ents, horizon, mieteinnahmen, mietsteigerung,
                profil2=_profil2_eo, ergebnis2=_ergebnis2_eo, veranlagung=_ver_eo,
                gehalt_monatlich=gehalt,
                ausgaben_plan=_ausgaben_plan if _ausgaben_plan else None,
            )
            _vgl_df = pd.DataFrame(_vgl_jd).set_index("Jahr")
            if _real_toggle and _real_inf > 0:
                _inf_r2 = _real_inf / 100
                _defl2 = {j: 1.0 / (1 + _inf_r2) ** (j - _start_j) for j in _vgl_df.index}
                if "Netto" in _vgl_df.columns:
                    _vgl_df["Netto"] = _vgl_df["Netto"] * _vgl_df.index.map(_defl2)
            fig_vgl2 = go.Figure()
            fig_vgl2.add_trace(go.Scatter(
                name="Optimal",
                x=df_jd.index, y=df_jd["Netto"],
                mode="lines+markers",
                line=dict(color="#4CAF50", width=2.5),
                hovertemplate="%{x}: %{y:,.0f} € Netto<extra>Optimal</extra>",
            ))
            fig_vgl2.add_trace(go.Scatter(
                name=_sel_vgl,
                x=_vgl_df.index, y=_vgl_df["Netto"],
                mode="lines+markers",
                line=dict(color="#2196F3", width=2, dash="dash"),
                hovertemplate="%{x}: %{y:,.0f} € Netto<extra>" + _sel_vgl + "</extra>",
            ))
            _diff_total = df_jd["Netto"].sum() - _vgl_df["Netto"].sum()
            _ylabel = "€ / Jahr (real)" if _real_toggle else "€ / Jahr"
            fig_vgl2.update_layout(
                template="plotly_white", height=360,
                xaxis=dict(title="Jahr", dtick=2),
                yaxis=dict(title=_ylabel, tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=10, t=50, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_vgl2, use_container_width=True)
            _sign = "+" if _diff_total >= 0 else ""
            st.caption(
                f"Differenz (Optimal − {_sel_vgl}): "
                f"**{_sign}{_de(_diff_total)} €** über {horizon} Jahre"
                + (" (inflationsbereinigt)" if _real_toggle else "") + "."
            )

        # ── Kapitalanlage-Pool Verlauf ─────────────────────────────────────────
        if "Kap_Pool" in df_jd.columns and df_jd["Kap_Pool"].sum() > 0:
            st.subheader("Kapitalanlage-Pool Verlauf")
            fig_pool = go.Figure()
            fig_pool.add_trace(go.Scatter(
                name="Poolwert", x=df_jd.index, y=df_jd["Kap_Pool"],
                mode="lines+markers", line=dict(color="#1565C0", width=2.5),
                hovertemplate="%{x}: %{y:,.0f} € Poolwert<extra></extra>",
            ))
            if "Src_Kapitalverzehr" in df_jd.columns and df_jd["Src_Kapitalverzehr"].sum() > 0:
                fig_pool.add_trace(go.Bar(
                    name="Entnahme", x=df_jd.index, y=df_jd["Src_Kapitalverzehr"],
                    marker_color="#42A5F5", opacity=0.7,
                    yaxis="y2",
                    hovertemplate="%{x}: %{y:,.0f} € Entnahme<extra></extra>",
                ))
            fig_pool.update_layout(
                barmode="stack", template="plotly_white", height=360,
                xaxis=dict(title="Jahr", dtick=2),
                yaxis=dict(title="Poolwert (€)", tickformat=",.0f"),
                yaxis2=dict(title="Entnahme (€/Jahr)", overlaying="y", side="right",
                            tickformat=",.0f", showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=10, t=50, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_pool, use_container_width=True)

        # ── Hypothek-Vergleich: Kapitalanlage vs. Ratenkredit ────────────────
        _restschuld = get_restschuld_end()
        if _restschuld > 0:
            with st.expander("🏠 Hypothek-Restschuld: Optionsvergleich", expanded=False):
                st.caption(
                    f"Restschuld am Hypothek-Endjahr: **{_de(_restschuld)} €**. "
                    "Vergleich der Behandlungsoptionen unter Einbeziehung von Steuer, KV und Kapitalrendite."
                )
                # Mindest-Netto Eingabe
                _mindest_j = st.number_input(
                    "Mindest-Haushaltsnetto (€/Jahr) als Zielgröße",
                    min_value=0, max_value=500_000,
                    value=int(st.session_state.get(f"rc{_rc}_eo_mindest_netto_j", 24_000)),
                    step=1_000,
                    key=f"rc{_rc}_eo_mindest_netto_j",
                    help="Jahreswert (= Monatswert × 12), der als Mindestversorgung gelten soll.",
                )

                # Plan für jede Option berechnen
                hyp_d = st.session_state.get("hyp_daten", {})
                endjahr_hyp = int(hyp_d.get("endjahr", AKTUELLES_JAHR + 20))
                anschluss_zins = float(hyp_d.get("anschluss_zins_pa", 0.04))
                anschluss_lz = int(hyp_d.get("anschluss_laufzeit", 10))

                try:
                    from tabs.hypothek import _annuitaet_rate as _hyp_annuitaet_rate
                    rate_rk = _hyp_annuitaet_rate(_restschuld, anschluss_zins, anschluss_lz)
                except Exception:
                    rate_rk = _restschuld / max(1, anschluss_lz)

                _plan_ka = {endjahr_hyp: _restschuld}
                _plan_rk = {endjahr_hyp + 1 + i: rate_rk for i in range(anschluss_lz)}
                _plan_keine = {}

                with st.spinner("Vergleich wird berechnet …"):
                    _opt_ka = _run_optimierung(
                        "eo_ka", _profil_eo, _ergebnis_eo, produkte_obj, produkte_dicts,
                        horizon, mieteinnahmen, mietsteigerung,
                        profil2=_profil2_eo, ergebnis2=_ergebnis2_eo,
                        veranlagung=_ver_eo, gehalt=gehalt,
                        ausgaben_plan=_plan_ka,
                    )
                    _opt_rk = _run_optimierung(
                        "eo_rk", _profil_eo, _ergebnis_eo, produkte_obj, produkte_dicts,
                        horizon, mieteinnahmen, mietsteigerung,
                        profil2=_profil2_eo, ergebnis2=_ergebnis2_eo,
                        veranlagung=_ver_eo, gehalt=gehalt,
                        ausgaben_plan=_plan_rk,
                    )
                    _opt_keine = _run_optimierung(
                        "eo_keine", _profil_eo, _ergebnis_eo, produkte_obj, produkte_dicts,
                        horizon, mieteinnahmen, mietsteigerung,
                        profil2=_profil2_eo, ergebnis2=_ergebnis2_eo,
                        veranlagung=_ver_eo, gehalt=gehalt,
                        ausgaben_plan=None,
                    )

                def _min_netto_j(opt_res: dict) -> float:
                    if not opt_res.get("jahresdaten"):
                        return float("inf")
                    return min(r["Netto"] for r in opt_res["jahresdaten"])

                def _min_netto_rente_j(opt_res: dict) -> float:
                    if not opt_res.get("jahresdaten"):
                        return float("inf")
                    renten_jahre = [
                        r for r in opt_res["jahresdaten"]
                        if r.get("Src_Gehalt", 0) == 0
                    ]
                    return min((r["Netto"] for r in renten_jahre), default=float("inf"))

                _netto_ka   = _opt_ka.get("bestes_netto", 0.0)
                _netto_rk   = _opt_rk.get("bestes_netto", 0.0)
                _netto_kein = _opt_keine.get("bestes_netto", 0.0)
                _min_ka     = _min_netto_rente_j(_opt_ka)
                _min_rk     = _min_netto_rente_j(_opt_rk)

                # Tabelle
                import pandas as _pd_cmp
                df_cmp = _pd_cmp.DataFrame({
                    "Option": [
                        "Keine Planung (Restschuld offen)",
                        "Kapitalanlage-Tilgung",
                        f"Ratenkredit ({anschluss_zins*100:.1f}%, {anschluss_lz}J.)",
                    ],
                    "Netto gesamt (€)": [
                        round(_netto_kein), round(_netto_ka), round(_netto_rk)
                    ],
                    "Diff. zu kein Plan (€)": [
                        0,
                        round(_netto_ka - _netto_kein),
                        round(_netto_rk - _netto_kein),
                    ],
                    "Min.-Netto Rentenphase (€/J)": [
                        "–",
                        _de(_min_ka) if _min_ka < float("inf") else "–",
                        _de(_min_rk) if _min_rk < float("inf") else "–",
                    ],
                    "Mindest-Netto erreicht?": [
                        "–",
                        "✅ Ja" if _min_ka >= _mindest_j else "❌ Nein",
                        "✅ Ja" if _min_rk >= _mindest_j else "❌ Nein",
                    ],
                })
                st.dataframe(df_cmp.set_index("Option"), use_container_width=True)

                # Empfehlung
                _ka_ok = _min_ka >= _mindest_j
                _rk_ok = _min_rk >= _mindest_j
                if _ka_ok and _rk_ok:
                    if _netto_ka >= _netto_rk:
                        st.success(
                            "**Empfehlung: Kapitalanlage-Tilgung.** "
                            "Beide Optionen erfüllen das Mindest-Netto; "
                            f"Kapitalanlage erzielt {_de(_netto_ka - _netto_rk)} € mehr über den Planungshorizont."
                        )
                    else:
                        st.success(
                            "**Empfehlung: Ratenkredit.** "
                            "Beide Optionen erfüllen das Mindest-Netto; "
                            f"Ratenkredit erzielt {_de(_netto_rk - _netto_ka)} € mehr "
                            "(Kapitalanlage erzielt höhere Rendite als Kreditzins)."
                        )
                elif _ka_ok and not _rk_ok:
                    st.success(
                        "**Empfehlung: Kapitalanlage-Tilgung.** "
                        "Nur diese Option hält das Mindest-Netto während der Ratenkredit-Laufzeit."
                    )
                elif _rk_ok and not _ka_ok:
                    st.warning(
                        "**Empfehlung: Ratenkredit.** "
                        "Die Kapitalanlage ist ggf. nicht groß genug – der Pool würde das verfügbare "
                        "Netto im Tilgungsjahr stark reduzieren."
                    )
                else:
                    st.error(
                        "**Keine Option erfüllt das Mindest-Netto.** "
                        "Mögliche Maßnahmen: Sondertilgungen erhöhen, Sparquote anpassen, "
                        "Renteneintritt verschieben oder Mindest-Netto reduzieren."
                    )

        # ── Jahresdetails ─────────────────────────────────────────────────────
        st.subheader("Jahresdetails")
        _min_j_jd = int(df_jd.index.min())
        _max_j_jd = int(df_jd.index.max())
        _def_j_jd = min(_max_j_jd, max(_min_j_jd, _profil_eo.eintritt_jahr))
        _sel_j = st.slider(
            "Betrachtungsjahr", _min_j_jd, _max_j_jd, _def_j_jd, key=f"rc{_rc}_eo_sel_jahr",
            help="Zeigt Monatswerte aus dem optimalen Auszahlungsplan für das gewählte Jahr.",
        )
        if _sel_j in df_jd.index:
            _jrow = df_jd.loc[_sel_j]
            jm1, jm2, jm3, jm4 = st.columns(4)
            jm1.metric(f"Brutto {_sel_j}", f"{_de(_jrow['Brutto'] / 12)} €/Mon.")
            jm2.metric(f"Netto {_sel_j}", f"{_de(_jrow['Netto'] / 12)} €/Mon.")
            jm3.metric(f"Steuer {_sel_j}", f"{_de(_jrow['Steuer'] / 12)} €/Mon.")
            jm4.metric(f"KV/PV {_sel_j}", f"{_de(_jrow['KV_PV'] / 12)} €/Mon.")
            if _jrow["Netto"] < 0:
                st.warning(
                    f"⚠️ Netto in {_sel_j} ist **negativ** ({_de(_jrow['Netto'] / 12)} €/Mon.)! "
                    "Die Ausgaben (Steuern, KV, Sonderausgaben) übersteigen die Einnahmen. "
                    "Kapitalanlage-Pool oder Einnahmen erhöhen, oder Ausgaben reduzieren."
                )
            if "KV_P2" in df_jd.columns and _jrow["KV_P2"] > 0:
                st.caption(
                    f"KV-Aufteilung: P1 {_de(_jrow['KV_P1'] / 12)} €/Mon. "
                    f"| P2 {_de(_jrow['KV_P2'] / 12)} €/Mon."
                )

        st.divider()

        # ── Steuer- und KV-Verlauf ────────────────────────────────────────────
        st.subheader("Steuer- und KV-Verlauf")
        fig_tax = go.Figure()
        fig_tax.add_trace(go.Bar(
            name="Progressivsteuer", x=df_jd.index, y=df_jd["Steuer_Progressiv"],
            marker_color="#EF9A9A",
            hovertemplate="%{x}: %{y:,.0f} €<extra>Progressivsteuer</extra>",
        ))
        if "Steuer_Abgeltung" in df_jd.columns:
            fig_tax.add_trace(go.Bar(
                name="Abgeltungsteuer", x=df_jd.index, y=df_jd["Steuer_Abgeltung"],
                marker_color="#FFCDD2",
                hovertemplate="%{x}: %{y:,.0f} €<extra>Abgeltungsteuer</extra>",
            ))
        _hat_p2_kv = "KV_P2" in df_jd.columns and df_jd["KV_P2"].sum() > 0
        if _hat_p2_kv:
            _kv_custom = [
                f"P1: {_de(r['KV_P1'])} €<br>P2: {_de(r['KV_P2'])} €"
                for _, r in df_jd.iterrows()
            ]
            fig_tax.add_trace(go.Bar(
                name="KV/PV", x=df_jd.index, y=df_jd["KV_PV"],
                marker_color="#FFF176",
                customdata=_kv_custom,
                hovertemplate="%{x}: %{y:,.0f} €<br><i>%{customdata}</i><extra>KV/PV</extra>",
            ))
        else:
            fig_tax.add_trace(go.Bar(
                name="KV/PV", x=df_jd.index, y=df_jd["KV_PV"],
                marker_color="#FFF176",
                hovertemplate="%{x}: %{y:,.0f} €<extra>KV/PV</extra>",
            ))
        fig_tax.add_trace(go.Scatter(
            name="zvE", x=df_jd.index, y=df_jd["zvE"],
            mode="lines", line=dict(color="#5C6BC0", width=2, dash="dot"),
            yaxis="y2",
            hovertemplate="%{x}: %{y:,.0f} € zvE<extra></extra>",
        ))
        if not _profil_eo.bereits_rentner:
            _vline_label_tax = "P1 Renteneintritt" if _profil2_eo else "Renteneintritt"
            fig_tax.add_vline(
                x=_profil_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#5C6BC0",
                annotation_text=_vline_label_tax, annotation_position="top right",
            )
        if _profil2_eo and not _profil2_eo.bereits_rentner:
            fig_tax.add_vline(
                x=_profil2_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#E91E63",
                annotation_text="P2 Renteneintritt", annotation_position="top left",
            )
        fig_tax.update_layout(
            barmode="stack", template="plotly_white", height=380,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
            yaxis2=dict(title="zvE (€)", tickformat=",.0f", overlaying="y",
                        side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=50, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_tax, use_container_width=True)

        # ── Gesamtbelastung Steuer + KV über Planungshorizont ─────────────────
        st.subheader(f"Gesamtbelastung über {horizon} Rentenjahre")
        _steuer_ges = df_jd["Steuer"].sum()
        _kv_ges     = df_jd["KV_PV"].sum()

        _ist_splitting = _ver_eo == "Zusammen"
        _steuer_p1_ges = _steuer_ges / 2 if (_ist_splitting and _profil2_eo) else _steuer_ges
        _steuer_p2_ges = _steuer_ges / 2 if (_ist_splitting and _profil2_eo) else 0.0

        if "KV_P1" in df_jd.columns and df_jd["KV_P1"].sum() > 0:
            _kv_p1_ges = df_jd["KV_P1"].sum()
            _kv_p2_ges = df_jd["KV_P2"].sum() if "KV_P2" in df_jd.columns else 0.0
        elif _profil2_eo:
            _kv_p1_ges = _kv_ges / 2
            _kv_p2_ges = _kv_ges / 2
        else:
            _kv_p1_ges = _kv_ges
            _kv_p2_ges = 0.0

        gb1, gb2, gb3 = st.columns(3)
        gb1.metric("Steuer P1 gesamt", f"{_de(_steuer_p1_ges)} €",
                   help="Progressiv- + Abgeltungsteuer Person 1 über den Planungshorizont.")
        gb2.metric("Steuer P2 gesamt", f"{_de(_steuer_p2_ges)} €",
                   help="Progressiv- + Abgeltungsteuer Person 2 über den Planungshorizont.")
        gb3.metric("Steuer gesamt", f"{_de(_steuer_ges)} €",
                   help="Progressiv- + Abgeltungsteuer gesamt über den Planungshorizont.")
        gb4, gb5, gb6 = st.columns(3)
        gb4.metric("KV/PV P1 gesamt", f"{_de(_kv_p1_ges)} €",
                   help="Kranken- + Pflegeversicherung Person 1 über den Planungshorizont.")
        gb5.metric("KV/PV P2 gesamt", f"{_de(_kv_p2_ges)} €",
                   help="Kranken- + Pflegeversicherung Person 2 über den Planungshorizont.")
        gb6.metric("KV/PV gesamt", f"{_de(_kv_ges)} €",
                   help="Kranken- + Pflegeversicherung gesamt über den Planungshorizont.")
        if _ist_splitting and _profil2_eo:
            st.caption("Steueraufteilung P1/P2: halbiert (Splitting; Steuerprogression nicht neu berechnet).")

        st.divider()

        # ── Top-10 Kombinationen ──────────────────────────────────────────────
        st.subheader("Top-10 Kombinationen")
        df_top = pd.DataFrame(opt["top10"]).set_index("Kombination")
        st.dataframe(df_top, use_container_width=True)

        with st.expander("Rohdaten – Jahresverlauf"):
            st.dataframe(df_jd, use_container_width=True)

        st.caption(
            "⚠️ Simulation auf Basis der Rechtslage 2024. "
            "Solidaritätszuschlag, Kirchensteuer (auf progressive ESt), Sparerpauschbetrag, "
            "Altersentlastungsbetrag (§ 24a EStG) und PV-Kinderstaffelung (§ 55 Abs. 3a SGB XI) "
            "sind berücksichtigt. "
            "Kirchensteuer auf Abgeltungsteuer sowie weitere individuelle Freibeträge "
            "sind nicht modelliert. Steuerberatung empfohlen."
        )

        st.divider()

        # ── O3c: Kapitalverzehr-Kalkulator ────────────────────────────────────
        with st.expander("💰 Kapitalverzehr-Kalkulator", expanded=False):
            auszahlung.render_section(_profil_eo, _ergebnis_eo)
