# -*- coding: utf-8 -*-
"""
app_paths.py — Rutas de datos escribibles de la aplicación
==========================================================
Resuelve dónde viven los archivos de configuración que la app DEBE poder
persistir entre ejecuciones:

  - ``profiles.json``        → perfiles de inversor (mapa de registros, baud, …)
  - ``multi_inverter.json``  → tabla de inversores en paralelo (slave, mapa)

Por qué existe este módulo
--------------------------
Cuando la app corre desde el código fuente, esos archivos viven junto al
paquete ``felicity_monitor/``. Pero cuando corre empaquetada con PyInstaller
en modo *onefile*, ``__file__`` apunta al directorio temporal de extracción
(``%TEMP%\_MEIxxxxxx``), que PyInstaller **borra al cerrar la aplicación**.
Escribir ahí significa que cada perfil editado y cada tabla de inversores en
paralelo se pierden en el siguiente reinicio: la app parecería guardar bien
y luego olvidarse de todo.

Por eso, cuando está congelada (``sys.frozen``), los datos se guardan en
``%APPDATA%\\InversorPuebasApp``, una ubicación persistente y escribible por
el usuario normal. Al reinstalar o actualizar el .exe no se pierde nada.
"""

import os
import sys


# Nombre de la carpeta dentro de %APPDATA%
APP_DIR_NAME = "InversorPuebasApp"


def is_frozen() -> bool:
    """True si la app corre empaquetada (PyInstaller onefile)."""
    return bool(getattr(sys, "frozen", False))


def data_dir() -> str:
    """
    Devuelve el directorio donde se guardan los datos de configuración.

    - Empaquetada: ``%APPDATA%\\InversorPuebasApp`` (persistente).
    - Desde código: ``felicity_monitor/`` (junto al paquete, como siempre).
    """
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        candidate = os.path.join(base, APP_DIR_NAME)
    else:
        # core/app_paths.py -> felicity_monitor/
        candidate = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        os.makedirs(candidate, exist_ok=True)
    except OSError:
        # Si el directorio no se puede crear (permisos), seguimos con la
        # ruta tal cual: el llamador decidirá si puede escribir.
        pass

    return candidate


def data_file(name: str) -> str:
    """Ruta completa de un archivo de datos dentro de :func:`data_dir`."""
    return os.path.join(data_dir(), name)
