import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from .preprocessing import preprocess_gesture

EXPECTED_FEATURE_DIM = 84  # 2 hands × 21 landmarks × 2 coords (flattened)
GESTURE_DATASET_DIR = os.environ.get('DATASET_DIR', 'dataset')

class GestureDataset(Dataset):
    def __init__(self, gesture_name, all_gestures, negative_ratio=1, feature_dim=EXPECTED_FEATURE_DIM, dataset_dir=None):
        self.samples = []
        self.labels = []
        self.feature_dim = feature_dim
        dataset_dir = dataset_dir or os.environ.get('DATASET_DIR', 'dataset')
        gesture_dir = os.path.join(dataset_dir, gesture_name)
        for fname in os.listdir(gesture_dir):
            if fname.endswith('.npy'):
                arr = np.load(os.path.join(gesture_dir, fname))
                arr = preprocess_gesture(arr)
                if arr.size != self.feature_dim or arr.ndim != 1:
                    continue
                self.samples.append(arr)
                self.labels.append(1)
        negatives = []
        for other in all_gestures:
            if other == gesture_name:
                continue
            other_dir = os.path.join(dataset_dir, other)
            for fname in os.listdir(other_dir):
                if fname.endswith('.npy'):
                    arr = np.load(os.path.join(other_dir, fname))
                    arr = preprocess_gesture(arr)
                    if arr.size != self.feature_dim or arr.ndim != 1:
                        continue
                    negatives.append(arr)
        np.random.shuffle(negatives)
        negatives = negatives[:len(self.samples)*negative_ratio]
        self.samples.extend(negatives)
        self.labels.extend([0]*len(negatives))
        # Add 10 random noise samples (negative)
        noise_samples = 20
        for _ in range(noise_samples):
            noise = np.random.uniform(-1, 1, self.feature_dim).astype(np.float32)
            self.samples.append(noise)
            self.labels.append(0)
        # Add 10 zero-vector samples (negative)
        zero_vector_samples = 10
        for _ in range(zero_vector_samples):
            self.samples.append(np.zeros(self.feature_dim, dtype=np.float32))
            self.labels.append(0)
        if len(self.samples) == 0:
            raise ValueError(f"No valid samples found for gesture {gesture_name} with feature dim {self.feature_dim}")
        self.samples = np.array(self.samples, dtype=np.float32)
        self.labels = np.array(self.labels, dtype=np.float32)
    def __len__(self):
        return len(self.samples)
    def __getitem__(self, idx):
        return self.samples[idx], self.labels[idx]

class MLPClassifier(nn.Module):
    def __init__(self, input_size, hidden_size=128, dropout=0.2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, 1),
            nn.Sigmoid()
        )
    def forward(self, x):
        return self.net(x)

def train_gesture_mlp(gesture_name, all_gestures, input_size, epochs=100, batch_size=16, dataset_dir=None):
    dataset = GestureDataset(gesture_name, all_gestures, feature_dim=input_size, dataset_dir=dataset_dir)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    model = MLPClassifier(input_size)
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    for epoch in range(epochs):
        for X, y in loader:
            optimizer.zero_grad()
            out = model(X)
            loss = criterion(out.squeeze(), y)
            loss.backward()
            optimizer.step()
    return model

def save_model(model, path):
    torch.save(model.state_dict(), path)

def load_model(path, input_size):
    model = MLPClassifier(input_size)
    model.load_state_dict(torch.load(path))
    model.eval()
    return model

def train_all_gesture_mlp(dataset_dir=None, models_dir=None):
    """
    Train MLP models for all gestures found in the dataset directory.
    Args:
        dataset_dir (str): Directory containing gesture datasets.
        models_dir (str): Directory to save trained models.
    Returns:
        gestures (list): List of gesture names.
        input_size (int): Feature dimension size.
    """
    dataset_dir = dataset_dir or os.environ.get('DATASET_DIR', 'dataset')
    models_dir = models_dir or os.environ.get('MODELS_DIR', 'models')
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
    gestures = [g for g in os.listdir(dataset_dir) if os.path.isdir(os.path.join(dataset_dir, g)) and g != 'metaclassifier']
    input_size = EXPECTED_FEATURE_DIM
    for gesture in gestures:
        print(f"Training MLP for gesture: {gesture}")
        model = train_gesture_mlp(gesture, gestures, input_size, dataset_dir=dataset_dir)
        save_model(model, os.path.join(models_dir, f'{gesture}_mlp.pth'))
    print("All gesture MLPs trained.")
    # Train meta-classifier after all gesture MLPs
    from .meta import train_meta_classifier
    train_meta_classifier(gestures, input_size, dataset_dir=dataset_dir, models_dir=models_dir)
    print("Meta-classifier trained.")
    return gestures, input_size

