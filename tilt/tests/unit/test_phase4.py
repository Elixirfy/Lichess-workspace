import numpy as np
import pandas as pd

from tilt.evaluation import phase4


def frame():
    return pd.DataFrame(dict(weak_tilt_label=[1, 0, np.nan, 1, 0, 0], x=[5, 1, 9, 4, np.nan, 2]))


def test_table_separates_coverage_from_rate():
    f = frame()
    out = phase4.table(f, dict(all=pd.Series(True, index=f.index), none=pd.Series(False, index=f.index)))
    assert out['all'] == dict(rows=6, coverage=round(5 / 6, 3), labelled=5, tilt_rate=.4)
    assert out['none'] == dict(rows=0, coverage=None, labelled=0, tilt_rate=None)


def test_auc_keeps_direction_and_skips_missing():
    f = frame()
    assert phase4.auc(f, 'x') == dict(n=4, auc=1.0)
    f['x'] = -f.x
    assert phase4.auc(f, 'x')['auc'] == 0.0
    assert phase4.auc(f, 'x', mask=f.weak_tilt_label.eq(0)) is None
