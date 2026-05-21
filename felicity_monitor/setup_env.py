#!/usr/bin/env python3
"""
setup_env.py — Crea el entorno virtual e instala dependencias
Uso: python setup_env.py
"""
import os
import sys
import subprocess
import platform

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR    = os.path.join(PROJECT_DIR, "venv")

PACKAGES = [
    "pyserial",
    "PyQt5",
    "pyqtgraph",
    "fastapi",
    "uvicorn[standard]",
    "numpy",
]

def run(cmd, **kwargs):
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"ERROR: comando falló con código {result.returncode}")
        sys.exit(1)

def main():
    print("=" * 55)
    print("  Felicity Inverter Monitor — Setup de entorno")
    print("=" * 55)
    print(f"  Python: {sys.version}")
    print(f"  SO:     {platform.system()} {platform.release()}")
    print(f"  Dir:    {PROJECT_DIR}")
    print("=" * 55)

    # 1. Crear venv
    print("\n[1/3] Creando entorno virtual...")
    if os.path.exists(VENV_DIR):
        print("  Ya existe venv/ — saltando creación")
    else:
        run([sys.executable, "-m", "venv", VENV_DIR])
        print("  venv creado OK")

    # 2. Determinar pip del venv
    if platform.system() == "Windows":
        pip  = os.path.join(VENV_DIR, "Scripts", "pip.exe")
        python = os.path.join(VENV_DIR, "Scripts", "python.exe")
    else:
        pip  = os.path.join(VENV_DIR, "bin", "pip")
        python = os.path.join(VENV_DIR, "bin", "python")

    # 3. Actualizar pip
    print("\n[2/3] Actualizando pip...")
    run([pip, "install", "--upgrade", "pip"])

    # 4. Instalar paquetes
    print("\n[3/3] Instalando dependencias...")
    for pkg in PACKAGES:
        run([pip, "install", pkg])

    print("\n" + "=" * 55)
    print("  ¡Instalación completada!")
    print("=" * 55)
    print("\nPara ejecutar la app:")
    if platform.system() == "Windows":
        print(f"  venv\\Scripts\\activate")
    else:
        print(f"  source venv/bin/activate")
    print(f"  python main.py")
    print("\nPara verificar puertos disponibles:")
    print(f"  python -c \"from core.serial_engine import list_serial_ports; print(list_serial_ports())\"")

if __name__ == "__main__":
    main()
