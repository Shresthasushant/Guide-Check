"""D5: build and FREEZE the train / calibration / test split.

Two mechanisms, as required by plan S3.5:

  Temporal -- train on older sales, calibrate on a middle window, test on the
  newest. We never predict the past from the future.

  Spatial  -- GroupKFold grouped by SA2 for cross-validation *inside* the
  training window, so a property's neighbours never sit in both the fitting
  fold and the scoring fold.

Once splits.json is written and committed, the test set is untouched until
final scoring. Re-running this script refuses to overwrite an existing freeze.
"""

import json
import subprocess
from datetime import datetime, timezone

import pandas as pd
from sklearn.model_selection import GroupKFold

import config as C


def git_commit():
    """The commit the freeze was taken at, or an honest statement that there
    isn't one.

    Checked rather than trusted. `git rev-parse HEAD` echoes its own argument
    back when it cannot resolve the ref -- in a repository with no commits yet
    it prints the literal string "HEAD" and exits non-zero -- so reading stdout
    without checking the return code records "HEAD" as though it were a hash.
    That is what the 2026-09-16 freeze carries. A provenance field nobody
    validates is worse than no field: it reads like a verifiable claim and is
    not one.
    """
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=C.ROOT,
                           capture_output=True, text=True, timeout=10)
    except Exception as e:
        return f"(git unavailable: {type(e).__name__})"
    sha = r.stdout.strip()
    if r.returncode != 0 or len(sha) != 40 or not all(
            ch in "0123456789abcdef" for ch in sha.lower()):
        return "(not version controlled -- freeze_date and the id lists are " \
               "the authoritative record)"
    return sha


def main(force=False):
    if C.SPLITS.exists() and not force:
        meta = json.loads(C.SPLITS.read_text())
        print(f"splits.json already frozen on {meta['freeze_date']} -- refusing "
              f"to overwrite. Pass force=True only if you genuinely mean to "
              f"break the freeze.")
        return

    df = pd.read_parquet(C.CLEAN_PQ, columns=["property_id", "contract_date",
                                              C.GROUP_KEY])
    d = df["contract_date"]
    train_m = d < C.TRAIN_END
    calib_m = (d >= C.TRAIN_END) & (d < C.CALIB_END)
    test_m = d >= C.CALIB_END

    # The join key is sale_key (content-derived), not a positional index --
    # property_id repeats across separate sales of the same property, and a
    # positional index would be silently renumbered by any cleaning change.
    idx = df.index.to_numpy()
    train_idx = idx[train_m.to_numpy()]
    calib_idx = idx[calib_m.to_numpy()]
    test_idx = idx[test_m.to_numpy()]

    # Spatial folds within the training window only.
    tr = df.loc[train_idx]
    gkf = GroupKFold(n_splits=C.N_FOLDS)
    folds = [[str(x) for x in train_idx[va]]
             for _, va in gkf.split(tr, groups=tr[C.GROUP_KEY])]

    meta = {
        "freeze_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "git_commit": git_commit(),
        "split_method": "spatial_group + temporal",
        "group_key": C.GROUP_KEY,
        "temporal_cutoffs": {"train_end": C.TRAIN_END, "calib_end": C.CALIB_END},
        "n_train": len(train_idx), "n_calib": len(calib_idx),
        "n_test": len(test_idx),
        "train_ids": [str(x) for x in train_idx],
        "calib_ids": [str(x) for x in calib_idx],
        "test_ids": [str(x) for x in test_idx],
        "cv_folds": folds,
    }
    C.SPLITS.write_text(json.dumps(meta))

    print(f"FROZEN {C.SPLITS}")
    c = meta["git_commit"]
    print(f"  freeze_date  {meta['freeze_date']}   "
          f"commit {c[:12] if not c.startswith('(') else c}")
    for nm, m in [("train", train_m), ("calib", calib_m), ("test", test_m)]:
        sub = df[m.to_numpy()]
        print(f"  {nm:<6} {len(sub):>9,}  "
              f"{sub['contract_date'].min().date()} -> {sub['contract_date'].max().date()}  "
              f"{sub[C.GROUP_KEY].nunique():>4} SA2s")
    print(f"  cv folds     {C.N_FOLDS}, grouped by {C.GROUP_KEY}")


def load():
    """Return (train_idx, calib_idx, test_idx, meta)."""
    meta = json.loads(C.SPLITS.read_text())
    return (meta["train_ids"], meta["calib_ids"], meta["test_ids"], meta)


def fingerprint(write=True):
    """A tiny, verifiable proof of the freeze.

    splits.json is 61 MB because it lists 1.25M sale keys, which is too large to
    ship with source. A SHA-256 over each sorted key list proves the same thing
    in 1 KB: regenerate the split and the hashes must match exactly. If someone
    quietly re-froze the split to flatter a result, the hash changes.
    """
    import hashlib
    meta = json.loads(C.SPLITS.read_text())
    fp = {k: meta[k] for k in ("freeze_date", "git_commit", "split_method",
                               "group_key", "temporal_cutoffs",
                               "n_train", "n_calib", "n_test")}
    fp["sha256"] = {
        part: hashlib.sha256(
            "\n".join(sorted(meta[f"{part}_ids"])).encode()).hexdigest()
        for part in ("train", "calib", "test")}
    fp["verify"] = ("Regenerate with 'python src/run_all.py', then run "
                    "'python -c \"import sys; sys.path.insert(0,'src'); "
                    "import split; print(split.fingerprint(write=False))\"' "
                    "and compare the sha256 values.")
    if write:
        p = C.PROC / "splits_fingerprint.json"
        p.write_text(json.dumps(fp, indent=2))
        print(f"wrote {p}")
        for part, h in fp["sha256"].items():
            print(f"  {part:<6} {fp['n_' + part]:>9,} rows  sha256 {h[:16]}...")
    return fp


if __name__ == "__main__":
    main()
