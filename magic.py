import os
import json
import random
# This is a test, meaningless line

# Load configuration files
SPELLS = None
SPELL_RECIPES = None
MAX_SPELL_LENGTH = None
OBSTACLES = None

def load_config(filename):
    with open(filename, 'r') as f:
        return json.load(f)

def initialize_magic(base_dir):
    global SPELLS, SPELL_RECIPES, MAX_SPELL_LENGTH, OBSTACLES
    SPELLS = load_config(os.path.join(base_dir, 'spells.json'))
    OBSTACLES = load_config(os.path.join(base_dir, 'obstacles.json'))
    # Use lower-case for recipes to avoid case-sensitivity issues
    SPELL_RECIPES = {tuple(cmd.lower() for cmd in spell['recipe']): spell for spell in SPELLS}
    MAX_SPELL_LENGTH = max(len(spell['recipe']) for spell in SPELLS)

class SpellEffect:
    def __init__(self, spell, x, y):
        self.spell = spell
        self.x = x
        self.y = y
        self.timer = 0.5

    def update(self, dt):
        self.timer -= dt

class AreaEffectRing:
    def __init__(self, x, y, color, max_radius=60, duration=0.3):
        self.x = x
        self.y = y
        self.color = color
        self.radius = 0
        self.max_radius = max_radius
        self.duration = duration
        self.timer = duration

    def update(self, dt):
        self.timer -= dt
        progress = 1 - max(0, self.timer / self.duration)
        self.radius = int(progress * self.max_radius)

    def is_alive(self):
        return self.timer > 0

    def draw(self, surface):
        if self.radius > 0:
            alpha = int(255 * (self.timer / self.duration))
            import pygame
            ring_surf = pygame.Surface((self.max_radius*2, self.max_radius*2), pygame.SRCALPHA)
            try:
                base_color = tuple(int(min(255, max(0, c))) for c in self.color[:3])
                if len(base_color) != 3:
                    base_color = (255, 255, 255)
            except Exception:
                base_color = (255, 255, 255)
            alpha = int(min(255, max(0, alpha)))
            color_arg = (int(base_color[0]), int(base_color[1]), int(base_color[2]), int(alpha))
            pygame.draw.circle(ring_surf, color_arg, (self.max_radius, self.max_radius), self.radius, 6)
            surface.blit(ring_surf, (self.x - self.max_radius, self.y - self.max_radius))

class ImpactFlash:
    """Short, filled flash effect used for projectile impacts.

    Draws a filled circle that expands slightly and fades quickly.
    Compatible with Game.area_effect_rings list (has update, is_alive, draw).
    """
    def __init__(self, x, y, color, max_radius=30, duration=0.12):
        self.x = x
        self.y = y
        self.color = color
        self.radius = 0
        self.max_radius = max_radius
        self.duration = duration
        self.timer = duration

    def update(self, dt):
        self.timer -= dt
        progress = 1 - max(0.0, self.timer / self.duration)
        self.radius = int(progress * self.max_radius)

    def is_alive(self):
        return self.timer > 0

    def draw(self, surface):
        if self.timer > 0:
            alpha = int(255 * (self.timer / self.duration))
            import pygame
            surf = pygame.Surface((self.max_radius*2, self.max_radius*2), pygame.SRCALPHA)
            try:
                base_color = tuple(int(min(255, max(0, c))) for c in self.color[:3])
                if len(base_color) != 3:
                    base_color = (255, 255, 255)
            except Exception:
                base_color = (255, 255, 255)
            color_arg = (int(base_color[0]), int(base_color[1]), int(base_color[2]), int(min(255, max(0, alpha))))
            pygame.draw.circle(surf, color_arg, (self.max_radius, self.max_radius), max(1, self.radius))
            surface.blit(surf, (self.x - self.max_radius, self.y - self.max_radius))

def append_command_sequence(command_sequence, cmd):
    """Append cmd to command_sequence if not a duplicate of the last entry."""
    if not command_sequence or command_sequence[-1] != cmd:
        command_sequence.append(cmd)
    return command_sequence

def try_cast_spell_from_sequence(command_sequence, player, spell_effects, area_effect_rings, obstacles, cast_spell_callback=None):
    """Try to cast a spell from the command sequence. Returns True if a spell was cast."""
    best_spell = None
    best_length = 0
    # Lower-case the command sequence for matching
    lower_sequence = [cmd.lower() for cmd in command_sequence]
    for n in range(1, min(len(lower_sequence), MAX_SPELL_LENGTH) + 1):
        suffix = tuple(lower_sequence[-n:])
        spell = SPELL_RECIPES.get(suffix)
        if spell and n > best_length:
            best_spell = spell
            best_length = n
    if best_spell:
        if player.mana >= best_spell['mana_cost']:
            if cast_spell_callback:
                cast_spell_callback(best_spell)
            player.mana -= best_spell['mana_cost']
        command_sequence.clear()
        return True
    # If sequence is too long, trim from the front
    if len(command_sequence) > MAX_SPELL_LENGTH:
        command_sequence[:] = command_sequence[-MAX_SPELL_LENGTH:]
    return False

def cast_spell(spell, player, spell_effects, area_effect_rings, obstacles):
    """Apply the effects of a spell to the game state."""
    last_spell = spell['name']
    last_spell_weakness = False
    last_spell_timer = 1.5
    spell_name = spell['name'].lower()
    if spell_name == 'shield':
        player.cast_shield()
        player.shield_element = None
    elif spell_name == 'ice shield' or spell_name == 'fire shield':
        # Set color and element
        if spell_name == 'ice shield':
            color = (80, 180, 255)  # Blue for Ice Shield
            element = 'ice'
        else:
            color = (255, 100, 0)   # Orange-red for Fire Shield
            element = 'fire'
        player.cast_shield()
        player.shield_element = element  # Track shield element for collision logic
    else:
        # Target first obstacle
        if obstacles:
            target = obstacles[0]
            damage = spell['damage']
            # Determine whether this spell hits the target's weakness.
            # We consider a weakness hit if the obstacle's weakness string appears
            # in the spell's recipe (case-insensitive). Additionally, some spells
            # are conceptually "magic" even though their recipe doesn't contain
            # a literal 'magic' ingredient in the JSON. In particular, the
            # design treats "Magic Missile" and "Greater Magic Missile" as
            # magic-type attacks; mark them as such here so obstacles with
            # weakness 'magic' (e.g. Steel Block) take double damage.
            try:
                recipe = [r.lower() for r in spell.get('recipe', [])]
            except Exception:
                recipe = []
            name_lower = spell.get('name', '').lower()
            # Add implicit 'magic' tag for named magic missiles (no recipe change required)
            if name_lower in ("magic missile", "greater magic missile") and 'magic' not in recipe:
                recipe = recipe + ['magic']
            weakness_hit = str(target.weakness).lower() in recipe
            if weakness_hit:
                damage *= 2
            aoe_radius = spell.get('aoe', 0)
            if aoe_radius > 0:
                spell_name = spell['name'].lower()
                if spell_name == 'fireball':
                    color = (255, 100, 0)
                elif spell_name == 'cataclysm':
                    color = (180, 60, 255)  # Purple for Cataclysm
                elif spell_name == 'ice blast':
                    color = (80, 180, 255)  # Blue for Ice Blast
                else:
                    color = (100, 200, 255)
                area_effect_rings.append(AreaEffectRing(target.x, target.y, color, max_radius=aoe_radius, duration=0.3))
                for obs in obstacles:
                    dist = ((obs.x - target.x) ** 2 + (obs.y - target.y) ** 2) ** 0.5
                    if dist <= aoe_radius:
                        obs.health -= damage
                        if obs.health <= 0 and obs.state == 'alive':
                            obs.start_destroy()
                            player.score += obs.points
            else:
                target.health -= damage
                if target.health <= 0 and target.state == 'alive':
                    target.start_destroy()
                    player.score += target.points
            spell_effects.append(SpellEffect(spell, target.x, target.y))
            last_spell_weakness = weakness_hit
            last_spell_timer = 1.5
    return last_spell, last_spell_weakness, last_spell_timer
