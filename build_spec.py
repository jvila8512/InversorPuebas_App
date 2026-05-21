# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.__main__ import run as run_pyinstaller

# Run PyInstaller with the spec file
if __name__ == '__main__':
    run_pyinstaller(['build_spec.spec', '--onefile', '--name=InversorMonitor'])