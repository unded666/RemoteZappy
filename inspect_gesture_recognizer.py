import gesture_control as gc
import sys

with open('gesture_recognizer_info.txt', 'w', encoding='utf-8') as f:
    f.write('GestureRecognizer methods:\n')
    f.write(str(dir(gc.GestureRecognizer)))
    f.write('\n\n')
    f.write('GestureRecognizer docstring:\n')
    f.write(str(gc.GestureRecognizer.__doc__))
    f.write('\n')
    # Try to instantiate and inspect instance methods
    try:
        recognizer = gc.GestureRecognizer(required_gestures=['fire', 'ice', 'projectile', 'shield', 'magnify'])
        f.write('Instance methods:\n')
        f.write(str(dir(recognizer)))
        f.write('\n')
        # Try to get docstrings for each method
        for method in dir(recognizer):
            if not method.startswith('_'):
                attr = getattr(recognizer, method)
                if callable(attr):
                    f.write(f'\nMethod: {method}\n')
                    f.write(str(attr.__doc__))
    except Exception as e:
        f.write(f'Error instantiating GestureRecognizer: {e}\n')
