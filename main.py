import pygame
import json
import random
import os
from input_handler import InputHandler
import gesture_control as gc
import threading
import queue
import shutil
import tkinter as tk
from tkinter import simpledialog, ttk
import magic
from magic import append_command_sequence, try_cast_spell_from_sequence, cast_spell
import math
import socketserver
import json as _json

# Debug control: set to True to re-enable in-game debug logging
ENABLE_DEBUG = False

def debug_print(*args, **kwargs):
    """Print only when ENABLE_DEBUG is True."""
    if ENABLE_DEBUG:
        print(*args, **kwargs)

def dump_all_thread_stacks() -> None:
    """Print stack traces for all live threads to stdout (debug helper).

    This is intended as a lightweight, best-effort debugging helper used from
    the main thread. It uses sys._current_frames() to get per-thread frames and
    prints a readable stack for each thread. Exceptions are caught to avoid
    impacting the running program.
    """
    try:
        import threading
        import sys
        import traceback
    except Exception:
        debug_print('[THREAD DUMP] Required modules missing; cannot dump thread stacks', flush=True)
        return

    try:
        frames = sys._current_frames()
    except Exception as e:
        debug_print(f'[THREAD DUMP] sys._current_frames() unavailable: {e}', flush=True)
        return

    debug_print('\n[THREAD DUMP] Dumping stacks for all threads', flush=True)
    try:
        for thr in threading.enumerate():
            try:
                tid = thr.ident
                name = getattr(thr, 'name', '<unnamed>')
                debug_print(f'--- Thread: "{name}" id={tid} ---', flush=True)
                frame = frames.get(tid)
                if frame is None:
                    debug_print('  (no frame available for this thread)')
                    continue
                # Print formatted stack for the frame
                traceback.print_stack(frame)
            except Exception as inner:
                debug_print(f'  [THREAD DUMP ERROR] failed to dump thread {getattr(thr, "name", None)}: {inner}', flush=True)
    except Exception as e:
        debug_print(f'[THREAD DUMP] Unexpected error while dumping threads: {e}', flush=True)
    debug_print('[THREAD DUMP] End\n', flush=True)


# Try importing gesture_control for gesture studio
# try:
#     import gesture_control
# except ImportError:
#     gesture_control = None

# Constants
SCREEN_WIDTH = int(1600 * 0.9 * 0.9)
SCREEN_HEIGHT = int(1200 * 0.9 * 0.9)
FPS = 60
PLAYER_HEALTH = 100
PLAYER_MANA = 50
MANA_REGEN = 5  # per second
SHIELD_DURATION = 3  # seconds
SHIELD_BLOCK = 0.7  # 70% block
MIN_SPAWN_TIME = 2.0
MAX_SPAWN_TIME = 4.0
GESTURE_DIRECTORY = 'GestureDir'
GESTURE_DEBOUNCE_TIME = 0.7  # seconds
# Vertical pixel position (from top) where component icons, cast-display and gesture feedback should be centered
# Previously this was 1000 (off the bottom for typical window sizes). Use a value
# near the top so feedback appears where users expect it.
FEEDBACK_CENTER = 140
# Scale applied to obstacle speeds loaded from config (allows easy tuning)
OBSTACLE_SPEED_SCALE = 0.75

# Initialize magic module
magic.initialize_magic(os.path.dirname(__file__))

# Load configuration files
def load_config(filename):
    """
    Load a JSON configuration file and return its contents.
    Args:
        filename (str): Path to the JSON file.
    Returns:
        dict or list: Parsed JSON data.
    """
    with open(filename, 'r') as f:
        return json.load(f)

SPELLS = load_config(os.path.join(os.path.dirname(__file__), 'spells.json'))
OBSTACLES = load_config(os.path.join(os.path.dirname(__file__), 'obstacles.json'))

# Helper: get spell by recipe
SPELL_RECIPES = {tuple(spell['recipe']): spell for spell in SPELLS}
MAX_SPELL_LENGTH = max(len(spell['recipe']) for spell in SPELLS)

# Obstacle visual properties (color, shape)
OBSTACLE_VISUALS = {
    'Rock': {'color': (120, 120, 120), 'shape': 'circle'},
    'Ice Shard': {'color': (100, 200, 255), 'shape': 'triangle'},
    'Wooden Crate': {'color': (160, 100, 40), 'shape': 'rect'},
    'Fire Orb': {'color': (255, 80, 40), 'shape': 'circle'},
    'Steel Block': {'color': (180, 180, 200), 'shape': 'rect'},
}

# Damage indicator class
class DamageIndicator:
    def __init__(self, amount, x, y):
        """
        Initialize a damage indicator to display damage taken.
        Args:
            amount (int or str): Damage amount to display.
            x (int): X position.
            y (int): Y position.
        """
        self.amount = amount
        self.x = x
        self.y = y
        self.alpha = 255
        self.timer = 0.8  # seconds

    def update(self, dt):
        """
        Update the position and timer of the damage indicator.
        Args:
            dt (float): Time delta in seconds.
        """
        self.y -= 60 * dt  # float up
        self.timer -= dt
        self.alpha = int(255 * (self.timer / 0.8))

    def is_alive(self):
        """
        Check if the damage indicator is still active.
        Returns:
            bool: True if active, False otherwise.
        """
        return self.timer > 0

# Predict intercept helper: placed before ProjectileEffect so it's available when creating projectiles
def predict_intercept(start_x, start_y, target_x, target_y, target_vx, target_vy, projectile_speed):
    """
    Predict interception point where a projectile launched from (start_x,start_y)
    at speed `projectile_speed` (pixels/sec) meets a target at (target_x,target_y)
    moving with velocity (target_vx, target_vy) in pixels/sec.

    Returns (pred_x, pred_y). If no feasible intercept is found, returns the
    target's current position.
    """
    # Relative vector from shooter to target
    dx = target_x - start_x
    dy = target_y - start_y
    # Quadratic coefficients for ||(dx + v_t * t)||^2 = (v_p * t)^2
    # (v_t^2 - v_p^2) t^2 + 2*(dx*tvx + dy*tvy) t + dx^2 + dy^2 = 0
    a = (target_vx**2 + target_vy**2) - (projectile_speed**2)
    b = 2 * (dx * target_vx + dy * target_vy)
    c = dx*dx + dy*dy
    # If a is approximately 0, solve linear b t + c = 0
    eps = 1e-6
    t = None
    if abs(a) < eps:
        if abs(b) > eps:
            t_candidate = -c / b
            if t_candidate > 0:
                t = t_candidate
    else:
        disc = b*b - 4*a*c
        if disc >= 0:
            sqrt_d = math.sqrt(disc)
            t1 = (-b + sqrt_d) / (2*a)
            t2 = (-b - sqrt_d) / (2*a)
            # choose smallest positive t
            candidates = [tt for tt in (t1, t2) if tt > 0]
            if candidates:
                t = min(candidates)
    if t is None or t < 0:
        # no intercept found; return current target position
        return int(target_x), int(target_y)
    pred_x = target_x + target_vx * t
    pred_y = target_y + target_vy * t
    return int(pred_x), int(pred_y)

class ProjectileEffect:
    """
    Wrap a spell effect and animate a projectile flying from a start
    position toward a target position. Can operate in two modes:
      - wrap_mode: take an existing base_effect (SpellEffect) and animate its position
      - deferred_mode: hold spell metadata and call cast_spell(...) when the projectile arrives

    Args (wrap_mode): base_effect provided
    Args (deferred_mode): base_effect is None, and spell + owner provided
    """
    def __init__(self, base_effect=None, start_x=0, start_y=0, target_pos=(0,0), speed=900, *, spell=None, owner=None):
        # If base_effect is provided we're wrapping an existing SpellEffect
        self.base = base_effect
        try:
            self.spell = getattr(base_effect, 'spell', spell or {})
        except Exception:
            self.spell = spell or {}
        self.x = float(start_x)
        self.y = float(start_y)
        self.timer = getattr(base_effect, 'timer', 1.0)
        self.target_x = float(target_pos[0])
        self.target_y = float(target_pos[1])
        self.speed = float(speed)
        self.arrived = False
        self.trail = []
        self._max_trail = 12
        # Deferred casting support
        self.deferred = base_effect is None and spell is not None and owner is not None
        self.owner = owner  # expected to be Game instance when deferred or when wrapping
        self.executed = False
        self.hide_projectile = False
        try:
            if self.base is not None:
                self.base.x = int(self.x)
                self.base.y = int(self.y)
        except Exception:
            pass

    def update(self, dt):
        """Move projectile; if deferred mode, call cast_spell on arrival and mark for removal."""
        if not self.arrived:
            dx = self.target_x - self.x
            dy = self.target_y - self.y
            dist = math.hypot(dx, dy) if (dx or dy) else 0.0
            step = self.speed * dt
            if dist <= max(4.0, step) or dist == 0.0:
                self.x, self.y = self.target_x, self.target_y
                self.arrived = True
                # hide projectile visual immediately on arrival
                self.hide_projectile = True
                self.trail.clear()
                # create a short impact flash at arrival (use spell recipe to choose color)
                try:
                    try:
                        recipe = self.spell.get('recipe', []) if isinstance(self.spell, dict) else []
                    except Exception:
                        recipe = []
                    try:
                        rec = [r.lower() for r in recipe]
                    except Exception:
                        rec = recipe
                    col_fire = (255, 140, 50)
                    col_ice = (140, 220, 255)
                    # If the spell is Cataclysm, prefer a purple flash to match projectile color
                    try:
                        spell_name = self.spell.get('name', '') if isinstance(self.spell, dict) else getattr(self.spell, 'name', '') or ''
                    except Exception:
                        spell_name = ''
                    spell_name_lower = spell_name.lower() if isinstance(spell_name, str) else ''
                    # compute brightness factor based on recipe complexity (match draw scaling)
                    try:
                        comp_count = len(recipe)
                    except Exception:
                        comp_count = 0
                    try:
                        extra = max(0, comp_count - 1)
                        scale = 1.0 + 0.3 * extra
                    except Exception:
                        scale = 1.0
                    # choose base flash color, with Cataclysm override
                    if spell_name_lower == 'cataclysm':
                        base_flash = (160, 32, 240)
                    else:
                        base_flash = col_fire if 'fire' in rec else col_ice if 'ice' in rec else (220,220,220)
                    # brighten flash color by scale and clamp
                    try:
                        flash_color = tuple(min(255, int(c * scale)) for c in base_flash)
                    except Exception:
                        flash_color = base_flash
                    if self.owner is not None and hasattr(self.owner, 'area_effect_rings'):
                        # Use ImpactFlash for a short filled flash
                        try:
                            self.owner.area_effect_rings.append(magic.ImpactFlash(int(self.x), int(self.y), flash_color, max_radius=30, duration=0.12))
                        except Exception:
                            pass
                except Exception:
                    pass
                # Sync base if wrapping
                try:
                    if self.base is not None:
                        self.base.x = int(self.x)
                        self.base.y = int(self.y)
                        self.base.timer = max(getattr(self.base, 'timer', 0.1), 0.6)
                except Exception:
                    pass
            else:
                nx = dx / dist
                ny = dy / dist
                self.x += nx * step
                self.y += ny * step
                try:
                    if self.base is not None:
                        self.base.x = int(self.x)
                        self.base.y = int(self.y)
                except Exception:
                    pass

            # trail bookkeeping
            self.trail.append((self.x, self.y))
            if len(self.trail) > self._max_trail:
                self.trail.pop(0)
            # expose timer (proxy to base if present)
            self.timer = getattr(self.base, 'timer', self.timer)
        else:
            # If we've arrived and we're in deferred mode, execute the actual spell now
            if self.deferred and not self.executed:
                try:
                    # also create a short impact flash so arrival is visible
                    try:
                        try:
                            recipe = self.spell.get('recipe', []) if isinstance(self.spell, dict) else []
                        except Exception:
                            recipe = []
                        try:
                            rec = [r.lower() for r in recipe]
                        except Exception:
                            rec = recipe
                        col_fire = (255, 140, 50)
                        col_ice = (140, 220, 255)
                        try:
                            spell_name = self.spell.get('name', '') if isinstance(self.spell, dict) else getattr(self.spell, 'name', '') or ''
                        except Exception:
                            spell_name = ''
                        spell_name_lower = spell_name.lower() if isinstance(spell_name, str) else ''
                        # brightness based on recipe complexity
                        try:
                            comp_count = len(recipe)
                        except Exception:
                            comp_count = 0
                        try:
                            extra = max(0, comp_count - 1)
                            scale = 1.0 + 0.3 * extra
                        except Exception:
                            scale = 1.0
                        if spell_name_lower == 'cataclysm':
                            base_flash = (160, 32, 240)
                        else:
                            base_flash = col_fire if 'fire' in rec else col_ice if 'ice' in rec else (220,220,220)
                        try:
                            flash_color = tuple(min(255, int(c * scale)) for c in base_flash)
                        except Exception:
                            flash_color = base_flash
                        if self.owner is not None and hasattr(self.owner, 'area_effect_rings'):
                            try:
                                self.owner.area_effect_rings.append(magic.ImpactFlash(int(self.target_x), int(self.target_y), flash_color, max_radius=30, duration=0.12))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Call cast_spell to apply damage/area and to append underlying SpellEffect(s)
                    last_spell, last_spell_weakness, last_spell_timer = cast_spell(
                        self.spell, self.owner.player, self.owner.spell_effects, self.owner.area_effect_rings, self.owner.obstacles)
                    # Update owner's last-spell info from the result
                    try:
                        self.owner.last_spell = last_spell
                        self.owner.last_spell_weakness = last_spell_weakness
                        self.owner.last_spell_timer = last_spell_timer
                    except Exception:
                        pass
                except Exception:
                    pass
                # Mark executed and ensure the projectile is removed immediately
                self.executed = True
                # use negative timer to ensure removal during game.update filtering
                self.timer = -1.0
                # clear trail to avoid lingering drawing
                self.trail.clear()
                return

            # Normal wrapping mode: let base effect update (this will advance impact timers)
            if self.base is not None:
                try:
                    self.base.update(dt)
                    self.timer = getattr(self.base, 'timer', self.timer)
                    # keep positions synced
                    self.x = getattr(self.base, 'x', self.x)
                    self.y = getattr(self.base, 'y', self.y)
                except Exception:
                    # If base has no update, just decay timer
                    self.timer = max(0.0, self.timer - dt)

    def draw(self, surface):
        # Don't draw projectile visuals after arrival
        if getattr(self, 'hide_projectile', False):
            return
        try:
            recipe = self.spell.get('recipe', []) if isinstance(self.spell, dict) else []
        except Exception:
            recipe = []
        # normalize recipe strings to lowercase for robust checks
        try:
            recipe = [r.lower() for r in recipe]
        except Exception:
            recipe = recipe
        col_fire = (255, 140, 50)
        col_ice = (140, 220, 255)
        # choose base color from recipe but allow a spell-name override (e.g., Cataclysm -> purple)
        base_col = col_fire if 'fire' in recipe else col_ice if 'ice' in recipe else (200,200,200)
        try:
            spell_name = self.spell.get('name', '') if isinstance(self.spell, dict) else getattr(self.spell, 'name', '') or ''
        except Exception:
            spell_name = ''
        spell_name_lower = spell_name.lower() if isinstance(spell_name, str) else ''
        if spell_name_lower == 'cataclysm':
            purple = (160, 32, 240)
            base_col = purple

        # compute scale: base size for single-component spells, +30% per extra component
        try:
            comp_count = len(recipe)
        except Exception:
            comp_count = 0
        try:
            extra = max(0, comp_count - 1)
            scale = 1.0 + 0.3 * extra
        except Exception:
            scale = 1.0
        # brightness proportional to complexity (use same scale as size)
        try:
            brightness = float(scale)
        except Exception:
            brightness = 1.0
        # helper to brighten and clamp colors
        def _brighten(col, b):
            try:
                return tuple(min(255, int(c * b)) for c in col)
            except Exception:
                return col
        bright_base_col = _brighten(base_col, brightness)

        # trail (fading circles)
        for i, (tx, ty) in enumerate(self.trail):
            t = (i + 1) / max(1, len(self.trail))
            # increase alpha with brightness as well (clamped)
            alpha = min(255, int(200 * t * brightness))
            # base trail radius scales with t; apply overall scale
            radius = max(1, int((10 * t) * scale)) + 2
            s = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
            s_col = bright_base_col + (alpha,)
            pygame.draw.circle(s, s_col, (radius, radius), radius)
            surface.blit(s, (int(tx)-radius, int(ty)-radius))

        # projectile head
        # head color: override to purple for Cataclysm, otherwise element-based
        try:
            if spell_name_lower == 'cataclysm':
                head_base = (160, 32, 240)
            else:
                head_base = (255, 100, 0) if 'fire' in recipe else (100, 200, 255) if 'ice' in recipe else (220,220,220)
            # brighten head color by brightness
            head_col = _brighten(head_base, brightness)
            head_radius = max(2, int(round(12 * scale)))
            pygame.draw.circle(surface, head_col, (int(self.x), int(self.y)), head_radius)
        except Exception:
            pass

# Player class
class Player:
    def __init__(self):
        """
        Initialize the player with health, mana, shield, and position.
        """
        self.health = PLAYER_HEALTH
        # use floats for mana so regen math is unambiguous to type checkers
        self.mana = float(PLAYER_MANA)
        self.max_mana = float(PLAYER_MANA)
        self.shield = False
        self.shield_timer = 0
        self.score = 0
        self.last_damage = 0
        self.damage_indicator = None
        # Add position attributes for spell effects
        self.x = SCREEN_WIDTH // 2
        self.y = SCREEN_HEIGHT - 200
        self.shield_element = None  # Track shield element for ice/fire shields

    def regen_mana(self, dt):
        """
        Regenerate player's mana over time.
        Args:
            dt (float): Time delta in seconds.
        """
        self.mana = min(self.max_mana, self.mana + MANA_REGEN * dt)

    def take_damage(self, dmg, game=None):
        """
        Apply damage to the player, considering shield effects.
        Args:
            dmg (int): Damage amount.
            game (Game, optional): Reference to the game for damage indicator.
        """
        if self.shield:
            dmg *= (1 - SHIELD_BLOCK)
        dmg = int(dmg)
        self.health -= dmg
        self.last_damage = dmg
        if game is not None:
            # Show damage indicator above player
            px = SCREEN_WIDTH//2
            py = SCREEN_HEIGHT-200
            game.damage_indicators.append(DamageIndicator(f"-{dmg}", px, py))

    def cast_shield(self):
        """
        Activate the player's shield for a set duration.
        """
        self.shield = True
        self.shield_timer = SHIELD_DURATION

    def update(self, dt):
        """
        Update the player's shield timer and status.
        Args:
            dt (float): Time delta in seconds.
        """
        if self.shield:
            self.shield_timer -= dt
            if self.shield_timer <= 0:
                self.shield = False

# Obstacle class
class Obstacle:
    def __init__(self, config, start_x=None, start_y=None):
        """
        Initialize an obstacle with properties from config.
        Args:
            config (dict): Obstacle configuration.
        """
        self.name = config['name']
        self.max_health = config['health']
        self.health = config['health']
        self.speed = config['speed'] * OBSTACLE_SPEED_SCALE  # Scaleable speed factor
        self.weakness = config['weakness']
        self.damage = config['damage']
        self.points = config['points']
        # Use provided start coordinates when available; otherwise fall back to sensible defaults.
        if start_x is not None:
            # ensure obstacle center stays on-screen considering its draw size (~35px padding)
            self.x = int(max(35, min(SCREEN_WIDTH - 35, start_x)))
        else:
            self.x = random.randint(100, SCREEN_WIDTH - 100)
        if start_y is not None:
            self.y = int(max(0, min(SCREEN_HEIGHT - 100, start_y)))
        else:
            self.y = 100
        self.state = 'alive'  # 'alive', 'destroying'
        self.destroy_timer = 0
        self.visual = OBSTACLE_VISUALS.get(self.name, {'color': (180, 80, 80), 'shape': 'rect'})

    def update(self, dt):
        """
        Update the obstacle's position and destruction timer.
        Args:
            dt (float): Time delta in seconds.
        """
        self.y += self.speed
        if self.state == 'destroying':
            self.destroy_timer -= dt

    def is_half_health(self):
        """
        Check if the obstacle is at half health or less.
        Returns:
            bool: True if at half health or less.
        """
        return self.health <= self.max_health / 2

    def start_destroy(self):
        """
        Begin the obstacle's destruction sequence.
        """
        self.state = 'destroying'
        self.destroy_timer = 0.5

    def draw(self, surface, font):
        """
        Draw the obstacle on the given surface.
        Args:
            surface (pygame.Surface): Surface to draw on.
            font (pygame.font.Font): Font for rendering text.
        """
        color = self.visual['color']
        if self.is_half_health():
            color = tuple(min(255, c + 60) for c in color)  # brighten at half health
        if self.state == 'destroying':
            alpha = int(255 * (self.destroy_timer / 0.5))
        else:
            alpha = 255
        surf = pygame.Surface((70, 70), pygame.SRCALPHA)
        if self.visual['shape'] == 'circle':
            pygame.draw.circle(surf, color + (alpha,), (35, 35), 30)
        elif self.visual['shape'] == 'triangle':
            pygame.draw.polygon(surf, color + (alpha,), [(35, 5), (65, 65), (5, 65)])
        else:  # rect
            pygame.draw.rect(surf, color + (alpha,), (10, 10, 50, 50))
        # Removed name rendering on obstacle
        surface.blit(surf, (self.x-35, self.y-35))

# Main game
class Game:
    def __init__(self):
        """
        Initialize the game, player, UI, and gesture system.
        """
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption('Wizard Spellcaster')
        self.clock = pygame.time.Clock()
        self.running = True
        self.profile_name = 'unded'
        self.update_gesture_paths()
        self.move_existing_gesture_data()
        self.player = Player()
        self.input_handler = InputHandler()
        self.obstacles = []
        self.spell_effects = []
        self.damage_indicators = []
        self.area_effect_rings = []  # List to store active area effect rings
        self.spawn_timer = 0
        # Increased font sizes so UI and component text are more readable
        self.font = pygame.font.SysFont('Arial', 40)
        self.small_font = pygame.font.SysFont('Arial', 30)
        # Add smaller UI fonts for compact HUD elements (health/mana/score, obstacle key)
        self.ui_font = pygame.font.SysFont('Arial', 20)
        self.key_font = pygame.font.SysFont('Arial', 20)
        self.command_sequence = []
        # Storage for showing a transient cast visual (icons + fade rectangle)
        self.cast_display = None  # dict with keys: parts (list), comp_indices (list), timer, duration, rect_pad
        self.last_spell = None
        self.last_spell_weakness = False
        self.last_spell_timer = 0
        self.state = 'start'  # 'start' or 'playing'
        self.input_method = 'Keyboard'  # or 'Gesture'
        self.gesture_recognizer = None
        self.gesture_thread = None
        self.gesture_queue = queue.Queue()
        self.gesture_thread_running = False
        self.menu_options = ['New Game', f'Input Method: {self.input_method}', 'Gesture Studio', 'Switch/Create Profile', 'Quit']
        self.menu_index = 0
        self.gui_request_queue = queue.Queue()  # For thread-safe GUI/dialog requests
        # Persistent Tk root for all dialogs
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()
        # --- Component icon loading (do this once at game instantiation) ---
        # Search for an `icons` directory next to the script and preload images for recipe components
        self.icon_dir = os.path.join(os.path.dirname(__file__), 'icons')
        self.component_icons = {}  # maps component_name -> pygame.Surface
        # Increase icon size used for command/component icons (was 48)
        self.icon_size = 120
        try:
            if os.path.isdir(self.icon_dir):
                # collect component names from SPELLS to be robust/extendable
                comp_names = set()
                try:
                    for sp in SPELLS:
                        try:
                            for r in sp.get('recipe', []):
                                comp_names.add(str(r).lower())
                        except Exception:
                            pass
                except Exception:
                    pass
                files = os.listdir(self.icon_dir)
                for comp in comp_names:
                    found = None
                    for fname in files:
                        if comp in fname.lower():
                            found = fname
                            break
                    if found:
                        fp = os.path.join(self.icon_dir, found)
                        try:
                            img = pygame.image.load(fp).convert_alpha()
                            # Preserve aspect ratio: scale so the largest dimension equals self.icon_size
                            ow, oh = img.get_size()
                            if ow > 0 and oh > 0:
                                if ow >= oh:
                                    new_w = self.icon_size
                                    new_h = max(1, int(oh * (self.icon_size / float(ow))))
                                else:
                                    new_h = self.icon_size
                                    new_w = max(1, int(ow * (self.icon_size / float(oh))))
                                img = pygame.transform.smoothscale(img, (new_w, new_h))
                            else:
                                # Fallback: avoid division by zero, keep original
                                pass
                            self.component_icons[comp] = img
                        except Exception:
                            # ignore any load error and leave fallback to text
                            pass
        except Exception:
            # If anything goes wrong, fall back to entirely text-based sequence
            self.component_icons = {}
        # Frame-push support (optional): if FRAMEPIPE_URL env var is set, the game will
        # capture scaled frames and send JPEGs to the bridge's /framepipe endpoint.
        # This runs in a background thread and uses a small queue to avoid blocking
        # the main game loop. The feature is disabled by default.
        try:
            self.framepipe_url = os.environ.get('FRAMEPIPE_URL')
        except Exception:
            self.framepipe_url = None
        if self.framepipe_url:
            self._frame_pipe_queue = queue.Queue(maxsize=2)
            self._frame_pipe_thread = threading.Thread(target=self._frame_pipe_worker, daemon=True)
            self._frame_pipe_thread.start()
        else:
            self._frame_pipe_queue = None
            self._frame_pipe_thread = None

        # Optional local TCP input listener (accepts JSON lines and posts pygame events).
        # Enabled by setting INPUT_LISTEN_PORT or ENABLE_INPUT_LISTENER=1 in the environment.
        try:
            port_env = os.environ.get('INPUT_LISTEN_PORT')
            enable_input = os.environ.get('ENABLE_INPUT_LISTENER', '0') == '1'
            if port_env:
                self._input_listen_port = int(port_env)
            elif enable_input:
                self._input_listen_port = 5001
            else:
                self._input_listen_port = None
        except Exception:
            self._input_listen_port = None

        if self._input_listen_port:
            self._input_server_thread = threading.Thread(target=self._start_input_server, daemon=True)
            self._input_server_thread.start()
        else:
            self._input_server_thread = None

    def update_gesture_paths(self):
        """
        Update gesture dataset and model paths for the current profile.
        """
        self.profile_dir = os.path.join(GESTURE_DIRECTORY, self.profile_name)
        self.dataset_dir = os.path.join(self.profile_dir, 'datasets')
        self.models_dir = os.path.join(self.profile_dir, 'models')
        os.makedirs(self.dataset_dir, exist_ok=True)
        os.makedirs(self.models_dir, exist_ok=True)

    def move_existing_gesture_data(self):
        """
        Move old gesture datasets/models to the current profile directory if needed.
        """
        # Move old datasets/models to profile if not already there
        old_dataset = os.path.join(GESTURE_DIRECTORY, 'datasets')
        old_models = os.path.join(GESTURE_DIRECTORY, 'models')
        if os.path.exists(old_dataset) and not os.path.exists(self.dataset_dir):
            shutil.move(old_dataset, self.dataset_dir)
        if os.path.exists(old_models) and not os.path.exists(self.models_dir):
            shutil.move(old_models, self.models_dir)

    def request_gui_action(self, action, *args, **kwargs):
        """
        Queue a GUI/dialog action to be executed on the main thread.
        Args:
            action (callable): Function to execute.
            *args: Arguments for the action.
            **kwargs: Keyword arguments for the action.
        """
        self.gui_request_queue.put((action, args, kwargs))

    def process_gui_requests(self):
        """Execute all pending GUI/dialog requests from the queue."""
        while not self.gui_request_queue.empty():
            action, args, kwargs = self.gui_request_queue.get()
            try:
                action(*args, **kwargs)
            except Exception as e:
                print(f"[GUI ERROR] Exception in GUI action: {e}")

    def switch_profile(self):
        """
        Switch to a different gesture profile or create a new one.
        """
        gesture_dir = GESTURE_DIRECTORY
        if not os.path.exists(gesture_dir):
            os.makedirs(gesture_dir)
        profiles = [d for d in os.listdir(gesture_dir) if os.path.isdir(os.path.join(gesture_dir, d))]
        dialog = ProfileDialog(self.tk_root, profiles, title="Switch/Create Profile")
        new_profile = dialog.result
        if new_profile and new_profile.strip():
            self.profile_name = new_profile.strip()
            self.update_gesture_paths()
            self.move_existing_gesture_data()
            # Reset input method to Keyboard when switching profiles
            self.set_input_method('Keyboard')
            self.menu_options[1] = f'Input Method: {self.input_method}'
            self.menu_options[3] = 'Switch/Create Profile'

    def launch_gesture_studio(self):
        """
        Launch the gesture studio for recording and training gestures.
        """
        # Ensure the persistent root stays hidden while studio is open
        self.tk_root.withdraw()
        app = gc.studio(destination=self.dataset_dir,
                       models=self.models_dir,
                       required_gestures=['fire', 'ice', 'projectile', 'shield', 'magnify'],
                       root=self.tk_root)
        self.tk_root.wait_window(app.window)
        self.tk_root.withdraw()

    def handle_input(self):
        """
        Handle user input events for menu navigation and gameplay.
        """
        self.process_gui_requests()  # Always process GUI requests before handling input
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif self.state == 'start':
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        self.menu_index = (self.menu_index - 1) % len(self.menu_options)
                    elif event.key == pygame.K_DOWN:
                        self.menu_index = (self.menu_index + 1) % len(self.menu_options)
                    elif event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                        selected = self.menu_options[self.menu_index]
                        if selected == 'New Game':
                            # Only dump thread stacks when explicit debug mode is enabled. Unconditional
                            # calls here cause the main thread's stack (including this call) to be printed
                            # and can be noisy or confusing in normal runs.
                            debug_print('[DEBUG] Menu: New Game selected', flush=True)
                            if ENABLE_DEBUG:
                                dump_all_thread_stacks()


                            self.state = 'playing'
                            self.reset_game()
                            debug_print('[DEBUG] After reset_game, state set to', self.state, flush=True)
                        elif 'Input Method:' in selected:
                            # Toggle input method
                            new_method = 'Gesture' if self.input_method == 'Keyboard' else 'Keyboard'
                            self.set_input_method(new_method)
                            self.menu_options[1] = f'Input Method: {self.input_method}'
                        elif selected == 'Gesture Studio':
                            self.launch_gesture_studio()
                        elif selected == 'Switch/Create Profile':
                            self.switch_profile()
                        elif selected == 'Quit':
                            self.running = False
            elif self.state == 'playing':
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.state = 'start'
                else:
                    cmd = self.input_handler.handle_event(event)
                    if cmd:
                        append_command_sequence(self.command_sequence, cmd)
                        self.try_cast_spell_from_sequence()

    def start_gesture_thread(self):
        """
        Start the gesture recognition thread if not already running.
        """
        if self.gesture_thread and self.gesture_thread.is_alive():
            return
        self.gesture_thread_running = True
        self.last_gesture_time = 0  # Track last gesture time
        def on_gesture(label, gesture_probs, meta_probs, gestures, meta_classes):
            import time
            now = time.time()
            if label and label != 'No gesture':
                if now - self.last_gesture_time >= GESTURE_DEBOUNCE_TIME:
                    self.gesture_queue.put(label)
                    self.last_gesture_time = now
        def gesture_worker():
            self.gesture_recognizer = gc.GestureRecognizer(dataset_dir=self.dataset_dir,
                                      models_dir=self.models_dir)
            try:
                self.gesture_recognizer.recognize(on_gesture=on_gesture)
            except Exception as e:
                import traceback
                debug_print(f"[DEBUG] Exception in gesture thread: {e}\n{traceback.format_exc()}")
        self.gesture_thread = threading.Thread(target=gesture_worker, daemon=True)
        self.gesture_thread.start()

    def stop_gesture_thread(self):
        """
        Stop the gesture recognition thread and clean up resources.
        """
        self.gesture_thread_running = False
        if self.gesture_thread:
            self.gesture_thread.join(timeout=1)
        self.gesture_thread = None
        with self.gesture_queue.mutex:
            self.gesture_queue.queue.clear()
        # Attempt to stop gesture recognition window if API allows
        if self.gesture_recognizer is not None:
            if hasattr(self.gesture_recognizer, "stop"):
                try:
                    self.gesture_recognizer.stop()
                except Exception as e:
                    debug_print(f"[DEBUG] Error stopping gesture recognizer: {e}")
            self.gesture_recognizer = None
        if hasattr(gc, "close_studio"):
            try:
                close_fn = getattr(gc, 'close_studio')
                if callable(close_fn):
                    close_fn()
            except Exception as e:
                debug_print(f"[DEBUG] Error closing gesture studio: {e}")

    def set_input_method(self, method):
        """
        Set the input method (Keyboard or Gesture) and start/stop gesture thread as needed.
        Args:
            method (str): 'Keyboard' or 'Gesture'.
        """
        self.input_method = method
        if method == 'Gesture':
            self.start_gesture_thread()
        else:
            self.stop_gesture_thread()

    def poll_gesture(self):
        """
        Poll the gesture queue for new gestures and process them.
        """
        if self.state == 'playing' and self.input_method == 'Gesture':
            while not self.gesture_queue.empty():
                gesture = self.gesture_queue.get()
                if gesture:
                    cmd = gesture.lower().strip()
                    append_command_sequence(self.command_sequence, cmd)
                    self.try_cast_spell_from_sequence()

    def try_cast_spell_from_sequence(self):
        """
        Attempt to cast a spell from the current command sequence.
        Returns:
            bool: True if a spell was cast, False otherwise.
        """
        def do_cast(spell):
            # Capture the current command sequence visuals for a transient cast display.
            try:
                cs_capture = list(self.command_sequence)
                if cs_capture:
                    parts_local = []
                    pad = 8
                    # Convert rendered text to alpha-capable surfaces so set_alpha works reliably
                    plus_surf = self.small_font.render('+', True, (200,200,255)).convert_alpha()
                    for i, comp in enumerate(cs_capture):
                        key = comp.lower() if isinstance(comp, str) else str(comp)
                        icon = self.component_icons.get(key)
                        if icon is not None:
                            surf = icon.copy()
                        else:
                            surf = self.small_font.render(comp, True, (200,200,255)).convert_alpha()
                        parts_local.append((surf, True))
                        if i != len(cs_capture) - 1:
                            parts_local.append((plus_surf.copy(), False))
                    # compute positions centered like draw()
                    total_w = sum(s.get_width() for s, _ in parts_local) + pad * (len(parts_local) - 1)
                    reference_h = self.small_font.get_height()
                    x = SCREEN_WIDTH // 2 - total_w // 2
                    # Place the visual so its center is at TARGET_CENTER (pixels from top)
                    TARGET_CENTER = FEEDBACK_CENTER
                    y_center = TARGET_CENTER
                    # y is the top coordinate for the reference band; align so center matches
                    y = int(y_center - (reference_h // 2))
                    stored_parts = []
                    comp_indices = []
                    idx = 0
                    for s, is_comp in parts_local:
                        # compute bounding rect center-aware top
                        try:
                            b = s.get_bounding_rect()
                            content_center = b.top + (b.height / 2)
                            sy = int(y + (reference_h // 2) - content_center)
                        except Exception:
                            sy = y + (reference_h - s.get_height()) // 2
                        stored_parts.append({'surf': s, 'x': x, 'y': sy, 'w': s.get_width(), 'h': s.get_height(), 'is_comp': is_comp})
                        if is_comp:
                            comp_indices.append(idx)
                        idx += 1
                        x += s.get_width() + pad
                    # store cast_display with duration matching gesture debounce time
                    self.cast_display = {
                        'parts': stored_parts,
                        'comp_indices': comp_indices,
                        'timer': GESTURE_DEBOUNCE_TIME,
                        'duration': GESTURE_DEBOUNCE_TIME,
                        'rect_pad': 8,
                    }
            except Exception:
                # don't let visual capture break casting
                self.cast_display = None
            # If the spell contains a projectile ingredient, defer execution until projectile arrival
            try:
                recipe = spell.get('recipe', [])
            except Exception:
                recipe = []
            # normalize recipe
            try:
                recipe = [r.lower() for r in recipe]
            except Exception:
                pass

            proj_speed = 900.0
            if 'projectile' in recipe:
                # determine a target position (prefer the first obstacle)
                if self.obstacles:
                    target = self.obstacles[0]
                    # estimate target velocity in pixels/sec. Obstacles currently move vertically by target.speed per frame,
                    # so convert per-frame to per-second by multiplying with FPS to be robust.
                    target_vx = 0.0
                    target_vy = getattr(target, 'speed', 0.0) * FPS
                    # shooter start point (player hand)
                    start_x = getattr(self.player, 'x', SCREEN_WIDTH//2)
                    start_y = getattr(self.player, 'y', SCREEN_HEIGHT - 200) - 20
                    # predict intercept point
                    target_pos = predict_intercept(start_x, start_y, target.x, target.y, target_vx, target_vy, proj_speed)
                else:
                    target_pos = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
                    start_x = getattr(self.player, 'x', SCREEN_WIDTH//2)
                    start_y = getattr(self.player, 'y', SCREEN_HEIGHT - 200) - 20
                # Create a deferred projectile that will call cast_spell on arrival
                proj = ProjectileEffect(base_effect=None,
                                        start_x=int(start_x),
                                        start_y=int(start_y),
                                        target_pos=(int(target_pos[0]), int(target_pos[1])),
                                        speed=int(proj_speed),
                                        spell=spell, owner=self)
                self.spell_effects.append(proj)
                # update last spell display info immediately
                self.last_spell = spell.get('name')
                self.last_spell_weakness = False
                self.last_spell_timer = 1.5
            else:
                # Non-projectile spells: cast immediately as before
                before_len = len(self.spell_effects)
                self.last_spell, self.last_spell_weakness, self.last_spell_timer = cast_spell(
                    spell, self.player, self.spell_effects, self.area_effect_rings, self.obstacles)
                # wrap new effects created by cast_spell (keep old wrapping behavior)
                for i in range(before_len, len(self.spell_effects)):
                    eff = self.spell_effects[i]
                    try:
                        rec = eff.spell.get('recipe', []) if isinstance(eff.spell, dict) else []
                        rec = [r.lower() for r in rec]
                    except Exception:
                        rec = []
                    if 'projectile' in rec:
                        if self.obstacles:
                            target = self.obstacles[0]
                            # estimate target velocity
                            target_vx = 0.0
                            target_vy = getattr(target, 'speed', 0.0) * FPS
                            start_x = getattr(self.player, 'x', SCREEN_WIDTH//2)
                            start_y = getattr(self.player, 'y', SCREEN_HEIGHT - 200) - 20
                            target_pos = predict_intercept(start_x, start_y, target.x, target.y, target_vx, target_vy, proj_speed)
                        else:
                            target_pos = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
                            start_x = getattr(self.player, 'x', SCREEN_WIDTH//2)
                            start_y = getattr(self.player, 'y', SCREEN_HEIGHT - 200) - 20
                        wrapped = ProjectileEffect(base_effect=eff,
                                                    start_x=int(start_x),
                                                    start_y=int(start_y),
                                                    target_pos=(int(target_pos[0]), int(target_pos[1])),
                                                    speed=int(proj_speed),
                                                    owner=self)
                        self.spell_effects[i] = wrapped

        return try_cast_spell_from_sequence(
            self.command_sequence, self.player, self.spell_effects, self.area_effect_rings, self.obstacles, cast_spell_callback=do_cast)

    def reset_game(self):
        """
        Reset the game state for a new game session.
        """
        debug_print('[DEBUG] reset_game() start', flush=True)
        self.player = Player()
        self.input_handler = InputHandler()
        self.obstacles = []
        self.spell_effects = []
        self.damage_indicators = []
        self.area_effect_rings = []  # Reset area effect rings
        self.spawn_timer = 0
        self.command_sequence = []
        self.last_spell = None
        self.last_spell_weakness = False
        self.last_spell_timer = 0
        debug_print('[DEBUG] reset_game() end', flush=True)

    def update(self, dt):
        """
        Update all game objects and handle obstacle spawning and collisions.
        Args:
            dt (float): Time delta in seconds.
        """
        debug_print(f'[DEBUG] update start (dt={dt})', flush=True)
        self.player.regen_mana(dt)
        self.player.update(dt)
        for obs in self.obstacles:
            obs.update(dt)
        for eff in self.spell_effects:
            eff.update(dt)
        for ring in self.area_effect_rings:  # Update area effect rings
            ring.update(dt)
        # Update transient cast-display fade timer
        if getattr(self, 'cast_display', None) is not None:
            try:
                self.cast_display['timer'] -= dt
                if self.cast_display['timer'] <= 0:
                    self.cast_display = None
            except Exception:
                self.cast_display = None
        # Remove finished spell effects
        self.spell_effects = [e for e in self.spell_effects if e.timer > 0]
        # Remove destroyed obstacles
        self.obstacles = [o for o in self.obstacles if not (o.state == 'destroying' and o.destroy_timer <= 0)]
        # Update and remove damage indicators
        for di in self.damage_indicators:
            di.update(dt)
        self.damage_indicators = [di for di in self.damage_indicators if di.is_alive()]
        # Check for obstacles reaching player
        for obs in self.obstacles:
            if obs.y >= SCREEN_HEIGHT - 200 and obs.state == 'alive':
                # If shield is active and matches obstacle weakness, destroy obstacle and award points
                if self.player.shield and self.player.shield_element and obs.weakness == self.player.shield_element:
                    obs.start_destroy()
                    self.player.score += obs.points
                else:
                    self.player.take_damage(obs.damage, self)
                    obs.start_destroy()
        # Spawn obstacles
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            self.spawn_obstacle()
            self.spawn_timer = random.uniform(MIN_SPAWN_TIME, MAX_SPAWN_TIME)
        debug_print('[DEBUG] update end', flush=True)

    def spawn_obstacle(self):
        """
        Spawn a new obstacle at a random location.
        """
        config = random.choice(OBSTACLES)
        # Compute horizontal bounds between the Health display (centered bar) and the obstacle key (top-right legend).
        try:
            # Health bar geometry (must match draw_health_bar)
            bar_width = 500
            health_x = SCREEN_WIDTH//2 - bar_width//2
            health_right = health_x + bar_width
            # Obstacle key geometry (must match draw_obstacle_key)
            key_margin = 12
            surf_size = 40
            key_x = int(SCREEN_WIDTH - (surf_size + 10) - 150)
            key_x = max(key_margin, key_x)
            # Apply small padding to avoid collision with HUD elements
            pad = 8
            x_min = health_right + pad
            x_max = key_x - pad
            # If computed bounds are invalid (narrow screen), fall back to safe full-range
            if x_max - x_min < 80:
                x_min = 100
                x_max = SCREEN_WIDTH - 100
            spawn_x = random.randint(int(x_min), int(x_max))
            # Start Y should be beneath the component feedback icons centered at FEEDBACK_CENTER
            icon_half = getattr(self, 'icon_size', 120) // 2
            spawn_y = FEEDBACK_CENTER + icon_half + 12
        except Exception:
            # Fallback to previous behaviour on any error
            spawn_x = random.randint(100, SCREEN_WIDTH - 100)
            spawn_y = 100

        self.obstacles.append(Obstacle(config, start_x=spawn_x, start_y=spawn_y))

    def _blit_icon_centered(self, surface, icon_surf, dest_x, dest_y, box_w, box_h):
        """Blit icon_surf centered into a box at (dest_x, dest_y) of size box_w x box_h."""
        try:
            iw, ih = icon_surf.get_size()
            x = int(dest_x + (box_w - iw) / 2)
            y = int(dest_y + (box_h - ih) / 2)
            surface.blit(icon_surf, (x, y))
        except Exception:
            try:
                surface.blit(icon_surf, (dest_x, dest_y))
            except Exception:
                pass

    def draw(self):
        """
        Draw all game elements, UI, and effects to the screen.
        """
        debug_print('[DEBUG] draw start', flush=True)
        self.screen.fill((0, 0, 0))
        # Draw player (wizard's hand)
        pygame.draw.circle(self.screen, (200, 200, 255), (SCREEN_WIDTH//2, SCREEN_HEIGHT-160), 80)
        # Draw shield
        if self.player.shield:
            # Choose color based on shield type
            if self.player.shield_element == 'fire':
                shield_color = (255, 100, 0)  # Fire shield: orange-red
            elif self.player.shield_element == 'ice':
                shield_color = (80, 180, 255)  # Ice shield: blue
            else:
                shield_color = (255, 255, 255)  # Plain shield: white
            pygame.draw.circle(self.screen, shield_color, (SCREEN_WIDTH//2, SCREEN_HEIGHT-160), 110, 6)
        # Draw obstacles
        for i, obs in enumerate(self.obstacles):
            obs.draw(self.screen, self.small_font)
        # Draw targeting sight on first obstacle
        if self.obstacles:
            target = self.obstacles[0]
            tx, ty = target.x, target.y
            pygame.draw.circle(self.screen, (255,255,0), (tx, ty), 40, 4)
            pygame.draw.line(self.screen, (255,255,0), (tx-50, ty), (tx+50, ty), 2)
            pygame.draw.line(self.screen, (255,255,0), (tx, ty-50), (tx, ty+50), 2)
        # Draw spell effects (allow wrappers to draw themselves)
        for eff in self.spell_effects:
            if hasattr(eff, 'draw'):
                try:
                    eff.draw(self.screen)
                except Exception:
                    pass
            else:
                # fallback drawing behavior
                try:
                    recipe = eff.spell.get('recipe', [])
                except Exception:
                    recipe = []
                # Skip drawing impact circle for projectile spells (visual handled by projectiles)
                try:
                    rec_lower = [r.lower() for r in recipe]
                except Exception:
                    rec_lower = recipe
                if 'projectile' in rec_lower:
                    continue
                color = (255, 100, 0) if 'fire' in recipe else (100, 200, 255) if 'ice' in recipe else (200, 200, 200)
                try:
                    pygame.draw.circle(self.screen, color, (int(eff.x), int(eff.y)), 40, 5)
                except Exception:
                    pass
        # Draw area effect rings
        for ring in self.area_effect_rings:
            ring.draw(self.screen)
        # Draw UI
        self.draw_health_bar()
        # Compact HUD: tuck health/mana/score into the top-left corner using smaller UI font
        health_text = self.ui_font.render(f'HP: {int(self.player.health)}', True, (255,255,255))
        mana_text = self.ui_font.render(f'MP: {int(self.player.mana)}', True, (100,200,255))
        score_text = self.ui_font.render(f'Score: {self.player.score}', True, (255,255,100))
        # tight corner padding
        corner_x = 10
        corner_y = 8
        row_h = self.ui_font.get_height() + 6
        self.screen.blit(health_text, (corner_x, corner_y))
        self.screen.blit(mana_text, (corner_x, corner_y + row_h))
        self.screen.blit(score_text, (corner_x, corner_y + 2*row_h))
        # Draw command sequence
        # Render command sequence as icons when available (fallback to text)
        try:
            cs = self.command_sequence
            if cs:
                pad = 8
                plus_surf = self.small_font.render('+', True, (200,200,255)).convert_alpha()
                # We'll render each component inside a fixed square cell (box) of width self.icon_size
                cell_w = self.icon_size
                cell_h = self.icon_size
                # Compute total width considering plus signs (plus signs use their surface width)
                total_w = 0
                parts_meta = []  # tuples (is_comp, surf_or_text)
                for i, comp in enumerate(cs):
                    key = comp.lower() if isinstance(comp, str) else str(comp)
                    icon = self.component_icons.get(key)
                    if icon is not None:
                        parts_meta.append((True, icon))
                        total_w += cell_w
                    else:
                        txt = self.small_font.render(comp, True, (200,200,255)).convert_alpha()
                        parts_meta.append((True, txt))
                        total_w += cell_w
                    if i != len(cs) - 1:
                        parts_meta.append((False, plus_surf))
                        total_w += plus_surf.get_width() + pad
                    else:
                        # no trailing pad for last element
                        pass
                    # add padding between cells
                    total_w += pad

                # adjust for the extra pad added at the end
                if total_w > 0:
                    total_w -= pad

                reference_h = max(self.small_font.get_height(), cell_h)
                x = SCREEN_WIDTH // 2 - total_w // 2
                # Place command/cast visuals so their center is at TARGET_CENTER (pixels from top)
                TARGET_CENTER = FEEDBACK_CENTER
                y_center = TARGET_CENTER
                # y is the top coordinate for the reference band; align so center matches
                y = int(y_center - (reference_h // 2))
                # Blit each element; component icons are centered inside their square cell
                for is_comp, surf in parts_meta:
                     if is_comp:
                         # draw the component inside a cell centered vertically on y_center
                         cell_top = y_center - (cell_h // 2)
                         try:
                             # center icon/text inside the fixed cell without scaling
                             self._blit_icon_centered(self.screen, surf, x, cell_top, cell_w, cell_h)
                         except Exception:
                             try:
                                 self.screen.blit(surf, (x, cell_top))
                             except Exception:
                                 pass
                         x += cell_w + pad
                     else:
                         # plus sign; center vertically relative to reference band
                         try:
                             b = surf.get_bounding_rect()
                             content_center = b.top + (b.height / 2)
                             sy = int(y_center - content_center)
                         except Exception:
                             sy = y_center - (surf.get_height() // 2)
                         self.screen.blit(surf, (x, sy))
                         x += surf.get_width() + pad
        except Exception:
             # fall back to original text render if anything goes wrong
             try:
                seq_text = self.font.render(' + '.join(self.command_sequence), True, (200,200,255))
                # center fallback text vertically at TARGET_CENTER (use FEEDBACK_CENTER)
                TARGET_CENTER = FEEDBACK_CENTER
                y_text = int(TARGET_CENTER - seq_text.get_height() // 2)
                self.screen.blit(seq_text, (SCREEN_WIDTH//2 - seq_text.get_width()//2, y_text))
             except Exception:
                 pass
        # Draw transient cast display (fading icons + rectangle) if present
        try:
            cd = getattr(self, 'cast_display', None)
            if cd:
                parts = cd.get('parts', [])
                dur = max(1e-6, cd.get('duration', GESTURE_DEBOUNCE_TIME))
                t = max(0.0, cd.get('timer', 0.0))
                alpha = int(255 * (t / dur))
                # draw rectangle around component icons
                comp_rects = [pygame.Rect(p['x'], p['y'], p['w'], p['h']) for i, p in enumerate(parts) if p.get('is_comp')]
                if comp_rects:
                    left = min(r.left for r in comp_rects) - cd.get('rect_pad', 6)
                    top = min(r.top for r in comp_rects) - cd.get('rect_pad', 6)
                    right = max(r.right for r in comp_rects) + cd.get('rect_pad', 6)
                    bottom = max(r.bottom for r in comp_rects) + cd.get('rect_pad', 6)
                    rect_w = right - left
                    rect_h = bottom - top
                    # create transparent surface for rectangle
                    rect_surf = pygame.Surface((rect_w, rect_h), pygame.SRCALPHA)
                    rect_color = (173, 216, 230, alpha)  # light blue with alpha
                    pygame.draw.rect(rect_surf, rect_color, (0, 0, rect_w, rect_h), 4, border_radius=6)
                    self.screen.blit(rect_surf, (left, top))
                # draw parts with alpha
                for p in parts:
                    try:
                        s = p['surf'].copy()
                        s.set_alpha(alpha)
                        # If this part is a component icon, it may be smaller than the square cell used
                        # when it was created; center it inside a box of size self.icon_size
                        if p.get('is_comp'):
                            # compute the top-left of the cell that was used when capturing the cast display
                            cell_w = self.icon_size
                            cell_h = self.icon_size
                            cell_top = p['y'] - (cell_h - p['h']) // 2 if p['h'] < cell_h else p['y']
                            cell_left = p['x'] - (cell_w - p['w']) // 2 if p['w'] < cell_w else p['x']
                            self._blit_icon_centered(self.screen, s, cell_left, cell_top, cell_w, cell_h)
                        else:
                            self.screen.blit(s, (p['x'], p['y']))
                    except Exception:
                        try:
                            self.screen.blit(p['surf'], (p['x'], p['y']))
                        except Exception:
                            pass
        except Exception:
            pass
        # Draw last spell cast near the feedback area. Use a modest upward offset so
        # the text sits above the icon row and remains visible for common window sizes.
        if self.last_spell and self.last_spell_timer > 0:
            color = (255,60,60) if self.last_spell_weakness else (255,255,255)
            spell_text = self.font.render(f'Cast: {self.last_spell}', True, color)
            # Place the spell text below the feedback icon row so it doesn't overlap
            # Icons are centered at FEEDBACK_CENTER and have height self.icon_size.
            # Position the text at: FEEDBACK_CENTER + (icon_half) + padding.
            icon_half = getattr(self, 'icon_size', 120) // 2
            padding = 10
            y_spell = FEEDBACK_CENTER + icon_half + padding
            # Ensure we don't draw off the bottom of the screen
            y_spell = min(SCREEN_HEIGHT - spell_text.get_height() - 10, y_spell)
            self.screen.blit(spell_text, (SCREEN_WIDTH//2 - spell_text.get_width()//2, y_spell))
            self.last_spell_timer -= 1/self.clock.get_fps() if self.clock.get_fps() > 0 else 1/60
        # Draw damage indicators
        for di in self.damage_indicators:
            dmg_surf = self.font.render(str(di.amount), True, (255, 60, 60))
            dmg_surf.set_alpha(di.alpha)
            self.screen.blit(dmg_surf, (di.x - dmg_surf.get_width()//2, di.y))
        # Draw obstacle key/legend
        self.draw_obstacle_key()
        pygame.display.flip()
        debug_print('[DEBUG] draw end', flush=True)

    def draw_health_bar(self):
        """
        Draw the player's health bar on the screen.
        """
        bar_width = 500
        bar_height = 32
        x = SCREEN_WIDTH//2 - bar_width//2
        y = SCREEN_HEIGHT - 60
        health_ratio = max(0.0, self.player.health / PLAYER_HEALTH)
        pygame.draw.rect(self.screen, (60,60,60), (x, y, bar_width, bar_height), border_radius=12)
        pygame.draw.rect(self.screen, (200,40,40), (x, y, int(bar_width*health_ratio), bar_height), border_radius=12)
        pygame.draw.rect(self.screen, (255,255,255), (x, y, bar_width, bar_height), 2, border_radius=12)
        # Draw hit point total centered in the bar
        hp_text = self.font.render(f"{int(self.player.health)} / {PLAYER_HEALTH}", True, (255,255,255))
        self.screen.blit(hp_text, (x + bar_width//2 - hp_text.get_width()//2, y + bar_height//2 - hp_text.get_height()//2))

    def draw_obstacle_key(self):
        """
        Draw the obstacle legend/key on the screen.
        """
        # Compact legend in the top-right corner
        key_margin = 12
        surf_size = 40  # smaller legend icons
        # compute key_x but ensure it doesn't go off-screen on narrow windows
        key_x = int(SCREEN_WIDTH - (surf_size + 10) - 150)
        key_x = max(key_margin, key_x)
        key_y = key_margin
        # Title uses smaller UI font so it doesn't dominate
        key_title = self.ui_font.render('Obstacle Key', True, (255,255,255))
        self.screen.blit(key_title, (key_x, key_y))
        y_offset = key_y + self.ui_font.get_height() + 6
        for name, visual in OBSTACLE_VISUALS.items():
            surf = pygame.Surface((surf_size, surf_size), pygame.SRCALPHA)
            color = visual['color']
            if visual['shape'] == 'circle':
                pygame.draw.circle(surf, color + (255,), (surf_size//2, surf_size//2), surf_size//2 - 3)
            elif visual['shape'] == 'triangle':
                padding = 3
                pygame.draw.polygon(surf, color + (255,), [(surf_size//2, padding), (surf_size - padding, surf_size - padding), (padding, surf_size - padding)])
            else:
                pygame.draw.rect(surf, color + (255,), (4, 4, surf_size - 8, surf_size - 8))
            self.screen.blit(surf, (key_x, y_offset))
            name_text = self.key_font.render(name, True, (255,255,255))
            self.screen.blit(name_text, (key_x + surf_size + 8, y_offset + (surf_size - name_text.get_height())//2))
            y_offset += surf_size + 6

    def draw_start_screen(self):
        """
        Draw the start/menu screen with profile and options.
        """
        self.screen.fill((0, 0, 0))
        # Show current profile at the top
        gesture_dir = GESTURE_DIRECTORY
        profiles = [d for d in os.listdir(gesture_dir) if os.path.isdir(os.path.join(gesture_dir, d))] if os.path.exists(gesture_dir) else []
        if profiles:
            profile_display = self.profile_name
        else:
            profile_display = 'None'
        profile_text = self.small_font.render(f'Current Profile: {profile_display}', True, (180, 220, 255))
        self.screen.blit(profile_text, (SCREEN_WIDTH//2 - profile_text.get_width()//2, 140))
        title = self.font.render('Wizard Spellcaster', True, (255,255,255))
        self.screen.blit(title, (SCREEN_WIDTH//2 - title.get_width()//2, 180))
        for i, option in enumerate(self.menu_options):
            color = (255,255,0) if i == self.menu_index else (200,200,200)
            opt_text = self.font.render(option, True, color)
            self.screen.blit(opt_text, (SCREEN_WIDTH//2 - opt_text.get_width()//2, 320 + i*60))
        # Move the instruction text significantly lower than the last menu option
        instr = self.small_font.render('Use UP/DOWN to select, ENTER to confirm', True, (180,180,180))
        menu_bottom = 320 + (len(self.menu_options)-1)*60 + 60
        instr_y = menu_bottom + 40  # 40px below the last option
        self.screen.blit(instr, (SCREEN_WIDTH//2 - instr.get_width()//2, instr_y))
        pygame.display.flip()

    def run(self):
        """
        Main game loop. Handles state transitions and rendering.
        """
        try:
            while self.running:
                dt = self.clock.tick(FPS) / 1000.0
                self.handle_input()
                self.poll_gesture()  # Always poll gesture input during gameplay
                if self.state == 'start':
                    self.draw_start_screen()
                elif self.state == 'playing':
                    if self.player.health > 0:
                        self.update(dt)
                        self.draw()
                        # After drawing, capture a downscaled frame and queue it for the
                        # background frame-pusher if enabled. Non-blocking and best-effort.
                        try:
                            self._maybe_queue_frame()
                        except Exception:
                            pass
                    else:
                        self.game_over()
                        # Wait for a moment, then reset and return to menu
                        self.reset_game()
                        self.state = 'start'
        finally:
            self.stop_gesture_thread()

    # Frame-push helper methods
    def _maybe_queue_frame(self, target_w=640, target_h=480):
        """Capture the current screen, downscale to target_w x target_h and enqueue
        a raw RGB buffer for the background sender to JPEG-encode and transmit.
        This method is non-blocking: it drops frames when the queue is full.
        """
        if not getattr(self, '_frame_pipe_queue', None):
            return
        try:
            # create a scaled copy to reduce bandwidth/CPU
            surf = pygame.transform.smoothscale(self.screen, (target_w, target_h))
            # get raw RGB bytes
            raw = pygame.image.tostring(surf, 'RGB')
            frame = {'w': target_w, 'h': target_h, 'rgb': raw}
            try:
                self._frame_pipe_queue.put_nowait(frame)
            except Exception:
                # queue full -> drop frame
                pass
        except Exception:
            # If capture fails for any reason, silently ignore to avoid crashing the game
            pass

    def _frame_pipe_worker(self):
        """Background thread: connects to the bridge /framepipe and sends JPEG bytes
        for frames pulled from the `_frame_pipe_queue`. Reconnects on failure.
        """
        # import heavy dependencies inside the thread so normal game runs don't require them
        try:
            import asyncio
            import aiohttp
            from PIL import Image
            import io as _io
        except Exception:
            print('[framepipe] Required packages for frame-push are missing (aiohttp, Pillow)')
            return

        async def _sender_loop():
            session_timeout = aiohttp.ClientTimeout(total=None)
            while True:
                try:
                    async with aiohttp.ClientSession(timeout=session_timeout) as session:
                        async with session.ws_connect(self.framepipe_url) as ws:
                            # send frames as they arrive
                            while True:
                                try:
                                    frame = await asyncio.get_event_loop().run_in_executor(None, self._frame_pipe_queue.get)
                                except Exception:
                                    await asyncio.sleep(0.01)
                                    continue
                                if frame is None:
                                    return
                                try:
                                    pil = Image.frombytes('RGB', (frame['w'], frame['h']), frame['rgb'])
                                    bio = _io.BytesIO()
                                    pil.save(bio, format='JPEG', quality=75)
                                    bio.seek(0)
                                    await ws.send_bytes(bio.read())
                                except Exception as e:
                                    # on send failure, break to reconnect
                                    print(f'[framepipe] send error: {e}')
                                    break
                except Exception as e:
                    print(f'[framepipe] connection error: {e}; reconnecting in 1s')
                    await asyncio.sleep(1)

        try:
            asyncio.run(_sender_loop())
        except Exception as e:
            print(f'[framepipe] worker exiting due to: {e}')

    def _start_input_server(self):
        """Start a simple ThreadingTCPServer on localhost that accepts JSON lines and posts
        pygame key events. This runs in a background thread and exits when the process exits.
        """
        port = self._input_listen_port
        if not port:
            return

        class _Handler(socketserver.StreamRequestHandler):
            def handle(inner_self):
                peer = inner_self.client_address
                try:
                    for raw in inner_self.rfile:
                        try:
                            line = raw.decode('utf-8').strip()
                            if not line:
                                continue
                            msg = _json.loads(line)
                            # Only handle key messages for now
                            if msg.get('type') == 'key':
                                down = bool(msg.get('down'))
                                key_name = msg.get('key') or msg.get('code') or ''
                                # try to map to a pygame key code
                                try:
                                    # pygame.key.key_code accepts names like 'a', 'space', 'return'
                                    keycode = pygame.key.key_code(key_name)
                                except Exception:
                                    # fallback mappings for common keys
                                    kn = key_name.lower()
                                    mapping = {
                                        'arrowup': pygame.K_UP, 'arrowdown': pygame.K_DOWN,
                                        'arrowleft': pygame.K_LEFT, 'arrowright': pygame.K_RIGHT,
                                        'enter': pygame.K_RETURN, 'return': pygame.K_RETURN,
                                        ' ': pygame.K_SPACE, 'space': pygame.K_SPACE,
                                        'escape': pygame.K_ESCAPE, 'esc': pygame.K_ESCAPE,
                                        'tab': pygame.K_TAB, 'backspace': pygame.K_BACKSPACE
                                    }
                                    keycode = mapping.get(kn)
                                    if keycode is None and len(kn) == 1:
                                        try:
                                            # letters/digits
                                            keycode = pygame.key.key_code(kn)
                                        except Exception:
                                            keycode = None
                                if keycode is not None:
                                    ev_type = pygame.KEYDOWN if down else pygame.KEYUP
                                    ev = pygame.event.Event(ev_type, {'key': keycode, 'mod': 0})
                                    pygame.event.post(ev)
                        except Exception:
                            # ignore malformed lines
                            continue
                except Exception:
                    return

        class _ThreadingServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        try:
            server = _ThreadingServer(('127.0.0.1', port), _Handler)
            server.serve_forever()
        except Exception as e:
            print(f"[input-server] failed to start on 127.0.0.1:{port}: {e}")

class ProfileDialog(simpledialog.Dialog):
    def __init__(self, parent, profiles, title=None):
        """
        Dialog for selecting or creating a gesture profile.
        Args:
            parent (tk.Tk): Parent window.
            profiles (list): List of profile names.
            title (str, optional): Dialog title.
        """
        self.profiles = profiles
        self.selected_profile = None
        self.new_profile = None
        super().__init__(parent, title)

    def body(self, master):
        """
        Create the dialog body with profile selection and entry.
        Args:
            master (tk.Frame): Parent frame.
        Returns:
            tk.Entry: Entry widget for new profile name.
        """
        tk.Label(master, text="Select existing profile:").grid(row=0, column=0, sticky="w")
        self.combo = ttk.Combobox(master, values=self.profiles, state="readonly")
        self.combo.grid(row=0, column=1, padx=5, pady=5)
        self.combo.bind("<<ComboboxSelected>>", self.on_combo_selected)

        tk.Label(master, text="Or enter new profile:").grid(row=1, column=0, sticky="w")
        self.entry = tk.Entry(master)
        self.entry.grid(row=1, column=1, padx=5, pady=5)
        return self.entry

    def on_combo_selected(self, event):
        """
        Clear the entry field when a profile is selected from the combo box.
        """
        self.entry.delete(0, tk.END)

    def apply(self):
        """
        Set the result to the selected or entered profile name.
        """
        selected = self.combo.get()
        entered = self.entry.get().strip()
        if entered:
            self.result = entered
        elif selected:
            self.result = selected
        else:
            self.result = None

def thread_exception_handler(args):
    """
    Handle uncaught exceptions in threads and print error info.
    Args:
        args (threading.ExceptHookArgs): Exception hook arguments.
    """
    exc_type = args.exc_type
    exc_value = args.exc_value
    exc_traceback = args.exc_traceback
    thread = args.thread
    print(f"[THREAD ERROR] Exception in thread {thread.name}: {exc_type}: {exc_value}")
    # If you want to show a dialog, use the request_gui_action mechanism
    # Example: game.request_gui_action(show_error_dialog, str(exc_value))
    # But do NOT call tkinter/dialogs directly here!

threading.excepthook = thread_exception_handler

# Guard: warn if tkinter is used from a non-main thread
import tkinter
_tk_init = tkinter.Tk.__init__
def tk_init_guard(self, *args, **kwargs):
    """
    Guard to warn if Tk() is created from a non-main thread.
    """
    if threading.current_thread() is not threading.main_thread():
        print("[WARNING] Attempt to create Tk() from non-main thread! This will cause async errors.")
    return _tk_init(self, *args, **kwargs)
tkinter.Tk.__init__ = tk_init_guard

def main():
    """
    Entry point for the game. Initializes and runs the game loop.
    """
    game = Game()
    game.run()
    # Only destroy the persistent root at program exit
    game.tk_root.destroy()

if __name__ == "__main__":
    main()
