"""Rentenberechnungs-Engine – keine Streamlit-Abhängigkeit.

Alle Berechnungen sind Näherungen für Simulationszwecke.
Keine Haftung für steuerliche oder rechtliche Entscheidungen.
"""

from __future__ import annotations
from dataclasses import dataclass, replace
import numpy as np

# ── Konstanten ────────────────────────────────────────────────────────────────
RENTENWERT_2024 = 39.32        # €/Punkt West, Stand 01.07.2024
GRUNDFREIBETRAG_2024 = 11_604  # €
WERBUNGSKOSTEN_PAUSCHBETRAG = 102   # € Pauschbetrag für Rentner
SONDERAUSGABEN_PAUSCHBETRAG = 36    # €
AKTUELLES_JAHR = 2025


# ── Steuerformeln (§ 32a EStG Grundtarif 2024) ────────────────────────────────

def einkommensteuer(zvE: float) -> float:
    """Einkommensteuer nach Grundtarif 2024. zvE = zu versteuerndes Einkommen."""
    if zvE <= 11_604:
        return 0.0
    if zvE <= 17_005:
        y = (zvE - 11_604) / 10_000
        return (928.37 * y + 1_400) * y
    if zvE <= 66_760:
        z = (zvE - 17_005) / 10_000
        return (176.64 * z + 2_397) * z + 1_025.38
    if zvE <= 277_825:
        return 0.42 * zvE - 9_972.98
    return 0.45 * zvE - 18_307.73


def besteuerungsanteil(eintritt_jahr: int) -> float:
    """Besteuerungsanteil der gesetzlichen Rente nach § 22 Nr. 1 Satz 3 EStG (JStG 2022)."""
    if eintritt_jahr <= 2005:
        return 0.50
    if eintritt_jahr <= 2020:
        return min(0.50 + (eintritt_jahr - 2005) * 0.02, 0.80)
    if eintritt_jahr == 2021:
        return 0.81
    if eintritt_jahr == 2022:
        return 0.82
    # Ab 2023: nur noch +0,5 % p.a.
    return min(0.825 + (eintritt_jahr - 2023) * 0.005, 1.0)


# ── Datenprofil ───────────────────────────────────────────────────────────────

@dataclass
class Profil:
    geburtsjahr: int = 1970
    renteneintritt_alter: int = 67
    aktuelle_punkte: float = 25.0
    punkte_pro_jahr: float = 1.2
    zusatz_monatlich: float = 0.0      # bAV / Riester / Rürup – monatliche Auszahlung in Rente
    sparkapital: float = 50_000.0      # bereits angespartes Kapital
    sparrate: float = 500.0            # monatliche Sparrate bis Rente
    rendite_pa: float = 0.05           # Rendite auf Sparkapital p.a.
    rentenanpassung_pa: float = 0.02   # jährliche Rentenanpassung
    krankenversicherung: str = "GKV"   # "GKV" oder "PKV"
    pkv_beitrag: float = 500.0         # €/Monat, nur bei PKV
    gkv_zusatzbeitrag: float = 0.017   # kassenindividueller Zusatzbeitrag
    kinder: bool = True

    @property
    def aktuelles_alter(self) -> int:
        return AKTUELLES_JAHR - self.geburtsjahr

    @property
    def eintritt_jahr(self) -> int:
        return self.geburtsjahr + self.renteneintritt_alter

    @property
    def jahre_bis_rente(self) -> int:
        return max(0, self.renteneintritt_alter - self.aktuelles_alter)


# ── Ergebnis-Dataclass ────────────────────────────────────────────────────────

@dataclass
class RentenErgebnis:
    brutto_monatlich: float
    steuer_monatlich: float
    kv_monatlich: float
    netto_monatlich: float
    kapital_bei_renteneintritt: float
    besteuerungsanteil: float
    effektiver_steuersatz: float
    gesamtpunkte: float
    brutto_gesetzlich: float
    rentenwert_angepasst: float
    zvE_jahres: float
    jahressteuer: float


# ── Kernberechnungen ──────────────────────────────────────────────────────────

def kapitalwachstum(kapital: float, sparrate: float, rendite_pa: float, jahre: int) -> float:
    """Endkapital nach `jahre` Jahren mit monatlicher Sparrate und Zinseszins."""
    if jahre <= 0:
        return kapital
    monate = jahre * 12
    r_m = rendite_pa / 12
    endwert = kapital * (1 + rendite_pa) ** jahre
    if r_m > 0:
        endwert += sparrate * ((1 + r_m) ** monate - 1) / r_m
    else:
        endwert += sparrate * monate
    return endwert


def berechne_rente(p: Profil) -> RentenErgebnis:
    # Gesetzliche Rente
    gesamtpunkte = p.aktuelle_punkte + p.punkte_pro_jahr * p.jahre_bis_rente
    rentenwert = RENTENWERT_2024 * (1 + p.rentenanpassung_pa) ** p.jahre_bis_rente
    brutto_gesetzlich = gesamtpunkte * rentenwert
    brutto_total = brutto_gesetzlich + p.zusatz_monatlich

    # Sparkapital
    kapital = kapitalwachstum(p.sparkapital, p.sparrate, p.rendite_pa, p.jahre_bis_rente)

    # Einkommensteuer
    ba = besteuerungsanteil(p.eintritt_jahr)
    zvE = max(
        0.0,
        brutto_total * 12 * ba
        - WERBUNGSKOSTEN_PAUSCHBETRAG
        - SONDERAUSGABEN_PAUSCHBETRAG,
    )
    jahressteuer = einkommensteuer(zvE)
    steuer_monatlich = jahressteuer / 12

    # Krankenversicherung
    if p.krankenversicherung == "PKV":
        kv = p.pkv_beitrag
    else:
        kv_satz = 0.073 + p.gkv_zusatzbeitrag / 2
        pv_satz = 0.034 if p.kinder else 0.040
        kv = brutto_total * (kv_satz + pv_satz)

    netto = brutto_total - steuer_monatlich - kv
    eff_st = steuer_monatlich / brutto_total if brutto_total > 0 else 0.0

    return RentenErgebnis(
        brutto_monatlich=brutto_total,
        steuer_monatlich=steuer_monatlich,
        kv_monatlich=kv,
        netto_monatlich=netto,
        kapital_bei_renteneintritt=kapital,
        besteuerungsanteil=ba,
        effektiver_steuersatz=eff_st,
        gesamtpunkte=gesamtpunkte,
        brutto_gesetzlich=brutto_gesetzlich,
        rentenwert_angepasst=rentenwert,
        zvE_jahres=zvE,
        jahressteuer=jahressteuer,
    )


def simuliere_szenarien(p: Profil) -> dict[str, RentenErgebnis]:
    """Pessimistisch / Neutral / Optimistisch – Rentenanpassung und Kapitalrendite."""
    return {
        "Pessimistisch": berechne_rente(replace(p, rentenanpassung_pa=0.01, rendite_pa=0.03)),
        "Neutral":       berechne_rente(replace(p, rentenanpassung_pa=p.rentenanpassung_pa,
                                                    rendite_pa=p.rendite_pa)),
        "Optimistisch":  berechne_rente(replace(p, rentenanpassung_pa=0.03, rendite_pa=0.07)),
    }


# ── Vorsorge-Bausteine ────────────────────────────────────────────────────────

@dataclass
class VorsorgeProdukt:
    id: str
    typ: str            # "bAV" | "PrivateRente" | "Riester" | "LV"
    name: str
    kapital: float      # Kapitalwert bei Renteneintritt (Einmalauszahlung)
    monatsrente: float  # Monatliche Rente laut Versicherungsangebot (0 = unbekannt)
    laufzeit_jahre: int # 0 = lebenslang (= Horizont), sonst befristete Laufzeit

    @property
    def ist_lebensversicherung(self) -> bool:
        return self.typ == "LV"


def _annuitaet(kapital: float, rendite_pa: float, jahre: int) -> float:
    """Monatliche Entnahme-Annuität: Kapital wird über `jahre` aufgebraucht."""
    if jahre <= 0 or kapital <= 0:
        return 0.0
    r_m = rendite_pa / 12
    n = jahre * 12
    if r_m > 0:
        return kapital * r_m / (1 - (1 + r_m) ** (-n))
    return kapital / n


def vergleiche_produkt(
    produkt: VorsorgeProdukt,
    rendite_pa: float,
    horizon_jahre: int,
) -> dict:
    """
    Vergleicht Einmal / Monatlich / Kombiniert für ein Produkt.

    Rückgabe je Szenario: {'monatlich': float, 'total': float}
    Zusätzlich: 'bestes' (Schlüssel des besten Szenarios),
                'kombiniert_anteil' (optimaler Kapitalanteil 0–1).
    """
    H = horizon_jahre
    K = produkt.kapital
    M = produkt.monatsrente if produkt.monatsrente > 0 else _annuitaet(K, rendite_pa, H)
    lz = produkt.laufzeit_jahre if produkt.laufzeit_jahre > 0 else H
    effective_lz = min(lz, H)

    # Einmalauszahlung: K investieren, als Annuität über H Jahre entnehmen
    m_einmal = _annuitaet(K, rendite_pa, H)
    t_einmal = m_einmal * 12 * H

    # Monatliche Rente (Versicherer / eigene Berechnung)
    t_monatlich = M * 12 * effective_lz
    m_monatlich = M

    # Kombiniert: optimalen Kapitalanteil x suchen
    if not produkt.ist_lebensversicherung and produkt.monatsrente > 0:
        xs = np.linspace(0.0, 1.0, 101)
        totale = [
            _annuitaet(K * x, rendite_pa, H) * 12 * H
            + M * (1 - x) * 12 * effective_lz
            for x in xs
        ]
        best_idx = int(np.argmax(totale))
        best_x = float(xs[best_idx])
        t_komb = float(totale[best_idx])
        m_komb = _annuitaet(K * best_x, rendite_pa, H) + M * (1 - best_x)
    else:
        best_x = 1.0
        t_komb = t_einmal
        m_komb = m_einmal

    if produkt.ist_lebensversicherung or produkt.monatsrente <= 0:
        bestes = "einmal"
    else:
        bestes = max(
            {"einmal": t_einmal, "monatlich": t_monatlich, "kombiniert": t_komb},
            key=lambda k: {"einmal": t_einmal, "monatlich": t_monatlich, "kombiniert": t_komb}[k],
        )

    return {
        "einmal":     {"monatlich": m_einmal,    "total": t_einmal},
        "monatlich":  {"monatlich": m_monatlich, "total": t_monatlich},
        "kombiniert": {"monatlich": m_komb,      "total": t_komb, "anteil": best_x},
        "bestes": bestes,
    }


def kapital_vs_rente(kapital: float, rendite_pa: float, laufzeit_jahre: int) -> dict:
    """Monatliche Annuität und Kapitalverlauf bei Verzehr über `laufzeit_jahre`."""
    r_m = rendite_pa / 12
    n = max(1, laufzeit_jahre * 12)
    if r_m > 0:
        monatsrate = kapital * r_m / (1 - (1 + r_m) ** (-n))
    else:
        monatsrate = kapital / n
    verlauf = []
    k = kapital
    for i in range(n + 1):
        verlauf.append({"Monat": i, "Kapital": max(0.0, k)})
        k = k * (1 + r_m) - monatsrate
    return {
        "monatsrate": monatsrate,
        "verlauf": verlauf,
        "gesamtauszahlung": monatsrate * n,
    }
