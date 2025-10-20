"""
Check how each icon would be scaled by the game's loader (preserve aspect ratio logic).
Runs a small pygame-based loader and prints original and scaled sizes.
"""
import os
import pygame

ICON_DIR = os.path.join(os.path.dirname(__file__), '..', 'icons')
ICON_DIR = os.path.abspath(ICON_DIR)
ICON_SIZE = 120

print('Initializing pygame...')
pygame.init()
# Some pygame image operations (convert_alpha) require a video mode; use a tiny hidden surface
# set_mode is sufficient and will not open a visible window in most headless CI, but in desktop
# environments this will create a small window which immediately gets closed by pygame.quit() at end.
try:
    pygame.display.set_mode((1, 1))
except Exception:
    pass

files = []
for fn in os.listdir(ICON_DIR):
    p = os.path.join(ICON_DIR, fn)
    if os.path.isfile(p) and os.path.splitext(fn)[1].lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tga'):
        files.append(p)

if not files:
    print('No icon files found in', ICON_DIR)
else:
    for f in sorted(files):
        try:
            img = pygame.image.load(f).convert_alpha()
            ow, oh = img.get_size()
            if ow > 0 and oh > 0:
                if ow >= oh:
                    new_w = ICON_SIZE
                    new_h = max(1, int(oh * (ICON_SIZE / float(ow))))
                else:
                    new_h = ICON_SIZE
                    new_w = max(1, int(ow * (ICON_SIZE / float(oh))))
            else:
                new_w, new_h = ow, oh
            print(f'{os.path.basename(f)}: original={ow}x{oh}, scaled={new_w}x{new_h}')
        except Exception as e:
            print('ERROR loading', f, e)

pygame.quit()
