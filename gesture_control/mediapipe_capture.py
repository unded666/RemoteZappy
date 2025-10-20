import os
import cv2
import mediapipe as mp
import numpy as np
import time
from typing import List, Optional, Tuple
CAPTURE_DELAY = 1.5  # seconds

def get_dataset_dir() -> str:
    """
    Get the dataset directory from the DATASET_DIR environment variable, or use 'dataset' as default.
    Returns:
        str: Path to the dataset directory.
    """
    return os.environ.get('DATASET_DIR', 'dataset')

def capture_gesture_frames(gesture_name: str, num_samples: int = 10, dataset_dir: str = "dataset") -> None:
    """
    Capture single-frame gesture samples using MediaPipe and save them as .npy files.

    Args:
        gesture_name (str): Name of the gesture to capture.
        num_samples (int): Number of samples to capture.
        dataset_dir (str): Directory to save the captured samples.
    """
    mp_hands = mp.solutions.hands
    cap = cv2.VideoCapture(0)
    save_dir = os.path.join(dataset_dir, gesture_name)
    os.makedirs(save_dir, exist_ok=True)
    sample_count = 0
    prompt_first = True
    while sample_count < num_samples:
        ret, frame = cap.read()
        if not ret:
            continue
        display = frame.copy()
        if prompt_first:
            cv2.putText(display, f"Press SPACE to capture the first image", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
            cv2.putText(display, "Press 'q' to quit", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100,100,100), 2)
            cv2.imshow("Capture Gesture", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == 32:  # Spacebar
                # After SPACE, wait for 2 * CAPTURE_DELAY before capturing
                countdown = 2 * CAPTURE_DELAY
                start_time = time.time()
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        continue
                    elapsed = time.time() - start_time
                    remaining = max(0, countdown - elapsed)
                    display = frame.copy()
                    cv2.putText(display, f"Capturing first image in {remaining:.2f}s", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
                    cv2.putText(display, "Press 'q' to quit", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100,100,100), 2)
                    cv2.imshow("Capture Gesture", display)
                    key2 = cv2.waitKey(1) & 0xFF
                    if key2 == ord('q'):
                        cap.release()
                        cv2.destroyAllWindows()
                        return
                    if remaining <= 0:
                        break
                prompt_first = False
            else:
                continue
        else:
            # CAPTURE_DELAY countdown for subsequent images
            countdown = CAPTURE_DELAY
            start_time = time.time()
            while True:
                ret, frame = cap.read()
                if not ret:
                    continue
                elapsed = time.time() - start_time
                remaining = max(0, countdown - elapsed)
                display = frame.copy()
                cv2.putText(display, f"Capturing in {remaining:.2f}s ({sample_count+1}/{num_samples})", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
                cv2.putText(display, "Press 'q' to quit", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100,100,100), 2)
                cv2.imshow("Capture Gesture", display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    cap.release()
                    cv2.destroyAllWindows()
                    return
                if remaining <= 0:
                    break
        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with mp_hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.5) as hands:
            results = hands.process(image)
            all_landmarks = []
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks[:2]:
                    all_landmarks.extend([[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark])
                while len(all_landmarks) < 42:
                    all_landmarks.extend([[0, 0, 0]])
            else:
                all_landmarks = [[0, 0, 0]] * 42
            all_landmarks = all_landmarks[:42]
            landmarks = np.array(all_landmarks).flatten().astype(np.float32)
            fname = os.path.join(save_dir, f"{time.strftime('%Y%m%d_%H%M%S')}_{sample_count:02d}.npy")
            np.save(fname, landmarks)
            # Save the second captured frame as a PNG image only if it does not already exist
            if sample_count == 1:
                png_name = os.path.join(save_dir, f"{gesture_name}_002.png")
                if not os.path.exists(png_name):
                    cv2.imwrite(png_name, frame)
            # Show feedback
            cv2.putText(frame, "Captured!", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            cv2.imshow("Capture Gesture", frame)
            cv2.waitKey(500)
            sample_count += 1
    cap.release()
    cv2.destroyAllWindows()

def extract_hand_landmarks(image: np.ndarray, max_num_hands: int = 2) -> Optional[np.ndarray]:
    """
    Extract hand landmarks from an image using MediaPipe Hands.

    Args:
        image (np.ndarray): The input image (BGR format).
        max_num_hands (int): Maximum number of hands to detect.

    Returns:
        Optional[np.ndarray]: Flattened array of hand landmarks (shape: (num_hands * 63,)), or None if no hands detected.
    """
    mp_hands = mp.solutions.hands
    with mp_hands.Hands(static_image_mode=True, max_num_hands=max_num_hands, min_detection_confidence=0.5) as hands:
        results = hands.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if not results.multi_hand_landmarks:
            return None
        all_landmarks = []
        for hand_landmarks in results.multi_hand_landmarks[:max_num_hands]:
            all_landmarks.extend([[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark])
        while len(all_landmarks) < max_num_hands * 21:
            all_landmarks.extend([[0,0,0]])
        return np.array(all_landmarks).flatten().astype(np.float32)

