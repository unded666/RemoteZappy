import numpy as np
from typing import Union

def preprocess_gesture(points: Union[np.ndarray, list]) -> np.ndarray:
    """
    Preprocess gesture landmarks to relative, normalized coordinates and flatten to 1D.
    Args:
        points: np.ndarray or list of shape (N,) or (N, 3) or (N, 2)
            - If (N,), will reshape to (42, 3) for 2 hands (21 landmarks each, 3 coords)
    Returns:
        np.ndarray of shape (N*2,): relative (x, y) coordinates scaled to [-1, 1], flattened
    """
    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim == 1:
        if arr.shape[0] == 126:
            arr = arr.reshape((42, 3))
        elif arr.shape[0] == 63:
            arr = arr.reshape((21, 3))
        else:
            raise ValueError(f"Unexpected flattened input shape: {arr.shape}")
    if arr.shape[1] > 2:
        arr = arr[:, :2]  # Only use x, y
    base = arr[0]
    rel = arr - base
    dists = np.linalg.norm(rel, axis=1)
    max_dist = np.max(dists)
    if max_dist == 0:
        rel = np.zeros_like(rel)
    else:
        rel = rel / max_dist
    return rel.flatten()

