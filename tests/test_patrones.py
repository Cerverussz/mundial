import json

from mundial.notificaciones import patrones

PATRON = {
    "id": "empate_ko_parejo",
    "familia": "empates_ko",
    "hipotesis": "En eliminatorias parejas el empate a 90' está subvalorado",
    "filtro": {"fase_eliminacion": True, "diff_rating_max": 0.35},
    "mercado_objetivo": "1x2",
    "lado": "empate",
    "efecto": {"tasa": 0.41, "baseline": 0.31, "lift": 0.10},
    "n": 73, "p_adj_bh": 0.03, "ic95": [0.33, 0.49],
    "registrado_en_commit": "PENDIENTE",
    "ventana_validez": ["2026-06-11", "2026-07-19"],
    "umbral_prob_implicita": 0.32,
    "estado": "en_papel",
}


def contexto_prueba(**extra):
    base = {"fase_eliminacion": True, "jornada": None, "diff_rating": 0.2,
            "confederacion_local": "UEFA", "confederacion_visitante": "CONMEBOL",
            "dead_rubber_local": False, "dead_rubber_visitante": False, "fecha": "2026-06-29"}
    base.update(extra)
    return base


def test_filtro_declarativo():
    assert patrones.satisface(PATRON["filtro"], contexto_prueba())
    assert not patrones.satisface(PATRON["filtro"], contexto_prueba(diff_rating=0.9))
    assert not patrones.satisface(PATRON["filtro"], contexto_prueba(fase_eliminacion=False))


def test_condicion_de_precio():
    # prob implícita devig del empate 0.30 <= umbral 0.32 → dispara
    assert patrones.precio_cumple(PATRON, {"empate": 0.30})
    assert not patrones.precio_cumple(PATRON, {"empate": 0.35})


def test_validacion_preregistro_rechaza_no_commiteado(tmp_path):
    ruta = tmp_path / "patrones.json"
    ruta.write_text(json.dumps([PATRON]))
    activos = patrones.cargar_validados(ruta, fecha_partido="2026-06-29T19:00:00Z", repo=None)
    assert activos == []  # commit 'PENDIENTE' no existe → rechazado
