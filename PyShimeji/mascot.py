import os
import zipfile
import random
import tempfile
import shutil
import math
import xml.etree.ElementTree as ET
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QTimer, QPoint, QUrl
from PyQt6.QtGui import QPixmap, QImage, QCursor, QPainter, QTransform
from PyQt6.QtMultimedia import QSoundEffect
from window_manager import WindowManager

# Physics Constants
GRAVITY = 1
MAX_FALL_SPEED = 40

class Mascot(QWidget):
    def __init__(self, zip_path, config=None):
        super().__init__()
        self.zip_path = zip_path
        self.config = config or {}
        
        self.images = {}
        self.actions = {}
        self.sounds = {} # Map name -> QSoundEffect
        self.temp_dir = tempfile.mkdtemp()
        
        # State
        self.current_action = None
        self.current_action_name = ""
        self.current_behavior = "Fall" 
        self.frame_index = 0
        self.velocity_x = 0
        self.velocity_y = 0
        self.facing_right = False
        self.ticks_in_frame = 0
        
        # Current Frame Data
        self.current_anchor_x = 0
        self.current_anchor_y = 0
        
        # Environment
        screen = QApplication.primaryScreen().geometry()
        self.screen_width = screen.width()
        self.screen_height = screen.height()
        self.floor_y = self.screen_height - 50 
        self.current_window = None # (hwnd, rect) if standing on a window

        # Timer
        self.fps = self.config.get("fps", 30)
        self.tick_interval = int(1000 / self.fps)
        self.time_scale = 30.0 / self.fps # Normalization factor relative to 30FPS
        
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.game_loop)
        
        # Window setup
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self.load_resources()
        
        # Initial Drop
        self.move(random.randint(100, self.screen_width - 100), -100)
        self.tick_timer.start(self.tick_interval)

        # Dragging
        self.dragging = False
        self.drag_offset = QPoint()
        self.velocity_history = []
        self.last_pos = QPoint()
        
        # Internal High-Precision Position
        self._x_float = float(self.x())
        self._y_float = float(self.y())
        self.corner_ticks = 0

    def teleport_to_random_pos(self):
        screens = WindowManager.get_screens_info()
        if not screens: return
        
        # Pick random screen
        screen = random.choice(screens)
        sl, st, sr, sb = screen[0], screen[1], screen[2], screen[3]
        
        margin = 30
        new_x = random.randint(sl + margin, sr - margin)
        new_y = random.randint(st + margin, sb - margin)
        
        # Move and sync
        self.move(new_x - self.current_anchor_x, new_y - self.current_anchor_y)
        self._x_float = float(self.x())
        self._y_float = float(self.y())
        
        # Reset state
        self.velocity_x = 0
        self.velocity_y = 0
        self.current_behavior = "Fall"
        self.set_action("Falling")

    def cleanup(self):
        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def load_resources(self):
        with zipfile.ZipFile(self.zip_path, 'r') as z:
            # Extract Sounds
            for file_info in z.infolist():
                if file_info.filename.lower().endswith('.wav'):
                    # Flatten: just use basename
                    name = os.path.basename(file_info.filename)
                    target_path = os.path.join(self.temp_dir, name)
                    with open(target_path, "wb") as f:
                        f.write(z.read(file_info))
                    
                    effect = QSoundEffect()
                    effect.setSource(QUrl.fromLocalFile(target_path))
                    self.sounds[name] = effect

            # Load Actions
            try:
                conf_path = 'conf/actions.xml'
                if conf_path not in z.namelist():
                     # Try finding it?
                     for n in z.namelist():
                         if n.endswith('actions.xml'):
                             conf_path = n
                             break
                
                with z.open(conf_path) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    ns = {'ns': 'http://www.group-finity.com/Mascot'}
                    
                    for action in root.findall('.//ns:Action', ns):
                        name = action.get('Name')
                        type_ = action.get('Type')
                        
                        animations = []
                        anim_node = action.find('ns:Animation', ns)
                        if anim_node is not None:
                            for pose in anim_node.findall('ns:Pose', ns):
                                img_path = pose.get('Image')
                                duration = int(pose.get('Duration', 5))
                                velocity = pose.get('Velocity', '0,0')
                                vx, vy = map(float, velocity.split(','))
                                anchor = pose.get('ImageAnchor', '0,0')
                                ax, ay = map(int, anchor.split(','))
                                sound_file = pose.get('Sound', '')
                                
                                animations.append({
                                    'image': img_path,
                                    'duration': duration,
                                    'vx': vx,
                                    'vy': vy,
                                    'ax': ax,
                                    'ay': ay,
                                    'sound': sound_file
                                })
                        
                        if name:
                            self.actions[name] = {
                                'type': type_, 
                                'frames': animations
                            }
            except Exception as e:
                print(f"Error parsing actions.xml: {e}")

            # Pre-load Images
            for file_info in z.infolist():
                if file_info.filename.lower().endswith('.png'):
                    # The xml refers to "/shime1.png", ensure key matches
                    # Usually XML uses "/shime1.png" or "shime1.png"
                    # Zip has "img/shime1.png"
                    base = os.path.basename(file_info.filename)
                    key = "/" + base 
                    # Also store without slash just in case
                    key2 = base 
                    
                    data = z.read(file_info)
                    image = QImage.fromData(data)
                    pix = QPixmap.fromImage(image)
                    self.images[key] = pix
                    self.images[key2] = pix

    def set_action(self, action_name):
        # Try exact match
        if action_name in self.actions:
            self.current_action = self.actions[action_name]
            self.current_action_name = action_name
            self.frame_index = 0
            self.ticks_in_frame = 0
            return

        # Try Partial Match (e.g. "Walk" finds "Walk1")
        # Prefer shorter matches (Walk matches Walk1 before Walk_Special)
        candidates = [k for k in self.actions.keys() if action_name in k]
        if candidates:
            # Sort by length to pick "Walk" over "WalkWithEars" if both exist, or "Walk1"
            candidates.sort(key=len)
            best = candidates[0]
            self.current_action = self.actions[best]
            self.current_action_name = best
            self.frame_index = 0
            self.ticks_in_frame = 0
            return

        # Fallback to "Stand" if possible
        if "Stand" in self.actions:
             self.current_action = self.actions["Stand"]
             self.current_action_name = "Stand"
             self.frame_index = 0
             self.ticks_in_frame = 0
             return

        # Ultimate Fallback
        if self.actions:
             name = list(self.actions.keys())[0]
             self.current_action = self.actions[name]
             self.current_action_name = name

    def update_volume(self):
        vol = self.config.get("volume", 50) / 100.0
        for sound in self.sounds.values():
            sound.setVolume(vol)

    def game_loop(self):
        self.update_animation()

        if self.dragging:
            self.set_action("Pinched") 
            self.velocity_x = 0
            self.velocity_y = 0
            return

        # Use internal float position
        foot_x = self._x_float + self.current_anchor_x
        foot_y = self._y_float + self.current_anchor_y

        # Environment - cached in loop to avoid lookups
        screens = WindowManager.get_screens_info()
        current_screen = WindowManager.get_screen_at(foot_x, foot_y)
        sl, st, sr, sb = current_screen
        
        # Determine Floor (Global Awareness)
        target_floor = WindowManager.get_floor_at(foot_x, foot_y)        
        # Check for Windows for FLOOR
        if self.config.get("interact_windows", True):
            win = WindowManager.get_window_under_foot(foot_x, foot_y, int(self.winId()), self.velocity_y)
            if win:
                target_floor = win[1][1]
                self.current_window = win
            else:
                self.current_window = None

        on_floor = False
        ts = self.time_scale
        allowed_sink = MAX_FALL_SPEED * ts
        
        # Snap to floor logic (Only if falling)
        if self.velocity_y >= 0:
            if foot_y >= target_floor - 5 and foot_y <= target_floor + allowed_sink:
                 self._y_float = target_floor - self.current_anchor_y
                 on_floor = True
                 self.velocity_y = 0.0
                 foot_y = target_floor
            elif foot_y > target_floor:
                 self._y_float = target_floor - self.current_anchor_y
                 on_floor = True
                 self.velocity_y = 0.0
                 foot_y = target_floor

        # Prevent "Walking" or "Sitting" in the Sky
        # If we are above the monitor floor and not standing on a window, force falling behavior
        is_in_sky = foot_y < st - 10
        if is_in_sky and not self.current_window and self.current_behavior not in ["Thrown", "Cling", "Climb"]:
             self.current_behavior = "Fall"
             self.set_action("Falling")
             
        # High-Velocity Recovery (Faster Gravity when way off screen)
        # 10x gravity if more than 2000px up, 5x if more than 500px up
        gravity_mult = 1.0
        if foot_y < st - 2000:
            gravity_mult = 10.0
        elif foot_y < st - 500:
            gravity_mult = 5.0 
        
        # --- Corner Failsafe ---
        # Only true outer edges (no monitor in that direction)
        at_left_edge = abs(foot_x - sl) < 15 and not WindowManager.is_x_in_any_monitor(foot_x - 20)
        at_right_edge = abs(foot_x - sr) < 15 and not WindowManager.is_x_in_any_monitor(foot_x + 20)
        at_bottom_edge = abs(foot_y - target_floor) < 15
        
        if (at_left_edge or at_right_edge) and at_bottom_edge:
            self.corner_ticks += 1
            if self.corner_ticks >= 5 * self.fps:
                # LAUNCH toward center of monitor
                self.corner_ticks = 0
                cx, cy = (sl + sr) / 2, (st + sb) / 2
                dx = cx - foot_x
                dy = cy - foot_y
                dist = math.sqrt(dx*dx + dy*dy)
                if dist > 0:
                    # Teleport OUT of the corner first to clear any 'sticky' boundary checks
                    nudge = 20
                    nx = foot_x + (dx / dist) * nudge
                    ny = foot_y + (dy / dist) * nudge
                    self._x_float = nx - self.current_anchor_x
                    self._y_float = ny - self.current_anchor_y
                    self.move(int(self._x_float), int(self._y_float))

                    # Random "bounce" velocity biased toward center
                    power = random.uniform(self.config.get("launch_power_min", 15), self.config.get("launch_power_max", 25))
                    self.velocity_x = (dx / dist) * power + random.uniform(-2, 2)
                    self.velocity_y = (dy / dist) * power - 20 # Stronger upward kick
                    self.current_behavior = "Thrown"
                    self.set_action("Falling")
                    return # Skip rest of loop for this tick
        else:
            self.corner_ticks = 0

        # Behavior Logic
        if self.current_behavior == "Thrown":
            if on_floor:
                self.current_behavior = "Stand"
                self.set_action("Stand")
                self.velocity_x = 0.0
                self.velocity_y = 0.0
            else:
                self.velocity_y += GRAVITY * ts * gravity_mult
                if self.velocity_y > MAX_FALL_SPEED: self.velocity_y = MAX_FALL_SPEED
                self.velocity_x *= (0.99 ** ts) 
                
                # Check for Wall Hit while flying
                if foot_y < target_floor - 10:
                    hit_info = WindowManager.get_vertical_wall_collision(foot_x, foot_y, self.velocity_x * ts, int(self.winId()))
                    if hit_info:
                        side, wall_x, is_sky_wall, is_window = hit_info
                        # Only hit if moving TOWARDS the wall
                        if (side == "Left" and self.velocity_x < -1) or (side == "Right" and self.velocity_x > 1):
                            if is_sky_wall:
                                # BOUNCE off sky wall
                                self.velocity_x *= -0.6
                                self._x_float = wall_x - self.current_anchor_x
                            else:
                                # CLING to wall (Window or Monitor boundary)
                                self.current_behavior = "Cling"
                                self.velocity_x = 0.0
                                self.velocity_y = 0.0
                                self.climb_wall_x = wall_x # Store for pinning
                                self._x_float = wall_x - self.current_anchor_x
                                self.facing_right = (side == "Right") 
                                self.set_action("GrabWall" if "GrabWall" in self.actions else "Pinched")

        elif self.current_behavior == "Cling":
            self.velocity_x = 0.0
            self.velocity_y = 0.0
            # Pin to wall
            if hasattr(self, 'climb_wall_x'):
                self._x_float = self.climb_wall_x - self.current_anchor_x
                
            if on_floor:
                self.current_behavior = "Stand"
                self.set_action("Stand")
            elif random.random() < 0.02 * ts:
                self.current_behavior = "Climb"
                self.set_action("ClimbWall" if "ClimbWall" in self.actions else "GrabWall")
            elif random.random() < 0.005 * ts:
                self.current_behavior = "Fall"
                self.velocity_x = -5.0 if self.facing_right else 5.0
                
        elif self.current_behavior == "Climb":
             self.velocity_x = 0.0
             self.velocity_y = -3.0 * ts
             # Pin to wall
             if hasattr(self, 'climb_wall_x'):
                 self._x_float = self.climb_wall_x - self.current_anchor_x
             
             if self.current_action_name != "ClimbWall":
                 self.set_action("ClimbWall" if "ClimbWall" in self.actions else "GrabWall")
             
             if foot_y <= st + 30:
                 self.current_behavior = "Fall"
                 self.velocity_x = -5.0 if self.facing_right else 5.0
             
             if random.random() < 0.01 * ts:
                 self.current_behavior = "Fall"

        elif self.current_behavior == "Fall":
            if on_floor:
                self.current_behavior = "Stand"
                self.set_action("Stand")
            else:
                self.velocity_y += GRAVITY * ts * gravity_mult
                if self.velocity_y > MAX_FALL_SPEED: self.velocity_y = MAX_FALL_SPEED
                if self.current_action_name != "Falling" and self.velocity_y > 2:
                    self.set_action("Falling")

        elif self.current_behavior == "Walk":
            if not on_floor:
                self.current_behavior = "Fall"
            else:
                vx = 4.0 * ts
                dx = vx if self.facing_right else -vx
                self.velocity_x = dx
                
                # Check for walls
                hit_info = WindowManager.get_vertical_wall_collision(foot_x, foot_y, dx * ts, int(self.winId()))
                if hit_info:
                    side, wall_x, is_sky_wall, is_window = hit_info
                    # Only hit if moving TOWARDS the wall
                    if (side == "Left" and self.velocity_x < 0) or (side == "Right" and self.velocity_x > 0):
                        if not is_sky_wall and random.random() < 0.1:
                                self.current_behavior = "Cling"
                                self.climb_wall_x = wall_x
                                self._x_float = wall_x - self.current_anchor_x
                                self.facing_right = (side == "Right")
                                self.set_action("GrabWall" if "GrabWall" in self.actions else "Pinched")
                        else:
                                self.facing_right = not self.facing_right
                                self.velocity_x = -dx
                
                if random.random() < 0.02 * ts:
                    self.current_behavior = "Stand"
                    self.set_action("Stand")
                    self.velocity_x = 0.0

        elif self.current_behavior in ["Stand", "Sit"]:
            self.velocity_x = 0.0
            if on_floor and hasattr(self, 'climb_wall_x'):
                delattr(self, 'climb_wall_x')

            if not on_floor:
                self.current_behavior = "Fall"
            elif random.random() < 0.005 * ts:
                self.current_behavior = "Walk"
                # If hit a wall, Walk behavior will handle the turn
            elif random.random() < 0.002 * ts:
                new_state = "Sit" if self.current_behavior == "Stand" else "Stand"
                self.current_behavior = new_state
                self.set_action(new_state)
            else:
                if self.current_action_name != self.current_behavior:
                    self.set_action(self.current_behavior)

        # Final Position Application
        self._x_float += self.velocity_x * ts
        self._y_float += self.velocity_y * ts

        # Unified Boundary Clamping (Total Desktop)
        min_x = min(s[0] for s in screens)
        max_x = max(s[2] for s in screens)
        
        # Re-calc local foot_x after movement
        new_fx = self._x_float + self.current_anchor_x
        if new_fx < min_x:
            self._x_float = min_x - self.current_anchor_x
            if self.velocity_x < 0: self.velocity_x = 0
        elif new_fx > max_x:
            self._x_float = max_x - self.current_anchor_x
            if self.velocity_x > 0: self.velocity_x = 0

        # Strict Animation State Enforcement
        # Ensure visual state matches physical state to prevent moonwalking
        is_moving_horizontally = abs(self.velocity_x) > 0.1
        
        # Only enforce for standard floor behaviors
        if on_floor and self.current_behavior in ["Walk", "Stand", "Sit"]:
            if is_moving_horizontally:
                # Physical: Moving. Visual: Must NOT be static.
                # If current action looks static (Standard Stand/Sit), force Walk.
                if "Walk" not in self.current_action_name and "Run" not in self.current_action_name:
                     self.set_action("Walk")
            else:
                # Physical: Still. Visual: Must NOT be moving.
                if "Walk" in self.current_action_name or "Run" in self.current_action_name:
                     self.set_action("Stand")

        # Use rounding for the actual widget move
        self.move(int(self._x_float), int(self._y_float))

    def update_animation(self):
        if not self.current_action: return
        frames = self.current_action['frames']
        if not frames: return

        # Strict Animation State Enforcement
        # Ensure that if we are climbing, we play a climbing action.
        # If the current action is Walk but behavior is Cling/Climb, force correction.
        if self.current_behavior in ["Cling", "Climb"] and "Walk" in self.current_action_name:
             self.set_action("ClimbWall" if "ClimbWall" in self.actions else "GrabWall")

        frame = frames[self.frame_index % len(frames)]
        
        self.current_anchor_x = frame['ax']
        self.current_anchor_y = frame['ay']

        # Sound
        if self.config.get("sound", True) and frame.get('sound') and self.ticks_in_frame == 0:
            sound_name = os.path.basename(frame['sound'])
            if sound_name in self.sounds:
                s = self.sounds[sound_name]
                s.setVolume(self.config.get("volume", 50) / 100.0)
                s.play()

        # Image
        pixmap = self.images.get(frame['image']) or self.images.get(os.path.basename(frame['image']))
        if pixmap:
            final = pixmap
            if self.facing_right:
                final = pixmap.transformed(QTransform().scale(-1, 1))
            self.resize(final.size())
            self.setMask(final.mask())
            self.current_pixmap = final
            self.update()

        # Normalize animation speed?
        # Duration is in ticks (shimeji spec). 
        # If we change tick rate, we change animation speed.
        # We want animation to be constant time.
        # Duration 5 ticks at 30FPS = 166ms.
        # At 30FPS (33ms tick), 5 ticks = 165ms.
        # At 60FPS (16ms tick), 5 ticks = 80ms (too fast).
        # We should accumulate ticks scaled by time_scale?
        # self.ticks_in_frame += 1 * ts?
        self.ticks_in_frame += self.time_scale
        
        if self.ticks_in_frame >= frame['duration']:
            self.ticks_in_frame = 0
            self.frame_index += 1

    def paintEvent(self, event):
        if hasattr(self, 'current_pixmap'):
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self.current_pixmap)
            
    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            self.current_behavior = "Dragged"
            self.last_pos = event.globalPosition().toPoint()
            self.velocity_history = []

    def mouseMoveEvent(self, event):
        if self.dragging:
            curr = event.globalPosition().toPoint()
            self.move(curr - self.drag_offset)
            self._x_float = float(self.x())
            self._y_float = float(self.y())
            delta = curr - self.last_pos
            self.velocity_history.append(delta)
            if len(self.velocity_history) > 5:
                self.velocity_history.pop(0)
            self.last_pos = curr

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            
            if hasattr(self, 'velocity_history') and self.velocity_history:
                avg_x = sum(p.x() for p in self.velocity_history) / len(self.velocity_history)
                avg_y = sum(p.y() for p in self.velocity_history) / len(self.velocity_history)
                self.velocity_x = avg_x * 1.5 
                self.velocity_y = avg_y * 1.5
                self.current_behavior = "Thrown"
            else:
                self.current_behavior = "Fall"
                self.velocity_y = 0
            
            # Immediate bounds check to prevent floating out of screen
            x = self.x()
            y = self.y()
            fx, fy = x + self.current_anchor_x, y + self.current_anchor_y
            screen = WindowManager.get_screen_at(fx, fy)
            if fx < screen[0]: self.move(screen[0] - self.current_anchor_x, y)
            if fx > screen[2]: self.move(screen[2] - self.current_anchor_x, y)
            
            # CRITICAL: Sync float coordinates after hard move
            self._x_float = float(self.x())
            self._y_float = float(self.y())
