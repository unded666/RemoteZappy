"""
Create a Game instance, simulate pressing ENTER to select 'New Game', and run a few update/draw cycles.
This avoids needing to interact with the real window.
"""
import os
import sys
from pathlib import Path
# Ensure repo root is on sys.path so 'import main' works when running from scripts/
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import pygame
import time
import main

print('Starting test: instantiate Game')
g = main.Game()
print('Game created; initial state =', g.state)
# Ensure menu index is 0 to select 'New Game'
g.menu_index = 0
# Post a KEYDOWN event for RETURN to the pygame event queue
enter_event = pygame.event.Event(pygame.KEYDOWN, {'key': pygame.K_RETURN})
pygame.event.post(enter_event)
# Call handle_input once to process the event
print('Posting KEYDOWN K_RETURN and calling handle_input()')
g.handle_input()
print('After handle_input, state=', g.state)
# Run a few update/draw ticks
for i in range(5):
    print('Tick', i)
    g.update(1.0/60.0)
    g.draw()
    time.sleep(0.01)
print('Test finished')
# cleanup
try:
    g.tk_root.destroy()
except Exception:
    pass
