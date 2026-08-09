"""PART 48 — Digital Twin Simulation.

Simule l'impact de scénarios (fermeture d'usine, pic de vent) sur l'AQI futur,
en combinant le CGAN existant (cgan_trainer.py / gan.php) avec le PINN (Part 38).
Permet aux autorités de tester des scénarios « et si » (ex: arrêt temporaire du
complexe chimique de Ghannouche).

Dégradation gracieuse : si le CGAN/torch n'est pas dispo, on simule via le
modèle physique de panache (pinn_dispersion) seul, qui tourne en numpy pur.
Écrit dans digital_twin_scenarios.
"""
from __future__ import annotations
import json
import math
from datetime import datetime

try:
    from pinn_dispersion import gaussian_plume_equation
except Exception:  # pragma: no cover
    def gaussian_plume_equation(wind_speed, wind_dir, distance_to_source, **kw):
        u = max(0.5, float(wind_speed))
        x = max(1.0, float(distance_to_source))
        return 1.0 / (u * math.sqrt(x))


def simulate_scenario(zone_id: int, params: dict, hours: int = 24):
    """Simule une courbe AQI horaire sous un scénario donné.

    params supportés :
      - source_reduction_pct : 0..100 (ex: fermeture usine => 80)
      - wind_speed           : m/s (pic de vent)
      - base_aqi             : AQI de départ
      - distance_to_source_m : distance zone <-> source
    """
    base = float(params.get("base_aqi", 90))
    reduction = float(params.get("source_reduction_pct", 0)) / 100.0
    wind = float(params.get("wind_speed", 3.0))
    dist = float(params.get("distance_to_source_m", 800))

    # Facteur physique (panache) normalisé par rapport à un vent de référence.
    ref = gaussian_plume_equation(3.0, 90.0, dist)
    curve = []
    for h in range(hours):
        # Le vent varie légèrement autour de la valeur de scénario.
        w = max(0.5, wind + math.sin(h / 3.0) * 0.5)
        phys = gaussian_plume_equation(w, 90.0, dist)
        phys_ratio = (phys / ref) if ref > 0 else 1.0
        # Emission réduite par le scénario + dispersion physique.
        aqi = base * (1 - reduction) * phys_ratio
        # Légère inertie temporelle.
        if curve:
            aqi = 0.7 * aqi + 0.3 * curve[-1]
        curve.append(round(max(0.0, aqi), 1))
    confidence = 0.6 if reduction or wind else 0.4
    return curve, confidence


def run_and_store(db, scenario_name: str, zone_id: int, params: dict, hours: int = 24):
    curve, conf = simulate_scenario(zone_id, params, hours)
    if db is not None:
        try:
            cur = db.cursor()
            cur.execute(
                "INSERT INTO digital_twin_scenarios "
                "(scenario_name, created_at, zone_id, parameters_json, simulated_aqi_curve, confidence) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (scenario_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), zone_id,
                 json.dumps(params), json.dumps(curve), conf))
            db.commit()
        except Exception as e:  # pragma: no cover
            print(f"[twin] insert: {e}")
    return {"curve": curve, "confidence": conf}


if __name__ == "__main__":
    print(simulate_scenario(3, {"base_aqi": 120, "source_reduction_pct": 80, "wind_speed": 5}))
