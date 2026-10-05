# Ablation -- feature groups

Point model retrained with one group removed, identical frozen split.
Positive delta means removing the group made the model worse, i.e. the
group was carrying real signal.

| arm | removed | MAPE_% | delta_pp |
|---|---|---|---|
| abl_all_features | (none) | 25.81 | +0.00 |
| abl_no_index | index | 25.83 | +0.02 |
| abl_no_spatial | spatial | 26.82 | +1.01 |
| abl_no_structural | structural | 28.52 | +2.71 |
| abl_no_temporal | temporal | 30.58 | +4.77 |
