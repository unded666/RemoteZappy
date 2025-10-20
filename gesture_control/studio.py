import tkinter as tk
from tkinter import simpledialog, messagebox, ttk
import threading
import os
import sys
import subprocess
from typing import Optional, List
from gesture_control.mediapipe_capture import capture_gesture_frames
from .mlp import train_all_gesture_mlp
from gesture_control.recognizer import GestureRecognizer

def threaded(fn):
    def wrapper(*args, **kwargs):
        t = threading.Thread(target=fn, args=args, kwargs=kwargs)
        t.daemon = True
        t.start()
    return wrapper

class GestureApp:
    def __init__(self, root,
                 destination: Optional[str] = None,
                 models: Optional[str] = None,
                 required_gestures: Optional[List[str]] = None):
        """Initialize the Gesture Training System GUI.
            Args:
                root: The Tkinter root window (persistent, not destroyed by this UI).
                destination: Directory to save collected gesture samples.
                models: Directory to save trained models.
                required_gestures: List of gestures to collect samples for.
            Note:
                The main UI is a Toplevel window (self.window). Use self.window for all widgets.
        """
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.title("Gesture Training System")
        self.window.geometry("400x400")  # Increased height by 50 pixels
        self.status_var = tk.StringVar()
        self.status_var.set("Ready.")
        self.required_gestures = required_gestures
        self.dataset_dir = destination if destination else os.environ.get("DATASET_DIR", "dataset")
        if destination is not None:
            os.environ["DATASET_DIR"] = destination
        if models is not None:
            os.environ["MODELS_DIR"] = models
        tk.Label(self.window, text="Gesture Training System", font=("Arial", 16)).pack(pady=10)
        tk.Button(self.window, text="Collect Gesture Samples", command=self.collect_gesture_ui, width=30).pack(pady=5)
        tk.Button(self.window, text="Train Models", command=self.train_models_ui, width=30).pack(pady=5)
        tk.Button(self.window, text="Start Recognition", command=self.start_recognition_ui, width=30).pack(pady=5)
        self.stop_btn = tk.Button(self.window, text="Stop Recognition", command=self.stop_recognition_ui, width=30, state=tk.DISABLED)
        self.stop_btn.pack(pady=5)
        tk.Button(self.window, text="Audit Data", command=self.audit_data_ui, width=30).pack(pady=5)
        tk.Button(self.window, text="Exit", command=self.on_exit, width=30).pack(pady=5)
        tk.Label(self.window, textvariable=self.status_var, fg="blue", wraplength=380, justify="left").pack(pady=20)
        self.recognition_proc = None
        self.dropdown_window = None
        self.recognizer = None

    def _get_gesture_data_status(self):
        """Return a dict mapping gesture name to True (has data) or False (no data)."""
        status = {}
        for gesture in self.required_gestures:
            gesture_path = os.path.join(self.dataset_dir, gesture)
            has_data = os.path.isdir(gesture_path) and any(f.endswith('.npy') for f in os.listdir(gesture_path))
            status[gesture] = has_data
        return status

    def _show_gesture_dropdown(self):
        if self.dropdown_window is not None and tk.Toplevel.winfo_exists(self.dropdown_window):
            self.dropdown_window.lift()
            return
        self.dropdown_window = tk.Toplevel(self.root)
        self.dropdown_window.title("Select Gesture")
        self.dropdown_window.geometry("300x300")
        tk.Label(self.dropdown_window, text="Select a gesture to collect samples for:").pack(pady=10)
        frame = tk.Frame(self.dropdown_window)
        frame.pack(fill=tk.BOTH, expand=True)
        status = self._get_gesture_data_status()
        for gesture in self.required_gestures:
            color = "green" if status[gesture] else "red"
            btn = tk.Button(frame, text=gesture, fg=color, width=20,
                            command=lambda g=gesture: self._on_gesture_selected(g))
            btn.pack(pady=2)
        tk.Button(self.dropdown_window, text="Cancel", command=self.dropdown_window.destroy).pack(pady=10)

    def _on_gesture_selected(self, gesture):
        if self.dropdown_window:
            self.dropdown_window.destroy()
        self.collect_gesture_ui(gesture_name=gesture)

    def collect_gesture_ui(self, gesture_name=None):
        if self.required_gestures and gesture_name is None:
            self._show_gesture_dropdown()
            return
        gesture = gesture_name
        if gesture is None:
            gesture = simpledialog.askstring("Gesture Name", "Enter gesture name:")
            if not gesture:
                return
        num = simpledialog.askinteger("Number of Samples", "How many samples? (default 30):", initialvalue=30)
        if not num:
            num = 30
        self.status_var.set(f"Collecting samples for '{gesture}'...")
        def run_capture():
            capture_gesture_frames(gesture_name=gesture, num_samples=num, dataset_dir=self.dataset_dir)
            # Only schedule the GUI update; do not call any Tkinter methods directly from this thread
            try:
                self.root.after(0, lambda: self._finish_collect_status(gesture))
            except RuntimeError:
                pass  # If mainloop is not running, skip GUI update
        threading.Thread(target=run_capture, daemon=True).start()

    def _finish_collect_status(self, gesture):
        # This method is always called from the main thread via .after
        try:
            def update():
                self.status_var.set(f"Finished collecting samples for '{gesture}'.")
            self.root.after(0, update)
            if self.required_gestures:
                self._refresh_gesture_dropdown()
        except Exception:
            pass

    def _refresh_gesture_dropdown(self):
        # If dropdown is open, destroy and reopen to update colors
        if self.dropdown_window and tk.Toplevel.winfo_exists(self.dropdown_window):
            self.dropdown_window.destroy()
            self._show_gesture_dropdown()

    def set_status(self, msg):
        def update():
            self.status_var.set(msg)
        try:
            self.root.after(0, update)
        except RuntimeError:
            print(f"[STATUS] {msg}")  # Fallback: log to console only

    def train_models_ui(self):
        def set_status(msg):
            def update():
                self.status_var.set(msg)
            try:
                self.root.after(0, update)
            except RuntimeError:
                self.status_var.set(msg)
        set_status("Training models...")
        def do_training():
            try:
                train_all_gesture_mlp(dataset_dir=self.dataset_dir, models_dir=os.environ.get("MODELS_DIR", "models"))
                set_status("Training complete.")
            except Exception as e:
                set_status(f"Training failed: {e}")
        threading.Thread(target=do_training, daemon=True).start()

    def poll_recognition_stop(self):
        if getattr(self, '_recognition_should_stop', False):
            self._on_recognition_stopped()
        else:
            self.root.after(100, self.poll_recognition_stop)

    def _on_recognition_stopped(self):
        """Handle UI updates and cleanup after recognition stops."""
        self.status_var.set("Recognition stopped.")
        self.stop_btn.config(state=tk.DISABLED)
        # Optionally, add more cleanup here if needed

    def start_recognition_ui(self):
        def set_status(msg):
            def update():
                self.status_var.set(msg)
            self.root.after(0, update)
        if self.recognizer is not None and getattr(self.recognizer, '_running', False):
            self.root.after(0, set_status, "Recognition already running.")
            return
        self.root.after(0, set_status, "Starting recognition...")
        self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))
        self.recognizer = GestureRecognizer(dataset_dir=self.dataset_dir, models_dir=os.environ.get("MODELS_DIR", "models"))
        self._recognition_should_stop = False

        def recognition_thread():
            self.recognizer.recognize()
            self._recognition_should_stop = True

        threading.Thread(target=recognition_thread, daemon=True).start()
        self.poll_recognition_stop()  # <-- Now called from the main thread

    def stop_recognition_ui(self):
        if self.recognizer is not None and getattr(self.recognizer, '_running', False):
            self.recognizer.stop()
            self.root.after(0, lambda: self.status_var.set("Recognition stopped by user."))
            self.root.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))
        else:
            self.root.after(0, lambda: self.status_var.set("Recognition is not running."))

    def audit_data_ui(self):
        """Audit the gesture data in the dataset directory and show results."""
        from gesture_control.gesture_integrity import health_check, evaluate_landmark_integrity, delete_files_with_few_landmarks
        gesture_dirs = [os.path.join(self.dataset_dir, d) for d in os.listdir(self.dataset_dir)
                        if os.path.isdir(os.path.join(self.dataset_dir, d)) and d != "metaclassifier"]
        if not gesture_dirs:
            messagebox.showinfo("Audit Data", "No gesture directories found.")
            return
        # Create a new Toplevel window for colored results
        result_win = tk.Toplevel(self.window)
        result_win.title("Audit Data Results")
        result_win.geometry("600x400")
        frame = tk.Frame(result_win)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for gdir in gesture_dirs:
            gesture = os.path.basename(gdir)
            total_files = len([f for f in os.listdir(gdir) if f.endswith('.npy')])
            healthy, reason = health_check(gdir)
            mean, std, count_zero = evaluate_landmark_integrity(gdir)
            text = f"{gesture} ({total_files}): {reason} (mean={mean:.1f}, std={std:.1f}, zero={count_zero})"
            color = "red" if not healthy else "black"
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=text, fg=color, anchor="w", justify="left", width=60).pack(side=tk.LEFT, fill=tk.X, expand=True)
            # Add 'Clean Dataset' button if there are zero files or a 'landmarks' failure
            if count_zero > 0 or reason == "landmarks":
                def make_cleaner(gdir=gdir, row=row, gesture=gesture, reason=reason):
                    def clean_dataset():
                        if reason == "landmarks":
                            from gesture_control.gesture_integrity import files_with_few_landmarks
                            # Remove all files with < 5 landmarks
                            to_delete = files_with_few_landmarks(gdir, 4)
                            deleted = 0
                            for fname in to_delete:
                                try:
                                    os.remove(os.path.join(gdir, fname))
                                    deleted += 1
                                except Exception as e:
                                    print(f"Failed to delete {fname}: {e}")
                            msg = f"Removed {deleted} files with <5 landmarks."
                        else:
                            deleted = delete_files_with_few_landmarks(gdir, 0)
                            msg = f"Removed {deleted} zero files."
                        tk.Label(row, text=msg, fg="blue").pack(side=tk.RIGHT)
                    return clean_dataset
                tk.Button(row, text="Clean Dataset", command=make_cleaner()).pack(side=tk.RIGHT, padx=5)
        tk.Button(result_win, text="Close", command=result_win.destroy).pack(pady=10)

    def on_exit(self):
        """Safely exit the application, handling both script and embedded use cases."""
        try:
            self.window.destroy()
        except Exception:
            pass

def studio(destination: str = None,
           models: str = None,
           required_gestures: Optional[List[str]] = None,
           root: Optional[tk.Tk] = None):
    """
    Launch the Gesture Training System studio UI.
    Args:
        destination: Directory to save collected gesture samples.
        models: Directory to save trained models.
        required_gestures: List of gestures to collect samples for.
        root: Optional existing Tk root. If None, a new root is created.
    Returns:
        app: The GestureApp instance. The main window is app.window (a Toplevel).
    Usage:
        app = studio(..., root=existing_root)
        existing_root.wait_window(app.window)  # Regain control after studio closes
    """
    created_root = False
    if root is None:
        root = tk.Tk()
        root.withdraw()  # Hide the empty root window
        created_root = True
    app = GestureApp(root, destination, models, required_gestures)
    if created_root:
        root.wait_window(app.window)
        root.destroy()
    return app

