import numpy as np

from mundial.analisis import mineria


def test_bh_controla_nulos():
    rng = np.random.default_rng(7)
    candidatos = []
    for i in range(200):  # 200 hipótesis nulas: tasa real = baseline
        exitos = int(rng.binomial(80, 0.5))
        candidatos.append(mineria.Candidato(
            id=f"nulo_{i}", familia="nulos", hipotesis="x", filtro={},
            mercado_objetivo="over_under_25", lado="over@2.5",
            exitos=exitos, n=80, baseline=0.5))
    reportables = mineria.ajustar_bh(candidatos, q=0.10)
    assert sum(1 for c in reportables if c.reportable) <= 4  # FDR controlado


def test_detecta_efecto_plantado():
    candidatos = [mineria.Candidato(
        id="real", familia="f", hipotesis="x", filtro={}, mercado_objetivo="btts",
        lado="yes", exitos=70, n=100, baseline=0.5)]
    for i in range(50):
        candidatos.append(mineria.Candidato(
            id=f"n{i}", familia="f", hipotesis="x", filtro={}, mercado_objetivo="btts",
            lado="yes", exitos=50, n=100, baseline=0.5))
    resultado = mineria.ajustar_bh(candidatos, q=0.10)
    real = next(c for c in resultado if c.id == "real")
    assert real.reportable and real.p_adj < 0.05
    assert real.ic95[0] > 0.5  # IC de Wilson por encima del baseline


def test_familia_goles_por_fase(tmp_path):
    from mundial.persistencia import bd, esquema
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    filas = []
    for i in range(60):  # grupos: pocos goles; KO: muchos (efecto plantado)
        filas.append((f"g{i}", 2018, "group stage", 1, 0, "2018-06-14", "A", "B", 1, 0, 1, 0, 0, 0))
        filas.append((f"k{i}", 2018, "final", 0, 1, "2018-07-14", "A", "B", 3, 2, 3, 2, 0, 0))
    conexion.executemany(
        "INSERT OR REPLACE INTO resultados_wc VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    conexion.commit()
    candidatos = mineria.minar(conexion, anio_desde=1994)
    sobre_ko = [c for c in candidatos if c.familia == "goles_por_fase"
                and "eliminacion" in c.id and c.lado == "over@2.5"]
    assert sobre_ko and sobre_ko[0].exitos == 60 and sobre_ko[0].n == 60
