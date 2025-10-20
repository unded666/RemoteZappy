"""
gesture_integrity.py

This module provides methods for validating the integrity of gesture dataset files.
"""
import json
import numpy as np
import os
from typing import Optional, Tuple

# Load health check thresholds from gestures.json in the current working directory, create with defaults if missing
json_path = os.path.join(os.getcwd(), 'gestures.json')
defaults = {
    'ZERO_LANDMARKS_THRESHOLD': 0.05,
    'MEAN_LANDMARKS_THRESHOLD': 5,
    'STD_LANDMARKS_THRESHOLD': 6
}
if not os.path.exists(json_path):
    try:
        with open(json_path, 'w') as f:
            json.dump(defaults, f, indent=2)
    except Exception:
        pass

with open(json_path, 'r') as f:
    _config = json.load(f)
    ZERO_LANDMARKS_THRESHOLD = _config.get('ZERO_LANDMARKS_THRESHOLD', 0.05)
    MEAN_LANDMARKS_THRESHOLD = _config.get('MEAN_LANDMARKS_THRESHOLD', 5)
    STD_LANDMARKS_THRESHOLD = _config.get('STD_LANDMARKS_THRESHOLD', 6)


def count_nonzero_landmarks(npy_path: str) -> int:
    """
    Count the number of non-zero landmarks in a gesture .npy file.
    Each landmark is considered present if any of its coordinates (x, y, z) is nonzero.
    """
    try:
        arr = np.load(npy_path)
    except Exception:
        return 0
    if arr.size == 0:
        return 0
    try:
        landmarks = arr.reshape(-1, 3)
    except Exception:
        # Corrupt or invalid file, treat as zero landmarks
        return 0
    present = np.any(landmarks != 0, axis=1)
    return int(np.sum(present))


def evaluate_landmark_integrity(directory: str) -> Tuple[float, float, int]:
    """
    Evaluate the integrity of all gesture .npy files in a directory.
    Returns a tuple: (mean, std, count_zero).
    """
    counts = []
    for fname in os.listdir(directory):
        if fname.endswith('.npy'):
            fpath = os.path.join(directory, fname)
            count = count_nonzero_landmarks(fpath)
            counts.append(count)
    if not counts:
        return (0.0, 0.0, 0)
    arr = np.array(counts)
    mean = float(np.mean(arr))
    std = float(np.std(arr))
    count_zero = int(np.sum(arr == 0))
    return (mean, std, count_zero)


def health_check(directory: str) -> Tuple[bool, str]:
    """
    Evaluate the health of the gesture dataset in a directory.
    Returns (healthy: bool, reason: str).
    """
    mean, std, count_zero = evaluate_landmark_integrity(directory)
    total_files = len([f for f in os.listdir(directory) if f.endswith('.npy')])
    if total_files == 0:
        return (False, "empty")
    zero_ratio = count_zero / total_files
    if zero_ratio > ZERO_LANDMARKS_THRESHOLD:
        return (False, "zeros")
    if mean < MEAN_LANDMARKS_THRESHOLD:
        return (False, "landmarks")
    if std > STD_LANDMARKS_THRESHOLD:
        return (False, "inconsistent")
    return (True, "healthy")


def files_with_few_landmarks(directory: str, min_landmarks: int = 0) -> list:
    result = []
    for fname in os.listdir(directory):
        if fname.endswith('.npy'):
            fpath = os.path.join(directory, fname)
            count = count_nonzero_landmarks(fpath)
            if count <= min_landmarks:
                result.append(fname)
    return result


def delete_files_with_few_landmarks(directory: str, max_landmarks: int = 0) -> int:
    to_delete = files_with_few_landmarks(directory, max_landmarks)
    deleted_count = 0
    for fname in to_delete:
        fpath = os.path.join(directory, fname)
        try:
            os.remove(fpath)
            deleted_count += 1
        except Exception:
            pass
    return deleted_count

