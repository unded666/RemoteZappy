import os
import cv2
import numpy as np
import torch
import mediapipe as mp
from typing import Callable, List, Optional, Dict, Any
from gesture_control.mlp import load_model, EXPECTED_FEATURE_DIM
from gesture_control.meta import load_meta_classifier
from .mediapipe_capture import get_dataset_dir
from .preprocessing import preprocess_gesture
import threading

CONFIDENCE_THRESHOLD = 0.8  # Minimum confidence to accept a gesture
CONFUSION_THRESHOLD = 0.15  # If second-best is within this of best, treat as unknown

class GestureRecognizer:
    """
    API for real-time gesture recognition using MediaPipe and trained models.
    """
    def __init__(self, dataset_dir: Optional[str] = None, models_dir: Optional[str] = None):
        """
        Initialize the recognizer with dataset and model directories.
        Args:
            dataset_dir: Directory containing gesture datasets.
            models_dir: Directory containing trained models.
        """
        self.dataset_dir = dataset_dir or get_dataset_dir()
        self.models_dir = models_dir or os.environ.get('MODELS_DIR', 'models')
        self.gestures = [g for g in os.listdir(self.dataset_dir)
                         if os.path.isdir(os.path.join(self.dataset_dir, g)) and g != 'metaclassifier']
        self.input_size = EXPECTED_FEATURE_DIM
        self.models = self._load_gesture_models(self.gestures, self.input_size)
        self.meta_classifier = None
        try:
            self.meta_classifier = load_meta_classifier(models_dir=self.models_dir, num_gestures=len(self.gestures))
        except Exception:
            self.meta_classifier = None
        self._running = False
        self._last_result = None
        self._window_closed_event = threading.Event()
        self._recognition_thread = None
        self._cv_window_name = 'Gesture Recognition'
        self._reference_images = self._load_reference_images()

    def _load_gesture_models(self, gestures: List[str], input_size: int) -> Dict[str, Any]:
        models = {}
        for g in gestures:
            model = load_model(os.path.join(self.models_dir, f'{g}_mlp.pth'), input_size)
            models[g] = model
        return models

    def _load_reference_images(self):
        """Load and scale reference images for each gesture if available."""
        ref_images = {}
        for gesture in self.gestures:
            ref_path = os.path.join(self.dataset_dir, gesture, f"{gesture}_002.png")
            if os.path.exists(ref_path):
                img = cv2.imread(ref_path)
                if img is not None:
                    # Scale to height 40px (leave 10px for label), keep aspect ratio
                    h, w = img.shape[:2]
                    scale = 40 / h
                    new_w = max(1, int(w * scale))
                    img_resized = cv2.resize(img, (new_w, 40))
                    ref_images[gesture] = img_resized
        return ref_images

    def recognize(self,
                  callback: Optional[Callable[[str, List[float], List[float], List[str], List[str]], None]] = None,
                  show_window: bool = True,
                  on_gesture: Optional[Callable[[str, List[float], List[float], List[str], List[str]], None]] = None
                  ) -> None:
        """
        Start real-time gesture recognition. Optionally provide a callback for results and a callback for recognized gestures.
        Args:
            callback: Function called with (label, gesture_probs, meta_probs, gestures, meta_classes) each frame.
            show_window: If True, display OpenCV window with results.
            on_gesture: Function called with (label, gesture_probs, meta_probs, gestures, meta_classes) when a gesture is recognized (label != 'No gesture').
        """
        mp_hands = mp.solutions.hands
        self._running = True
        self._window_closed_event.clear()
        cap = cv2.VideoCapture(0)
        try:
            with mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.5) as hands:
                label = 'No hand'
                while self._running and not self._window_closed_event.is_set():
                    ret, frame = cap.read()
                    if not ret:
                        continue
                    h, w, c = frame.shape
                    # Reference image display parameters
                    ref_height = 110
                    ref_spacing = 15
                    ref_label_height = 10
                    ref_total_height = ref_height + ref_label_height
                    max_bar_height = 120
                    # Calculate total width required for all reference images
                    ref_widths = []
                    for gesture in self.gestures:
                        ref_img = self._reference_images.get(gesture)
                        if ref_img is not None:
                            rh, rw = ref_img.shape[:2]
                            scale = ref_height / rh
                            new_w = max(1, int(rw * scale))
                            ref_widths.append(new_w + ref_spacing)
                    total_width = sum(ref_widths)
                    n_per_row = []
                    row_width = 0
                    count = 0
                    for w_i in ref_widths:
                        if row_width + w_i > w and row_width > 0:
                            n_per_row.append(count)
                            row_width = w_i
                            count = 1
                        else:
                            row_width += w_i
                            count += 1
                    if count > 0:
                        n_per_row.append(count)
                    n_rows = len(n_per_row)
                    bar_height = max_bar_height * n_rows
                    # Create a new image with extra space for the black bar(s)
                    display_img = np.zeros((h + bar_height, w, c), dtype=np.uint8)
                    # Place the video frame at the top
                    display_img[:h, :, :] = frame
                    # The black bar(s) are already zeroed at the bottom
                    # Process hand landmarks as before
                    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
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
                    sample = np.array(landmarks, dtype=np.float32)
                    sample = preprocess_gesture(sample)
                    sample_tensor = torch.tensor(sample.flatten(), dtype=torch.float32).unsqueeze(0)
                    with torch.no_grad():
                        gesture_probs = [float(self.models[g](sample_tensor).item()) for g in self.gestures]
                    # --- META-CLASSIFIER DECISION ---
                    if self.meta_classifier is not None:
                        meta_input = torch.tensor([gesture_probs], dtype=torch.float32)
                        meta_out = self.meta_classifier(meta_input)
                        meta_probs = torch.softmax(meta_out, dim=1).detach().cpu().numpy()[0]
                        best_idx = int(np.argmax(meta_probs))
                        label = 'unknown' if best_idx == len(self.gestures) else self.gestures[best_idx]
                    else:
                        # fallback to rules-based
                        best_idx = int(np.argmax(gesture_probs))
                        best_prob = gesture_probs[best_idx]
                        sorted_probs = sorted(gesture_probs, reverse=True)
                        second_best_prob = sorted_probs[1] if len(sorted_probs) > 1 else 0.0
                        if best_prob < CONFIDENCE_THRESHOLD:
                            label = 'unknown'
                        elif (best_prob - second_best_prob) < CONFUSION_THRESHOLD:
                            label = 'unknown'
                        else:
                            label = self.gestures[best_idx]
                        meta_probs = gesture_probs
                    meta_classes = self.gestures + ['unknown']
                    self._last_result = (label, gesture_probs, meta_probs, self.gestures, meta_classes)
                    if callback:
                        callback(label, gesture_probs, meta_probs, self.gestures, meta_classes)
                    if on_gesture and label != 'unknown':
                        on_gesture(label, gesture_probs, meta_probs, self.gestures, meta_classes)
                    if show_window:
                        # Draw reference images in the black bar(s), wrap to next row as needed
                        y_bar = h
                        x = 5
                        row = 0
                        img_idx = 0
                        for gesture in self.gestures:
                            ref_img = self._reference_images.get(gesture)
                            if ref_img is not None:
                                rh, rw = ref_img.shape[:2]
                                scale = ref_height / rh
                                new_w = max(1, int(rw * scale))
                                img_resized = cv2.resize(ref_img, (new_w, ref_height))
                                if x + new_w > w and x > 5:
                                    row += 1
                                    x = 5
                                    y_bar = h + row * max_bar_height
                                display_img[y_bar:y_bar+ref_height, x:x+new_w] = img_resized
                                label_y = y_bar + ref_height + 8 if y_bar + ref_height + 8 < h + bar_height else y_bar + ref_height - 2
                                cv2.putText(display_img, gesture, (x, label_y), cv2.FONT_HERSHEY_PLAIN, 1.2, (255,255,255), 2)
                                x += new_w + ref_spacing
                                img_idx += 1
                        # Draw gesture probabilities and main label above the black bar
                        for i, (g, p) in enumerate(zip(self.gestures, gesture_probs)):
                            cv2.putText(display_img, f'{g}: {p:.2f}', (10, 60 + 25 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
                        cv2.putText(display_img, f'Gesture: {label}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
                        cv2.imshow(self._cv_window_name, display_img)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            break
        finally:
            cap.release()
            cv2.destroyAllWindows()
            self._running = False
            self._window_closed_event.set()

    def stop(self) -> None:
        """
        Stop the recognition loop.
        """
        self._running = False
        self._window_closed_event.set()

    def close(self) -> None:
        """
        Immediately and safely close the gesture recognition window and stop any running recognition loop or background thread.
        This method is safe to call multiple times and can be called from another thread.
        If recognition is running in a blocking mainloop or thread, close() will cause the recognition window to close and the recognize() method to return as soon as possible.
        """
        self._running = False
        self._window_closed_event.set()
        try:
            cv2.destroyWindow(self._cv_window_name)
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    def get_last_result(self) -> Optional[tuple]:
        """
        Get the last recognition result.
        Returns:
            Tuple of (label, gesture_probs, meta_probs, gestures, meta_classes) or None.
        """
        return self._last_result

