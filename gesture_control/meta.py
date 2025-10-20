import os
import numpy as np
import torch
import joblib
from sklearn.linear_model import LogisticRegression
from .mlp import load_model
from .preprocessing import preprocess_gesture
import torch.nn as nn
import torch.optim as optim

class MetaClassifier(nn.Module):
    def __init__(self, num_gestures, hidden_size=32, dropout=0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(num_gestures, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, num_gestures + 1)  # +1 for 'unknown'
        )
    def forward(self, x):
        return self.net(x)

def train_meta_classifier(gestures, input_size, dataset_dir=None, models_dir=None, epochs=50, batch_size=16):
    """
    Train the meta-classifier using the output probabilities of gesture models.
    Args:
        gestures (list): List of gesture names.
        input_size (int): Feature dimension size.
        dataset_dir (str): Directory containing gesture datasets.
        models_dir (str): Directory containing trained models.
    """
    dataset_dir = dataset_dir or os.environ.get('DATASET_DIR', 'dataset')
    models_dir = models_dir or os.environ.get('MODELS_DIR', 'models')
    meta_model_path = os.path.join(models_dir, 'meta_classifier.pth')
    models = {g: load_model(os.path.join(models_dir, f'{g}_mlp.pth'), input_size) for g in gestures}
    X_meta = []
    y_meta = []
    for idx, gesture in enumerate(gestures):
        gesture_dir = os.path.join(dataset_dir, gesture)
        for fname in os.listdir(gesture_dir):
            if fname.endswith('.npy'):
                sample = np.load(os.path.join(gesture_dir, fname)).astype(np.float32)
                sample = preprocess_gesture(sample)
                if sample.size != input_size or sample.ndim != 1:
                    continue
                sample_tensor = torch.tensor(sample).unsqueeze(0)
                probs = [float(models[g](sample_tensor).item()) for g in gestures]
                X_meta.append(probs)
                y_meta.append(idx)  # class index for gesture
    # Add random noise and zero-vector samples as 'unknown' (last class)
    unknown_idx = len(gestures)
    for _ in range(50):
        sample = np.random.uniform(-1, 1, input_size).astype(np.float32)
        sample_tensor = torch.tensor(sample).unsqueeze(0)
        probs = [float(models[g](sample_tensor).item()) for g in gestures]
        X_meta.append(probs)
        y_meta.append(unknown_idx)
    for _ in range(20):
        sample = np.zeros(input_size, dtype=np.float32)
        sample_tensor = torch.tensor(sample).unsqueeze(0)
        probs = [float(models[g](sample_tensor).item()) for g in gestures]
        X_meta.append(probs)
        y_meta.append(unknown_idx)
    if len(set(y_meta)) < 2:
        print(f"Meta-classifier training failed: only found these classes in training data: {set(y_meta)}. At least two classes are required.")
        return
    X_meta = np.array(X_meta, dtype=np.float32)
    y_meta = np.array(y_meta, dtype=np.int64)
    # Train MLP meta-classifier
    model = MetaClassifier(num_gestures=len(gestures))
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()
    X_tensor = torch.tensor(X_meta, dtype=torch.float32)
    y_tensor = torch.tensor(y_meta, dtype=torch.long)
    dataset = torch.utils.data.TensorDataset(X_tensor, y_tensor)
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)
    for epoch in range(epochs):
        for Xb, yb in loader:
            optimizer.zero_grad()
            out = model(Xb)
            loss = criterion(out, yb)
            loss.backward()
            optimizer.step()
    torch.save(model.state_dict(), meta_model_path)
    print(f"Meta-classifier trained and saved to {meta_model_path}.")

def load_meta_classifier(models_dir=None, num_gestures=None):
    models_dir = models_dir or os.environ.get('MODELS_DIR', 'models')
    meta_model_path = os.path.join(models_dir, 'meta_classifier.pth')
    model = MetaClassifier(num_gestures=num_gestures)
    model.load_state_dict(torch.load(meta_model_path))
    model.eval()
    return model

