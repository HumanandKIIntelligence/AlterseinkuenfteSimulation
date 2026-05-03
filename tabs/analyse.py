"""Profil-Analyse: regelbasierte Hinweise und Warnungen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from engine import Profil, RentenErgebnis

from engine import (
    AKTUELLES_JAHR, GRUNDSICHERUNG_SCHWELLE,
    kapitalwachstum, regelaltersgrenze,
)

_WARN = "warning"
_ERR  = "error"
_INFO = "info"
_OK   = "success"
_ICONS = {_ERR: "🔴", _WARN: "🟡", _INFO: "🔵", _OK: "🟢"}


@dataclass
class Hinweis:
    typ:   str
    titel: str
    text:  str

    @property
    def icon(self) -> str:
        return _ICONS.get(self.typ, "⚪")


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ── Checks pro Person ────────────────────────────────────────────────────────

def _analyse_person(
    profil: "Profil",
    ergebnis: "RentenErgebnis",
    label: str,
    mieteinnahmen: float,
    hat_partner: bool,
    rc: int,
) -> list[Hinweis]:
    ss = st.session_state
    _lhk_key = "p2_lhk" if label == "Person 2" else "p1_lhk"
    _lhk = float(ss.get(f"rc{rc}_{_lhk_key}", 0.0))
    _fixausgaben = list(ss.get("hh_fixausgaben", []))
    _fix_eintritt = sum(
        fa["betrag_monatlich"] for fa in _fixausgaben
        if fa["startjahr"] <= profil.eintritt_jahr <= fa["endjahr"]
    )
    _netto = ergebnis.netto_monatlich
    _brutto_g = profil.aktuelles_brutto_monatlich
    hinweise: list[Hinweis] = []

    # 1. Grundsicherungsrisiko
    if 0 < _netto < GRUNDSICHERUNG_SCHWELLE:
        hinweise.append(Hinweis(_ERR, "Grundsicherungsrisiko",
            f"Nettorente **{_de(_netto)} €/Mon.** liegt unter der Grundsicherungsschwelle "
            f"(ca. {_de(GRUNDSICHERUNG_SCHWELLE)} €/Mon., § 41 SGB XII). "
            f"Mögliche Maßnahmen: späterer Renteneintritt, höhere Sparrate, "
            f"Vorsorgeprodukt ergänzen oder Mieteinnahmen erschließen."))

    # 2. Versorgungslücke
    if not profil.bereits_rentner and _brutto_g > 0:
        _netto_quote = _netto / _brutto_g
        if _netto_quote < 0.65:
            hinweise.append(Hinweis(_WARN, "Hohe Versorgungslücke",
                f"Nettorente **{_de(_netto)} €/Mon.** = nur **{_netto_quote:.0%}** "
                f"des heutigen Bruttogehalts ({_de(_brutto_g)} €/Mon.). "
                f"Lücke: **{_de(_brutto_g - _netto)} €/Mon.** "
                f"Zusatzvorsorge (bAV, Rürup, ETF-Sparplan) prüfen."))

    # 3. Fixausgaben nahe an Nettorente
    _gesamt_fix = _lhk + _fix_eintritt
    if _gesamt_fix > 0 and _netto > 0 and _gesamt_fix >= _netto * 0.85:
        hinweise.append(Hinweis(_ERR, "Fixausgaben decken fast die gesamte Nettorente",
            f"Lebenshaltungskosten + Fixausgaben: **{_de(_gesamt_fix)} €/Mon.** "
            f"({_gesamt_fix / _netto:.0%} der Nettorente). "
            f"Kaum freies Einkommen – Ausgaben oder Einnahmen überprüfen."))

    # 4. Rentenabschlag
    if ergebnis.rentenabschlag > 0:
        _abschlag_euro = (
            ergebnis.brutto_gesetzlich / (1 - ergebnis.rentenabschlag)
            * ergebnis.rentenabschlag
        )
        _rag = regelaltersgrenze(profil.geburtsjahr)
        hinweise.append(Hinweis(_WARN, "Dauerhafter Rentenabschlag durch Frühverrentung",
            f"Renteneintritt mit **{profil.renteneintritt_alter} Jahren** – "
            f"Regelaltersgrenze: **{_rag:.4g} Jahre**. "
            f"Lebenslanger Abschlag: **{ergebnis.rentenabschlag:.1%}** "
            f"(≈ **{_de(_abschlag_euro)} €/Mon.**). "
            f"Jeden Monat früher kostet 0,3 % (§ 77 SGB VI)."))

    # 5. Hoher Besteuerungsanteil
    _ba = ergebnis.besteuerungsanteil
    if _ba >= 0.85 and not profil.ist_pensionaer:
        hinweise.append(Hinweis(_INFO, "Hoher Besteuerungsanteil der Rente",
            f"**{_ba:.0%}** der gesetzlichen Rente sind steuerpflichtig "
            f"(Renteneintritt {profil.eintritt_jahr}, § 22 EStG / JStG 2022). "
            f"Sonderausgaben (z.B. Rürup-Beiträge) oder Freibeträge prüfen."))

    # 6. Keine Vorsorgeprodukte bei langem Horizont
    _vp_person = [
        p for p in ss.get("vp_produkte", [])
        if p.get("person", "Person 1") == label
    ]
    _horizont = profil.jahre_bis_rente if not profil.bereits_rentner else 0
    if not profil.bereits_rentner and _horizont >= 5 and not _vp_person and profil.zusatz_monatlich == 0:
        hinweise.append(Hinweis(_WARN, "Keine Vorsorgeprodukte konfiguriert",
            f"Noch **{_horizont} Jahre** bis zur Rente, aber keine Vorsorge "
            f"(bAV, Rürup, Riester, ETF …) hinterlegt. "
            f"Tab **Vorsorge-Bausteine** nutzen, um Produkte zu erfassen."))

    # 7. Rentenanpassung 0 %
    if profil.rentenanpassung_pa == 0.0 and not profil.ist_pensionaer:
        hinweise.append(Hinweis(_INFO, "Rentenanpassung auf 0 % gesetzt",
            f"Sehr konservative Annahme – historisch ~1–2 % p.a. (DRV West). "
            f"Tab **Simulation** zeigt Szenarien mit realistischeren Werten."))

    # 8. Keine Sparrate und kaum Kapital
    if (
        not profil.bereits_rentner
        and _horizont >= 10
        and profil.sparrate == 0
        and profil.sparkapital < 10_000
        and not profil.ist_pensionaer
    ):
        _sim_kapital = kapitalwachstum(0, 100, 0.05, _horizont)
        hinweise.append(Hinweis(_WARN, "Keine Sparrate und kaum Kapital",
            f"Noch **{_horizont} Jahre** bis zur Rente, Sparrate = 0 € und "
            f"Sparkapital < 10.000 €. Schon **100 €/Mon.** bei 5 % Rendite "
            f"ergeben **{_de(_sim_kapital)} €** nach {_horizont} Jahren."))

    # 9. Hohe PKV-Beiträge
    if profil.krankenversicherung == "PKV" and _netto > 0 and ergebnis.kv_monatlich > 0:
        _pkv_anteil = ergebnis.kv_monatlich / _netto
        if _pkv_anteil > 0.15:
            hinweise.append(Hinweis(_WARN, "PKV-Beitrag hoch relativ zur Nettorente",
                f"PKV-Beitrag **{_de(ergebnis.kv_monatlich)} €/Mon.** = "
                f"**{_pkv_anteil:.0%}** der Nettorente. "
                f"Standard- oder Basistarif (§ 152 VAG) prüfen."))

    # 10. Hypothek läuft in den Ruhestand
    _hyp = ss.get("hyp_daten")
    if _hyp and _hyp.get("aktiv") and not profil.bereits_rentner:
        _hyp_ende = int(_hyp.get("endjahr", 0))
        if _hyp_ende > profil.eintritt_jahr:
            _rest_jahre = _hyp_ende - profil.eintritt_jahr
            hinweise.append(Hinweis(_WARN, "Hypothek läuft in den Ruhestand hinein",
                f"Hypothek endet **{_hyp_ende}** – "
                f"**{_rest_jahre} Jahr{'e' if _rest_jahre != 1 else ''} nach** "
                f"Renteneintritt ({profil.eintritt_jahr}). "
                f"Raten belasten das Rentenbudget. Sondertilgungen prüfen."))

    # 11. Niedrige Rentenpunkte
    if not profil.ist_pensionaer and not profil.bereits_rentner:
        _ep = ergebnis.gesamtpunkte
        if _ep < 30:
            hinweise.append(Hinweis(_WARN, "Niedrige Entgeltpunkte",
                f"Prognostizierte Entgeltpunkte: **{_ep:.1f}** "
                f"(empfohlen: ≥ 35 für solide gesetzliche Rente). "
                f"Mögliche Ursachen: niedrigeres Gehalt, kurze Beitragszeiten, Teilzeit. "
                f"Freiwillige Beiträge (§ 197 SGB VI) oder Zusatzvorsorge prüfen."))

    return hinweise


# ── Checks für den Haushalt ──────────────────────────────────────────────────

def _analyse_haushalt(
    profil: "Profil",
    ergebnis: "RentenErgebnis",
    profil2: "Profil",
    ergebnis2: "RentenErgebnis",
    veranlagung: str,
    hh: dict,
) -> list[Hinweis]:
    hinweise: list[Hinweis] = []

    # 12. Splitting-Vorteil
    _split = hh.get("steuerersparnis_splitting", 0.0)
    if veranlagung == "Zusammen" and _split > 20:
        hinweise.append(Hinweis(_OK, "Splitting-Vorteil aktiv",
            f"Zusammenveranlagung spart **{_de(_split)} €/Mon.** "
            f"(**{_de(_split * 12)} €/Jahr**) gegenüber getrennter Veranlagung "
            f"(§ 32a Abs. 5 EStG)."))
    elif veranlagung == "Getrennt":
        _diff = abs(ergebnis.zvE_jahres - ergebnis2.zvE_jahres)
        if _diff > 10_000:
            hinweise.append(Hinweis(_WARN, "Splitting-Vorteil wird nicht genutzt",
                f"Einkommensunterschied P1 vs. P2: **{_de(_diff)} €/Jahr**. "
                f"Zusammenveranlagung könnte Steuer spürbar senken – "
                f"im Dashboard unter **Zusammen** prüfen."))

    # 13. Beide ohne Vorsorge
    _vp_alle = st.session_state.get("vp_produkte", [])
    if (
        not _vp_alle
        and profil.zusatz_monatlich == 0
        and ergebnis2.brutto_monatlich < 200
        and not profil.bereits_rentner
        and not profil2.bereits_rentner
    ):
        hinweise.append(Hinweis(_WARN, "Haushalt ohne Vorsorgeprodukte",
            f"Weder Person 1 noch Person 2 haben Vorsorgeprodukte erfasst. "
            f"Tab **Vorsorge-Bausteine** nutzen für gemeinsame Vorsorgestrategie."))

    return hinweise


# ── Öffentliche Render-Funktion ───────────────────────────────────────────────

def render_analyse(
    profil: "Profil",
    ergebnis: "RentenErgebnis",
    label: str = "Person 1",
    profil2: "Profil | None" = None,
    ergebnis2: "RentenErgebnis | None" = None,
    veranlagung: str = "Getrennt",
    mieteinnahmen: float = 0.0,
    hh: dict | None = None,
    rc: int = 0,
) -> None:
    hat_partner = profil2 is not None and ergebnis2 is not None

    hinweise = _analyse_person(profil, ergebnis, label, mieteinnahmen, hat_partner, rc)
    if hat_partner and hh is not None:
        hinweise += _analyse_haushalt(
            profil, ergebnis, profil2, ergebnis2, veranlagung, hh
        )

    _order = {_ERR: 0, _WARN: 1, _INFO: 2, _OK: 3}
    hinweise.sort(key=lambda h: _order.get(h.typ, 9))

    _n_kritisch = sum(1 for h in hinweise if h.typ == _ERR)
    _n_warn     = sum(1 for h in hinweise if h.typ == _WARN)
    _n_ok       = sum(1 for h in hinweise if h.typ == _OK)

    _badge = ""
    if _n_kritisch:
        _badge += f" · {_n_kritisch} Kritisch"
    if _n_warn:
        _badge += f" · {_n_warn} Hinweis{'e' if _n_warn != 1 else ''}"
    if _n_ok:
        _badge += f" · {_n_ok} OK"

    _expanded = _n_kritisch > 0 or _n_warn > 0

    with st.expander(f"🔍 Profil-Analyse{_badge}", expanded=_expanded):
        if not hinweise:
            st.success("✅ Keine Auffälligkeiten gefunden.")
            return
        for h in hinweise:
            msg = f"**{h.icon} {h.titel}**\n\n{h.text}"
            if h.typ == _ERR:
                st.error(msg)
            elif h.typ == _WARN:
                st.warning(msg)
            elif h.typ == _OK:
                st.success(msg)
            else:
                st.info(msg)
