"""
Trim icons by cropping a fixed percentage off each side (left+right) while
leaving vertical dimensions intact.

Usage:
    python scripts/trim_icons.py --icons ../icons

Default behavior:
    - Finds image files in the provided icons directory (non-recursive by default)
    - Creates a backup directory inside the icons directory named `backup_YYYYmmdd_HHMMSS`
      and copies the original files there before modifying them
    - Crops `percent` (default 15) percent from the left and right sides of each image
      (i.e. 15% from left and 15% from right)
    - Overwrites the originals with the cropped images, preserving file format

Options:
    --icons PATH     Path to the icons directory (default: ./icons)
    --percent N      Percent to trim from each side (default: 15)
    --recursive      Process files recursively under the icons directory
    --dry-run        Don't write any files; just print what would be done
    --verbose        Print extra progress information

Requirements:
    Pillow (PIL). The project's requirements.txt already lists pillow, but you can
    install it with: pip install pillow

This script is intentionally conservative: it will skip files that would result in
non-positive width after cropping and will preserve original file formats.
"""

from __future__ import annotations
import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image
except Exception as e:
    print("This script requires Pillow. Install with: pip install pillow")
    raise

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tga'}


def find_image_files(directory: Path, recursive: bool = False) -> Iterable[Path]:
    if recursive:
        for p in directory.rglob('*'):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                yield p
    else:
        for p in directory.iterdir():
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                yield p


def backup_files(files: Iterable[Path], backup_dir: Path, *, verbose: bool = False) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = backup_dir / f.name
        if verbose:
            print(f'Backing up: {f} -> {dest}')
        shutil.copy2(f, dest)


def crop_image_horizontally(img: Image.Image, percent_each_side: float) -> Image.Image:
    """Crop `percent_each_side` percent off the left and right sides of `img`.

    percent_each_side is specified as percentage (e.g. 15 for 15%).
    Vertical dimensions are left intact.
    """
    if percent_each_side <= 0:
        return img.copy()
    w, h = img.size
    # Compute pixels to trim from each side; round to nearest int
    trim = int(round(w * (percent_each_side / 100.0)))
    new_w = w - 2 * trim
    if new_w <= 0:
        raise ValueError(f'Crop percent too large for image width {w}: would produce width {new_w}')
    left = trim
    right = w - trim
    # box is (left, upper, right, lower)
    return img.crop((left, 0, right, h))


def process_icons(icons_dir: Path, percent: float = 15.0, recursive: bool = False, dry_run: bool = False, verbose: bool = False) -> int:
    if not icons_dir.exists() or not icons_dir.is_dir():
        raise FileNotFoundError(f'Icons directory not found: {icons_dir}')

    files = list(find_image_files(icons_dir, recursive=recursive))
    if not files:
        if verbose:
            print(f'No image files found in {icons_dir} (recursive={recursive})')
        return 0

    # Create backup directory with timestamp inside icons_dir
    # ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = icons_dir / 'backup'

    if dry_run:
        print('[DRY RUN] Would ensure backup dir exists:', backup_dir)
    else:
        backup_dir.mkdir(exist_ok=True)

    # Copy originals to backup (do this before modifying any file). We copy the files
    # that will be modified and preserve names. If a file with the same name already
    # exists in the backup dir, we append a numeric suffix to avoid overwrite.
    for f in files:
        dest = backup_dir / f.name
        if dry_run:
            print(f'[DRY RUN] Backup: {f} -> {dest}')
            continue
        if dest.exists():
            # find available name
            stem = f.stem
            suffix = f.suffix
            i = 1
            while True:
                candidate = backup_dir / f"{stem}_{i}{suffix}"
                if not candidate.exists():
                    dest = candidate
                    break
                i += 1
        if verbose:
            print(f'Backing up {f} -> {dest}')
        shutil.copy2(f, dest)

    processed = 0
    for f in files:
        try:
            if verbose:
                print(f'Processing: {f}')
            with Image.open(f) as im:
                # Ensure we operate in a mode that supports cropping reliably; keep original mode
                cropped = crop_image_horizontally(im, percent)
                if dry_run:
                    print(f'[DRY RUN] Would save cropped image to {f} (size: {cropped.size})')
                else:
                    # Preserve format where possible; Image.save will infer format from suffix
                    # To preserve PNG transparency, ensure mode is appropriate
                    save_kwargs = {}
                    fmt = im.format or f.suffix.lstrip('.').upper()
                    # For PNG, preserve transparency by saving in PNG
                    if f.suffix.lower() == '.png':
                        # If cropped mode lacks alpha but original had, convert
                        if 'A' in im.getbands() and 'A' not in cropped.getbands():
                            cropped = cropped.convert(im.mode)
                    # Overwrite original file
                    cropped.save(f)
                    if verbose:
                        print(f'Wrote cropped image: {f} (new size: {cropped.size})')
                    processed += 1
        except Exception as e:
            print(f'[ERROR] Failed to process {f}: {e}')

    if verbose:
        print(f'Processed {processed} / {len(files)} files.')
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Trim icons by cropping percent from each side of images')
    parser.add_argument('--icons', '-i', type=str, default=os.path.join(os.path.dirname(__file__), '..', 'icons'),
                        help='Path to icons directory (default: ./icons relative to repo root)')
    parser.add_argument('--percent', '-p', type=float, default=15.0, help='Percent to trim from each side (default: 15)')
    parser.add_argument('--recursive', '-r', action='store_true', help='Process images recursively')
    parser.add_argument('--dry-run', action='store_true', help="Don't write files; just show what would be done")
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args(argv)

    icons_dir = Path(args.icons).resolve()
    try:
        processed = process_icons(icons_dir, percent=args.percent, recursive=args.recursive, dry_run=args.dry_run, verbose=args.verbose)
        if args.dry_run:
            print('[DRY RUN] No files written.')
        else:
            print(f'Done. Processed {processed} files. Originals backed up in backup directory inside {icons_dir}')
        return 0
    except Exception as e:
        print(f'Error: {e}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
