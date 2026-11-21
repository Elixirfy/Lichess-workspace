"""Small deterministic CPU LSTM over completed recent games plus current game."""
import numpy as np
import torch
from torch import nn


def prior_indices(frame, length=8):
    """Right-aligned sequences; overlaps and unknown ends never enter history."""
    result = np.full((len(frame), length), -1, dtype=np.int64)
    for _, group in frame.groupby('player_id', sort=False):
        ordered = group.sort_values(['start_ms', 'game_id'])
        for index, row in ordered.iterrows():
            prior = ordered[(ordered.end_upper_ms < row.start_ms) & (ordered.index != index)]
            if 'split' in prior:
                prior = prior[prior.split != 'purged_shared_game']
            prior = prior.sort_values(['end_upper_ms', 'game_id']).index.tolist()[-(length - 1):]
            ids = prior + [index]
            result[index, -len(ids):] = ids
    return result


def materialize(x, indices):
    # Zero left padding + explicit observed-step channel distinguish real zeros.
    padded = np.zeros((*indices.shape, x.shape[1] + 1), dtype=np.float32)
    mask = indices >= 0
    padded[mask, :-1] = x[indices[mask]]
    padded[mask, -1] = 1
    return padded


class Network(nn.Module):
    def __init__(self, width, hidden=24):
        super().__init__()
        self.rnn = nn.LSTM(width, hidden, batch_first=True)
        self.output = nn.Linear(hidden, 2)

    def forward(self, x):
        values, _ = self.rnn(x)
        return self.output(values[:, -1])


def fit(x, y, soft, train, validation, epochs=12, seed=42, threads=2):
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    net = Network(x.shape[2])
    optimizer = torch.optim.Adam(net.parameters(), lr=.003, weight_decay=.001)
    inputs = torch.from_numpy(x)
    target = torch.tensor(np.nan_to_num(y), dtype=torch.float32)
    continuous = torch.tensor(np.nan_to_num(soft), dtype=torch.float32)
    positives = float(target[train].sum())
    weight = torch.tensor((len(train) - positives) / max(positives, 1))
    criterion = nn.BCEWithLogitsLoss(pos_weight=weight)
    rng = np.random.default_rng(seed)
    best, best_loss, stale = None, float('inf'), 0
    for _ in range(epochs):
        net.train()
        for ids in np.array_split(rng.permutation(train), max(1, int(np.ceil(len(train) / 256)))):
            pred = net(inputs[ids])
            loss = criterion(pred[:, 0], target[ids]) + ((pred[:, 1].sigmoid() - continuous[ids]) ** 2).mean()
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 2)
            optimizer.step()
        if len(validation):
            net.eval()
            with torch.no_grad():
                pred = net(inputs[validation])
                loss = float(criterion(pred[:, 0], target[validation]) + ((pred[:, 1].sigmoid() - continuous[validation]) ** 2).mean())
            if loss < best_loss:
                best_loss, stale = loss, 0
                best = {k: v.clone() for k, v in net.state_dict().items()}
            else:
                stale += 1
                if stale >= 3:
                    break
    if best is not None:
        net.load_state_dict(best)
    return dict(width=x.shape[2], state={k: v.numpy() for k, v in net.state_dict().items()})


def predict(state, x):
    net = Network(state['width'])
    net.load_state_dict({k: torch.from_numpy(v) for k, v in state['state'].items()})
    net.eval()
    result = []
    with torch.no_grad():
        for start in range(0, len(x), 512):
            result.append(net(torch.from_numpy(x[start:start + 512])).sigmoid().numpy())
    values = np.concatenate(result) if result else np.empty((0, 2))
    return values[:, 0], values[:, 1] * 100
