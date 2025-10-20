import pygame

# Default hotkeys for commands
DEFAULT_HOTKEYS = {
    'fire': pygame.K_f,
    'ice': pygame.K_i,
    'projectile': pygame.K_p,
    'shield': pygame.K_s,
    'magnify': pygame.K_m
}

class InputHandler:
    def __init__(self, hotkeys=None):
        self.hotkeys = hotkeys or DEFAULT_HOTKEYS.copy()
        self.command_queue = []

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            for command, key in self.hotkeys.items():
                if event.key == key:
                    self.command_queue.append(command)
                    return command
        return None

    def get_command_sequence(self):
        seq = self.command_queue[:]
        self.command_queue.clear()
        return seq

    def set_hotkey(self, command, key):
        self.hotkeys[command] = key

    def reset(self):
        self.command_queue.clear()

