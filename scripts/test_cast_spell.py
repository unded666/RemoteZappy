import os
import sys
# Ensure the project root is on sys.path so 'magic' can be imported when running this script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import magic

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
magic.initialize_magic(BASE_DIR)

# Helper: find spell by name
def get_spell(name):
    for s in magic.SPELLS:
        if s['name'].lower() == name.lower():
            return s
    return None

# Dummy player
class DummyPlayer:
    def __init__(self):
        self.mana = 999
        self.score = 0
        self.shield = False
        self.shield_timer = 0
        self.shield_element = None
    def cast_shield(self):
        self.shield = True
        self.shield_timer = 1.0

# Dummy obstacle matching Steel Block
class DummyObstacle:
    def __init__(self):
        self.name = 'Steel Block'
        self.max_health = 30
        self.health = 30
        self.speed = 1.5
        self.weakness = 'magic'
        self.damage = 15
        self.points = 10
        self.x = 100
        self.y = 100
        self.state = 'alive'
        self.destroy_timer = 0
    def start_destroy(self):
        self.state = 'destroying'
        self.destroy_timer = 0.5


def run_test(spell_name):
    spell = get_spell(spell_name)
    if not spell:
        print('Spell not found:', spell_name)
        return
    player = DummyPlayer()
    spell_effects = []
    area_effect_rings = []
    obstacles = [DummyObstacle()]
    print('\nCasting', spell_name, 'damage', spell['damage'])
    last_spell, last_spell_weakness, last_spell_timer = magic.cast_spell(spell, player, spell_effects, area_effect_rings, obstacles)
    print('last_spell:', last_spell)
    print('weakness_hit:', last_spell_weakness)
    print('obstacle health after:', obstacles[0].health)
    print('player score:', player.score)
    print('spell_effects count:', len(spell_effects))
    print('area_effect_rings count:', len(area_effect_rings))

if __name__ == '__main__':
    run_test('Magic Missile')
    run_test('Greater Magic Missile')
