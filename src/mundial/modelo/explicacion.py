"""Explicación en español de los factores que movieron una predicción."""
from __future__ import annotations


def generar(factores: list[dict], p_modelo: dict, p_mercado: dict, n_casas: int) -> list[str]:
    lineas: list[str] = []
    relevantes = [
        f for f in factores
        if abs(f["local"] - 1.0) > 0.005 or abs(f["visitante"] - 1.0) > 0.005
    ]
    relevantes.sort(
        key=lambda f: max(abs(f["local"] - 1.0), abs(f["visitante"] - 1.0)), reverse=True
    )
    for f in relevantes:
        efectos = []
        if abs(f["local"] - 1.0) > 0.005:
            efectos.append(f"{(f['local'] - 1) * 100:+.0f}% goles esperados del local")
        if abs(f["visitante"] - 1.0) > 0.005:
            efectos.append(f"{(f['visitante'] - 1) * 100:+.0f}% del visitante")
        detalle = f" — {f['detalle']}" if f.get("detalle") else ""
        lineas.append(f"{f['nombre']}: {', '.join(efectos)}{detalle}")
    if p_mercado:
        lineas.append(
            f"mercado ({n_casas} casas, de-vig Shin): "
            f"{p_mercado['local'] * 100:.0f}/{p_mercado['empate'] * 100:.0f}/"
            f"{p_mercado['visitante'] * 100:.0f} vs modelo "
            f"{p_modelo['local'] * 100:.0f}/{p_modelo['empate'] * 100:.0f}/"
            f"{p_modelo['visitante'] * 100:.0f}"
        )
    return lineas
