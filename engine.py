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
REGELALTERSGRENZE = 67         # Jahrgänge ab 1964 (§ 35 SGB VI)
ABSCHLAG_PRO_MONAT = 0.003     # 0,3 % je Monat Frühverrentung (§ 77 SGB VI)

# KV/PV-Konstanten 2024 (§ 226 Abs. 2 SGB V, § 223 Abs. 3 SGB V)
BAV_FREIBETRAG_MONATLICH   = 187.25    # Freibetrag Versorgungsbezüge (nur KVdR-Pflichtmitglieder)
BBG_KV_MONATLICH           = 5_175.0   # Beitragsbemessungsgrenze KV/PV 2024
SPARERPAUSCHBETRAG         = 1_000     # € pro Person (§ 20 Abs. 9 EStG 2024)
# Mindestbemessungsgrundlage freiwillig Versicherte §240 Abs. 4 SGB V (2024)
# = 1/90 der monatlichen Bezugsgröße West (3.535 €) × 27,85 ≈ 1.096,67 €
MINDEST_BMG_FREIWILLIG_MONO = 1_096.67

# Versorgungsfreibetrag § 19 Abs. 2 EStG – für Beamtenpensionen
# Format: Versorgungsbeginn-Jahr → (Anteil, MaxBetrag_€, Zuschlag_€)
# 2005–2020: Absenkung je -1,6 % / -120 € / -36 € pro Jahr
# 2021–2039: Absenkung je -0,8 % / -60 € / -18 € pro Jahr; ab 2040: 0
_VFB_2005 = (0.40, 3_000, 900)
_VFB_SCHRITT_A = (0.016, 120, 36)   # 2006–2020
_VFB_SCHRITT_B = (0.008,  60, 18)   # 2021–2039

# Altersentlastungsbetrag § 24a EStG – für Steuerpflichtige ab 64 Jahren
# Erstjahr = geburtsjahr + 65 (Veranlagungszeitraum nach Vollendung des 64. Lebensjahrs)
# 2005: 40 %/1.900 €; 2006–2020: −1,6 %/−76 €/Jahr; 2021–2039: −0,8 %/−38 €/Jahr; ab 2040: 0
_AEB_2005      = (0.40, 1_900)
_AEB_SCHRITT_A = (0.016,   76)      # 2006–2020
_AEB_SCHRITT_B = (0.008,   38)      # 2021–2039


def versorgungsfreibetrag(ruhestand_jahr: int, pension_jahres: float) -> float:
    """Versorgungsfreibetrag § 19 Abs. 2 EStG 2024 für Beamtenpensionen.

    Gibt den vom Bruttobezug abzuziehenden Freibetragsbetrag zurück.
    Bei Versorgungsbeginn ab 2040: 0 €.
    """
    j = max(2005, ruhestand_jahr)
    if j >= 2040:
        return 0.0
    if j <= 2005:
        anteil, max_betrag, zuschlag = _VFB_2005
    elif j <= 2020:
        n = j - 2005
        anteil    = _VFB_2005[0] - n * _VFB_SCHRITT_A[0]
        max_betrag = _VFB_2005[1] - n * _VFB_SCHRITT_A[1]
        zuschlag   = _VFB_2005[2] - n * _VFB_SCHRITT_A[2]
    else:
        # Wert für 2020 als Ausgangsbasis
        anteil_2020    = _VFB_2005[0] - 15 * _VFB_SCHRITT_A[0]   # = 0.16
        max_betrag_2020 = _VFB_2005[1] - 15 * _VFB_SCHRITT_A[1]  # = 1200
        zuschlag_2020   = _VFB_2005[2] - 15 * _VFB_SCHRITT_A[2]  # = 360
        n = j - 2020
        anteil    = anteil_2020    - n * _VFB_SCHRITT_B[0]
        max_betrag = max_betrag_2020 - n * _VFB_SCHRITT_B[1]
        zuschlag   = zuschlag_2020   - n * _VFB_SCHRITT_B[2]
    return max(0.0, min(pension_jahres * anteil, float(max_betrag)) + zuschlag)


def altersentlastungsbetrag(
    geburtsjahr: int,
    qualifying_jahres: float,
    bereits_genutzt: float = 0.0,
) -> float:
    """Altersentlastungsbetrag § 24a EStG.

    Qualifizierendes Einkommen: Arbeitslohn (§ 19, kein Versorgungsbezug), Ertragsanteil
    PrivateRente (§ 22 Nr. 1 S. 3a bb), Riester (§ 22 Nr. 5), BUV/DUV-Ertragsanteil,
    Mieteinnahmen (§ 21).
    Nicht qualifizierend: GRV (§ 22 Nr. 1 S. 3a aa), Rürup, bAV, Beamtenpension (§ 19 Abs. 2).
    bereits_genutzt: Bereits beanspruchter Betrag (für berechne_haushalt Cap-Schutz).
    """
    erstjahr = geburtsjahr + 65
    if erstjahr >= 2040:
        return 0.0
    if erstjahr <= 2005:
        anteil, max_betrag = _AEB_2005
    elif erstjahr <= 2020:
        n = erstjahr - 2005
        anteil    = _AEB_2005[0] - n * _AEB_SCHRITT_A[0]
        max_betrag = _AEB_2005[1] - n * _AEB_SCHRITT_A[1]
    else:
        n = erstjahr - 2020
        anteil    = max(0.0, (_AEB_2005[0] - 15 * _AEB_SCHRITT_A[0]) - n * _AEB_SCHRITT_B[0])
        max_betrag = max(0.0, (_AEB_2005[1] - 15 * _AEB_SCHRITT_A[1]) - n * _AEB_SCHRITT_B[1])
    remaining = max(0.0, max_betrag - bereits_genutzt)
    return min(qualifying_jahres * anteil, remaining)


# Ertragsanteil-Tabelle § 22 Nr. 1 S. 3a bb EStG (Anlage, vollständige gesetzliche Tabelle)
_ERTRAGSANTEIL: dict[int, int] = {
    0: 59, 1: 59, 2: 58, 3: 58, 4: 57, 5: 57, 6: 56, 7: 56, 8: 56,
    9: 55, 10: 55, 11: 54, 12: 54, 13: 53, 14: 53, 15: 52, 16: 52,
    17: 51, 18: 51, 19: 50, 20: 50, 21: 49, 22: 49, 23: 48, 24: 48,
    25: 47, 26: 47, 27: 46, 28: 45, 29: 45, 30: 44, 31: 44, 32: 43,
    33: 42, 34: 42, 35: 41, 36: 40, 37: 40, 38: 39, 39: 38, 40: 38,
    41: 37, 42: 36, 43: 35, 44: 35, 45: 34, 46: 33, 47: 33, 48: 32,
    49: 31, 50: 30, 51: 29, 52: 29, 53: 28, 54: 27, 55: 26, 56: 26,
    57: 25, 58: 24, 59: 23, 60: 22, 61: 22, 62: 21, 63: 20, 64: 19,
    65: 18, 66: 18, 67: 17, 68: 16, 69: 15, 70: 15, 71: 14, 72: 13,
    73: 13, 74: 12, 75: 11, 76: 10, 77: 10, 78: 9,  79: 9,  80: 8,
    81: 7,  82: 7,  83: 6,  84: 6,  85: 5,  86: 5,  87: 5,
    88: 4,  89: 4,  90: 4,  91: 4,  92: 3,  93: 3,
    94: 2,  95: 2,  96: 2,
}


def ertragsanteil(alter: int) -> float:
    """Ertragsanteil einer Leibrente (§ 22 Nr. 1 S. 3a bb EStG) als Dezimalzahl."""
    if alter < 0:
        return 0.59
    return _ERTRAGSANTEIL.get(alter, 1) / 100


def _pv_satz(kinder_anzahl: int) -> tuple[float, float]:
    """PV-Beitragssatz § 55 Abs. 1 und 3a SGB XI 2024. Returns (pv_voll, pv_halb).

    0 Kinder: Kinderlosenzuschlag 0,6 % trägt Versicherter allein (4,0 % / 2,3 %).
    1 Kind: Basissatz 3,4 % / 1,7 %. Ab 2. Kind: −0,25 % je Kind auf eigenen Anteil.
    """
    n = max(0, min(kinder_anzahl, 5))
    if n == 0:
        return 0.040, 0.023
    abschlag = (n - 1) * 0.0025
    return round(0.034 - abschlag, 4), round(0.017 - abschlag, 4)


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


def solidaritaetszuschlag(est: float) -> float:
    """Solidaritätszuschlag 2024. Freigrenze 17.543 € ESt; Gleitzone bis 33.912 €."""
    if est <= 17_543:
        return 0.0
    soli_voll = 0.055 * est
    if est <= 33_912:
        return min(soli_voll, 0.20 * (est - 17_543))
    return soli_voll


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
    kinder_anzahl: int = 1          # Anzahl Kinder (PV-Kinderstaffelung § 55 Abs. 3a SGB XI)

    zusatz_typ: str = "bAV"   # "bAV" | "Riester" | "Rürup" | "PrivateRente"

    # Ruhestand-Status
    ist_pensionaer:            bool  = False  # Beamter → § 19 EStG Versorgungsfreibetrag
    bereits_rentner:           bool  = False  # Rente/Pension wird bereits bezogen
    rentenbeginn_jahr:         int   = 2025   # Nur wenn bereits_rentner=True
    aktuelles_brutto_monatlich: float = 0.0   # Aktuelle/erwartete Brutto-Rente/Pension €/Mon.

    # Dienstunfähigkeitsversicherung (nur relevant wenn ist_pensionaer=True)
    duv_monatlich: float = 0.0    # Monatsrente aus DUV (§ 22 Nr. 1 S. 3a bb EStG, kein KVdR)
    duv_endjahr:   int   = 2040   # DUV läuft bis einschließlich dieses Jahres

    # Private Berufsunfähigkeitsversicherung (für Nicht-Beamte)
    # Steuerpflichtig mit Ertragsanteil § 22 Nr. 1 S. 3a bb EStG;
    # NICHT KVdR-pflichtig (private Versicherung, § 229 SGB V nicht anwendbar)
    buv_monatlich: float = 0.0    # Monatsrente aus privater BUV
    buv_endjahr:   int   = 2040   # BUV läuft bis einschließlich dieses Jahres

    # KV-Status im Rentenalter (§ 5 Abs. 1 Nr. 11 SGB V vs. §240 SGB V)
    # True  = KVdR-Pflichtmitglied: nur §229-Einkünfte beitragspflichtig
    # False = freiwillig GKV: ALLE Einnahmen inkl. Kapitalerträge/Mieten beitragspflichtig
    kvdr_pflicht: bool = True

    # Kirchensteuer (§ 51a EStG)
    kirchensteuer: bool = False         # Kirchensteuerpflicht
    kirchensteuer_satz: float = 0.09    # 9 % allgemein; 8 % Bayern + Baden-Württemberg

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
    rentenabschlag: float = 0.0            # Kürzungsfaktor gesetzl. Rente (0 = kein Abschlag)
    kv_gkv_monatlich: float = 0.0         # GKV-Anteil (Krankenkasse, ohne PV)
    kv_pv_monatlich: float = 0.0          # PV-Anteil (Pflegekasse)
    kirchensteuer_monatlich: float = 0.0  # Kirchensteuer (in steuer_monatlich enthalten)
    altersentlastungsbetrag_jahres: float = 0.0  # genutzter AEB § 24a EStG (Cap für berechne_haushalt)


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


def berechne_rente(p: Profil) -> RentenErgebnis:  # noqa: C901
    """Berechnet Brutto, Steuer, KV und Netto-Monatseinkommen.

    Fallunterscheidung:
    - Standard GRV: Rentenpunkte × Rentenwert, Besteuerungsanteil § 22 Nr. 1 EStG
    - Pensionär (Beamter): direkte Pensionseingabe, Versorgungsfreibetrag § 19 Abs. 2 EStG,
      volle KV-Basis (kein Freibetrag wie bei bAV, § 229 Abs. 1 Nr. 1 SGB V)
    - Bereits im Ruhestand: direkte Eingabe, kein Ansparzeitraum mehr
    """
    abschlag     = 0.0
    gesamtpunkte = 0.0
    rentenwert   = RENTENWERT_2024

    # ── Einkommensberechnung ──────────────────────────────────────────────────
    if p.bereits_rentner:
        # Rente wird bereits bezogen: direkte Bruttoeingabe, kein Ansparen
        brutto_gesetzlich = p.aktuelles_brutto_monatlich
        kapital           = p.sparkapital
        rentenbeginn      = p.rentenbeginn_jahr
    elif p.ist_pensionaer:
        # Beamter noch aktiv: erwartete Bruttopension direkt eingegeben
        brutto_gesetzlich = p.aktuelles_brutto_monatlich
        kapital           = kapitalwachstum(p.sparkapital, p.sparrate, p.rendite_pa,
                                            p.jahre_bis_rente)
        rentenbeginn      = p.eintritt_jahr
    else:
        # Standard GRV
        gesamtpunkte  = p.aktuelle_punkte + p.punkte_pro_jahr * p.jahre_bis_rente
        rentenwert    = RENTENWERT_2024 * (1 + p.rentenanpassung_pa) ** p.jahre_bis_rente
        monate_frueh  = max(0, (REGELALTERSGRENZE - p.renteneintritt_alter) * 12)
        abschlag      = monate_frueh * ABSCHLAG_PRO_MONAT
        brutto_gesetzlich = gesamtpunkte * rentenwert * (1.0 - abschlag)
        kapital       = kapitalwachstum(p.sparkapital, p.sparrate, p.rendite_pa,
                                        p.jahre_bis_rente)
        rentenbeginn  = p.eintritt_jahr

    brutto_total = brutto_gesetzlich + p.zusatz_monatlich

    # Alter bei Rentenbeginn (für Ertragsanteil PrivateRente / DUV)
    alter_rente = (p.rentenbeginn_jahr - p.geburtsjahr) if p.bereits_rentner \
        else p.renteneintritt_alter

    # Zusatzrente → zvE (typ-abhängig; bAV default für Sidebar ohne Typangabe)
    if p.zusatz_typ == "PrivateRente":
        zusatz_zvE = p.zusatz_monatlich * 12 * ertragsanteil(alter_rente)
    else:
        zusatz_zvE = p.zusatz_monatlich * 12

    # DUV: Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; nicht KVdR-pflichtig
    duv_monatl = 0.0
    duv_zvE_j  = 0.0
    if p.ist_pensionaer and p.duv_monatlich > 0 and rentenbeginn <= p.duv_endjahr:
        duv_monatl = p.duv_monatlich
        alter_duv  = AKTUELLES_JAHR - p.geburtsjahr   # Alter ca. bei DU-Beginn
        duv_zvE_j  = duv_monatl * 12 * ertragsanteil(alter_duv)

    # BUV (Nicht-Beamte): Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; nicht KVdR-pflichtig
    buv_monatl = 0.0
    buv_zvE_j  = 0.0
    if not p.ist_pensionaer and p.buv_monatlich > 0 and rentenbeginn <= p.buv_endjahr:
        buv_monatl = p.buv_monatlich
        alter_bu   = AKTUELLES_JAHR - p.geburtsjahr   # Alter ca. bei BU-Beginn
        buv_zvE_j  = buv_monatl * 12 * ertragsanteil(alter_bu)

    brutto_total += duv_monatl + buv_monatl

    # ── Einkommensteuer ────────────────────────────────────────────────────────
    if p.ist_pensionaer:
        # § 19 Abs. 2 EStG: Versorgungsfreibetrag (Beamtenpension)
        pension_j = brutto_gesetzlich * 12
        vfb = versorgungsfreibetrag(rentenbeginn, pension_j)
        zvE = max(0.0, pension_j - vfb + zusatz_zvE + duv_zvE_j
                  - WERBUNGSKOSTEN_PAUSCHBETRAG - SONDERAUSGABEN_PAUSCHBETRAG)
        # Effektiver Besteuerungsanteil (für Kompatibilität mit _netto_ueber_horizont)
        ba = max(0.0, pension_j - vfb) / pension_j if pension_j > 0 else 0.0
    else:
        # § 22 Nr. 1 S. 3a aa EStG: Besteuerungsanteil GRV
        ba  = besteuerungsanteil(rentenbeginn)
        zvE = max(0.0, brutto_gesetzlich * 12 * ba + zusatz_zvE + buv_zvE_j
                  - WERBUNGSKOSTEN_PAUSCHBETRAG - SONDERAUSGABEN_PAUSCHBETRAG)

    # ── Altersentlastungsbetrag § 24a EStG ────────────────────────────────────
    # Qualifizierend: §22 Nr.1 S.3a bb (PrivRV-Ertragsanteil, BUV/DUV), §22 Nr.5 (Riester)
    # Nicht qualifizierend: GRV/Rürup (§22 Nr.1 S.3a aa), bAV/Pension (§19 Abs.2)
    if p.ist_pensionaer:
        _aeb_qualifying = duv_zvE_j
    else:
        _aeb_qualifying = buv_zvE_j
        if p.zusatz_typ in ("PrivateRente", "Riester"):
            _aeb_qualifying += zusatz_zvE
    _aeb_j = altersentlastungsbetrag(p.geburtsjahr, _aeb_qualifying)
    zvE = max(0.0, zvE - _aeb_j)

    jahressteuer     = einkommensteuer(zvE)
    kist_j           = p.kirchensteuer_satz * jahressteuer if p.kirchensteuer else 0.0
    steuer_monatlich = (jahressteuer + kist_j) / 12

    # ── Krankenversicherung ────────────────────────────────────────────────────
    if p.krankenversicherung == "PKV":
        kv     = p.pkv_beitrag
        kv_gkv = p.pkv_beitrag
        kv_pv  = 0.0
    else:
        _pv_voll, _pv_halb = _pv_satz(p.kinder_anzahl if p.kinder else 0)
        if p.ist_pensionaer:
            # Beamtenversorgung freiwillig GKV: kein DRV-Trägeranteil, kein bAV-Freibetrag
            # §229 Abs. 1 Nr. 1 SGB V: volle Pensionsbasis (kein GRV-Beitragszuschuss)
            _kv_basis = min(brutto_gesetzlich, BBG_KV_MONATLICH)
            kv_gkv = _kv_basis * (0.146 + p.gkv_zusatzbeitrag)
            kv_pv  = _kv_basis * _pv_voll
        elif not p.kvdr_pflicht:
            # Freiwillig GKV, GRV-Rentner: DRV zahlt halben GKV-Beitrag auf GRV-Anteil (§ 106 SGB VI)
            # GRV-Portion: halber GKV-Satz (DRV zahlt die andere Hälfte)
            # Andere Einnahmen (Zusatzrente etc.): voller GKV-Satz
            # PV: voller Satz auf alles (kein DRV-Trägeranteil für PV)
            _kv_total  = min(brutto_total - buv_monatl, BBG_KV_MONATLICH)
            _grv_basis = min(brutto_gesetzlich, BBG_KV_MONATLICH)
            _non_grv   = max(0.0, _kv_total - _grv_basis)
            kv_gkv = (_grv_basis * (0.073 + p.gkv_zusatzbeitrag / 2)
                      + _non_grv * (0.146 + p.gkv_zusatzbeitrag))
            kv_pv  = _kv_total * _pv_voll
        else:
            # KVdR §249a SGB V: DRV trägt halben GKV- und PV-Beitrag
            # Kinderlosenzuschlag (0,6 %) trägt Rentner allein (in _pv_halb eingerechnet)
            # BUV ist kein Versorgungsbezug i.S.v. §229 SGB V → nicht KVdR-pflichtig
            _kv_basis = brutto_total - buv_monatl
            kv_gkv = _kv_basis * (0.073 + p.gkv_zusatzbeitrag / 2)
            kv_pv  = _kv_basis * _pv_halb
        kv = kv_gkv + kv_pv

    netto  = brutto_total - steuer_monatlich - kv
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
        rentenwert_angepasst=0.0 if (p.ist_pensionaer or p.bereits_rentner) else rentenwert,
        zvE_jahres=zvE,
        jahressteuer=jahressteuer,
        rentenabschlag=abschlag,
        kv_gkv_monatlich=kv_gkv,
        kv_pv_monatlich=kv_pv,
        kirchensteuer_monatlich=kist_j / 12,
        altersentlastungsbetrag_jahres=_aeb_j,
    )


def simuliere_szenarien(p: Profil) -> dict[str, RentenErgebnis]:
    """Pessimistisch / Neutral / Optimistisch – Rentenanpassung und Kapitalrendite."""
    return {
        "Pessimistisch": berechne_rente(replace(p, rentenanpassung_pa=0.01, rendite_pa=0.03)),
        "Neutral":       berechne_rente(replace(p, rentenanpassung_pa=p.rentenanpassung_pa,
                                                    rendite_pa=p.rendite_pa)),
        "Optimistisch":  berechne_rente(replace(p, rentenanpassung_pa=0.03, rendite_pa=0.07)),
    }


# ── Ehegatten-Splitting ───────────────────────────────────────────────────────

def einkommensteuer_splitting(zvE_gesamt: float) -> float:
    """Splittingtarif (§ 32a Abs. 5 EStG): 2 × ESt(zvE / 2)."""
    return 2.0 * einkommensteuer(zvE_gesamt / 2.0)


def berechne_haushalt(
    erg1: RentenErgebnis,
    erg2: "RentenErgebnis | None",
    veranlagung: str,           # "Zusammen" | "Getrennt"
    mieteinnahmen_monatlich: float = 0.0,
    profil1: "Profil | None" = None,
    profil2: "Profil | None" = None,
) -> dict:
    """Haushalts-Nettoeinkommen mit optionalem Splitting und Mieteinnahmen.

    Mieteinnahmen (§ 21 EStG): voll steuerpflichtig, keine KV-Pflicht.
    Bei Getrennte Veranlagung werden die Mieteinnahmen 50/50 aufgeteilt.
    profil1/profil2: optional; wenn vorhanden wird AEB § 24a auf Mieteinnahmen angewendet.
    """
    miet_jahres = mieteinnahmen_monatlich * 12

    def _aeb_miet(profil: "Profil | None", erg: RentenErgebnis, miet_anteil: float) -> float:
        if profil is None or miet_anteil <= 0:
            return 0.0
        return altersentlastungsbetrag(
            profil.geburtsjahr, miet_anteil,
            bereits_genutzt=erg.altersentlastungsbetrag_jahres,
        )

    if erg2 is None:
        brutto = erg1.brutto_monatlich + mieteinnahmen_monatlich
        kv = erg1.kv_monatlich
        _aeb1 = _aeb_miet(profil1, erg1, miet_jahres)
        zvE = max(0.0, erg1.zvE_jahres + miet_jahres - _aeb1)
        steuer = einkommensteuer(zvE) / 12
        return {
            "netto_gesamt": brutto - steuer - kv,
            "steuer_gesamt": steuer,
            "kv_gesamt": kv,
            "brutto_gesamt": brutto,
            "steuerersparnis_splitting": 0.0,
        }

    brutto = erg1.brutto_monatlich + erg2.brutto_monatlich + mieteinnahmen_monatlich
    kv = erg1.kv_monatlich + erg2.kv_monatlich

    # Getrennte Veranlagung: Mieteinnahmen 50/50 aufgeteilt; AEB je Person auf eigenen Anteil
    _aeb1_get = _aeb_miet(profil1, erg1, miet_jahres / 2)
    _aeb2_get = _aeb_miet(profil2, erg2, miet_jahres / 2) if erg2 is not None else 0.0
    steuer_getrennt = (
        einkommensteuer(max(0.0, erg1.zvE_jahres + miet_jahres / 2 - _aeb1_get))
        + einkommensteuer(max(0.0, erg2.zvE_jahres + miet_jahres / 2 - _aeb2_get))
    ) / 12

    if veranlagung == "Zusammen":
        # Zusammen: alle Mieteinnahmen gehen in gemeinsamen zvE; P1 beansprucht AEB auf Miet
        _aeb1_zus = _aeb_miet(profil1, erg1, miet_jahres)
        zvE_gesamt = max(0.0, erg1.zvE_jahres + erg2.zvE_jahres + miet_jahres - _aeb1_zus)
        steuer_zusammen = einkommensteuer_splitting(zvE_gesamt) / 12
        ersparnis = max(0.0, steuer_getrennt - steuer_zusammen)
        steuer = steuer_zusammen
    else:
        steuer = steuer_getrennt
        ersparnis = 0.0

    return {
        "netto_gesamt": brutto - steuer - kv,
        "steuer_gesamt": steuer,
        "kv_gesamt": kv,
        "brutto_gesamt": brutto,
        "steuerersparnis_splitting": ersparnis,
    }


# ── Vorsorge-Bausteine ────────────────────────────────────────────────────────

@dataclass
class VorsorgeProdukt:
    id: str
    typ: str                   # "bAV" | "PrivateRente" | "Riester" | "LV"
    name: str
    person: str                # "Person 1" | "Person 2"
    max_einmalzahlung: float   # Maximale Einmalauszahlung ab frühestem Startdatum
    max_monatsrente: float     # Maximale monatliche Rente ab frühestem Startdatum
    laufzeit_jahre: int        # 0 = lebenslang, sonst befristet
    fruehestes_startjahr: int  # Frühestes mögliches Startjahr
    spaetestes_startjahr: int  # Spätestes mögliches Startjahr
    aufschub_rendite: float    # Verzinsung je Aufschubjahr (0.02 = 2 % p.a.)
    vertragsbeginn: int = 2010        # Jahr des Vertragsabschlusses (§ 20 Abs. 1 Nr. 6 EStG)
    einzahlungen_gesamt: float = 0.0  # Summe eingezahlter Beiträge (für Ertragsberechnung)
    teilfreistellung: float = 0.30    # ETF: 30 % Teilfreistellung (§ 20 InvStG 2018)
    # None = Optimizer wählt; 0.0 = nur monatlich; 0.5 = 50/50; 1.0 = nur einmal
    erzwungener_anteil: float | None = None
    # Laufende monatliche Kapitalerträge aus dem Produkt (Zinsen, Dividenden, ETF-Ausschüttungen)
    # Relevant für freiwillig GKV-Versicherte: zählen zur beitragspflichtigen Bemessungsgrundlage
    # Abgeltungsteuer wird darauf berechnet (Sparerpauschbetrag berücksichtigt)
    laufende_kapitalertraege_mono: float = 0.0

    @property
    def ist_lebensversicherung(self) -> bool:
        return self.typ == "LV"

    @property
    def ist_nur_monatsrente(self) -> bool:
        """Rürup/Basisrente: kein Kapitalwahlrecht (§ 10 Abs. 1 Nr. 2b EStG)."""
        return self.typ == "Rürup"


def _annuitaet(kapital: float, rendite_pa: float, jahre: int) -> float:
    """Monatliche Entnahme-Annuität: Kapital wird über `jahre` aufgebraucht."""
    if jahre <= 0 or kapital <= 0:
        return 0.0
    r_m = rendite_pa / 12
    n = jahre * 12
    if r_m > 0:
        return kapital * r_m / (1 - (1 + r_m) ** (-n))
    return kapital / n


def _wert_bei_start(prod: VorsorgeProdukt, startjahr: int) -> tuple[float, float]:
    """Einmalbetrag und Monatsrente nach Aufschubverzinsung bis `startjahr`."""
    deferral = max(0, startjahr - prod.fruehestes_startjahr)
    f = (1 + prod.aufschub_rendite) ** deferral
    return prod.max_einmalzahlung * f, prod.max_monatsrente * f


def vergleiche_produkt(
    produkt: VorsorgeProdukt,
    rendite_pa: float,
    horizon_jahre: int,
) -> dict:
    """Vergleicht Einmal / Monatlich / Kombiniert für ein Produkt am frühesten Startdatum."""
    H = horizon_jahre
    K = produkt.max_einmalzahlung
    M = produkt.max_monatsrente if produkt.max_monatsrente > 0 else _annuitaet(K, rendite_pa, H)
    lz = produkt.laufzeit_jahre if produkt.laufzeit_jahre > 0 else H
    effective_lz = min(lz, H)

    m_einmal = _annuitaet(K, rendite_pa, H)
    t_einmal = m_einmal * 12 * H
    t_monatlich = M * 12 * effective_lz
    m_monatlich = M

    nur_einmal = produkt.ist_lebensversicherung or produkt.typ == "ETF" or produkt.max_monatsrente <= 0
    if produkt.ist_nur_monatsrente:
        best_x, t_komb, m_komb = 0.0, t_monatlich, m_monatlich
        bestes = "monatlich"
    elif nur_einmal:
        best_x, t_komb, m_komb = 1.0, t_einmal, m_einmal
        bestes = "einmal"
    else:
        xs = np.linspace(0.0, 1.0, 101)
        totale = [
            _annuitaet(K * x, rendite_pa, H) * 12 * H + M * (1 - x) * 12 * effective_lz
            for x in xs
        ]
        best_idx = int(np.argmax(totale))
        best_x = float(xs[best_idx])
        t_komb = float(totale[best_idx])
        m_komb = _annuitaet(K * best_x, rendite_pa, H) + M * (1 - best_x)
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


# ── Steueroptimierung Vertragsauszahlungen ────────────────────────────────────

def _netto_ueber_horizont(
    profil: Profil,
    ergebnis: RentenErgebnis,
    entscheidungen: list,   # [(VorsorgeProdukt, startjahr: int, einmal_anteil: float)]
    horizont_jahre: int,
    mieteinnahmen_monatlich: float = 0.0,
    mietsteigerung_pa: float = 0.0,
    profil2: "Profil | None" = None,
    ergebnis2: "RentenErgebnis | None" = None,
    veranlagung: str = "Getrennt",
    gehalt_monatlich: float = 0.0,
) -> tuple[float, list[dict]]:
    """
    Simuliert das Netto-Einkommen Jahr für Jahr über `horizont_jahre` ab Renteneintritt.

    Steuer- und KV-Behandlung:
    - Gesetzliche Rente: Besteuerungsanteil § 22 Nr. 1 S. 3a aa EStG.
    - bAV (monatl./Einmal): 100 % steuerpflichtig § 19 / § 22 Nr. 5 EStG; KVdR-pflichtig.
      Einmalauszahlung KV-Basis auf 10 Jahre verteilt (§ 229 Abs. 1 S. 3 SGB V).
    - Riester (monatl./Einmal): 100 % steuerpflichtig § 22 Nr. 5 EStG; NICHT KVdR.
    - Rürup (monatl.): Besteuerungsanteil § 22 Nr. 1 S. 3a aa EStG; NICHT KVdR; kein Einmal.
    - Private RV (monatl.): nur Ertragsanteil steuerpflichtig § 22 Nr. 1 S. 3a bb EStG; NICHT KVdR.
    - LV / Private RV (Einmal): § 20 Abs. 1 Nr. 6 EStG:
        - Vertrag vor 01.01.2005: steuerfrei (Altvertrag).
        - Ab 2005, Laufzeit ≥ 12 J. und Alter ≥ 60 (bis 2011) / ≥ 62 (ab 2012):
          50 % des Ertrags → progressiver Tarif (Halbeinkünfteverfahren).
        - Sonst: 25 % Abgeltungsteuer auf vollen Ertrag.
    - ETF (Einmal): Abgeltungsteuer auf Ertrag × (1 – Teilfreistellung); Sparerpauschbetrag.
    - Mieteinnahmen: voll steuerpflichtig § 21 EStG; NICHT KVdR.
    - Sparerpauschbetrag (§ 20 Abs. 9 EStG): 1.000 € auf Abgeltungsteuer-Pool.
    """
    ba = ergebnis.besteuerungsanteil
    gesetzl_mono = ergebnis.brutto_gesetzlich
    ist_pkv      = profil.krankenversicherung == "PKV"
    ist_freiwillig = (profil.krankenversicherung == "GKV" and not profil.kvdr_pflicht)
    # Beitragssätze je Mitgliedsstatus (eigener Anteil):
    # KVdR/AN: DRV/AG trägt halben GKV- und PV-Beitrag; Kinderlosenzuschlag (0,6 %) trägt Versicherter allein
    # Freiwillig: kein Trägeranteil → voller GKV- und PV-Satz
    _pv_voll, _pv_halb = _pv_satz(profil.kinder_anzahl if profil.kinder else 0)
    kv_rate_halb = (0.073 + profil.gkv_zusatzbeitrag / 2) + _pv_halb   # AN + KVdR

    # Person 2: feste Basiswerte für die Haushaltssimulation
    zusammen      = veranlagung == "Zusammen" and profil2 is not None and ergebnis2 is not None
    hat_partner   = profil2 is not None and ergebnis2 is not None
    p2_zvE_0         = ergebnis2.zvE_jahres       if hat_partner else 0.0
    p2_brutto_mo0    = ergebnis2.brutto_monatlich if hat_partner else 0.0
    p2_gesetzl_mono0 = ergebnis2.brutto_gesetzlich if hat_partner else 0.0
    p2_anp           = profil2.rentenanpassung_pa  if hat_partner else 0.0

    # P2 KV-Status für dynamische Berechnung je Jahr
    _p2_ist_pkv        = profil2.krankenversicherung == "PKV" if hat_partner else True
    _p2_ist_freiwillig = (profil2.krankenversicherung == "GKV" and not profil2.kvdr_pflicht) if hat_partner else False
    if hat_partner and not _p2_ist_pkv:
        _p2_pv_voll, _p2_pv_halb = _pv_satz(profil2.kinder_anzahl if profil2.kinder else 0)
        _p2_kv_rate_halb = (0.073 + profil2.gkv_zusatzbeitrag / 2) + _p2_pv_halb
    else:
        _p2_pv_voll      = 0.0
        _p2_kv_rate_halb = 0.0

    # Sidebar-Zusatzrente: Initialwerte je nach Typ (einmalig vor dem Loop berechnen)
    _z = profil.zusatz_monatlich * 12
    if profil.zusatz_typ == "bAV":
        _s_bav_j, _s_riester_j = _z, 0.0
        _s_ruerup_brutto_j, _s_ruerup_zvE_j = 0.0, 0.0
        _s_priv_brutto_j, _s_priv_zvE_j = 0.0, 0.0
    elif profil.zusatz_typ == "Riester":
        _s_bav_j, _s_riester_j = 0.0, _z
        _s_ruerup_brutto_j, _s_ruerup_zvE_j = 0.0, 0.0
        _s_priv_brutto_j, _s_priv_zvE_j = 0.0, 0.0
    elif profil.zusatz_typ == "Rürup":
        _s_bav_j, _s_riester_j = 0.0, 0.0
        _ba_r = besteuerungsanteil(profil.eintritt_jahr)
        _s_ruerup_brutto_j, _s_ruerup_zvE_j = _z, _z * _ba_r
        _s_priv_brutto_j, _s_priv_zvE_j = 0.0, 0.0
    else:  # PrivateRente
        ea_z = ertragsanteil(profil.renteneintritt_alter)
        _s_bav_j, _s_riester_j = 0.0, 0.0
        _s_ruerup_brutto_j, _s_ruerup_zvE_j = 0.0, 0.0
        _s_priv_brutto_j, _s_priv_zvE_j = _z, _z * ea_z

    # DUV: Ertragsanteil auf Basis des Alters bei DU-Beginn (ca. aktuelles Alter)
    _duv_ea = (ertragsanteil(AKTUELLES_JAHR - profil.geburtsjahr)
               if profil.ist_pensionaer and profil.duv_monatlich > 0 else 0.0)

    # BUV: Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; nicht KVdR-pflichtig
    _buv_ea = (ertragsanteil(AKTUELLES_JAHR - profil.geburtsjahr)
               if not profil.ist_pensionaer and profil.buv_monatlich > 0 else 0.0)

    # Simulationszeitraum: ab heute wenn Gehalt angegeben, sonst ab Renteneintritt (M6)
    _noch_aktiv = gehalt_monatlich > 0 and not profil.bereits_rentner
    if _noch_aktiv:
        _sim_start  = AKTUELLES_JAHR
        _pre_jahre  = max(0, profil.eintritt_jahr - AKTUELLES_JAHR)
    else:
        _sim_start  = profil.rentenbeginn_jahr if profil.bereits_rentner else profil.eintritt_jahr
        _pre_jahre  = 0
    _gesamt_jahre = _pre_jahre + horizont_jahre

    total_netto = 0.0
    jahresdaten: list[dict] = []

    for y in range(_gesamt_jahre):
        jahr = _sim_start + y
        in_rente = profil.bereits_rentner or (jahr >= profil.eintritt_jahr)
        _r_y = max(0, jahr - profil.eintritt_jahr)   # Jahre seit Renteneintritt

        # M5: Einkommensbasis je Phase
        if in_rente:
            gesetzl_j  = gesetzl_mono * 12 * (1 + profil.rentenanpassung_pa) ** _r_y
            ba_aktuell = ba
        else:
            gesetzl_j  = gehalt_monatlich * 12   # Bruttogehalt § 19 EStG voll steuerpflichtig
            ba_aktuell = 1.0

        miet_j = mieteinnahmen_monatlich * 12 * (1 + mietsteigerung_pa) ** y

        # Person 2: wächst ab Renteneintritt (Basis GRV/Pension)
        p2_fak             = (1 + p2_anp) ** _r_y
        p2_zvE_j           = p2_zvE_0      * p2_fak
        p2_gesetzl_mono_fak = p2_gesetzl_mono0 * p2_fak
        p2_brutto_j        = p2_brutto_mo0 * 12 * p2_fak
        p2_kv_j            = 0.0   # dynamisch nach Produkt-Loop berechnet

        # Mieteinnahmen-Anteil für P1-Steuer:
        # Getrenntveranlagung mit Partner → 50/50; sonst voller Betrag
        miet_tax_j = miet_j / 2 if (hat_partner and not zusammen) else miet_j

        # DUV: aktiv solange Jahr ≤ duv_endjahr (nicht KVdR, Ertragsanteil)
        duv_j     = 0.0
        duv_zvE_j = 0.0
        if profil.ist_pensionaer and profil.duv_monatlich > 0 and jahr <= profil.duv_endjahr:
            duv_j     = profil.duv_monatlich * 12
            duv_zvE_j = duv_j * _duv_ea

        # BUV: aktiv solange Jahr ≤ buv_endjahr (nicht KVdR, Ertragsanteil)
        buv_j     = 0.0
        buv_zvE_j = 0.0
        if not profil.ist_pensionaer and profil.buv_monatlich > 0 and jahr <= profil.buv_endjahr:
            buv_j     = profil.buv_monatlich * 12
            buv_zvE_j = buv_j * _buv_ea

        # Laufende Renten (Sidebar-Basis + Verträge)
        bav_lfd_j     = _s_bav_j           # bAV: 100 % steuerpfl., KVdR
        riester_lfd_j = _s_riester_j       # Riester: 100 % steuerpfl., nicht KVdR
        ruerup_brutto_j = _s_ruerup_brutto_j  # Rürup: besteuerungsanteil, nicht KVdR
        ruerup_zvE_j    = _s_ruerup_zvE_j
        priv_brutto_j   = _s_priv_brutto_j    # PrivRV: ertragsanteil, nicht KVdR
        priv_zvE_j      = _s_priv_zvE_j

        # P1-Einmalauszahlungen und KV-Akkumulatoren
        bav_einmal_kv_j = 0.0    # bAV-Einmal KV-Basis §229 SGB V (P1)
        einmal_brutto_j = 0.0    # alle sonstigen Einmal brutto (P1)
        einmal_progr_j  = 0.0    # → zvE progressiv (P1)
        einmal_abgelt_j = 0.0    # LV/PrivRV → Abgeltungsteuer (P1)
        etf_brutto_j    = 0.0    # ETF-Entnahme brutto (P1)
        etf_abgelt_j    = 0.0    # ETF → Abgeltungsteuer (P1)
        lfd_kap_j = sum(
            p.laufende_kapitalertraege_mono * 12 for p, _, _ in entscheidungen
            if not (hat_partner and p.person == "Person 2")
        )
        # P2-Akkumulatoren (getrennte KV-Berechnung je Personenstatus)
        p2_bav_lfd_j       = 0.0
        p2_bav_einmal_kv_j = 0.0
        p2_riester_j       = 0.0
        p2_ruerup_brutto_j = 0.0
        p2_ruerup_zvE_j    = 0.0
        p2_priv_brutto_j   = 0.0
        p2_priv_zvE_j      = 0.0
        p2_einmal_brutto_j = 0.0
        p2_einmal_progr_j  = 0.0
        p2_einmal_abgelt_j = 0.0
        p2_etf_brutto_j    = 0.0
        p2_etf_abgelt_j    = 0.0
        p2_lfd_kap_j = sum(
            p.laufende_kapitalertraege_mono * 12 for p, _, _ in entscheidungen
            if hat_partner and p.person == "Person 2"
        )

        for prod, startjahr, anteil in entscheidungen:
            if jahr < startjahr:
                continue
            einmal_wert, mono_wert = _wert_bei_start(prod, startjahr)
            ist_bav     = prod.typ == "bAV"
            ist_riester = prod.typ == "Riester"
            ist_ruerup  = prod.typ == "Rürup"
            ist_etf     = prod.typ == "ETF"
            lz = prod.laufzeit_jahre if prod.laufzeit_jahre > 0 else horizont_jahre
            _is_p2 = hat_partner and prod.person == "Person 2"
            _gbj   = profil2.geburtsjahr if _is_p2 else profil.geburtsjahr

            # ── Einmalauszahlung ──────────────────────────────────────────────
            if anteil > 0:
                betrag = einmal_wert * anteil
                if jahr == startjahr:
                    if ist_etf:
                        gain_ratio = (
                            max(0.0, 1.0 - prod.einzahlungen_gesamt / einmal_wert)
                            if einmal_wert > 0 else 0.0
                        )
                        _abgelt = betrag * gain_ratio * (1.0 - prod.teilfreistellung)
                        if _is_p2:
                            p2_etf_brutto_j += betrag
                            p2_etf_abgelt_j += _abgelt
                        else:
                            etf_brutto_j += betrag
                            etf_abgelt_j += _abgelt
                    else:
                        if _is_p2:
                            p2_einmal_brutto_j += betrag
                        else:
                            einmal_brutto_j += betrag
                        if ist_bav or ist_riester:
                            if _is_p2: p2_einmal_progr_j += betrag
                            else: einmal_progr_j += betrag
                        elif ist_ruerup:
                            _bp = betrag * besteuerungsanteil(startjahr)
                            if _is_p2: p2_einmal_progr_j += _bp
                            else: einmal_progr_j += _bp
                        else:
                            # LV / PrivateRente: § 20 Abs. 1 Nr. 6 EStG
                            ertrag = max(0.0, betrag - prod.einzahlungen_gesamt * anteil)
                            if prod.vertragsbeginn < 2005:
                                pass                           # Altvertrag: steuerfrei
                            else:
                                laufzeit_vtr = max(0, startjahr - prod.vertragsbeginn)
                                min_alter_hb = 60 if prod.vertragsbeginn <= 2011 else 62
                                alter_az = startjahr - _gbj
                                if laufzeit_vtr >= 12 and alter_az >= min_alter_hb:
                                    if _is_p2: p2_einmal_progr_j += ertrag * 0.5
                                    else: einmal_progr_j += ertrag * 0.5
                                else:
                                    if _is_p2: p2_einmal_abgelt_j += ertrag
                                    else: einmal_abgelt_j += ertrag

                # KV-Verteilung bAV-Einmal über 10 Jahre (§ 229 Abs. 1 S. 3 SGB V)
                if ist_bav and 0 <= jahr - startjahr < 10:
                    if _is_p2: p2_bav_einmal_kv_j += betrag / 10
                    else: bav_einmal_kv_j += betrag / 10

            # ── Laufende Monatsrente ──────────────────────────────────────────
            if 0 <= jahr - startjahr < lz and anteil < 1.0:
                mono = mono_wert * (1 - anteil) * 12
                if ist_bav:
                    if _is_p2: p2_bav_lfd_j += mono
                    else: bav_lfd_j += mono
                elif ist_riester:
                    if _is_p2: p2_riester_j += mono
                    else: riester_lfd_j += mono
                elif ist_ruerup:
                    ba_r = besteuerungsanteil(startjahr)
                    if _is_p2:
                        p2_ruerup_brutto_j += mono
                        p2_ruerup_zvE_j    += mono * ba_r
                    else:
                        ruerup_brutto_j += mono
                        ruerup_zvE_j    += mono * ba_r
                elif not ist_etf:
                    # PrivateRente: nur Ertragsanteil steuerpflichtig
                    alter_start = startjahr - _gbj
                    ea = ertragsanteil(alter_start)
                    if _is_p2:
                        p2_priv_brutto_j += mono
                        p2_priv_zvE_j    += mono * ea
                    else:
                        priv_brutto_j += mono
                        priv_zvE_j    += mono * ea

        # DUV und BUV gehen in privaten Renten-Tracker (nicht KVdR)
        priv_brutto_j += duv_j + buv_j
        priv_zvE_j    += duv_zvE_j + buv_zvE_j

        # P2 Produkteinkommen zum P2-zvE addieren (für Splitting-Steuer)
        p2_zvE_j += (
            p2_bav_lfd_j + p2_riester_j + p2_ruerup_zvE_j
            + p2_priv_zvE_j + p2_einmal_progr_j
        )

        # ── Altersentlastungsbetrag § 24a EStG ───────────────────────────────
        # Qualifying P1: §22 Nr.1 S.3a bb (priv_zvE incl. DUV/BUV), §22 Nr.5 Riester, §21 Miete
        # Qualifying P2 (Zusammen): §22 Nr.1 S.3a bb, §22 Nr.5 Riester
        # Salary (Arbeitslohn §19, kein Versorgungsbezug) qualifiziert ebenfalls.
        if profil.geburtsjahr + 64 < jahr:
            if in_rente:
                _aeb_qual_p1 = priv_zvE_j + riester_lfd_j + miet_tax_j
            else:
                _aeb_qual_p1 = gesetzl_j + miet_tax_j
            _aeb_p1 = altersentlastungsbetrag(profil.geburtsjahr, _aeb_qual_p1)
        else:
            _aeb_p1 = 0.0
        if zusammen and profil2.geburtsjahr + 64 < jahr:
            _p2_aeb = altersentlastungsbetrag(profil2.geburtsjahr, p2_priv_zvE_j + p2_riester_j)
            p2_zvE_j = max(0.0, p2_zvE_j - _p2_aeb)

        # P2 KV dynamisch je Versicherungsstatus
        if not hat_partner:
            p2_kv_j = 0.0
        elif _p2_ist_pkv:
            p2_kv_j = profil2.pkv_beitrag * 12
        elif _p2_ist_freiwillig:
            _p2_grv_mono     = p2_gesetzl_mono_fak
            _p2_non_grv_mono = (
                p2_bav_lfd_j / 12
                + (p2_riester_j + p2_ruerup_brutto_j + p2_priv_brutto_j) / 12
                + p2_einmal_brutto_j / 12
                + p2_etf_brutto_j / 12
                + p2_lfd_kap_j / 12
                + (miet_j / 12 / 2 if not zusammen else 0.0)
            )
            _p2_grv_kv_basis = min(_p2_grv_mono, BBG_KV_MONATLICH)
            _p2_non_grv_kv   = min(_p2_non_grv_mono, max(0.0, BBG_KV_MONATLICH - _p2_grv_kv_basis))
            _p2_total_kv     = _p2_grv_kv_basis + _p2_non_grv_kv
            if _p2_total_kv < MINDEST_BMG_FREIWILLIG_MONO:
                _p2_non_grv_kv += MINDEST_BMG_FREIWILLIG_MONO - _p2_total_kv
                _p2_total_kv    = MINDEST_BMG_FREIWILLIG_MONO
            _p2_kv_gkv = (
                _p2_grv_kv_basis * (0.073 + profil2.gkv_zusatzbeitrag / 2)
                + _p2_non_grv_kv * (0.146 + profil2.gkv_zusatzbeitrag)
            )
            p2_kv_j = (_p2_kv_gkv + _p2_total_kv * _p2_pv_voll) * 12
        else:
            # KVdR §229 SGB V
            _p2_bav_kv_mono  = (p2_bav_lfd_j + p2_bav_einmal_kv_j) / 12
            _p2_bav_kv_basis = max(0.0, _p2_bav_kv_mono - BAV_FREIBETRAG_MONATLICH)
            _p2_kv_basis_mono = min(p2_gesetzl_mono_fak + _p2_bav_kv_basis, BBG_KV_MONATLICH)
            p2_kv_j = _p2_kv_basis_mono * 12 * _p2_kv_rate_halb

        # ── Einkommensteuer ───────────────────────────────────────────────────
        zvE_p1 = max(
            0.0,
            gesetzl_j * ba_aktuell   # Gehalt (1.0) oder Rente (Besteuerungsanteil)
            + bav_lfd_j + riester_lfd_j
            + ruerup_zvE_j
            + priv_zvE_j
            + einmal_progr_j
            + miet_tax_j
            - _aeb_p1
            - WERBUNGSKOSTEN_PAUSCHBETRAG - SONDERAUSGABEN_PAUSCHBETRAG,
        )
        # Laufende Kapitalerträge: Abgeltungsteuer (P1 + P2, je 1.000 € Sparerpauschbetrag)
        abgelt_pool   = (einmal_abgelt_j + etf_abgelt_j + lfd_kap_j
                         + p2_einmal_abgelt_j + p2_etf_abgelt_j + p2_lfd_kap_j)
        _spe = SPARERPAUSCHBETRAG * (2 if hat_partner else 1)
        steuer_abgelt = max(0.0, abgelt_pool - _spe) * 0.25
        if zusammen:
            steuer_progr = einkommensteuer_splitting(zvE_p1 + p2_zvE_j)
        else:
            steuer_progr = einkommensteuer(zvE_p1)
        _soli_j = solidaritaetszuschlag(steuer_progr)
        steuer = steuer_progr + _soli_j + steuer_abgelt
        # Kirchensteuer § 51a EStG (auf die progressive Einkommensteuer)
        if zusammen:
            # Splitting: KiSt je Ehegatte auf die ihm zuzurechnende Hälfte
            _kist = 0.0
            if profil.kirchensteuer:
                _kist += profil.kirchensteuer_satz * steuer_progr * 0.5
            if profil2 is not None and profil2.kirchensteuer:
                _kist += profil2.kirchensteuer_satz * steuer_progr * 0.5
            steuer += _kist
        elif profil.kirchensteuer:
            steuer += profil.kirchensteuer_satz * steuer_progr

        # ── KV / PV ───────────────────────────────────────────────────────────
        if ist_pkv:
            kv_p1 = profil.pkv_beitrag * 12
        elif not in_rente:
            # Arbeitnehmerjahre: AN-Anteil auf Gehalt (AG zahlt die andere Hälfte)
            kv_p1 = min(gehalt_monatlich, BBG_KV_MONATLICH) * 12 * kv_rate_halb
        elif ist_freiwillig:
            # Freiwillig GKV §240 SGB V + §106 SGB VI (Beitragszuschuss):
            # GRV-Rente: DRV zahlt halben GKV-Beitrag → Person zahlt nur 7,3 % + Zusatz/2
            # Andere Einnahmen (bAV, Miete etc.): voller GKV-Beitrag (14,6 % + Zusatz)
            # PV: voller Satz auf alles – §106 SGB VI gilt nicht für PV
            _grv_mono     = gesetzl_j / 12
            _non_grv_mono = (
                bav_lfd_j / 12                          # bAV laufend (kein Freibetrag)
                + (riester_lfd_j + ruerup_brutto_j + priv_brutto_j) / 12
                + einmal_brutto_j / 12                  # alle Einmalauszahlungen im Auszahlungsjahr
                + etf_brutto_j / 12
                + miet_j / 12
                + lfd_kap_j / 12
            )
            _grv_kv_basis = min(_grv_mono, BBG_KV_MONATLICH)
            _non_grv_kv   = min(_non_grv_mono, max(0.0, BBG_KV_MONATLICH - _grv_kv_basis))
            _total_kv     = _grv_kv_basis + _non_grv_kv
            # Mindest-BMG §240 Abs. 4 SGB V: Lücke wird dem Nicht-GRV-Anteil zugerechnet
            if _total_kv < MINDEST_BMG_FREIWILLIG_MONO:
                _non_grv_kv += MINDEST_BMG_FREIWILLIG_MONO - _total_kv
                _total_kv    = MINDEST_BMG_FREIWILLIG_MONO
            _kv_gkv = (_grv_kv_basis * (0.073 + profil.gkv_zusatzbeitrag / 2)
                       + _non_grv_kv * (0.146 + profil.gkv_zusatzbeitrag))
            kv_p1 = (_kv_gkv + _total_kv * _pv_voll) * 12
        else:
            # KVdR §229 SGB V: nur gesetzl. Rente + bAV (abzgl. Freibetrag); DRV zahlt halben Satz
            bav_kv_mono  = (bav_lfd_j + bav_einmal_kv_j) / 12
            bav_kv_basis = max(0.0, bav_kv_mono - BAV_FREIBETRAG_MONATLICH)
            kv_basis_mono = min(gesetzl_mono + bav_kv_basis, BBG_KV_MONATLICH)
            kv_p1 = kv_basis_mono * 12 * kv_rate_halb
        kv = kv_p1 + p2_kv_j   # Haushalt: P1 + P2

        brutto = (
            gesetzl_j + bav_lfd_j + riester_lfd_j
            + ruerup_brutto_j + priv_brutto_j
            + einmal_brutto_j + etf_brutto_j + miet_j
            + p2_brutto_j   # P2-Rente/Pension (Basis)
            + p2_bav_lfd_j + p2_riester_j + p2_ruerup_brutto_j + p2_priv_brutto_j
            + p2_einmal_brutto_j + p2_etf_brutto_j
        )
        netto = brutto - steuer - kv
        total_netto += netto
        zvE_display = zvE_p1 + (p2_zvE_j if zusammen else 0.0)
        jahresdaten.append({
            "Jahr": jahr,
            "Brutto": round(brutto),
            "Steuer": round(steuer),
            "KV_PV": round(kv),
            "KV_P1": round(kv_p1),
            "KV_P2": round(p2_kv_j),
            "Netto": round(netto),
            "Src_Gehalt":     round(gesetzl_j if not in_rente else 0.0),
            "Src_GesRente":   round(gesetzl_j if in_rente else 0.0),
            "Src_P2_Rente":   round(p2_brutto_j),
            "Src_Versorgung": round(bav_lfd_j + riester_lfd_j + ruerup_brutto_j + priv_brutto_j
                                    + p2_bav_lfd_j + p2_riester_j + p2_ruerup_brutto_j + p2_priv_brutto_j),
            "Src_Einmal":     round(einmal_brutto_j + etf_brutto_j
                                    + p2_einmal_brutto_j + p2_etf_brutto_j),
            "Src_Miete":      round(miet_j),
            "zvE":            round(zvE_display),
            "Steuer_Progressiv": round(steuer_progr),
            "Steuer_Abgeltung":  round(steuer_abgelt),
        })

    return total_netto, jahresdaten


_EXHAUSTIVE_LIMIT = 50_000  # Kombinationen; darüber → Koordinaten-Abstieg


def optimiere_auszahlungen(
    profil: Profil,
    ergebnis: RentenErgebnis,
    produkte: list,
    horizont_jahre: int,
    mieteinnahmen_monatlich: float = 0.0,
    mietsteigerung_pa: float = 0.0,
    profil2: "Profil | None" = None,
    ergebnis2: "RentenErgebnis | None" = None,
    veranlagung: str = "Getrennt",
    gehalt_monatlich: float = 0.0,
) -> dict:
    """
    Sucht die steuerlich optimale Kombination aus Startjahr × Auszahlungsart.

    Bis _EXHAUSTIVE_LIMIT Kombinationen: vollständige Suche.
    Darüber: Koordinaten-Abstieg (je Produkt beste Option, fixierte andere).
    Startjahre: bis zu 4 gleichmäßig verteilte Punkte im erlaubten Bereich.
    Auszahlungsarten: Einmal (100%), Kombiniert (50/50), Monatlich (0%).
    """
    from itertools import product as iterproduct
    from math import prod as math_prod

    if not produkte:
        return {}

    def optionen(prod: VorsorgeProdukt) -> list[tuple[int, float]]:
        jahre = list(range(prod.fruehestes_startjahr, prod.spaetestes_startjahr + 1))
        if len(jahre) > 4:
            idx = [0, len(jahre) // 3, 2 * len(jahre) // 3, len(jahre) - 1]
            jahre = [jahre[i] for i in idx]
        if prod.ist_nur_monatsrente or prod.max_einmalzahlung <= 0:
            anteile = [0.0]
        elif prod.ist_lebensversicherung or prod.typ == "ETF" or prod.max_monatsrente <= 0:
            anteile = [1.0]
        elif prod.erzwungener_anteil is not None:
            anteile = [prod.erzwungener_anteil]
        else:
            anteile = [0.0, 0.5, 1.0]
        return [(j, a) for j in jahre for a in anteile]

    def _label(kombi: list[tuple[int, float]]) -> str:
        return " | ".join(
            f"{produkte[i].name}: "
            f"{'Einmal' if kombi[i][1] == 1.0 else 'Monatlich' if kombi[i][1] == 0.0 else '50/50'} "
            f"ab {kombi[i][0]}"
            for i in range(len(produkte))
        )

    def _eval(kombi: list[tuple[int, float]]) -> float:
        ents = [(produkte[i], kombi[i][0], kombi[i][1]) for i in range(len(produkte))]
        netto, _ = _netto_ueber_horizont(profil, ergebnis, ents, horizont_jahre,
                                          mieteinnahmen_monatlich, mietsteigerung_pa,
                                          profil2, ergebnis2, veranlagung, gehalt_monatlich)
        return netto

    alle_optionen = [optionen(p) for p in produkte]
    anzahl_kombinationen = math_prod(len(o) for o in alle_optionen)
    alle_ergebnisse: list[dict] = []

    if anzahl_kombinationen <= _EXHAUSTIVE_LIMIT:
        # ── Vollständige Suche ────────────────────────────────────────────────
        bestes_netto = float("-inf")
        beste_kombi: list[tuple[int, float]] = []
        for kombi in iterproduct(*alle_optionen):
            kombi = list(kombi)
            netto = _eval(kombi)
            alle_ergebnisse.append({"Kombination": _label(kombi), "Netto gesamt (€)": round(netto)})
            if netto > bestes_netto:
                bestes_netto = netto
                beste_kombi = kombi
    else:
        # ── Koordinaten-Abstieg ───────────────────────────────────────────────
        # Start: für jedes Produkt erste Option (frühest, monatlich/einmal je Typ)
        beste_kombi = [opts[0] for opts in alle_optionen]
        bestes_netto = _eval(beste_kombi)
        alle_ergebnisse.append({"Kombination": _label(beste_kombi), "Netto gesamt (€)": round(bestes_netto)})

        for _ in range(6):  # max. 6 Runden bis Konvergenz
            verbessert = False
            for i, opts in enumerate(alle_optionen):
                for opt in opts:
                    kombi = list(beste_kombi)
                    kombi[i] = opt
                    netto = _eval(kombi)
                    alle_ergebnisse.append({"Kombination": _label(kombi), "Netto gesamt (€)": round(netto)})
                    if netto > bestes_netto:
                        bestes_netto = netto
                        beste_kombi = list(kombi)
                        verbessert = True
            if not verbessert:
                break

    alle_ergebnisse.sort(key=lambda x: x["Netto gesamt (€)"], reverse=True)
    # Duplikate entfernen (Koordinaten-Abstieg bewertet manche Kombis mehrfach)
    seen: set[str] = set()
    alle_ergebnisse = [
        e for e in alle_ergebnisse
        if e["Kombination"] not in seen and not seen.add(e["Kombination"])  # type: ignore[func-returns-value]
    ]

    beste_entscheidungen = [(produkte[i], beste_kombi[i][0], beste_kombi[i][1])
                             for i in range(len(produkte))]
    _kw = dict(profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung,
               gehalt_monatlich=gehalt_monatlich)
    _, jahresdaten = _netto_ueber_horizont(profil, ergebnis, beste_entscheidungen, horizont_jahre,
                                           mieteinnahmen_monatlich, mietsteigerung_pa, **_kw)

    ref_mono   = [(p, p.fruehestes_startjahr, 0.0) for p in produkte]
    ref_einmal = [(p, p.fruehestes_startjahr, 1.0) for p in produkte]
    netto_mono,   _ = _netto_ueber_horizont(profil, ergebnis, ref_mono,   horizont_jahre,
                                            mieteinnahmen_monatlich, mietsteigerung_pa, **_kw)
    netto_einmal, _ = _netto_ueber_horizont(profil, ergebnis, ref_einmal, horizont_jahre,
                                            mieteinnahmen_monatlich, mietsteigerung_pa, **_kw)

    return {
        "bestes_netto":          bestes_netto,
        "beste_entscheidungen":  beste_entscheidungen,
        "jahresdaten":           jahresdaten,
        "top10":                 alle_ergebnisse[:10],
        "netto_alle_monatlich":  netto_mono,
        "netto_alle_einmal":     netto_einmal,
        "anzahl_kombinationen":  len(alle_ergebnisse),
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
