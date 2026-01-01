import sys
import os
import glob
import json
from PyQt6.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QDialog, 
                             QVBoxLayout, QCheckBox, QLabel, QSlider, QPushButton, 
                             QFormLayout, QTextEdit)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt
from mascot import Mascot

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    default = {
        "fps": 30,
        "sound": True,
        "volume": 50,
        "interact_windows": True,
        "interact_windows": True,
        "blacklisted_windows": ["Program Manager", "Settings"],
        "launch_power_min": 15,
        "launch_power_max": 25
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return {**default, **json.load(f)}
        except:
            pass
    return default

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

import winreg

def set_startup(enable):
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
    try:
        if enable:
            # We need to run pythonw.exe to avoid console, but current process might be python.exe
            # For robustness, use sys.executable and the path to main.py
            exe = sys.executable.replace("python.exe", "pythonw.exe")
            target = f'"{exe}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(key, "PyShimeji", 0, winreg.REG_SZ, target)
        else:
            try:
                winreg.DeleteValue(key, "PyShimeji")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)

def is_startup_enabled():
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
    try:
        winreg.QueryValueEx(key, "PyShimeji")
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)

class SettingsDialog(QDialog):
    def __init__(self, config, on_alloc):
        super().__init__()
        self.config = config
        self.on_apply = on_alloc
        self.setWindowTitle("PyShimeji Settings")
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        layout = QFormLayout()
        
        # FPS
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setRange(10, 60)
        self.fps_slider.setValue(self.config.get("fps", 30))
        self.fps_label = QLabel(f"{self.fps_slider.value()} FPS")
        self.fps_slider.valueChanged.connect(lambda v: self.fps_label.setText(f"{v} FPS"))
        layout.addRow("Framerate:", self.fps_label)
        layout.addRow(self.fps_slider)

        # Volume
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.config.get("volume", 50))
        self.vol_label = QLabel(f"{self.vol_slider.value()}%")
        self.vol_slider.valueChanged.connect(lambda v: self.vol_label.setText(f"{v}%"))
        layout.addRow("Volume:", self.vol_label)
        layout.addRow(self.vol_slider)

        # Launch Power Min
        self.launch_min_slider = QSlider(Qt.Orientation.Horizontal)
        self.launch_min_slider.setRange(5, 50)
        self.launch_min_slider.setValue(self.config.get("launch_power_min", 15))
        self.launch_min_label = QLabel(f"{self.launch_min_slider.value()}")
        self.launch_min_slider.valueChanged.connect(self.on_min_changed)
        layout.addRow("Min Launch Power:", self.launch_min_label)
        layout.addRow(self.launch_min_slider)

        # Launch Power Max
        self.launch_max_slider = QSlider(Qt.Orientation.Horizontal)
        self.launch_max_slider.setRange(5, 50)
        self.launch_max_slider.setValue(self.config.get("launch_power_max", 25))
        self.launch_max_label = QLabel(f"{self.launch_max_slider.value()}")
        self.launch_max_slider.valueChanged.connect(self.on_max_changed)
        layout.addRow("Max Launch Power:", self.launch_max_label)
        layout.addRow(self.launch_max_slider)

        # Sound Checkbox
        self.sound_chk = QCheckBox("Enable Sound")
        self.sound_chk.setChecked(self.config.get("sound", True))
        layout.addRow(self.sound_chk)

        # Window Interaction
        self.win_chk = QCheckBox("Interact with Windows (Walk/Drag)")
        self.win_chk.setChecked(self.config.get("interact_windows", True))
        layout.addRow(self.win_chk)
        
        # Startup Checkbox (Registry)
        self.startup_chk = QCheckBox("Run on Windows Startup")
        self.startup_chk.setChecked(is_startup_enabled())
        layout.addRow(self.startup_chk)

        # Blacklist
        self.blacklist_edit = QTextEdit()
        self.blacklist_edit.setPlainText("\n".join(self.config.get("blacklisted_windows", [])))
        self.blacklist_edit.setPlaceholderText("Window Titles to ignore (one per line)")
        self.blacklist_edit.setMaximumHeight(100)
        layout.addRow("Window Blacklist:", self.blacklist_edit)

        # Buttons
        btn_box = QVBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.apply_settings)
        btn_box.addWidget(apply_btn)
        
        layout.addRow(btn_box)
        self.setLayout(layout)

    def on_min_changed(self, val):
        self.launch_min_label.setText(str(val))
        if self.launch_max_slider.value() < val:
            self.launch_max_slider.setValue(val)

    def on_max_changed(self, val):
        self.launch_max_label.setText(str(val))
        if self.launch_min_slider.value() > val:
            self.launch_min_slider.setValue(val)

    def apply_settings(self):
        self.config["fps"] = self.fps_slider.value()
        self.config["volume"] = self.vol_slider.value()
        self.config["launch_power_min"] = self.launch_min_slider.value()
        self.config["launch_power_max"] = self.launch_max_slider.value()
        self.config["sound"] = self.sound_chk.isChecked()
        self.config["interact_windows"] = self.win_chk.isChecked()
        self.config["blacklisted_windows"] = [line for line in self.blacklist_edit.toPlainText().split('\n') if line.strip()]
        
        # Apply startup
        set_startup(self.startup_chk.isChecked())
        
        save_config(self.config)
        if self.on_apply:
            self.on_apply()
        self.accept()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    icon = QIcon() 
    style = app.style()
    icon = style.standardIcon(style.StandardPixmap.SP_ComputerIcon)

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("PyShimeji")
    
    mascots = []
    config = load_config()

    def update_mascots():
        print("Updating settings...")
        interval = int(1000 / config["fps"])
        # Update time_scale and volume
        time_scale = 30.0 / config["fps"]
        
        for m in mascots:
            m.tick_timer.setInterval(interval)
            m.fps = config["fps"]
            m.time_scale = time_scale
            m.config = config
            m.update_volume()

    def open_settings():
        dlg = SettingsDialog(config, update_mascots)
        dlg.exec()

    def pause_all():
        for m in mascots:
            if m.tick_timer.isActive():
                m.tick_timer.stop()
            else:
                m.tick_timer.start()

    def reset_all():
        print("Resetting mascot positions...")
        for m in mascots:
            m.teleport_to_random_pos()

    # Menu
    menu = QMenu()
    
    reset_action = QAction("Reset Positions", app)
    reset_action.triggered.connect(reset_all)
    menu.addAction(reset_action)

    settings_action = QAction("Settings", app)
    settings_action.triggered.connect(open_settings)
    menu.addAction(settings_action)

    pause_action = QAction("Pause/Resume", app)
    pause_action.triggered.connect(pause_all)
    menu.addAction(pause_action)

    exit_action = QAction("Exit", app)
    exit_action.triggered.connect(app.quit)
    menu.addAction(exit_action)

    tray.setContextMenu(menu)
    tray.show()

    # Load Mascots
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    zip_files = glob.glob(os.path.join(base_dir, "*.zip"))
    
    if not zip_files:
        print(f"No zip files found in {base_dir}")
        return

    for zip_path in zip_files:
        try:
            mascot = Mascot(zip_path, config)
            mascot.show()
            mascots.append(mascot)
        except Exception as e:
            print(f"Failed to load {zip_path}: {e}")

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
