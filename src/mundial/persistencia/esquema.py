"""Esquema de la base local. Idempotente."""
from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS equipos(
  nombre TEXT PRIMARY KEY,
  tla TEXT,
  confederacion TEXT
);
CREATE TABLE IF NOT EXISTS estadios(
  nombre TEXT PRIMARY KEY,
  ciudad TEXT, pais TEXT,
  altitud_m REAL, lat REAL, lon REAL, tz TEXT
);
CREATE TABLE IF NOT EXISTS partidos(
  id INTEGER PRIMARY KEY,
  fecha_utc TEXT NOT NULL,
  local TEXT NOT NULL,
  visitante TEXT NOT NULL,
  fase TEXT, grupo TEXT, jornada INTEGER,
  estadio TEXT,
  estado TEXT,
  goles_local INTEGER, goles_visitante INTEGER,
  id_fifa TEXT,
  fuente TEXT
);
CREATE TABLE IF NOT EXISTS resultados_historicos(
  fecha TEXT NOT NULL,
  local TEXT NOT NULL,
  visitante TEXT NOT NULL,
  goles_local INTEGER NOT NULL,
  goles_visitante INTEGER NOT NULL,
  torneo TEXT, ciudad TEXT, pais TEXT,
  neutral INTEGER NOT NULL,
  PRIMARY KEY(fecha, local, visitante)
);
CREATE TABLE IF NOT EXISTS ratings(
  equipo TEXT NOT NULL,
  fecha_ajuste TEXT NOT NULL,
  ataque REAL NOT NULL,
  defensa REAL NOT NULL,
  PRIMARY KEY(equipo, fecha_ajuste)
);
CREATE TABLE IF NOT EXISTS modelo_meta(
  fecha_ajuste TEXT PRIMARY KEY,
  mu REAL, ventaja_local REAL, rho REAL,
  n_partidos INTEGER, n_equipos INTEGER,
  log_verosimilitud REAL,
  version TEXT
);
"""


def crear(conexion: sqlite3.Connection) -> None:
    conexion.executescript(DDL)
    conexion.commit()
