import win32gui
import win32con
import win32api
import win32process
import ctypes
import time
import os
import math

class WindowManager:
    _window_cache = []
    _last_cache_time = 0
    CACHE_DURATION = 0.5 

    @staticmethod
    def update_cache():
        """Refreshes the internal list of window rects, excluding PyShimeji itself and fullscreen windows."""
        now = time.time()
        if now - WindowManager._last_cache_time < WindowManager.CACHE_DURATION:
            return
        
        my_pid = os.getpid()
        new_cache = []
        
        # Get screen areas for fullscreen detection
        screens = WindowManager.get_screens_info()
        
        def enum_handler(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                # Exclude windows belonging to our own process
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == my_pid: return
                
                title = win32gui.GetWindowText(hwnd)
                if title and title not in ["Program Manager", "Settings", "Microsoft Text Input Application"]:
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                        w = rect[2] - rect[0]
                        h = rect[3] - rect[1]
                        
                        if w > 50 and h > 50:
                            # Check if fullscreen (covers any monitor)
                            is_fullscreen = False
                            for s in screens:
                                # Fullscreen window matches or exceeds monitor bounds
                                # We use a small tolerance or just >= check
                                if rect[0] <= s[0] and rect[1] <= s[1] and rect[2] >= s[2] and rect[3] >= s[3]:
                                    is_fullscreen = True
                                    break
                            
                            if not is_fullscreen:
                                new_cache.append((hwnd, rect, title))
                    except: pass
        
        win32gui.EnumWindows(enum_handler, None)
        WindowManager._window_cache = new_cache
        WindowManager._last_cache_time = now

    @staticmethod
    def get_windows():
        WindowManager.update_cache()
        return WindowManager._window_cache

    @staticmethod
    def get_window_under_foot(foot_x, foot_y, current_hwnd_to_ignore, velocity_y=0):
        # Only snap if falling
        if velocity_y < 0: return None
        
        WindowManager.update_cache()
        for hwnd, rect, title in WindowManager._window_cache:
            if hwnd == current_hwnd_to_ignore: continue
            left, top, right, bottom = rect
            if left <= foot_x <= right:
                if abs(foot_y - top) < 15:
                    return (hwnd, rect)
        return None

    @staticmethod
    def move_window(hwnd, dx, dy):
        try:
            rect = win32gui.GetWindowRect(hwnd)
            x, y = rect[0], rect[1]
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            win32gui.MoveWindow(hwnd, x + dx, y + dy, w, h, True)
        except: pass

    @staticmethod
    def get_screens_info():
        screens = []
        monitors = win32api.EnumDisplayMonitors()
        for monitor in monitors:
            info = win32api.GetMonitorInfo(monitor[0])
            screens.append(info['Monitor'])
        return screens

    @staticmethod
    def get_screen_at(x, y):
        screens = WindowManager.get_screens_info()
        if not screens: return (0, 0, 1920, 1080)
        for s in screens:
            # Lenient vertical check (100px buffer) to handle staggered monitors
            if s[0] <= x <= s[2] and s[1]-100 <= y <= s[3]+100:
                return s
        
        # If not inside any, return the closest one horizontally
        def horiz_dist(px, rect):
            if rect[0] <= px <= rect[2]: return 0
            return min(abs(rect[0] - px), abs(rect[2] - px))
        
        return min(screens, key=lambda s: horiz_dist(x, s))

    @staticmethod
    def get_floor_at(x, y):
        screens = WindowManager.get_screens_info()
        if not screens: return 1080 - 50
        
        # Find all screens that contain this X coordinate
        candidates = [s for s in screens if s[0] <= x <= s[2]]
        
        if not candidates:
            # In a gap? Use the closest screen horizontally
            def horiz_dist(px, rect):
                if rect[0] <= px <= rect[2]: return 0
                return min(abs(rect[0] - px), abs(rect[2] - px))
            closest = min(screens, key=lambda s: horiz_dist(x, s))
            return closest[3] - 50
        
        # Of the candidates that share this X, find the one that actually contains Y,
        # or the first one whose top is below Y (the one we would fall onto).
        candidates.sort(key=lambda s: s[1])
        
        # Default to the bottom-most floor in case we're below all screens
        best_floor = candidates[-1][3] - 50 
        
        for s in candidates:
            if s[1] <= y <= s[3]:
                # We are inside this screen's vertical range
                return s[3] - 50
            if s[1] > y:
                # This screen is below us; it's the next floor we'd hit
                return s[3] - 50
                
        return best_floor

    @staticmethod
    def is_x_in_any_monitor(x, buffer=5):
        screens = WindowManager.get_screens_info()
        for s in screens:
            if s[0] - buffer <= x <= s[2] + buffer:
                return True
        return False

    @staticmethod
    def get_vertical_wall_collision(x, y, dx, current_hwnd_to_ignore):
        screens = WindowManager.get_screens_info()
        WindowManager.update_cache()
        target_x = x + dx
        
        # Check if target_x is within ANY monitor's X-range (the "Sky")
        # Use a small buffer to handle rounding/tiny gaps
        found_next_space = WindowManager.is_x_in_any_monitor(target_x, buffer=5)
        
        if not found_next_space:
            curr_s = WindowManager.get_screen_at(x, y)
            # Check if we are above the monitor (Sky)
            is_sky = y < curr_s[1]
            # Return: (Side, X, is_sky, is_window)
            if dx < 0: return ('Left', curr_s[0], is_sky, False)
            else: return ('Right', curr_s[2], is_sky, False)

        # Window Edges from Cache (Only if NOT in sky)
        margin = 25
        for hwnd, rect, title in WindowManager._window_cache:
            if hwnd == current_hwnd_to_ignore: continue
            left, top, right, bottom = rect
            # Vertical overlap check
            if top < y < bottom:
                if dx > 0 and abs(x - left) < margin: return ('Right', left, False, True)
                if dx < 0 and abs(x - right) < margin: return ('Left', right, False, True)
        return None
