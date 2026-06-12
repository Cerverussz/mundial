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


def test_ratings_asof_sin_fuga(tmp_path):
    import numpy as np

    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    rng = np.random.default_rng(3)
    equipos = [f"EQ{i}" for i in range(6)]
    filas = []
    for anio in (2019, 2020, 2021, 2022):
        for k in range(120):
            i, j = rng.choice(6, 2, replace=False)
            filas.append((f"{anio}-0{1 + k % 9}-10", equipos[i], equipos[j],
                          int(rng.poisson(1.3)), int(rng.poisson(1.1)), "T", "X", "Y", 1))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    n = entrenar.ratings_asof(conexion, anios=(2021, 2022), minimo_ajuste=100)
    assert n == 2
    fechas = {f["fecha_ajuste"] for f in conexion.execute(
        "SELECT DISTINCT fecha_ajuste FROM ratings")}
    assert {"2021-01-01", "2022-01-01"} <= fechas
    rating = entrenar.rating_asof(conexion, "EQ0", "2021-06-15")
    assert rating is not None and "ataque" in rating
    # un equipo que solo juega en 2022 no tiene rating as-of 2021
    conexion.execute(
        "INSERT INTO resultados_historicos VALUES ('2022-03-01','NUEVO','EQ0',9,0,'T','X','Y',1)")
    conexion.commit()
    entrenar.ratings_asof(conexion, anios=(2021,), minimo_ajuste=100)
    assert entrenar.rating_asof(conexion, "NUEVO", "2021-06-15") is None
