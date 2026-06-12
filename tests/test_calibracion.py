import pytest

from mundial.modelo import calibracion
from mundial.persistencia import bd, esquema


def test_optimizar_w_shrinkage(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    # 20 partidos donde el MODELO clavó (p_modelo alta al resultado real) y el mercado no.
    for k in range(20):
        conexion.execute(
            """INSERT INTO partidos(id, fecha_utc, local, visitante, estado,
               goles_local, goles_visitante)
               VALUES (?, ?, 'A', 'B', 'FINISHED', 1, 0)""",
            (k, f"2026-06-{12 + k % 15:02d}T19:00:00Z"))
        conexion.execute(
            """INSERT INTO predicciones (partido_id, creado_en, marcador,
               p_local, p_empate, p_visitante,
               p_local_modelo, p_empate_modelo, p_visitante_modelo,
               p_local_mercado, p_empate_mercado, p_visitante_mercado)
               VALUES (?, ?, '1-0', 0.5,0.3,0.2, 0.85,0.10,0.05, 0.40,0.35,0.25)""",
            (k, f"2026-06-{12 + k % 15:02d}T10:00:00Z"))
    conexion.commit()
    resultado = calibracion.optimizar_w(conexion)
    assert resultado["n"] == 20
    assert resultado["w_crudo"] > 0.9
    # shrinkage: (20*1.0 + 50*0.4)/70 = 0.5714, dentro de [0.2, 0.6]
    assert resultado["w_recomendado"] == pytest.approx(0.5714, abs=1e-3)


def test_muestra_insuficiente(tmp_path):
    conexion = bd.conectar(tmp_path / "m.db")
    esquema.crear(conexion)
    resultado = calibracion.optimizar_w(conexion)
    assert resultado["w_recomendado"] == 0.4
