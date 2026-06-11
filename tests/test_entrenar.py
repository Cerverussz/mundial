from datetime import date

import numpy as np

from mundial.modelo import entrenar
from mundial.persistencia import bd, esquema


def test_entrenar_y_guardar(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    rng = np.random.default_rng(7)
    equipos = [f"EQ{i}" for i in range(6)]
    filas = []
    for k in range(300):
        i, j = rng.choice(6, 2, replace=False)
        filas.append(
            (f"2025-0{1 + k % 9}-15", equipos[i], equipos[j],
             int(rng.poisson(1.3)), int(rng.poisson(1.1)), "Amistoso", "X", "Y", 1)
        )
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas
    )
    ajuste = entrenar.entrenar_y_guardar(conexion, referencia=date(2026, 6, 11))
    assert len(ajuste.equipos) == 6
    n_ratings = conexion.execute("SELECT COUNT(*) c FROM ratings").fetchone()["c"]
    assert n_ratings == 6
    meta = conexion.execute("SELECT * FROM modelo_meta").fetchone()
    assert meta["version"] == "dc-1.0"
