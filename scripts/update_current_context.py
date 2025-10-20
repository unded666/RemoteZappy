"""
Simple helper to append a concise timestamped entry to current_context.txt.
Usage:
    python scripts\update_current_context.py "Short note about change"
This is a convenience helper you can run locally after edits. The assistant will also update
`current_context.txt` itself when it makes edits during this conversation.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

CTX = Path(__file__).resolve().parents[1] / 'current_context.txt'

def main():
    msg = ' '.join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ''
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')
    entry = f"\n--- Change recorded {ts} ---\n{msg}\n"
    try:
        with CTX.open('a', encoding='utf-8') as f:
            f.write(entry)
        print(f'Appended change note to {CTX}: "{msg}"')
    except Exception as e:
        print('Failed to append to current_context.txt:', e)

if __name__ == '__main__':
    main()
