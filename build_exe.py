import sys
import os

# Add PyInstaller to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'Scripts'))

from PyInstaller.__main__ import run

# Run with no console window
sys.exit(run([
    'felicity_monitor.spec',
    '--name=FelicityInverterMonitor',
    '--onefile',
    '--windowed',
    '--clean'
]))