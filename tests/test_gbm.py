import numpy as np

from mundial.modelo import gbm
from mundial.persistencia import bd, esquema


def sembrar(tmp_path, n_anios=8):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    rng = np.random.default_rng(11)
    equipos = [f"EQ{i}" for i in range(10)]
    fuerza = rng.normal(0, 0.5, 10)
    filas = []
    for anio in range(2014, 2014 + n_anios):
        for k in range(200):
            i, j = rng.choice(10, 2, replace=False)
            lam = np.exp(0.1 + fuerza[i] - fuerza[j] * 0.5)
            mu = np.exp(0.1 + fuerza[j] - fuerza[i] * 0.5)
            filas.append((f"{anio}-0{1 + k % 9}-{10 + k % 18}", equipos[i], equipos[j],
                          int(rng.poisson(lam)), int(rng.poisson(mu)),
                          "FIFA World Cup" if k % 7 == 0 else "Friendly", "X", "Y", int(k % 2)))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_historicos VALUES (?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    from mundial.modelo import entrenar
    entrenar.ratings_asof(conexion, anios=range(2015, 2014 + n_anios + 1), minimo_ajuste=100)
    return conexion


def test_features_point_in_time(tmp_path):
    conexion = sembrar(tmp_path)
    X, y, fechas, nombres, meta = gbm.construir_features(conexion, desde="2016-01-01")
    assert X.shape[1] == len(nombres) >= 15
    assert len(X) == len(y) == len(fechas) == len(meta)
    assert set(np.unique(y)) <= {0, 1, 2}  # 0=local gana, 1=empate, 2=visita gana
    assert "diff_ataque" in nombres and "neutral" in nombres
    assert "local" in meta[0] and "neutral" in meta[0]


def test_ordinal_probs_consistentes(tmp_path):
    conexion = sembrar(tmp_path)
    modelo = gbm.entrenar_ordinal(conexion, desde="2016-01-01", hasta="2020-12-31")
    X, y, fechas, _, _ = gbm.construir_features(conexion, desde="2021-01-01")
    probas = gbm.predecir_probas(modelo, X)
    assert probas.shape == (len(X), 3)
    assert np.allclose(probas.sum(axis=1), 1.0, atol=1e-6)
    assert (probas >= 0).all()


def test_walk_forward_devuelve_bloques(tmp_path):
    conexion = sembrar(tmp_path)
    informe = gbm.walk_forward(
        conexion, bloques=[("2016-01-01", "2018-12-31", "2019-01-01", "2019-12-31"),
                           ("2016-01-01", "2019-12-31", "2020-01-01", "2020-12-31")])
    assert len(informe["bloques"]) == 2
    for bloque in informe["bloques"]:
        assert {"rps_gbm", "rps_dc", "n"} <= set(bloque)
    assert isinstance(informe["pasa_puerta"], bool)


def test_pool_log_lineal():
    import pytest
    p = gbm.pool_log_lineal(
        [{"local": 0.5, "empate": 0.3, "visitante": 0.2},
         {"local": 0.6, "empate": 0.25, "visitante": 0.15}], [0.5, 0.5])
    assert sum(p.values()) == pytest.approx(1.0)
    assert 0.5 < p["local"] < 0.6


def test_shap_top_contribuciones(tmp_path):
    conexion = sembrar(tmp_path)
    modelo = gbm.entrenar_ordinal(conexion, desde="2016-01-01", hasta="2020-12-31")
    X, y, fechas, nombres, _ = gbm.construir_features(conexion, desde="2021-01-01")
    contribuciones = gbm.shap_partido(modelo, X[0])
    assert len(contribuciones) == 3
    assert all(n in nombres for n, _ in contribuciones)
