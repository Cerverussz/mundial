import pytest

from mundial import config


def test_clave_presente(monkeypatch):
    monkeypatch.setenv("PRUEBA_CLAVE", "abc123")
    assert config.clave("PRUEBA_CLAVE") == "abc123"


def test_clave_faltante(monkeypatch):
    monkeypatch.delenv("NO_EXISTE", raising=False)
    with pytest.raises(RuntimeError, match="NO_EXISTE"):
        config.clave("NO_EXISTE")


def test_rutas_apuntan_al_repo():
    assert (config.RAIZ / "pyproject.toml").exists()
    assert config.DIR_SNAPSHOTS == config.RAIZ / "data" / "snapshots"
